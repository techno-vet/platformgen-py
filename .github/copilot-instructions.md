# Auger AI SRE Platform — Copilot Instructions

You are helping someone install, configure, or use the **Auger AI SRE Platform** — a Tkinter-based desktop SRE tool that runs in a Docker container on an Amazon WorkSpace (Ubuntu). When a user asks how to install or set up Auger, follow the steps below precisely. When they hit an error, use the troubleshooting section to diagnose and fix it.

---

## What Is Auger?

Auger is a desktop SRE dashboard built for the ASSIST program at GSA. It runs as a Docker container that renders its Python/Tkinter UI on the host X11 display. It contains ~24 widgets (Pods, GitHub, Artifactory, Cryptkeeper, Database, ServiceNow, Ask Auger, etc.) and an embedded AI assistant ("Ask Auger") powered by GitHub Copilot.

**Architecture:**
```
Amazon WorkSpace (host)
├── ~/.auger/          ← all config, tokens, task DB (persists forever)
├── ~/.kube/           ← kubectl config (mounted read-only)
├── ~/repos/           ← git repos (mounted read-write)
└── Docker container: auger-platform
    ├── Python/Tk UI   ← renders on host X11 display
    ├── auger CLI      ← wraps GitHub Copilot for Ask Auger
    └── host daemon    ← localhost:7437 (Jira login, browser control)
```

---

## Installation (Primary Path — Docker on Amazon WorkSpace)

**Prerequisites:**
- Amazon WorkSpace running Ubuntu (Docker is pre-installed)
- Network access to `artifactory.helix.gsa.gov`
- The repo already cloned (if you're reading this in VS Code, you have it ✅)

### One command to install and launch

```bash
bash scripts/auger-setup.sh
```

That's it. `auger-setup.sh` will:
1. **Auto-detect** any existing GitHub Copilot token on your machine (checks `gh` CLI, env vars, git credential store, `~/.auger/.env`) — if found, asks if you want to use it
2. **Guide you** through creating a token if none is found (with exact steps)
3. **Prompt for Artifactory credentials** if not already saved (FCS username + Artifactory API key)
4. **Save everything** to `~/.auger/.env` and launch `auger-launch.sh`

`auger-launch.sh` then:
- Logs in to Artifactory and pulls the image (~500 MB, once only)
- Starts the container with X11, `~/.auger/`, `~/.kube/`, and `~/repos/` mounted
- Opens the Auger window on your desktop

### GitHub Copilot token — what it is and where to get one

The token must be from **github.com** (not the enterprise github.helix.gsa.gov). It's used for Ask Auger.

**Check if you already have one:**
```bash
gh auth status   # shows github.com token if gh CLI is configured
```

**Create a new one:**
1. Go to: https://github.com/settings/tokens → Generate new token (classic)
2. Name: `Auger Copilot`
3. Scopes: ✅ `repo`  ✅ `read:user`  ✅ `copilot` (if available)
4. Copy it — paste into `auger-setup.sh` when prompted

> Some engineers have `gh` CLI already configured with a github.com token — `auger-setup.sh` detects this automatically and asks if you want to reuse it.

### Step 3 — Add other credentials (when ready)

Open the **API Keys+** widget (🔑 tab) or edit `~/.auger/.env` directly:

| Widget | Key in `.env` | Where to get it |
|--------|--------------|-----------------|
| Ask Auger | `GH_TOKEN` | github.com → Settings → Tokens (set by wizard) |
| GitHub widget | `GHE_TOKEN` | github.helix.gsa.gov → Settings → Tokens |
| Artifactory | `ARTIFACTORY_IDENTITY_TOKEN` | Artifactory UI → Profile → API Key |
| Rancher/K8s | `RANCHER_BEARER_TOKEN` | Rancher UI → API Keys |
| ServiceNow | `SN_COOKIES` | Auto-captured by Host Tools login flow |
| DataDog | `DATADOG_API_KEY`, `DATADOG_APP_KEY` | DataDog UI → Organization Settings |

---

## Installation (Alternative — Python venv, for contributors/alpha testers without Docker)

**Prerequisites:** Python 3.10+, `python3-tk` system package, X11 display

```bash
git clone https://github.helix.gsa.gov/assist/auger-ai-sre-platform.git
cd auger-ai-sre-platform
python3 -m venv venv
source venv/bin/activate
pip install -e .
auger init --token YOUR_GITHUB_COM_COPILOT_TOKEN
auger start
```

If `python3-tk` is missing:
```bash
sudo apt-get install -y python3-tk
```

---

## Key File Locations

| File | Purpose |
|------|---------|
| `~/.auger/.env` | All credentials/tokens (600 permissions, never commit) |
| `~/.auger/config.yaml` | App configuration |
| `~/.auger/tasks.db` | SQLite task database |
| `~/.auger/rules.yaml` | Auger AI operational rules |
| `~/.auger/prompts.yaml` | User-defined prompt library |
| `~/.auger/widget_screenshots/` | Cached widget screenshots |
| `auger/ui/widgets/*.py` | Widget source files (hot-reloadable) |
| `auger/data/widget_manifests.yaml` | Widget AI context metadata |

---

## Updating Auger

```bash
docker rm -f auger-platform
bash auger-launch.sh
```

All data in `~/.auger/` is preserved — it lives on the host, not in the container.

---

## Common Errors and Fixes

### "Docker login failed" or "unauthorized"
- Use your **FCS username** (not email) and your **Artifactory API key** (not your FCS password)
- Get the API key: https://artifactory.helix.gsa.gov → click your username → Profile → API Key

### "Auger window doesn't appear" / blank screen
```bash
xhost +local:docker
docker rm -f auger-platform
bash auger-launch.sh
```

### "_tkinter.TclError: couldn't connect to display"
```bash
export DISPLAY=:0    # or :1 on NICE DCV workspaces
bash auger-launch.sh
```

### Container exits immediately
```bash
docker logs auger-platform
```
Look for Python import errors. Most common cause: `python3-tk` not available (Docker image issue — report to SRE).

### "Ask Auger not responding" / no AI replies
- Verify token: open **API Keys+** widget → check `GH_TOKEN` is set
- Token must be from **github.com**, not github.helix.gsa.gov
- Tokens expire — regenerate at https://github.com/settings/tokens if needed

### "ModuleNotFoundError" (venv install only)
```bash
cd ~/repos/auger-ai-sre-platform
pip install -e . --force-reinstall --no-deps
```

### GitHub widget shows no repos
- Set `GHE_TOKEN` in `~/.auger/.env` — this is your **enterprise** github.helix.gsa.gov token
- Generate at: https://github.helix.gsa.gov/settings/tokens (scopes: `repo`, `read:user`)

---

## Demos (no credentials required)

**Terminal demo** (shows all 26 widget sections with animated output):
```bash
python3 ~/repos/auger-ai-sre-platform/demo_auger_full.py --offline --auto
```

**UI slideshow** (HTML, opens in any browser):
```bash
# After git pull:
xdg-open ~/repos/auger-ai-sre-platform/demo_auger_ui.html
```

---

## Getting Help

1. **Ask Auger directly** — once running, type any question into the Ask Auger panel
2. **Docs in the repo:**
   - `INSTALLATION_GUIDE.md` — full install reference
   - `ALPHA_TESTING.md` — alpha tester tasks and expected behavior
   - `FAQ.md` — token confusion, common setup questions
   - `docs/QUICKSTART.md` — fastest path to running
3. **Report issues:** https://github.helix.gsa.gov/assist/auger-ai-sre-platform/issues

---

## For Contributors — Widget Development Rules

Every new widget `.py` file **must** include all of the following (enforced):
1. `WIDGET_TITLE = "Human Readable Name"` — tab label
2. `WIDGET_ICON_FUNC = staticmethod(make_icon)` — tab icon
3. Entry in `auger/data/widget_manifests.yaml` with: `title`, `purpose`, `depends_on`, `used_by`, `key_data_files`, `auger_rules`, `session_resume_hint`
4. `WIDGET_DEMO_DATA = {...}` — curated sample data returned when `AUGER_DEMO=1` env var is set

Hot-reload workflow: write file → verify live in app (no restart needed) → commit.

Git pushes always use HTTPS to `github.helix.gsa.gov`, never SSH, never github.com:
```bash
git push https://${GHE_TOKEN}@github.helix.gsa.gov/assist/auger-ai-sre-platform.git <branch>
```
