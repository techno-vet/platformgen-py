# Fix: Auger Platform Launch SIGSEGV and Setup Hang

## Summary

Two bugs prevented the Auger SRE Platform from launching reliably on developer workstations:

1. **SIGSEGV (exit 139)** — Container crashed immediately after restoring all widgets on startup.
2. **Install wizard hang** — The setup wizard hung indefinitely at the "detecting GitHub token" step.

---

## Bug 1: SIGSEGV on Startup (exit 139)

### Root Cause

`auger/ui/hot_reload.py` — the background file watcher — called `importlib.reload()` on
ui-level modules (e.g. `ask_auger.py`, `content_area.py`, `status_bar.py`) during its **initial
scan** at startup. These modules were already loaded and active as live Tkinter widget classes.

Calling `importlib.reload()` on a live Tkinter class from a background thread corrupts Tcl/Tk
internals, causing a SIGSEGV crash (Python exits with code 139).

### Fix

**`auger/ui/hot_reload.py`** — two changes:

1. **Skip reload on initial scan for ui/ files.** The initial pass only records the mtime; it no
   longer calls `_reload_ui_module()`. Reloading only occurs on subsequent detected file changes
   (the intended hot-reload use case).

2. **Exclude `content_area.py` from the ui/ watch loop.** `ContentArea` is a core Tkinter
   `tk.Frame` subclass that is never safe to reload from a background thread while the app is
   running.

**`Dockerfile.user`** — added a `COPY` step to inject the patched `hot_reload.py` into
`/home/auger/auger-platform/auger_baked/ui/` during every personalized image build. This ensures
the fix is present even when the base image is rebuilt from Artifactory.

---

## Bug 2: Install Wizard Hang at GitHub Token Detection

### Root Cause

`scripts/install_wizard.py` — the `_detect_gh_token()` function ran `git credential fill` as a
subprocess. When no credential helper is configured, Git opens `/dev/tty` directly (bypassing
stdin) to prompt the user interactively. This blocked the setup thread indefinitely since the
wizard runs in a non-interactive subprocess context.

### Fix

**`scripts/install_wizard.py`** — added `GIT_TERMINAL_PROMPT=0` to the environment of the
`git credential fill` subprocess call. This prevents Git from attempting any interactive terminal
prompt; it fails fast (non-zero exit) instead of hanging, allowing the wizard to continue.

---

## Files Changed

| File | Change |
|------|--------|
| `auger/ui/hot_reload.py` | Skip ui/ reload on initial scan; exclude `content_area.py` from watch loop |
| `Dockerfile.user` | COPY patched `hot_reload.py` into `auger_baked/ui/` during image build |
| `scripts/install_wizard.py` | Set `GIT_TERMINAL_PROMPT=0` on `git credential fill` subprocess |

## Commit

`fix(hot-reload): prevent SIGSEGV from reloading live Tkinter modules on startup`
