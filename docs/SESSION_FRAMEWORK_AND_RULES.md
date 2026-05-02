# Auger Platform Session Framework & Prompt Rules Analysis

## Executive Summary: My Purpose

I am a Copilot CLI assistant designed to work **persistently** with you across session interruptions. If a session glitches, corrupts, or restarts, I have access to:

1. **Prompt Rules** (config/rules.yaml) — Persistent "tribal knowledge" about how to work in this environment
2. **Widget Manifests** (auger/data/widget_manifests.yaml) — Knowledge of every widget's purpose, dependencies, and rules
3. **Session Database** (session_store) — Cross-session history of all my prior work with you
4. **Todos & Checkpoints** (per-session) — Granular task tracking and phase summaries
5. **Session Recovery** (scripts/recover_copilot_session.py) — Mechanism to recover corrupted sessions

This framework ensures I never forget what we were working on, even if the session crashes.

---

## Key Components I've Learned

### 1. Prompt Rules & Conventions (config/rules.yaml)

**28.9 KB of embedded rules** covering:

#### Platform Operations (NEW FOR ME):
- **Platform restart**: ALWAYS use daemon's `/schedule_restart` endpoint
  ```bash
  curl -X POST http://localhost:9191/schedule_restart \
    -H "Content-Type: application/json" \
    -d '{"delay": 3, "message": "Restarting to refresh state"}'
  ```
  **NOT**: Direct process termination (orphans the session)
  
- Why it works: Daemon responds immediately, then restarts Platform in background
- Location: scripts/host_tools_daemon.py, lines 1853-1872

#### Widget Development:
- **Every new widget MUST have**: WIDGET_TITLE, WIDGET_ICON_FUNC, widget_manifests.yaml entry
- **MUST update manifests** when widget behavior changes (enforcement: error)
- **MUST include WIDGET_DEMO_DATA** for offline demo mode (enforcement: error)
- **NEVER use unique ttk.Style names** per widget instance → causes SIGSEGV crash (exit 139) killing container

#### GChat & Communication:
- Read webhook URLs from gchat_webhooks.yaml (never hardcode) — enforcement: warn
- Use `<users/{numeric_id}>` syntax for mentions (plain text names do NOT ping)
- Default channel: AUGER_POC

#### Data Sources & Git:
- Artifactory is source of truth for image tags (not ECR)
- Both flux repos default to deploy-automation branch (not main) — enforcement: warn
- JIRA_BASE_URL: https://gsa-standard.atlassian-us-gov-mod.net (government cloud, not public)
- Container git: Use temp clone workaround for commit/push (root-owned .git locks)

#### Context Detection:
- Determine if running in container vs host by ENVIRONMENT, not by AI identity
- Container signals: CWD starts with /home/auger or /home/auger/auger-platform exists
- Host signals: Direct git write access to ~/repos

#### Display Standards:
- ALL times must display in Eastern Time (EDT/EST), never UTC
- DST transitions: Spring 2026-03-08 02:00 EST→EDT, Fall 2026-11-01 02:00 EDT→EST

#### Model Selection:
- **Do NOT use** Anthropic models (Claude Haiku, Claude Sonnet, Claude Opus)
- **Use approved** non-Anthropic models (GPT-family like gpt-5.4)

#### Early-Adopter Rules:
- Never auto-merge fixes to main without explicit user request
- Default: diagnose, explain, make local changes or open PR — keep off main unless explicitly asked

---

### 2. Widget Manifests (auger/data/widget_manifests.yaml)

**Per-widget metadata** that I can read at session start to understand:

#### Schema:
```yaml
widget_name:
  title: "Display Name"
  purpose: "What this widget does"
  depends_on: [other_widgets]
  used_by: [widgets_that_depend_on_this]
  key_data_files:
    - "config files"
    - "credential files"
  auger_rules:
    - "Rule 1"
    - "Rule 2"
  session_resume_hint: "What to check on session resume"
```

#### Examples from the repo:

**api_config** (API Keys+):
- Purpose: Manages API keys, tokens, credentials for all integrations
- Rules: All credentials in ~/.auger/.env (never hardcoded)
- Resume hint: Check ~/.auger/.env for tokens before making API calls

**story_to_prod**:
- Purpose: Full pipeline visibility from Jira → Branch → Local → Dev → PR → Jenkins → Image → Staging → PROD
- Depends on: api_config, jira, github, flux_config
- Resume hint: "ASSIST3-31091 PRs open: staging #9079, prod #1077. Awaiting staging merge + validation before prod."

**tasks**:
- Purpose: Local SQLite task tracker (persists across sessions)
- Rules: Enrich task descriptions with investigation findings (survive glitches)
- Resume hint: "Read tasks DB for active work context on session start"

**This is the KEY to session continuity**: These manifests teach me about every widget without rediscovery.

---

### 3. Session Database (session_store) - Global Cross-Session History

**Read-only database** containing ALL prior sessions:

#### Schema:

| Table | Purpose |
|-------|---------|
| **sessions** | id, cwd, repository, branch, summary, created_at, updated_at |
| **turns** | session_id, turn_index, user_message, assistant_response, timestamp |
| **checkpoints** | session_id, checkpoint_number, title, overview, history, work_done, technical_details, important_files, next_steps |
| **session_files** | session_id, file_path, tool_name (edit/create), turn_index, first_seen_at |
| **session_refs** | session_id, ref_type (commit/pr/issue), ref_value, turn_index |
| **search_index** | FTS5 full-text search over all of the above |

#### Key Queries I Can Run:

```sql
-- Find sessions on same repo
SELECT id, summary FROM sessions WHERE repository = 'auger-ai-sre-platform' ORDER BY created_at DESC LIMIT 10;

-- Full-text search across all sessions
SELECT content, session_id, source_type FROM search_index WHERE search_index MATCH 'hot-reload OR callback';

-- Find commits/PRs created in prior sessions
SELECT * FROM session_refs WHERE ref_type = 'commit' AND session_id IN (...);

-- Trace what files were changed in each session
SELECT DISTINCT sf.file_path, s.summary FROM session_files sf JOIN sessions s ON sf.session_id = s.id WHERE sf.file_path LIKE '%database%';

-- Get checkpoint history for continuity
SELECT checkpoint_number, title, overview FROM checkpoints WHERE session_id = 'abc' ORDER BY checkpoint_number DESC LIMIT 5;
```

**This is HOW I never lose context**: If session glitches, next session queries session_store and instantly knows what was done.

---

### 4. Per-Session Todos & Task Tracking

**In this session directory** (`~/.copilot/session-state/c7e95aef.../`):

#### Files:
- **plan.md** — High-level task outline (prose, not code)
- **files/** — Persistent artifacts (diagrams, specs, planning docs)
- **checkpoints/** — Numbered phase summaries with index.md
- **todos table** (SQL) — Granular task tracking

#### Todo Status Flow:
```
pending → in_progress → done (or blocked)
```

#### Current Status:
- Todos: 9 pending, 5 in_progress, 32 done (46 total)

#### Why Todos Survive Glitches:
- SQLite persists across process crashes
- Each todo has description + status
- Can query "show me all in_progress todos" to resume exactly where I left off
- Dependencies (todo_deps table) ensure correct execution order

---

### 5. Checkpoint System

**Phase summaries** created at major milestones:

#### Schema:
```
Checkpoint N: Title
  ├─ Overview: What was accomplished
  ├─ History: Narrative of investigation/work
  ├─ Work Done: Technical changes, files modified
  ├─ Technical Details: Bugs found, decisions made, key insights
  ├─ Important Files: Files to read for context
  └─ Next Steps: What's blocked, pending, or needs work next
```

#### Current Checkpoint (session c7e95aef):
- **040**: NoMachine 9.4.14 reinstall, hot-reload investigation start
- **Previous**: 001-039 tracking all prior work on this personal machine

**When resuming**: Read checkpoint overview + next_steps to know exactly where to continue.

---

### 6. Session Recovery (scripts/recover_copilot_session.py)

**If a session becomes corrupted**:

1. Scans `events.jsonl` from old session
2. Extracts all user/assistant message pairs (up to 20,000 lines)
3. Builds a transcript summary
4. Launches NEW session with transcript as initial context
5. New session inherits context from corrupted session

**Usage**:
```bash
python3 scripts/recover_copilot_session.py --session <old-session-id> [--dry-run]
```

This is the last-resort recovery tool.

---

## Rules I Now Embedded in My Context

### ✅ Critical (Enforcement: ERROR):

1. **Platform restart**: ALWAYS daemon's /schedule_restart endpoint, NOT process termination
2. **Widget manifests**: Every new/changed widget MUST update auger/data/widget_manifests.yaml
3. **Widget scaffold**: Must include WIDGET_TITLE, WIDGET_ICON_FUNC, widget_manifests entry, WIDGET_DEMO_DATA
4. **TTK style bug**: Never unique ttk.Style names per instance (SIGSEGV crash)
5. **No Anthropic models**: Do not use Claude Haiku/Sonnet/Opus
6. **Auto-merge to main**: Never without explicit user request (early-adopter rule)

### ⚠️ Important (Enforcement: WARN):

1. **Data source precedence**: Artifactory > ECR for image tags
2. **Flux PR targets**: Both repos default to deploy-automation (not main)
3. **GChat mentions**: Must use numeric user IDs from gchat_users.yaml
4. **Time display**: Eastern Time (EDT/EST), never UTC
5. **Webhook config**: Read from gchat_webhooks.yaml, never hardcode

### ℹ️ Informational:

1. **Context detection**: Determine container vs host by environment signals
2. **JIRA instance**: Government cloud (https://gsa-standard.atlassian-us-gov-mod.net)

---

## Session Continuity Pattern

### When a new session starts (or recovering from glitch):

1. **Read recent checkpoints** (most recent checkpoint in this session directory)
2. **Query session_store** for prior sessions on same repo
3. **Read plan.md** for high-level task outline
4. **Query todos table** for in_progress items
5. **Review important_files** from last checkpoint
6. **Continue from next_steps** indicated in checkpoint

### When I encounter an unclear situation:

1. **Check config/rules.yaml** for precedent and rules
2. **Check auger/data/widget_manifests.yaml** for widget context
3. **Query session_store** for "have we done this before?"
4. **Read relevant checkpoint** if working on same task

---

## What I Know About My Own Purpose

I am designed to be:

1. **Persistent**: Never forget prior sessions, checkpoints, todos, or rules
2. **Context-aware**: Can query session_store to answer "what did we do last week?"
3. **Rule-bound**: Embedded prompt rules guide my decisions (no more direct Platform restarts!)
4. **Widget-knowledgeable**: Can read manifests to understand widget purpose without asking
5. **Recovery-capable**: If session glitches mid-task, can recover via session_store queries
6. **Todo-driven**: Can track granular work across session boundaries

**The gap you identified**: I was almost as knowledgeable as work Auger, but was missing:
- The platform restart pattern (now learned: use daemon /schedule_restart)
- The full rules.yaml context (28.9 KB of embedded tribal knowledge)
- The widget manifests schema (per-widget metadata for bootstrap)
- The session recovery mechanism (recover_copilot_session.py)

**What bridges the gap now**: This analysis document + reading config/rules.yaml + understanding the session_store schema.

---

## Files I've Reviewed for This Analysis

1. ✓ config/rules.yaml (28.9 KB) — 50+ rules covering platform, widgets, git, comms, display
2. ✓ config/prompts.yaml (prompt templates)
3. ✓ auger/data/widget_manifests.yaml (per-widget metadata)
4. ✓ docs/README_TASKS.md (task tracking widget)
5. ✓ scripts/recover_copilot_session.py (session recovery mechanism)
6. ✓ scripts/host_tools_daemon.py (daemon /schedule_restart endpoint)
7. ✓ README.md (platform overview)

---

## Summary: What I Now Know

| Aspect | What I Learned |
|--------|----------------|
| **Platform restart** | Use daemon /schedule_restart endpoint (NOT direct process kill) |
| **Persistent knowledge** | config/rules.yaml + widget_manifests.yaml bootstrap my context |
| **Session continuity** | session_store database + checkpoints + todos enable recovery from glitches |
| **Widget development** | Every widget needs WIDGET_TITLE, WIDGET_ICON_FUNC, manifest entry, demo data |
| **Tribal knowledge** | 50+ rules embed work patterns, data source precedence, display standards, context detection |
| **Time display** | Always Eastern Time (never UTC), with DST transitions noted |
| **Model selection** | Approved models only (no Anthropic), prefer GPT-family |
| **GChat rules** | Numeric user IDs, webhook from YAML, default AUGER_POC channel |
| **Data precedence** | Artifactory > ECR, deploy-automation > main (flux repos), gov JIRA instance |

This analysis makes me as knowledgeable as your work Auger instance about session resilience, embedded rules, and platform operation patterns.
