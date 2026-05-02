# Auger SRE Platform — Use Cases

**Version:** 1.0 (Alpha)
**Audience:** GSA IT Stakeholders, ASSIST Program Teams
**Status:** Draft for Socialization

---

## Overview

Auger is an AI-assisted SRE platform that consolidates the tools, data, and workflows used by the ASSIST SRE team into a single desktop application. Instead of toggling between Jira, Jenkins, Kubernetes dashboards, Artifactory, Flux configs, ServiceNow, and GChat, engineers operate from one context-aware workspace.

---

## Platform-Level Use Cases

| # | Use Case | Before Auger | With Auger |
|---|----------|-------------|------------|
| P1 | Full deployment pipeline visibility | Check Jira → Jenkins → Artifactory → Flux → k8s separately | Single Story→Prod view shows all stages in real time |
| P2 | On-call incident triage | SSH to cluster, run kubectl, check DataDog in browser | K8s Explorer: pods, logs, describe — all in one widget |
| P3 | Promote a fix from DEV to STAGING | Find flux YAML, edit tag, push branch, open PR, get 2 reviews | Flux Config widget: auto-generates PR with correct image tag |
| P4 | Notify stakeholders of a deployment block | Manually DM people in GChat | Auger auto-@mentions assignee/SRE/PO via GChat on block events |
| P5 | Security vulnerability scan before release | Run separate CVE tools, parse output manually | Prospector widget surfaces CVEs inline |
| P6 | Secret rotation or retrieval | Log into Cryptkeeper web UI separately | Cryptkeeper widget handles encrypt/decrypt in-app |
| P7 | Create a PR and shepherd through review | Open GitHub, create PR, manually ping reviewers | GitHub widget creates PR; Auger pings SRE review channel |
| P8 | Run ad-hoc kubectl/bash commands | Open a terminal, remember full command syntax | Shell Terminal widget with pre-loaded context (namespace, env) |

---

## Widget-Level Use Cases

### 📋 Jira Widget
- View active sprint stories and their assignees without opening a browser
- Drill into story details (acceptance criteria, linked PRs, labels) from the pipeline view
- Look up story assignee email for automatic GChat @mention routing

### 🚀 Story → Prod Pipeline
- Trace a single Jira story from creation through branch, build, image, flux config, to live pod
- See at a glance which stage is blocked and why (red/amber/green per stage)
- One-click creation of a Flux Config PR to promote an image to STAGING or PROD
- Automatically @mentions the developer on Jenkins build failure, SRE on Flux or pod failures
- Dev stage shows who (Auger vs Human) owns each sub-step, with button to open IDE context

### 🔍 K8s Explorer
- Browse namespaces and pods for DEV, STAGING, and PROD without a terminal
- Stream live pod logs with follow mode, filter by keyword
- View pod describe, environment variables, and labels/annotations in tabbed panels
- Restart or exec into a pod directly from the widget

### 🔭 Panner
- Panoramic health view across all services and environments simultaneously
- Spot anomalies across 20+ services without building DataDog dashboards
- Phase 1: auto-sources kubectl status + DataDog metrics on open

### ☸️ Pods
- Quick status check: running/pending/crashlooping pods per namespace
- Surface restartCount and last-state reason for crash diagnosis

### 🔄 Flux Config
- Browse flux YAML files for any environment without cloning the repo
- Create a promotion PR (dev→staging, staging→prod) with the correct image tag pre-filled
- All prod PRs enforce the 2-approval requirement automatically

### 🔐 Cryptkeeper / Cryptkeeper Lite
- Encrypt and decrypt secrets using ASSIST's key management system
- Lite mode: offline encryption without API dependency for dev/test use

### 🗄️ Database Widget
- Run read-only SQL against ASSIST PostgreSQL databases (dev/staging/prod)
- Browse table schemas and run ad-hoc queries without a separate DB client
- Used by SREs for accrual investigation, billing reconciliation lookups

### 💬 GChat Widget
- Send formatted messages to any team channel from within Auger
- Manage system webhooks (add/edit/delete) — changes auto-committed to git via GHE API
- Test a webhook endpoint before saving

### 🔧 Jenkins Widget
- View build status and console output for any job
- Trigger a parameterized build without opening the Jenkins UI
- Link build failures directly to the Story→Prod pipeline block state

### 📦 Artifactory Widget
- Browse image repositories and tags
- Identify latest build artifact for a service to use in flux promotion

### 🚢 Production Release
- Manage release branches and BUILD tags for ASSIST components
- Track release readiness across environments

### 🔎 Prospector
- Scan container images and dependencies for CVEs before releasing to production
- Surfaces CVSS score, affected package, fix version in a sortable table

### 🎫 ServiceNow
- Auto-login and navigate ASSIST change requests and incidents
- Create and link change tickets to Auger deployment actions

### 🐙 GitHub Widget
- Browse open PRs, view diffs, post review comments
- Navigate repository file trees and search code without leaving Auger

### 💻 Shell Terminal
- Run kubectl, bash, Python snippets in a context-aware terminal panel
- Pre-loaded with correct namespace/environment for current task

### 🤖 Ask Auger (AI Panel)
- Natural language queries: "What's deployed in staging for data-utils?"
- Intelligent command suggestions: "How do I tail logs for a crashlooping pod?"
- Context-aware: Auger knows current branch, active story, and deployment state

### ✅ Tasks Widget
- Track SRE action items, bugs, and TODOs without leaving the platform
- Auto-suggested by Auger when a new action item arises in conversation

### 🆘 Help Viewer
- Contextual help for each widget, pulled from markdown docs
- Search across all platform documentation inline

### 🔑 API Config
- Centralized credential management: Jira, Jenkins, GHE, Artifactory, DataDog, ServiceNow
- Validates connectivity to each service on save

### 💬 Prompts Manager
- Manage and version AI prompt templates used by Ask Auger
- Share prompts across the team via git-backed YAML

---

## Role-Based Use Cases

### SRE Engineer
- Morning: open Pods widget → check for crashloops → K8s Explorer for log detail
- Deployment: Story→Prod widget → click through pipeline stages → create Flux PR
- Incident: Shell Terminal + K8s Explorer simultaneously for triage

### Release Manager
- Story→Prod → verify all stages green → trigger prod promotion with 2-approval PR
- Production Release widget to tag and cut release branch

### Developer (self-service)
- Story→Prod → see build status for their story without bothering SRE
- Get @mentioned by Auger on build failure with direct link to console log

### Product Owner
- Story→Prod gives transparent progress view from Jira ticket to live pod
- @mentioned by Auger when a story is blocked at the prod promotion stage

---

*Document generated by Auger AI · ASSIST SRE Platform · Draft v1.0*
