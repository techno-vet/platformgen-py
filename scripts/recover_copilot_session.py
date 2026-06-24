#!/usr/bin/env python3
"""Recover Copilot session from an existing (possibly corrupted) session-state.

Usage: python3 scripts/recover_copilot_session.py [--session <id>] [--dry-run]

What it does:
- Finds the most-recent session under ~/.copilot/session-state if --session not given
- Scans events.jsonl for user/assistant messages and builds a transcript
- Starts a new Copilot session by sending the transcript as a prompt (single call)
- Detects the newly-created session-id and writes it to the runtime pinned-session storage
  (plus legacy `.session_id` compatibility for the default auto scope).

This is a best-effort helper to recover state into a fresh session.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from auger.ai.provider_sessions import copilot_pin_path, write_copilot_pinned_session_id
from auger.utils.file_lock import acquire_file_lock, ensure_lock_file, release_file_lock
from platformgen.runtime import state_dir


def find_most_recent_session():
    base = Path.home() / '.copilot' / 'session-state'
    if not base.exists():
        return None
    entries = [p for p in base.iterdir() if p.is_dir()]
    if not entries:
        return None
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return entries[0]


def parse_events(events_path: Path, max_lines=20000):
    msgs = []
    try:
        lines = events_path.read_text().splitlines()
    except Exception:
        return msgs
    # keep last max_lines lines for performance
    for raw in lines[-max_lines:]:
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        t = obj.get('type', '')
        data = obj.get('data', {}) or {}
        if t == 'user.message' or t == 'assistant.message':
            # data.message may contain the text, fallback to data.content
            text = data.get('message') or data.get('content') or data.get('text') or ''
            role = 'user' if t == 'user.message' else 'assistant'
            if text:
                msgs.append((role, text))
        # Some older events embed messages differently
        elif t == 'assistant.turn_end' or t == 'assistant.turn_start':
            # skip
            continue
    return msgs


def build_transcript(msgs):
    parts = []
    for role, text in msgs:
        if role == 'user':
            parts.append('\nUser: ' + text.strip() + '\n')
        else:
            parts.append('\nAssistant: ' + text.strip() + '\n')
    return '\n'.join(parts)


def run_copilot_prompt(prompt: str, env: dict):
    copilot = shutil_which('copilot')
    if not copilot:
        raise RuntimeError('copilot binary not found in PATH')
    # run copilot in a subprocess; allow it some time to create session
    proc = subprocess.Popen([copilot, '-p', prompt, '--allow-all', '--continue'],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env=env)
    # stream output for user visibility
    out = []
    try:
        for line in proc.stdout:
            out.append(line)
    except Exception:
        pass
    try:
        proc.wait(timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
    return '\n'.join(out)


def shutil_which(name):
    from shutil import which
    return which(name)


def detect_new_session(old_session_id=None):
    base = Path.home() / '.copilot' / 'session-state'
    if not base.exists():
        return None
    entries = [p for p in base.iterdir() if p.is_dir()]
    if not entries:
        return None
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in entries:
        sid = p.name
        if sid != old_session_id:
            return sid
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--session', help='Session id to recover from')
    p.add_argument('--model', default='auto', help='Pinned Copilot model scope to update (default: auto)')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()

    runtime_dir = state_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)

    # determine source session
    if args.session:
        src = Path.home() / '.copilot' / 'session-state' / args.session
        if not src.exists():
            print('Session not found:', args.session)
            return 2
    else:
        src = find_most_recent_session()
        if not src:
            print('No copilot sessions found under ~/.copilot/session-state')
            return 2

    print('Using source session:', src.name)
    events = src / 'events.jsonl'
    if not events.exists():
        print('No events.jsonl in session, aborting')
        return 2

    msgs = parse_events(events)
    if not msgs:
        print('No user/assistant messages found to recover')
        return 2

    # build transcript from last ~50 messages
    transcript = build_transcript(msgs[-50:])

    prompt = (
        'Recover conversation context and continue. The transcript follows. ' 
        'Do not produce unrelated output; respond as the assistant to the last user message.\n\n'
        + transcript
    )

    # prepare env: load runtime .env if present
    env = os.environ.copy()
    env_file = runtime_dir / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            env[k.strip()] = v.strip().strip('"').strip("'")

    # record current newest session id
    old = find_most_recent_session()
    old_id = old.name if old else None

    # If dry-run, show a short transcript preview and exit
    if args.dry_run:
        print('\n--- Transcript preview (last ~50 turns) ---\n')
        print(transcript[:4000])
        print('\n--- End preview ---\n')
        return 0

    lock = runtime_dir / '.copilot.lock'
    ensure_lock_file(lock)
    with open(lock, 'r+') as lf:
        acquire_file_lock(lf, blocking=True)
        try:
            out = run_copilot_prompt(prompt, env)
            print(out[:1000])
        finally:
            release_file_lock(lf)

    # detect new session
    time.sleep(1)
    new_id = detect_new_session(old_id)
    if not new_id:
        print('No new session detected (copilot may have resumed an existing session)')
        return 1

    print('Detected new session id:', new_id)
    if args.dry_run:
        print(f"Dry-run; not writing pinned session files under {runtime_dir}")
        return 0

    sid_file = runtime_dir / '.session_id'
    if sid_file.exists():
        sid_file.rename(runtime_dir / f'.session_id.bak-{int(time.time())}')
    write_copilot_pinned_session_id(args.model, new_id)
    print('Wrote Copilot pinned session id to', copilot_pin_path(args.model))
    if args.model == 'auto':
        print('Updated legacy compatibility session file at', sid_file)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
