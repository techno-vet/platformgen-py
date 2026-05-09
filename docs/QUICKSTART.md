# PlatformGen — Quick Start

**Time to first launch: ~5 minutes** (mostly Docker pull on first run)

## Prerequisites

- Amazon WorkSpace running Ubuntu
- Docker installed (pre-installed on standard WorkSpaces)
- Network access to `artifactory.helix.gsa.gov`

---

## Step 1 — Clone the repo

```bash
mkdir -p ~/projects && cd ~/projects
# Use your current PlatformGen checkout URL if cloning fresh:
git clone <platformgen-repo-url> platformgen-py
cd platformgen-py
```

---

## Optional Step 1a — Pre-fill `~/.platformgen/.env`

```bash
mkdir -p ~/.platformgen
cp .env.example ~/.platformgen/.env
chmod 600 ~/.platformgen/.env
```

You can leave values blank and only fill in the keys you already have before onboarding.

---

## Step 2 — Run the install wizard

```bash
./scripts/install_wizard
```

The wizard will:
1. **Auto-detect credentials** from AU Gold (`~/.astutl/`), `gh` CLI, or env vars — no typing required if you have AU Gold installed
2. **Capture missing GitHub tokens early** — both `GH_TOKEN` (github.com) and `GHE_TOKEN` (github.helix.gsa.gov)
3. **Validate** each credential live before saving (GitHub, Enterprise GitHub, Artifactory image access)
4. **Pull the image** from Artifactory (~500 MB, once only)
5. **Launch PlatformGen** — the platform window opens on your desktop

> **AU Gold users**: the wizard detects `astutl_secure_config.env` automatically and imports Artifactory, GitHub, DataDog, Rancher, Jenkins, Jira, and Cryptkeeper keys silently — you likely won't be prompted for anything.

> **No AU Gold?** The wizard will ask for your `github.com` token, your `github.helix.gsa.gov` token, and your Artifactory credentials, then validate them before proceeding.

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
| Ask Genny | `GH_TOKEN` | github.com → Fine-grained personal access tokens → create one with `Copilot requests` permission |
| GitHub widget | `GHE_TOKEN` (`GHE_URL` defaults to `https://github.helix.gsa.gov`) | github.helix.gsa.gov → Settings → Tokens |
| Artifactory | `ARTIFACTORY_IDENTITY_TOKEN` (preferred) or legacy `ARTIFACTORY_API_KEY` | Artifactory → Profile / Authentication Settings |
| Rancher/Pods | `RANCHER_BEARER_TOKEN` | Rancher → API Keys |
| DataDog | `DATADOG_API_KEY`, `DATADOG_APP_KEY` | DataDog → Org Settings |
| Jira | `JIRA_API_TOKEN` | gsa-standard.atlassian-us-gov-mod.net → Profile |
| Jenkins | `JENKINS_API_TOKEN` | jenkins-mcaas.helix.gsa.gov → Configure |

Open the **API Keys+** tab (🔑) inside PlatformGen to add or update any credential.

---

## Updating PlatformGen

```bash
cd ~/projects/platformgen-py
git pull
docker rm -f platformgen-platform
bash scripts/platformgen-launch.sh
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Window doesn't appear | `xhost +local:docker` then re-run |
| `couldn't connect to display` | `export DISPLAY=:0` then re-run |
| Container exits immediately | `docker logs platformgen-platform` |
| Ask Genny not responding | Check `GH_TOKEN` in API Keys+ — must be github.com token |
| Artifactory login failed | Use Identity Token (not password); API key is legacy only |

Full install guide: `INSTALLATION_GUIDE.md`  
Alpha testing tasks: `ALPHA_TESTING.md`
