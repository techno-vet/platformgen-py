# Release Manager Widget

The **Release Manager** widget manages production deployments end-to-end — tracking services, PRs, deployment status, and audit history in a local SQLite database.

> **Status: Active Development** — Core deployment tracking is fully functional. Confluence integration (deployment notes publishing) is in progress.

## Features

| Feature | Detail |
|---------|--------|
| **Deployment tracker** | Create and manage named deployments with Jira story association |
| **Service list** | Add services with repo, branch, and deploy order |
| **PR tracking** | Link GitHub PRs to each service; track merge status |
| **Deployment log** | Time-stamped audit trail for every deployment event |
| **History** | Dropdown to review past deployments |

## Workflow

1. **Create a deployment** — give it a name and link the Jira story (e.g., `ASSIST-1234`)
2. **Add services** — list all services being deployed with their repos and branches
3. **Link PRs** — paste PR URLs for each service as they're opened
4. **Track merges** — mark PRs as merged as they get approvals
5. **Deploy** — trigger the deployment and record the timestamp
6. **Close** — mark deployment complete

## Database

Deployment history is stored at `~/.auger/logs/deployments.db` — persisted across container restarts via volume mount.

## Confluence Integration *(In Progress)*

The Release Manager will publish deployment notes to Confluence automatically:
- Create a Confluence page per deployment in the Release Notes space
- Include service list, PR links, Jira story, and deployment timestamp
- Update page status as deployment progresses

**Authentication:**
```bash
JIRA_COOKIES=<captured automatically by Jira widget login>
CONFLUENCE_BASE_URL=https://gsa-standard.atlassian-us-gov-mod.net/wiki
# Optional fallback:
CONFLUENCE_TOKEN=<your-confluence-api-token>
```

The widget now prefers the shared Atlassian MFA cookies captured by the Jira widget for `gsa-standard.atlassian-us-gov-mod.net` and falls back to `CONFLUENCE_TOKEN` only when needed.

## ⚠️ Production Safety

All service deployments to production still go through Flux Config (GitOps). This widget **tracks** the deployment — it does not push to prod directly. Production changes always require a `assist-prod-flux-config` PR with 2 approvals.

> **Tip:** Ask Auger: *"Create a Release Manager deployment for ASSIST-1234 with services data-utils and api-gateway"*
