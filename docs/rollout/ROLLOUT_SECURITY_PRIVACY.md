# Auger SRE Platform — Security & Privacy Considerations

**Version:** 1.0
**Audience:** ISSO, GSA IT Security, ATO Reviewers
**Status:** Draft for Review

---

## Scope

This document describes the security posture of the Auger AI SRE Platform, covering credential management, data handling, network boundary, AI usage, and compliance with GSA IT policies.

---

## 1. Credential Management

### Storage
All API credentials are stored in `~/.auger/.env` on the user's local workstation. This file:
- Is owned by and readable only by the individual user (`chmod 600` recommended)
- Is listed in `.gitignore` — **never committed to any repository**
- Contains user-scoped tokens (each user's own GHE token, Jira token, Jenkins token)
- Is never transmitted or shared by the application

### Secrets in Transit
- All API calls use HTTPS (TLS) to internal GSA endpoints
- No credentials are logged or included in GChat notifications
- GHE API token is passed in `Authorization: token <token>` HTTP headers over TLS

### No Shared Service Accounts
Auger does not use shared service accounts. Each user authenticates with their own credentials. Auger cannot perform any action that the user themselves could not perform via the respective tool's UI.

---

## 2. Data Classification

| Data Type | Source | Stored By Auger | Transmitted Outside GSA |
|-----------|--------|----------------|------------------------|
| Jira story details | Jira API | In memory only | No |
| Pod logs | kubectl/k8s API | In memory only | No |
| Database query results | RDS via psycopg2 | In memory only | No |
| Flux YAML files | GHE API | Local disk (flux_cache/) | No |
| GChat webhooks | gchat_webhooks.yaml | Local + GHE repo | URL only (to Google Chat, GSA Workspace) |
| AI chat context | Ask Auger panel | In memory per session | See AI section below |

### No PII in Automated Actions
Auger automated commits and GChat notifications contain:
- Jira story keys (e.g., ASSIST3-12345)
- Image tags and environment names
- GChat @mention user IDs (numeric, not PII)

No personally identifiable information beyond team member names (already in GChat group context) is included in automated messages.

---

## 3. Network Boundary

All Auger network traffic targets these endpoints:

| Endpoint | Protocol | Direction | Purpose |
|----------|----------|-----------|---------|
| `github.helix.gsa.gov` | HTTPS | Outbound | GHE API — code, PRs, commits |
| Jenkins (internal URL) | HTTPS | Outbound | Build status and triggers |
| Artifactory (internal URL) | HTTPS | Outbound | Image tag lookup |
| Jira (internal URL) | HTTPS | Outbound | Story and sprint data |
| RDS PostgreSQL endpoints | TCP 5432 | Outbound | Database queries (read-only) |
| EKS API server (internal) | HTTPS | Outbound | kubectl proxy — pod status, logs |
| `chat.googleapis.com` | HTTPS | Outbound | GChat webhook (GSA Google Workspace) |

**No traffic leaves the GSA network boundary except to GSA-managed Google Workspace (GChat).**

---

## 4. AI / LLM Usage

### Current Implementation
The Ask Auger AI panel invokes the `auger` CLI, which interacts with a language model for query resolution and command suggestions.

### Data Sent to AI
- User's natural language query
- Limited context: current widget state, recent command output
- **No database query results are sent to AI**
- **No pod log contents are sent to AI**
- **No credentials or secrets are sent to AI**

### AI Provider
The current implementation uses [self-hosted / internal LLM — to be confirmed by SRE lead]. If an external provider is used, all queries will be reviewed against GSA's AI usage policy and no ASSIST data will be included in prompts.

*Action item: Document the specific LLM endpoint and data handling before Phase 2.*

---

## 5. Git Automation Security

Auger automates git commits via the GHE REST API. Security properties:

- **Pull Requests only for protected branches** — Auger creates PRs, never direct pushes to `main` or production branches
- **2-approval enforcement** — the Story→Prod widget will not create a prod PR without a UI warning that 2 approvals are required; the actual enforcement is GHE branch protection
- **Commit attribution** — all automated commits include the user's GHE username and a `Co-authored-by: Copilot` trailer for audit clarity
- **Token scope** — the GHE token requires `repo` scope; it cannot create or delete repositories, manage org settings, or access other orgs

---

## 6. Database Access

- All database widget queries are executed as the configured DB user
- The platform does not expose an INSERT, UPDATE, or DELETE interface — the query text box is unrestricted but the intent is read-only; formal read-only DB user enforcement is recommended for production use
- Query results are displayed in the widget and not cached to disk

*Recommendation: Provision a dedicated read-only PostgreSQL role for Auger users.*

---

## 7. Known Limitations & Open Items

| Item | Status | Owner |
|------|--------|-------|
| Confirm LLM provider and data handling policy | Open | SRE Lead |
| Formal read-only DB role for Auger | Recommended | DBA team |
| ATO path: standalone vs. ASSIST program inheritance | Open | ISSO |
| Container image scan (Prospector) before GA | Planned (Phase 3) | SRE team |
| `.env` file permission enforcement (chmod 600) | Documented | User responsibility |

---

*Document generated by Auger AI · ASSIST SRE Platform · Draft v1.0*
