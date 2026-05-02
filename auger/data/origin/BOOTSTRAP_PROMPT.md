# Auger SRE Platform — Bootstrap Prompt

This is the original prompt that was used to create the Auger SRE Platform from scratch using AI (GitHub Copilot via the `auger` CLI tool). The entire platform was built 100% through AI-assisted development — no code was written manually.

**Date**: 2026-02-27  
**Model**: GitHub Copilot (claude-sonnet-4.6)  
**Tool**: `auger` CLI  

---

## THE PROMPT

---

Build a complete Python Tkinter desktop application called the **Auger SRE Platform** — a self-building AI-powered tool for Site Reliability Engineers. The app is designed so an embedded AI agent (invoked via a CLI tool named `auger`) can generate new SRE widgets dynamically at runtime. The architecture must be modular, hot-reloadable, and dark-themed.

---

## Project Structure

Create the following directory and file layout:

```
auger-sre/
 app.py                        # Main entry point
 requirements.txt
 config.yaml                   # Platform config (environments, thresholds, etc.)
 .env                          # API keys (gitignored)
 .gitignore
 logs/
    .gitkeep
 data/                         # Backend data clients and fetchers
    __init__.py
 ui/
    __init__.py
    content_area.py           # Tabbed content area with hot-reload
    ask_auger.py              # Bottom AI agent panel (runs `auger` CLI)
    hot_reload.py             # Watches ui/widgets/ every 1s for changes
    markdown_widget.py        # Dark-themed Markdown-rendering Text widget
    widgets/
        __init__.py
        api_config.py         # First built-in widget (API Key Configurator)
 venv/
```

---

## Core Architecture

### 1. `app.py` — Main Application

- Subclass `tk.Tk`, title: `" Auger — AI SRE Platform"`
- Window size: 1400×920, min 900×650
- Dark theme: bg `#1e1e1e`, use `ttk.Style` with `clam` theme
- **Vertical PanedWindow**: top = `ContentArea` (60% height), bottom = `AskAugerPanel` (40%)
- **Menu bar** with these menus:
  - **File**: New Session (`Ctrl+N`), Clear Chat (`Ctrl+L`), separator, Exit (`Ctrl+Q`)
  - **View**: Tabbed / Stacked / Grid (stubs for layout switching)
  - **Widgets** submenu:
    - "Manage Widgets…" — shows messagebox with usage examples
    - separator
    - " API Key Configurator" — opens `APIConfigWidget` tab
    - " Service Health Monitor" — sets a sample prompt in AskAuger
    - " Alert Manager" — sets a sample prompt in AskAuger
    - " Runbook Widget" — sets a sample prompt in AskAuger
  - **Help**: "What can Auger do?" (sets sample prompt), About
- **CRITICAL**: Menu items that open widget tabs must NOT import the widget class at startup. They must do a live lookup from `sys.modules` every time they are clicked, like this:
  ```python
  command=lambda: self.content.add_widget_tab(
      "API Keys",
      sys.modules.get("ui.widgets.api_config",
                      __import__("ui.widgets.api_config", fromlist=["APIConfigWidget"])
                     ).APIConfigWidget)
  ```
  This is essential so that after hot-reload, the menu always opens the latest version of the widget.
- Start `HotReloader` after layout is built; wire its `on_change` callback to `content.hot_reload_update(path, module)`
- `_on_close`: stop reloader, destroy window

### 2. `ui/content_area.py` — Tabbed Content Area

Subclass `ttk.Notebook`. Key methods:

- `_add_home_tab()`: adds a Home tab with the app title `" Auger SRE Platform"`, subtitle `"Ask Auger below to build your platform"`, and a hint like `'Try: "create a service health monitor widget"'`
- `add_widget_tab(name, widget_class, **kwargs)`: instantiate `widget_class(frame)`, add as new tab, select it. On error show a red error label in the tab.
- `load_widget_from_code(code, name=None)`: parse the first `class Xxx(` from generated Python code, save to `ui/widgets/<name>.py` — the hot reloader picks it up automatically and creates the tab.
- `hot_reload_update(path, module)`: called by HotReloader. Find the `tk.Frame` subclass in the module. If a tab with that file stem already exists, replace its contents in-place (destroy children, re-instantiate). Flash the tab title with `" "` prefix for 1.2 seconds. If it's a new file, open as new tab.
- Right-click on any tab to close it (except Home).

### 3. `ui/hot_reload.py` — Hot Reloader

- Polls `ui/widgets/*.py` every 1.0 seconds using `threading.Thread` (daemon)
- On create or mtime change: `importlib.reload()` if already in `sys.modules`, else load fresh via `importlib.util.spec_from_file_location`
- Calls all registered `on_change(path, module)` callbacks
- Never crashes on syntax errors in widget files — catch and print, continue watching

### 4. `ui/markdown_widget.py` — Markdown Text Widget

Subclass `tk.Text`. Dark theme bg `#1a1a2e`, fg `#e0e0e0`. Renders:
- `# H1` → large teal bold (`#4ec9b0`, size 22)
- `## H2` → medium teal bold (size 17)
- `### H3` → blue bold (`#9cdcfe`, size 13)
- `**bold**`, `*italic*`, `***bold italic***`
- `` `inline code` `` → orange on dark bg (`#ce9178` on `#2d2d2d`)
- ` ```code block``` ` → yellow on black (`#dcdcaa` on `#111111`)
- `- bullet` and `* bullet` lists with `•` prefix
- `---` horizontal rule
- `> blockquote` → indented, grey italic
- Plain text fallback for anything not matched
- Methods: `append_markdown(text)`, `append_raw(text, tag="")`, `clear()`, `see(END)`
- Always re-enables then re-disables state around writes

### 5. `ui/ask_auger.py` — Ask Auger Panel

This is the AI agent interface at the bottom of the window. It runs the `auger` CLI tool as a subprocess and streams output into the markdown widget.

- Header bar: dark blue `#007acc`, label `"  🤖  Ask Auger"`, italic status label on right
- Response area: `MarkdownWidget` in a scrollable frame (takes up most of the panel)
- Input bar at the BOTTOM (packed `side=BOTTOM` BEFORE the response frame so it stays visible):
  - Multi-line `tk.Text`, height=2, dark themed
  - **Enter** = send, **Shift+Enter** = newline
  - "Ask  " button (blue), "Clear" button below it
- Locate `auger` binary: `shutil.which("auger") or str(Path.home() / ".local/bin/auger")`
- Run `auger` as subprocess: `subprocess.Popen([_AUGER, prompt], stdout=PIPE, stderr=STDOUT, text=True, bufsize=1)`
- Stream output line-by-line, strip ANSI escape codes with `re.sub(r"\x1b\[[0-9;]*[mK]", "", line)`
- Use a `queue.Queue` polled every 80ms via `self.after(80, self._poll_queue)` — NEVER update Tkinter widgets from background threads
- After response is complete, scan for Python code blocks containing `tk.Frame` subclasses. If found, offer a `messagebox.askyesno` to load the widget into the content area
- Welcome message (on init):
  ```
  ##  Auger AI Agent

  I'm your AI SRE assistant. Ask me anything, or build your platform:

  - `create a widget to configure and test API keys for PagerDuty, Datadog, and AWS`
  - `create a service health monitor widget`
  - `create an alert manager widget`
  - `create a Kubernetes pod status widget`
  - `create a log tail widget`

  Generated widgets will appear as tabs above. **Shift+Enter** for newline, **Enter** to send.
  ```
- Public method `set_prompt(text)` — populates input field (used by menu items)

---

## 6. `ui/widgets/api_config.py` — API Key Configurator Widget

This is a built-in widget. Subclass `tk.Frame`. Full dark theme matching the app.

### Layout
- Title: `"  API Key Configurator"` (teal, bold, size 16)
- Subtitle showing `.env` file path (grey, size 9)
- Vertically scrollable `tk.Canvas` + inner frame for all sections
- At the bottom: `"  Save to .env"` button (blue) left, `"  Reload"` button (grey) right
- Status log: `tk.Text` height=6, monospace, dark bg, with `ok` (teal), `err` (red), `info` (light blue) tags

### Sections (each separated by a `#3c3c3c` 1px divider)

Each section header is a **clickable underlined label** that opens the API registration URL in the system browser via `xdg-open` + `DISPLAY=:1001`. A `"↗"` symbol appears next to clickable headers.

Each section has a **🧪 Test Connection** button aligned to the RIGHT edge of the section.

#### Section 1: PagerDuty
- URL: `https://app.pagerduty.com/api_keys`
- Fields: `PAGERDUTY_API_KEY` (API Key, masked with  toggle), `PAGERDUTY_BASE_URL` (Base URL, default `https://api.pagerduty.com`)
- Test: `GET /abilities` with `Authorization: Token token=<key>`. 200 = valid, 401 = invalid key.

#### Section 2: Datadog
- URL: `https://app.datadoghq.com/organization-settings/api-keys`
- Fields: `DATADOG_API_KEY` (API Key, masked), `DATADOG_APP_KEY` (App Key, masked), `DATADOG_SITE` (Site, e.g. `datadoghq.com`)
- Test: `GET https://api.<site>/api/v1/validate` with `DD-API-KEY` header. 200 = valid.

#### Section 3: AWS
- URL: `https://console.aws.amazon.com/iam/home#/security_credentials`
- Fields: `AWS_ACCESS_KEY_ID` (Access Key ID, plain), `AWS_SECRET_ACCESS_KEY` (Secret, masked), `AWS_DEFAULT_REGION` (Region, plain)
- Test: Use `boto3.client('sts').get_caller_identity()` — if `boto3` not installed, fall back to a signed `GET https://sts.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15`. 200 = valid, any auth error = invalid.

#### Section 4: Grafana
- URL: `https://grafana.com/auth/sign-in`
- Fields: `GRAFANA_URL` (Base URL), `GRAFANA_API_KEY` (Service Account Token, masked)
- Test: `GET <url>/api/health` — no auth needed, 200 confirms Grafana is reachable. Then `GET <url>/api/org` with `Authorization: Bearer <key>` — 200 = key valid.

#### Section 5: Kubernetes / kubectl
- URL: `https://kubernetes.io/docs/tasks/tools/`
- Fields: `KUBECONFIG` (Path to kubeconfig file), `KUBE_CONTEXT` (Context name)
- Test: Run `kubectl --kubeconfig <path> --context <ctx> cluster-info` as subprocess. Parse stdout for "running" to confirm connectivity.

### Save logic
- `set_key(str(ENV_FILE), key, val)` for every non-empty field
- Show `messagebox.showinfo("Saved", "API keys saved to .env")`

### Load logic
- `load_dotenv(ENV_FILE, override=True)` then `var.set(os.getenv(key, ""))` for each field

---

## 7. `requirements.txt`

```
requests>=2.31.0
python-dotenv>=1.0.0
pyyaml>=6.0.1
boto3>=1.34.0
rich>=13.7.0
click>=8.1.7
```

---

## 8. `config.yaml` — starter config

```yaml
platform:
  name: Auger SRE Platform
  version: "1.0"

environments:
  - name: production
    color: "#f44747"
  - name: staging
    color: "#f0c040"
  - name: development
    color: "#4ec9b0"

thresholds:
  error_rate_pct: 1.0
  latency_p99_ms: 500
  cpu_pct: 80
  memory_pct: 85
```

---

## 9. Style Constants (use throughout)

```python
BG     = "#1e1e1e"   # main background
BG2    = "#252526"   # secondary background
FG     = "#e0e0e0"   # foreground text
ACCENT = "#007acc"   # blue accent (buttons, header)
GREEN  = "#4ec9b0"   # success / teal
RED    = "#f44747"   # error / alert
YELLOW = "#f0c040"   # warning
```

---

## 10. Critical Implementation Rules

1. **Never update Tkinter widgets from background threads** — always use `self.after(0, lambda: ...)` or a `queue.Queue` polled with `self.after(80, self._poll_queue)`
2. **Hot reload** watches `ui/widgets/*.py` every 1 second. New widgets written there are automatically loaded as tabs — no restart needed.
3. **Menu widget references** must use live `sys.modules` lookups (not static imports) so hot-reloaded classes are always used when opening from the menu.
4. **`DISPLAY=:1001`** must be set in the environment for `xdg-open` calls (NoMachine session).
5. **All widgets** are `tk.Frame` subclasses saved in `ui/widgets/`. The hot reloader finds them by scanning `dir(module)` for `issubclass(obj, tk.Frame)`.
6. **`.env`** is the single source of truth for all credentials. Never hardcode secrets.
7. Run the app with: `DISPLAY=:1001 python3 app.py` from the project root with the venv activated.
8. **⚠️ PRODUCTION FLUX — ALWAYS ASK BEFORE MERGING/PUSHING**: Never commit, push, or merge changes to the `assist-prod-flux-config` repository (or any file under a `production` Flux environment path) without **explicitly asking the user for confirmation first**. This applies to image tag updates, HelmRelease edits, and any other file changes. Lower environments (development, staging, test) may be pushed after confirming the change looks correct, but production is always a manual gate.

---

## What to Build First

After creating the full framework, verify it works by:
1. Running `python3 app.py` — the home tab and Ask Auger panel should appear
2. Opening Widgets → API Key Configurator — should show all 5 sections
3. Typing in Ask Auger: `create a simple hello world widget` — should generate a widget, offer to load it, and it should appear as a new tab that hot-reloads on save
