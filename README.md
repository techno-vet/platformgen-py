# platformgen 🚀

### The AI-Powered Platform Generator

> **Build ANY platform in days, not months.**
>
> Ask Genny what you want. Genny builds it. Deploy.

**platformgen is a meta-platform builder** — use it to generate production platforms for any business domain. Built entirely in Python/Tkinter with GitHub Copilot integration.

## What Can You Build?

✅ **Ask Genny** — SRE Dashboard (built WITH platformgen)  
✅ **OpenJuke** — Music/Media Platform (built WITH platformgen)  
✅ **Custom Dashboards** — Any business domain  
✅ **Internal Tools** — Microservices, APIs, monitoring  
✅ **Data Platforms** — ETL, analytics, reporting  

**The Meta-Story:** platformgen was built WITH platformgen. Genny can improve herself.

## How It Works

1. **Describe** — "I need a platform that tracks X"
2. **Genny Builds** — AI generates architecture, widgets, APIs
3. **Customize** — Add widgets, APIs, integrations (no code needed)
4. **Deploy** — Docker + Kubernetes ready (GitOps built-in)

## Key Features

- 🤖 **Ask Genny AI** — Embedded Copilot-powered assistant with real-time reasoning & token tracking
- 📊 **26+ Pre-built Widgets** — Jira, GitHub, Jenkins, Kubernetes, Flux, Artifactory, DataDog, and more
- 🔥 **Hot Reload** — Change widgets in 1 second (no app restart)
- 🐳 **Docker Native** — Runs as container on Amazon WorkSpace (Ubuntu)
- 🌐 **Cloud Native** — Kubernetes + Flux GitOps built-in
- 🎨 **Professional UI** — Dark theme, markdown rendering, animations
- 🔐 **Secure Credential Management** — Encrypted secrets, environment-based config
- 🔌 **Extensible** — Add widgets via natural language to Genny

---

## Alpha Testing

**Status**: Alpha 0.1.0 (August 2026)

✅ **What works**: CLI (genny init/start), Ask Genny, GitHub widget, configuration management  
⚠️ **Partial**: ServiceNow (needs cookies), DataDog (needs keys)  
❌ **Not ready**: Cryptkeeper, Database, Panner widgets

👉 **See [ALPHA_TESTING.md](ALPHA_TESTING.md) for full testing guide**

---

## Quick Start: Ask Genny (SRE Example)

### Universal installer (Linux, macOS, Windows)

```bash
git clone https://github.com/techno-vet/platformgen-py.git
cd platformgen-py
python3 scripts/install_wizard.py
```

The installer will:
1. ✅ Create Python venv in `~/.platformgen/`
2. ✅ Install all dependencies (including `python3-tk`)
3. ✅ **Prompt for your GitHub Copilot token** (required for Ask Genny)
4. ✅ Add `genny` command to your PATH
5. ✅ Optionally install GitHub Copilot CLI

Once installed, simply start the app:
```bash
genny start
```

**System Requirements:** Python 3.10+, X11 display (for UI rendering)

**Optional pre-install setup (Ubuntu/Debian only, installer handles this automatically):**
```bash
sudo apt-get install python3-tk
```

## Open Source + Commercial

**platformgen is MIT licensed** — use it freely in commercial projects.

**ask-genny.cloud** — Managed SaaS (coming soon) with:
- ☁️ Hosted agents (no local setup)
- 🔐 Private agent sessions  
- 🔗 Enterprise SSO
- 📈 Analytics & audit logs
- 💬 Slack integration

[Learn more →](https://ask-genny.ai)

---

## Documentation

- 📖 [Installation Guide](INSTALLATION_GUIDE.md) — Setup & configuration
- 🎬 [Quick Start](docs/QUICKSTART.md) — Get running in 5 minutes
- 🏗️ [Architecture](docs/ARCHITECTURE.md) — How platformgen works
- 🛠️ [Contributing](CONTRIBUTING.md) — Widget development guide
- 🔒 [Security Policy](SECURITY.md) — Vulnerability reporting
- 💬 [Ask Genny Prompts](docs/PROMPTS.md) — AI customization
- 🧪 [Testing Guide](ALPHA_TESTING.md) — Alpha testing

## Community

- 💬 [Discussions](https://github.com/techno-vet/platformgen-py/discussions) — Ask questions
- 🐛 [Issues](https://github.com/techno-vet/platformgen-py/issues) — Report bugs or request features
- 💬 [Discord](https://discord.gg/platformgen) — Real-time chat
- 🌟 [GitHub Sponsors](https://github.com/sponsors/techno-vet) — Support the project

## Roadmap

### Q3 2026
- [x] Open source core library (MIT)
- [x] Public GitHub org (techno-vet)
- [ ] Ask Genny v2.0 (reasoning animations, token tracking)
- [ ] Discord community launch

### Q4 2026
- [ ] Enterprise self-hosted tier
- [ ] Kubernetes operator for platform deployment
- [ ] Plugin marketplace (community widgets)
- [ ] GitHub Actions integration

[Full roadmap →](https://github.com/orgs/techno-vet/projects/1)

---

## CLI Commands

```bash
# Dual-mode usage:
genny                   # Open Ask Genny prompt (GUI)
genny "your question"   # Quick Genny query (terminal)

# Platform commands:
genny init              # Initialize configuration
genny start             # Launch GUI
genny doctor            # Run diagnostics
```

**Quick Copilot wrapper:** `genny` without subcommands opens interactive chat with GitHub Copilot.

---

## Support

- **Issues:** https://github.com/techno-vet/platformgen-py/issues
- **Ask Genny:** Open the chat panel for help!

---

**Made with ❤️ by the PlatformGen Team**
