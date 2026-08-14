# PlatformGen — Quick Start

**Time to first launch: ~3 minutes**

## Prerequisites

- Python 3.10+
- X11 display (for UI rendering)

---

## Step 1 — Clone and Install

```bash
git clone https://github.com/techno-vet/platformgen-py.git
cd platformgen-py
python3 scripts/install_wizard.py
```

The installer will:
1. ✅ Create a Python virtual environment in `~/.platformgen/`
2. ✅ Install all dependencies (including `python3-tk`)
3. ✅ **Prompt for your GitHub Copilot token** (required for Ask Genny)
4. ✅ Add `genny` command to your PATH
5. ✅ Optionally install GitHub Copilot CLI

**Optional pre-install (Ubuntu/Debian only):**
```bash
sudo apt-get install python3-tk
```

---

## Step 2 — Launch PlatformGen

```bash
genny start
```

The app window will open on your desktop.

---

## Step 3 — Ask Genny anything

Once the window opens, click the **Ask Genny** panel and type:

```
what can you do?
```

Genny will walk you through the available widgets and next steps.

---

## Credentials reference

| Widget | Key in `~/.platformgen/.env` | Where to get it |
|--------|----------------------|----------------|
| Ask Genny | `GH_TOKEN` | github.com → Settings → Developer settings → Personal access tokens → Fine-grained tokens (need `Copilot requests` scope) |
| GitHub widget | `GHE_TOKEN` | github.helix.gsa.gov → Settings → Developer settings → Personal access tokens |
| Artifactory | `ARTIFACTORY_IDENTITY_TOKEN` | Artifactory → Profile → Settings → API Token |
| DataDog | `DATADOG_API_KEY`, `DATADOG_APP_KEY` | DataDog → Organization settings → API keys |

Open the **API Keys+** tab (🔑) inside PlatformGen to add or update any credential.

---

## Updating PlatformGen

```bash
cd platformgen-py
git pull
python3 scripts/install_wizard.py
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `DISPLAY` not set | `export DISPLAY=:0` (or `:1` for NICE DCV) |
| Ask Genny not responding | Check `GH_TOKEN` in API Keys+ — must be github.com token (not enterprise) |
| Missing `python3-tk` | `sudo apt-get install python3-tk` (Linux) or `brew install python-tk` (macOS) |
| Permission denied on `genny` command | Log out and back in, or run: `export PATH="$HOME/.local/bin:$PATH"` |

Full install guide: `INSTALLATION_GUIDE.md`  
Alpha testing tasks: `ALPHA_TESTING.md`
