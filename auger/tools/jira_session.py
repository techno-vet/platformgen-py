"""
Jira Session Manager
Cookie-based authentication for gsa-standard.atlassian-us-gov-mod.net (PIV/MFA).
Cookies are captured via Selenium (jira_auto_login.py) and stored in ~/.auger/.env.
"""
import os
import json
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv, set_key
from urllib.parse import urlparse

try:
    from auger.ui.utils import auger_home as _auger_home
except ImportError:
    def _auger_home(): return Path.home()


class JiraSession:
    """Manage Jira session with MFA/cookie support."""

    DEFAULT_URL = 'https://gsa-standard.atlassian-us-gov-mod.net'

    def __init__(self, instance_url: str | None = None):
        self.env_file = _auger_home() / '.auger' / '.env'
        load_dotenv(self.env_file, override=True)
        self.instance_url = (instance_url or
                             os.getenv('JIRA_URL', self.DEFAULT_URL)).rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({'Accept': 'application/json'})
        self._loaded = self._load_session()

    # ── Session persistence ──────────────────────────────────────────────────

    def _load_session(self) -> bool:
        cookies_json  = os.getenv('JIRA_COOKIES')
        cookie_expiry = os.getenv('JIRA_COOKIE_EXPIRY')
        if not cookies_json:
            return False
        try:
            if cookie_expiry:
                expiry = datetime.fromisoformat(cookie_expiry)
                if datetime.now() >= expiry:
                    print('[JiraSession] Stored cookie expiry has passed; trying saved cookies anyway')
            cookies = json.loads(cookies_json)
            domain  = urlparse(self.instance_url).netloc
            for name, value in cookies.items():
                self.session.cookies.set(name, value, domain=domain)
            return True
        except Exception as e:
            print(f'[JiraSession] Cookie load error: {e}')
            return False

    def save_cookies(self, cookies: dict, expiry: datetime):
        """Persist cookies captured by the auto-login script."""
        set_key(str(self.env_file), 'JIRA_URL',            self.instance_url)
        set_key(str(self.env_file), 'JIRA_COOKIES',        json.dumps(cookies))
        set_key(str(self.env_file), 'JIRA_COOKIE_EXPIRY',  expiry.isoformat())

    def is_authenticated(self) -> bool:
        """Quick check: session cookies present and a lightweight API call succeeds."""
        if not self.session.cookies:
            return False
        try:
            r = self.session.get(
                f'{self.instance_url}/rest/api/2/myself',
                timeout=10, allow_redirects=False
            )
            return r.status_code == 200
        except Exception:
            return False

    def current_user(self) -> dict:
        """Return the logged-in user's Jira account info."""
        r = self._get('/rest/api/2/myself')
        return r.json() if r and r.ok else {}

    # ── REST helpers ─────────────────────────────────────────────────────────

    def _get(self, path: str, **params):
        try:
            return self.session.get(
                f'{self.instance_url}{path}', params=params, timeout=20
            )
        except Exception as e:
            print(f'[JiraSession] GET {path} error: {e}')
            return None

    def _post(self, path: str, payload: dict):
        try:
            return self.session.post(
                f'{self.instance_url}{path}', json=payload,
                headers={'Content-Type': 'application/json'}, timeout=20
            )
        except Exception as e:
            print(f'[JiraSession] POST {path} error: {e}')
            return None

    def _put(self, path: str, payload: dict):
        try:
            return self.session.put(
                f'{self.instance_url}{path}', json=payload,
                headers={'Content-Type': 'application/json'}, timeout=20
            )
        except Exception as e:
            print(f'[JiraSession] PUT {path} error: {e}')
            return None

    # ── Issue queries ─────────────────────────────────────────────────────────

    def my_issues(self, project: str = 'ASSIST3', max_results: int = 50,
                  include_closed: bool = False) -> list[dict]:
        """Return issues assigned to the current user."""
        status_filter = '' if include_closed else 'AND statusCategory != Done '
        jql = (f'project = {project} '
               f'AND assignee = currentUser() '
               f'{status_filter}'
               f'ORDER BY updated DESC')
        return self._search(jql, max_results)

    def sprint_issues(self, board_id: int, project: str = 'ASSIST3',
                      max_results: int = 100) -> list[dict]:
        """Return all issues in the active sprint for a board."""
        # Get active sprint id first
        r = self._get(f'/rest/agile/1.0/board/{board_id}/sprint',
                      state='active', maxResults=1)
        if not r or not r.ok:
            return []
        sprints = r.json().get('values', [])
        if not sprints:
            return []
        sprint_id = sprints[0]['id']
        jql = (f'project = {project} '
               f'AND sprint = {sprint_id} '
               f'ORDER BY status ASC, priority DESC')
        return self._search(jql, max_results)

    def get_issue(self, issue_key: str) -> dict | None:
        """Return full issue detail including renderedFields (HTML)."""
        r = self._get(f'/rest/api/2/issue/{issue_key}',
                      expand='renderedFields')
        return r.json() if r and r.ok else None

    def _search(self, jql: str, max_results: int = 50) -> list[dict]:
        fields = ['summary', 'status', 'assignee', 'priority', 'issuetype',
                  'description', 'comment', 'labels', 'fixVersions', 'updated', 'created',
                  'customfield_10022', 'customfield_10023']  # target start, target end
        # REST API v2 /search is removed on Atlassian Gov Cloud (returns 410).
        # Use v3 POST /search/jql instead — response shape is identical (issues[]).
        try:
            r = self.session.post(
                f'{self.instance_url}/rest/api/3/search/jql',
                json={'jql': jql, 'maxResults': max_results, 'fields': fields},
                timeout=20
            )
        except Exception as e:
            print(f'[JiraSession] _search error: {e}')
            return []
        if not r or not r.ok:
            print(f'[JiraSession] _search {r.status_code}: {r.text[:200]}')
            return []
        return r.json().get('issues', [])

    # ── Transitions ───────────────────────────────────────────────────────────

    def get_transitions(self, issue_key: str) -> list[dict]:
        """Return available transitions for an issue."""
        r = self._get(f'/rest/api/2/issue/{issue_key}/transitions')
        if not r or not r.ok:
            return []
        return r.json().get('transitions', [])

    def transition_issue(self, issue_key: str, transition_id: str) -> bool:
        """Move issue to a new status by transition id."""
        r = self._post(f'/rest/api/2/issue/{issue_key}/transitions',
                       {'transition': {'id': transition_id}})
        return r is not None and r.status_code == 204

    # ── Comments ──────────────────────────────────────────────────────────────

    def add_comment(self, issue_key: str, body: str) -> bool:
        r = self._post(f'/rest/api/2/issue/{issue_key}/comment', {'body': body})
        return r is not None and r.ok

    # ── Update ────────────────────────────────────────────────────────────────

    def update_summary(self, issue_key: str, summary: str) -> bool:
        r = self._put(f'/rest/api/2/issue/{issue_key}',
                      {'fields': {'summary': summary}})
        return r is not None and r.ok


def shared_atlassian_session(instance_url: str | None = None) -> requests.Session:
    """Return a requests session seeded with saved Jira/Atlassian MFA cookies."""
    env_file = _auger_home() / '.auger' / '.env'
    load_dotenv(env_file, override=True)

    target_url = (instance_url or os.getenv('JIRA_URL', JiraSession.DEFAULT_URL)).rstrip('/')
    session = requests.Session()
    session.headers.update({'Accept': 'application/json'})

    cookies_json = os.getenv('JIRA_COOKIES')
    if not cookies_json:
        return session

    try:
        cookies = json.loads(cookies_json)
        domain = urlparse(target_url).netloc
        for name, value in cookies.items():
            session.cookies.set(name, value, domain=domain)
    except Exception as e:
        print(f'[JiraSession] Shared Atlassian cookie load error: {e}')

    return session
