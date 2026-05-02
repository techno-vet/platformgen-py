# Auger SRE Platform — Installation Guide

> **One command. Zero config. Platform comes up.**

## Prerequisites

- Amazon WorkSpace (Ubuntu) — Docker is pre-installed and running
- Network access to `artifactory.helix.gsa.gov`
- The repo cloned to `~/repos/auger-ai-sre-platform`

---

## Install — One Command

```bash
cd ~/repos/auger-ai-sre-platform && ./scripts/install_wizard
```

That's it — one entry point for everyone (first-time testers, contributors, and devs). The wizard will:

1. **Seeds `~/.auger/.env` from `.env.example` if needed** — early adopters can pre-fill it before onboarding.
2. **Auto-detects or prompts for your GitHub Copilot token** — checks `gh` CLI, env vars, `~/.auger/.env`.
3. **Auto-detects or prompts for your Enterprise GitHub token** — stores `GHE_TOKEN` in `~/.auger/.env` for GitHub/Prospector/git flows.
4. **Auto-detects or prompts for Artifactory credentials** — checks `~/.auger/.env` then `~/.astutl/astutl_secure_config.env` (AU Gold).
5. **Installs the host `auger` CLI** — terminal Ask Auger is available from `~/.local/bin/auger` even if later launch steps fail.
6. **Pulls the image and launches** — ~500 MB Docker pull (once only), starts the container, opens Auger on your desktop.
7. **Installs a GNOME launcher + tray autostart** — subsequent launches use the app grid (or `docker-run.sh` directly), and after workspace login the Auger task tray starts automatically.

**For AU Gold users:** fully silent — no prompts at all.

Optional before an onboarding session:

```bash
mkdir -p ~/.auger
cp ~/repos/auger-ai-sre-platform/.env.example ~/.auger/.env
chmod 600 ~/.auger/.env
```

Then pre-fill any values you already have.

---

## After First Launch

**Ask Auger is your onboarding assistant.** Once the platform is open, just ask:

> *"What credentials do I need to set up the Jira widget?"*
> *"Help me configure kubectl access"*
> *"Show me what's in my API Keys+ widget"*

Auger knows every widget's dependencies and will guide you through any remaining setup.

---

## Additional Credentials (configure as needed)

Open the **API Keys+** widget (🔑 tab) or edit `~/.auger/.env` directly:

| Integration | `.env` key | Where to get it |
|------------|-----------|----------------|
| Ask Auger | `GH_TOKEN` | github.com → Fine-grained personal access tokens → create one with `Copilot requests` permission |
| Enterprise GitHub | `GHE_TOKEN` (`GHE_URL` defaults to `https://github.helix.gsa.gov`) | github.helix.gsa.gov → Settings → Tokens |
| Kubernetes | auto | Loaded from `~/.kube/config` |
| Jira | `JSESSIONID` | Click **Login** in the Jira widget |
| Artifactory | `ARTIFACTORY_IDENTITY_TOKEN` (preferred) or legacy `ARTIFACTORY_API_KEY` | Artifactory UI → Profile / Authentication Settings |
| Rancher | `RANCHER_BEARER_TOKEN` | Rancher UI → API Keys |
| DataDog | `DATADOG_API_KEY`, `DATADOG_APP_KEY` | DataDog → Organization Settings |

---

## Updating Auger

```bash
docker rm -f auger-platform
bash ~/repos/auger-ai-sre-platform/scripts/auger-launch.sh
```

All your data (`~/.auger/`) is preserved — it lives on the host, not in the container.

---

## Stopping Auger

```bash
docker rm -f auger-platform
```

---

## Workspace Restart

After a workspace reboot, the **Auger task tray** auto-starts — the GNOME autostart entry is registered automatically the first time you run `auger-launch.sh`. The full platform window does **not** auto-open; users can launch it from the tray or from the GNOME app grid.

The tray also includes a **Keep Workspace Awake** toggle. It starts/stops a host-side GNOME session inhibitor so you can keep the workspace active without using a physical mouse jiggler.

---

## Troubleshooting

**Auger window doesn't appear:**
```bash
docker ps | grep auger-platform   # check it's running
docker logs auger-platform        # check for errors
```

**"No display" error:**
```bash
xhost +local:docker
docker rm -f auger-platform
bash ~/repos/auger-ai-sre-platform/scripts/auger-launch.sh
```

**Ask Auger not responding:**
- Open **API Keys+** widget → verify `GH_TOKEN` is set
- Token must be from **github.com** (not github.helix.gsa.gov)
- Tokens expire — regenerate at https://github.com/settings/tokens

**Docker login failed:**
- Use your FCS username (not email)
- Prefer your Artifactory **Identity Token**; API key is legacy-only if your account still has one
- Do **not** use your FCS password
- Get it: https://artifactory.helix.gsa.gov → Profile / Authentication Settings

**Need help?**
> Open Auger → Ask Auger: *"I'm having trouble with [describe the issue]"*

---

## Architecture

```
Your Amazon WorkSpace (host)
├── ~/.auger/           ← all config, tokens, task DB (persists forever)
├── ~/.kube/            ← kubectl config (mounted read-only)
├── ~/repos/            ← your git repos (mounted read-write)
│
└── Docker container: auger-platform
    ├── Python/Tk UI    ← renders on host X11 display
    ├── auger CLI       ← wraps GitHub Copilot for Ask Auger
    └── host daemon     ← Python HTTP server on localhost:7437
        (app launch, browser control, platform restart)
```

---

*Questions? Ask Auger — it knows the whole platform.*
