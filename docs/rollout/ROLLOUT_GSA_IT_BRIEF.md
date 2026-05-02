# Auger AI SRE Platform — GSA IT Executive Brief

**Date:** March 2026
**Prepared by:** ASSIST SRE Team
**Distribution:** GSA IT Leadership, ISSO, Security Review Board

---

## What Is Auger?

Auger is an internal AI-assisted platform built by the ASSIST SRE team to manage software deployments, infrastructure monitoring, and release operations for the ASSIST program. It runs as a desktop application on SRE and developer workstations within the GSA network.

**It is not a SaaS product. It is not a vendor tool. It is purpose-built by ASSIST engineers for ASSIST workflows.**

---

## Problem It Solves

The ASSIST deployment pipeline spans 8+ separate tools: Jira (story tracking), GitHub Enterprise (code), Jenkins (CI/CD), Artifactory (image registry), Flux (GitOps), Kubernetes (runtime), ServiceNow (change management), and GChat (coordination). Engineers context-switch between all of these for every deployment, which:

- Increases human error (wrong image tag copied, wrong environment promoted)
- Slows incident response (multiple tools to check during an outage)
- Creates documentation gaps (actions taken in UI, not auditable in git)
- Reduces developer visibility (developers can't see pipeline status without SRE access)

---

## How Auger Addresses This

Auger provides a single desktop workspace that:
1. **Reads from** all ASSIST tools via their existing APIs (read-only where possible)
2. **Acts on** deployment workflows via GHE API (creates PRs, not direct pushes)
3. **Notifies** stakeholders via GChat when human action is required
4. **Enforces** existing policies (2-approval rule for prod, no direct push to main)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                  GSA Network Boundary            │
│                                                   │
│  [Auger Desktop App]                              │
│       │                                           │
│       ├── GHE Enterprise API (github.helix.gsa.gov)
│       ├── Jenkins API (internal)                  │
│       ├── Artifactory API (internal)              │
│       ├── Jira API (internal)                     │
│       ├── kubectl → EKS (internal VPC)            │
│       ├── PostgreSQL (ASSIST RDS, internal)       │
│       └── GChat Webhooks (Google Workspace)       │
│                                                   │
│  ✅ All data stays within GSA boundary            │
│  ✅ No external AI calls (self-hosted LLM)        │
│  ✅ No data persisted outside workstation         │
└─────────────────────────────────────────────────┘
```

---

## Security Posture

### Credentials & Secrets
- All credentials (GHE token, Jenkins API token, Jira token, etc.) stored in `~/.auger/.env` on the local workstation — **never in source code, never in the repository**
- The `.env` file is in `.gitignore` and is never committed
- Each user has their own credentials scoped to their GHE role — Auger cannot escalate beyond the user's existing permissions

### Data Handling
- Auger does not store, transmit, or cache ASSIST data outside the workstation
- Database queries are read-only (SELECT) — no INSERT/UPDATE/DELETE capability
- Log data viewed in K8s Explorer is streamed and not persisted

### Git Automation
- All automated git actions create GitHub Pull Requests — never direct pushes to protected branches
- All commits include structured messages with author attribution and Co-authored-by trailers
- Production deployments require 2 approvals — enforced at the platform level, not bypassable through Auger

### AI Panel (Ask Auger)
- The AI panel currently uses a self-hosted or locally-running language model
- No queries, code, or ASSIST data are sent to external commercial AI providers (OpenAI, Anthropic, etc.)
- This will be verified as part of the ATO review process

### Network
- All API calls target `*.gsa.gov`, `*.amazonaws.com` (within GSA's AWS accounts), or Google Chat webhooks (GSA-managed Google Workspace)
- No calls to external SaaS platforms, personal GitHub, or public cloud resources

---

## Compliance Touchpoints

| Requirement | How Auger Addresses It |
|------------|----------------------|
| Change management (CM) | All deployments produce a GHE PR with approval trail |
| Audit logging | Every automated action is a git commit with timestamp + author |
| Least privilege | Auger uses the user's own credentials — no shared service accounts |
| Data boundary | All traffic stays within GSA network |
| AI governance | Internal model only — no external AI data sharing |

---

## What We Are Asking For

1. **Awareness**: Acknowledge receipt of this brief and that the platform exists
2. **Review**: Share any security or compliance concerns before Phase 2 (Beta) rollout
3. **Informal sign-off**: Agreement that Phase 2 (expanding to developer teams) may proceed
4. **ATO path guidance**: Input on whether Auger requires a standalone ATO or can inherit ASSIST program coverage

We are not asking for an immediate formal authorization. We are asking for early engagement so we can address any concerns before broad rollout.

---

## Contact

**ASSIST SRE Lead:** Bobby Blair (bobby.blair@gsa.gov)
**Platform:** Auger AI SRE Platform, `auger-ai-sre-platform` repo on GHE

---

*Document generated by Auger AI · ASSIST SRE Platform · Draft v1.0*
