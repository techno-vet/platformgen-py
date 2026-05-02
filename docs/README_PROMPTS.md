# Prompts Widget

The **Prompts** widget is Auger's knowledge management center. It stores **Rules**, **Conventions**, **Standards**, and custom **Prompts** that are automatically injected into every Ask Auger conversation — keeping the AI grounded in your team's processes.

## What Gets Injected

Every time you use Ask Auger, the platform injects the full set of active rules, conventions, and standards as context. This means Auger always knows:

- Your branching and commit conventions
- Production safety rules (e.g., 2-approval requirement for flux-config)
- Team standards (e.g., every widget must define `WIDGET_ICON_FUNC`)
- Custom prompt templates

## Tabs

### Rules
Hard policies the team enforces. Example: *"assist-prod-flux-config always requires 2 approvals."*

### Conventions
Soft standards and naming patterns. Example: *"Feature branch naming: `feature/{jira_story}-{slug}`"*

### Standards
Technical standards for code and infrastructure. Example: *"Every widget must define WIDGET_ICON_FUNC."*

### Prompts
Reusable prompt templates for common SRE tasks (deploy checklist, incident runbook, PR review, etc.).

## Storage

- **Repo defaults**: `<repo>/auger/data/origin/` — checked into git, shared with all SREs
- **User overrides**: `~/.auger/rules.yaml`, `~/.auger/conventions.yaml`, `~/.auger/prompts.yaml`

When the same `id` exists in both, the user file wins. This lets you personalize without changing shared defaults.

## Editing

1. Select an item in the list panel (left)
2. Edit fields in the form panel (right)
3. Click **Save** — changes go to your user YAML file

New items added via the widget are saved to your user file only. To make a rule available to all SREs, edit the repo file and commit it.

> **Tip:** Ask Auger to add a new rule: *"Add a rule that we never delete prod databases without a Jira ticket"*
