# API Keys+ Widget

The **API Keys+** widget (`🔑`) is PlatformGen's credential management center. It provides a secure UI for viewing, editing, and validating the API tokens and credentials stored in `~/.platformgen/.env`.

## What It Manages

| Credential | Purpose |
|-----------|---------|
| `GHE_TOKEN` | Enterprise GitHub (github.helix.gsa.gov) — used for git push, API calls |
| `GH_TOKEN` | GitHub.com — used exclusively for GitHub Copilot (Ask Genny) |
| `JIRA_COOKIES` | Jira PIV/MFA session cookies for the Jira widget |
| `ARTIFACTORY_IDENTITY_TOKEN` | Artifactory identity/access token for docker login and package pull |
| `RANCHER_BEARER_TOKEN` | Rancher/Kubernetes API token for the Pods widget |
| `CONFLUENCE_TOKEN` | Confluence API token for the Release Manager widget |
| `JENKINS_API_TOKEN` | Jenkins CI token |

## Features

- **View** all configured keys (values masked by default)
- **Edit** any key directly in the UI
- **Validate** tokens with a live API test button
- **Save** changes immediately to `~/.platformgen/.env`

## Security

- Values are stored in `~/.platformgen/.env` which is volume-mounted (not baked into the Docker image)
- The file is only readable by your user
- Never commit `~/.platformgen/.env` to git

## First-Time Setup

When PlatformGen starts for the first time with no `.env`, the **First-Run Wizard** guides you through setting up `GHE_TOKEN` (the most critical credential). Once Ask Genny is working, you can configure everything else through this widget or by asking Genny for help.

> *"Help me set up my Jira cookie authentication"*
> *"How do I generate an Artifactory Identity Token?"*
