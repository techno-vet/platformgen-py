# Flux Config Widget

The **Flux Config** widget manages GitOps deployments via the Flux CD configuration repositories. It provides a safe UI for toggling service deployments and managing git operations across dev and prod flux repos.

## Overview

Flux CD deploys services by watching YAML files in two repos:

| Repo | Env | Path in `.env` |
|------|-----|---------------|
| `assist-flux-config` | Dev / Lower | `FLUX_REPO_DEV` |
| `assist-prod-flux-config` | **Production** | `FLUX_REPO_PROD` |

## ⚠️ Production Safety Rule

> **CRITICAL**: Changes to `assist-prod-flux-config` **always require 2 PR approvals** before merging — even for SRE team members with direct push access. **Never push directly to prod flux-config main.**

The widget enforces this by creating PRs for prod changes and displaying a warning banner.

## Features

- **Toggle deploy/undeploy** — Rename `.yaml` ↔ `.ignore` to deploy or undeploy a service (Airflow pattern)
- **Git pull** — Pull latest from all flux repos
- **Git status / diff** — View pending changes before committing  
- **Commit + push** — Commit with a conventional message and push
- **PR creation** — Creates a GHE pull request for review

## Workflow

1. Select the target environment (Dev or Prod) in the repo selector
2. Find the service in the file list
3. Toggle its state (deploy ↔ undeploy) or edit the YAML
4. Review the diff
5. **Dev**: commit and push directly to your feature branch
6. **Prod**: create a PR — wait for 2 approvals before merging

## Configuration (`.env`)

```bash
FLUX_REPO_DEV=/home/user/repos/assist-flux-config
FLUX_REPO_PROD=/home/user/repos/assist-prod-flux-config
GHE_TOKEN=<your-enterprise-github-token>
```

> **Tip:** *"Ask Auger to create a flux PR to deploy cryptkeeper to prod"*
