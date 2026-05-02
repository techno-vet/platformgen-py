"""
auger.tools.stakeholder_mention
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Route pipeline block events to the right stakeholder via GChat @mention.

Usage:
    from auger.tools.stakeholder_mention import mention_on_block

    mention_on_block(
        event='build_failure',
        story_key='ASSIST3-38045',
        stage='Jenkins',
        detail='core-assist-billing build #142 failed — OutOfMemoryError in test phase',
        link='https://jenkins-mcaas.helix.gsa.gov/job/ASSIST/job/core/job/...',
        jira_assignee_email='bobby.blair@gsa.gov',   # from Jira fields.assignee.emailAddress
    )
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests
import yaml


# ── Paths ─────────────────────────────────────────────────────────────────────
_DATA_DIR   = Path(__file__).resolve().parents[1] / 'data'
_ROLES_YAML = _DATA_DIR / 'stakeholder_roles.yaml'
_USERS_YAML = _DATA_DIR / 'gchat_users.yaml'
_USERS_CF   = Path(__file__).resolve().parents[2] / 'config' / 'gchat_users.yaml'

# Webhook for the Auger team GChat space
_WEBHOOKS_YAML = _DATA_DIR / 'gchat_webhooks.yaml'


# ── Loaders ───────────────────────────────────────────────────────────────────
def _load_roles() -> dict:
    if _ROLES_YAML.exists():
        return yaml.safe_load(_ROLES_YAML.read_text()).get('roles', {})
    return {}


def _load_users() -> list:
    for p in (_USERS_YAML, _USERS_CF):
        if p.exists():
            return yaml.safe_load(p.read_text()).get('users', [])
    return []


def _load_webhook() -> str:
    if _WEBHOOKS_YAML.exists():
        whs = yaml.safe_load(_WEBHOOKS_YAML.read_text()).get('webhooks', [])
        for w in whs:
            if w.get('name') == 'AUGER_POC':
                return w['url']
    return os.environ.get('GCHAT_WEBHOOK_AUGER_POC', '')


# ── Core lookup ───────────────────────────────────────────────────────────────
def email_to_user_id(email: str) -> Optional[str]:
    """Return GChat user_id for a given GSA email address, or None."""
    if not email:
        return None
    email = email.lower().strip()
    for u in _load_users():
        if u.get('email', '').lower() == email:
            return u['user_id']
    return None


def email_to_name(email: str) -> str:
    """Return display name for email, or the email itself as fallback."""
    email = email.lower().strip()
    for u in _load_users():
        if u.get('email', '').lower() == email:
            name = u.get('name', email)
            # Strip org suffix like "- IDQBF-C"
            return name.split(' - ')[0].strip()
    return email


def _mention(user_id: str) -> str:
    return f'<users/{user_id}>'


# ── Block event → recipients ──────────────────────────────────────────────────
def _resolve_recipients(event: str, jira_assignee_email: Optional[str]) -> list[dict]:
    """Return list of {email, user_id, role} dicts for the given event."""
    roles   = _load_roles()
    users   = _load_users()
    seen    = set()
    result  = []

    for role_name, role_cfg in roles.items():
        if event not in role_cfg.get('trigger_on', []):
            continue

        source = role_cfg.get('source')
        if source == 'jira_assignee':
            email = jira_assignee_email or ''
        else:
            email = role_cfg.get('email', '')

        if not email:
            continue

        uid = email_to_user_id(email)
        if not uid:
            # No GChat ID — still include for name mention in message body
            uid = None

        key = email.lower()
        if key not in seen:
            seen.add(key)
            result.append({
                'role':    role_name,
                'email':   email,
                'user_id': uid,
                'name':    email_to_name(email),
            })

    return result


# ── Message builder ───────────────────────────────────────────────────────────
_EVENT_LABELS = {
    'build_failure':            '🔴 Build Failure',
    'merge_conflict':           '🔀 Merge Conflict',
    'pr_stale':                 '⏳ Stale PR',
    'code_question':            '❓ Code Question',
    'flux_pr_needs_approval':   '⚓ Flux PR Needs Approval',
    'prod_drift':               '⚠️  Prod Drift',
    'prod_incident':            '🚨 Prod Incident',
    'infra_block':              '🏗️  Infra Block',
    'scope_question':           '📋 Scope Question',
    'priority_question':        '🎯 Priority Question',
}

_ASKS = {
    'build_failure':            'Can you investigate the failing build and push a fix?',
    'merge_conflict':           'Can you resolve the merge conflict on this branch?',
    'pr_stale':                 'Can you review or action this PR?',
    'code_question':            "I need a human decision here — Auger isn't confident enough to proceed.",
    'flux_pr_needs_approval':   'Can you review and approve the Flux PR?',
    'prod_drift':               'Prod is behind latest build — please confirm before I create a Flux PR.',
    'prod_incident':            'Pods are failing in prod — please investigate.',
    'infra_block':              'There is a cluster-level issue blocking deployment.',
    'scope_question':           'The story requirements are unclear — can you clarify?',
    'priority_question':        'Competing priorities need a human decision to proceed.',
}


def _build_message(
    event: str,
    story_key: str,
    stage: str,
    detail: str,
    link: Optional[str],
    recipients: list[dict],
) -> str:
    mentions = ' '.join(
        _mention(r['user_id']) if r['user_id'] else r['name']
        for r in recipients
    )
    event_label = _EVENT_LABELS.get(event, event)
    ask = _ASKS.get(event, 'Please take a look.')
    link_part = f'\n🔗 {link}' if link else ''

    return (
        f"{mentions}\n\n"
        f"*{event_label}* — `{story_key}` @ *{stage}*\n\n"
        f"{detail}{link_part}\n\n"
        f"_{ask} I'll resume automatically once this is resolved._\n\n"
        f"— Auger 🤖"
    )


# ── Public API ────────────────────────────────────────────────────────────────
def mention_on_block(
    event: str,
    story_key: str,
    stage: str,
    detail: str,
    link: Optional[str] = None,
    jira_assignee_email: Optional[str] = None,
    webhook_url: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """
    Fire a GChat @mention for a pipeline block event.

    Returns {sent: bool, recipients: [...], message: str, error: str|None}
    """
    recipients = _resolve_recipients(event, jira_assignee_email)

    if not recipients:
        return {'sent': False, 'recipients': [], 'message': '',
                'error': f'No recipients configured for event: {event}'}

    message = _build_message(event, story_key, stage, detail, link, recipients)

    if dry_run:
        return {'sent': False, 'recipients': recipients,
                'message': message, 'error': None}

    url = webhook_url or _load_webhook()
    if not url:
        return {'sent': False, 'recipients': recipients,
                'message': message, 'error': 'No GChat webhook URL found'}

    try:
        r = requests.post(url, json={'text': message}, timeout=10, verify=False)
        r.raise_for_status()
        return {'sent': True, 'recipients': recipients,
                'message': message, 'error': None}
    except Exception as e:
        return {'sent': False, 'recipients': recipients,
                'message': message, 'error': str(e)}


def list_events() -> list[str]:
    return list(_EVENT_LABELS.keys())


def list_roles() -> dict:
    return _load_roles()
