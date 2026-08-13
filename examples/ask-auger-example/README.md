# Ask Auger — SRE Platform Example

This is a production SRE dashboard built WITH platformgen.

## What Ask Auger Does

- 🔍 Monitors Kubernetes clusters
- 📊 Tracks GitHub PRs, workflows, deployments
- 🎯 Manages Jira stories
- 🚨 Scans for CVEs
- 🏪 Browses Artifactory artifacts
- 💬 AI-powered chat (Ask Genny) for SRE tasks

## How It Was Built

Ask Auger was created by describing this to Genny:

> "I need a desktop SRE dashboard with 26 widgets for monitoring Kubernetes, GitHub, Jira, ServiceNow, and more. It should have an AI chat assistant that understands SRE workflows."

Genny generated:
- Widget architecture (hot-reload capable)
- UI framework (Tkinter + dark theme)
- Ask Genny integration (Copilot)
- Credential management (encrypted secrets)
- Hot-reload system (1-second widget updates)

## Quick Start

```bash
docker run -e GH_TOKEN=xxx ghcr.io/techno-vet/platformgen-py:latest
```

Or:

```bash
pip install platformgen-py
auger start
```

## Building Your Own Ask Auger

1. Open platformgen
2. Ask Genny: "Build me an SRE dashboard with widgets for X, Y, Z"
3. Genny generates the platform
4. Deploy

---

**platformgen makes building Ask Auger-like platforms trivial.** 🚀
