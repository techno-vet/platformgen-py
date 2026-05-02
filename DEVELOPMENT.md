# Auger Development Guide

## Hot-Reload (venv installations)

### The Challenge
When developing widgets in a venv installation, changes to `auger/ui/widgets/*.py` files need to be automatically detected and reloaded in the running Auger app without restarting.

### How It Works
The hot-reload system (`auger/ui/hot_reload.py`) runs a background thread that:
1. Scans `auger/ui/widgets/` every 1 second
2. Checks the **modification time (mtime)** of each `.py` file
3. When mtime changes, reloads the module and triggers callbacks
4. Callbacks update the UI and display `[RELOAD]` indicator on the widget tab

### Critical Setup Requirements

**1. Editable Install**
```bash
cd ~/repos/auger-ai-sre-platform
pip install -e .
```
This makes the venv point directly to the source tree (not a copy in site-packages). Without this, changes won't be visible to the running app.

**2. Touch Files After Editing**
```bash
touch ~/repos/auger-ai-sre-platform/auger/ui/widgets/github.py
```
The hot-reloader watches file **mtimes**, not file contents. When you edit a file in a separate terminal or editor (e.g., VS Code), the running Auger process isn't notified of the change. You must explicitly update the file's mtime by touching it.

Why? The reloader checks `path.stat().st_mtime` every 1 second (line 130 in hot_reload.py). External edits don't trigger OS notifications that would wake the reloader thread.

### Workflow

**After editing widget files:**
```bash
# 1. Make your changes in editor/terminal
# 2. Touch the files to trigger detection
touch auger/ui/widgets/github.py auger/ui/widgets/api_config.py

# 3. Watch Auger app — you should see [RELOAD] in tabs within 1 second
```

**If changes don't show up:**
1. Check if `pip install -e .` was run in the venv
2. Verify the file was touched (it should have current timestamp: `ls -l auger/ui/widgets/github.py`)
3. Check the app logs for hot-reload errors (search for `[*] Hot reload` or `Hot reload error`)
4. As a last resort, restart the daemon: `curl -X POST http://localhost:7437/schedule_restart`

### Example: Typical Development Session

```bash
# Terminal 1: Start Auger (runs in venv)
cd ~/repos/auger-ai-sre-platform
python3 -m auger start

# Terminal 2: Make changes
# - Edit auger/ui/widgets/github.py in VS Code or vim
# - Add your feature/fix
# - Save the file

# Terminal 3: Trigger hot-reload
touch ~/repos/auger-ai-sre-platform/auger/ui/widgets/github.py

# Back to Auger window: Within 1 second, you should see [RELOAD] on the GitHub tab
# Click to test your changes — no restart needed
```

## Notes for Copilot

When making widget changes via code edits:
1. **Always** commit changes via git (don't just touch — changes must be saved to files)
2. **Always** touch files after edits so running Auger detects the changes
3. Tell the user to check for `[RELOAD]` indicators
4. If hot-reload doesn't work, suspect either:
   - Missing `pip install -e .` in the venv
   - File wasn't touched after editing
   - Auger was started before `pip install -e .` was run

---

## Repository Structure

```
auger-ai-sre-platform/
├── auger/
│   ├── app.py                    # Main Auger app, initializes HotReloader
│   ├── cli.py                    # CLI for Ask Auger / copilot wrapper
│   ├── ui/
│   │   ├── hot_reload.py         # Hot-reload watcher thread
│   │   ├── widgets/              # All widget implementations (hot-reloadable)
│   │   │   ├── github.py
│   │   │   ├── api_config.py
│   │   │   └── ...
│   │   ├── content_area.py       # Main tab manager + [RELOAD] display
│   │   └── ...
│   └── ...
├── ~/.auger/                     # User config (persists across runs)
│   ├── .env                      # API keys, tokens
│   ├── tasks.db                  # SQLite task database
│   ├── config.yaml               # App settings
│   ├── rules.yaml                # Operational rules (future)
│   └── venv/                     # Virtual environment (venv mode only)
└── ...
```

---

## Adding a New Widget

1. Create `auger/ui/widgets/myfeature.py`
2. Import dependencies, set `WIDGET_TITLE` and `WIDGET_ICON_FUNC`
3. Add entry to `auger/data/widget_manifests.yaml`
4. Touch the file: `touch auger/ui/widgets/myfeature.py`
5. Watch for hot-reload — the new widget should appear as a new tab
6. Iterate: edit → save → touch → test (no restart needed)

See `auger/ui/widgets/github.py` for a complete example.

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| Changes don't appear in running Auger | File wasn't touched | `touch auger/ui/widgets/xxx.py` |
| `[RELOAD]` never shows | venv is using stale site-packages copy | `pip install -e .` in venv |
| Hot-reload errors in console | Module import failed | Check Python syntax: `python3 -m py_compile auger/ui/widgets/xxx.py` |
| Widget disappears entirely | Module crashed on reload | Check app logs for traceback |

---

## Environment Variables for Development

```bash
# Force offline mode (skip API calls, use demo data)
export AUGER_DEMO=1

# Verbose logging
export DEBUG=1

# Change hot-reload interval (seconds)
# Usually 1.0 is fine, increase if CPU usage is high
export AUGER_RELOAD_INTERVAL=2.0
```
