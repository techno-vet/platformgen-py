# Auger Platform
### *Drill Down With Auger* 🔩

> ⚠️ **Alpha Release** - Currently in alpha testing. See [ALPHA_TESTING.md](ALPHA_TESTING.md) for testing guide.

**AI-powered SRE platform with dynamic widgets and chat assistant**

Auger Platform is a comprehensive tool for SREs, developers, BAs, and POs that provides:
- 🤖 **Ask Auger** - AI chat assistant to help configure and use the platform
- 📊 **Dynamic Widgets** - Pods monitoring, GitHub PRs, ServiceNow tickets, CVE scanning, and more  
- 🔐 **Secure Credential Management** - Encrypted secrets, environment-based configuration
- 🔄 **Hot Reload** - Develop and test widgets without restarting
- 🎨 **Modern UI** - Dark theme, responsive design
- 🔌 **Extensible** - Easy to add custom widgets and integrations

---

## Alpha Testing

**Status**: Alpha 0.1.0 (February 2026)

✅ **What works**: CLI, Ask Auger, GitHub widget, configuration management  
⚠️ **Partial**: ServiceNow (needs cookies), DataDog (needs keys)  
❌ **Not ready**: Cryptkeeper, Database, Panner widgets

👉 **See [ALPHA_TESTING.md](ALPHA_TESTING.md) for full testing guide**

---

## Quick Start

### Prerequisites
- Python 3.10 or higher
- Git
- X11 display (Linux) or XQuartz (macOS)

### Installation

```bash
# 1. Get the repo into ~/repos/auger-ai-sre-platform
#    (SSH, HTTPS, or VS Code source control are all fine)
git clone https://github.helix.gsa.gov/assist/auger-ai-sre-platform.git ~/repos/auger-ai-sre-platform

# 2. Run the install wizard — one entry point for everyone
cd ~/repos/auger-ai-sre-platform && ./scripts/install_wizard
```

Optional before onboarding: `cp .env.example ~/.auger/.env` and pre-fill any keys you already have.

The wizard handles token detection and prompts for missing `GH_TOKEN`, `GHE_TOKEN`, and Artifactory credentials early, installs the host `auger` CLI for terminal Ask Auger, pulls Docker images, and sets up the GNOME launcher. After first install, launch Auger from your app grid. On workspace login, Auger auto-starts the task tray so users can launch the platform from the tray or from the app grid.

---

## Features

- **Ask Auger Chat** - AI assistant helps configure integrations
- **Pods Monitor** - DataDog Kubernetes pod monitoring
- **GitHub** - PRs, repos, CI/CD status
- **ServiceNow** - Incidents, changes (web scraping, no API key!)
- **Cryptkeeper Lite** - Jasypt encryption, multi-environment
- **Prospector** - CVE scanning and diff
- **Hot Reload** - Widget development without restart

---

## Documentation

- [Session Framework & Rules](docs/SESSION_FRAMEWORK_AND_RULES.md) — *Learn how session recovery, prompt rules, and widgets work*
- [Quick Start Guide](docs/QUICKSTART.md)
- [Configuration Guide](docs/README_CONFLUENCE_INTEGRATION.md)
- [Widget Development](docs/HOW_DYNAMIC_WIDGETS_WORK.md)
- [Distribution Plan](docs/AUGER_DISTRIBUTION_PLAN.md)

---

## CLI Commands

```bash
# Dual-mode usage:
auger                   # Open ask prompt (GUI)
auger "your question"   # Quick ask (terminal)

# Platform commands:
auger init              # Initialize configuration
auger start             # Launch GUI
auger doctor            # Run diagnostics
auger config            # Show configuration
auger widgets           # List available widgets
auger test <integration> # Test integration (github, datadog, servicenow)
```

**New!** `auger` without subcommands acts as quick Copilot wrapper.

See also: [Auger Ask Documentation](docs/AUGER_ASK.md)

---

## Support

- **Issues:** https://github.helix.gsa.gov/assist/auger-ai-sre-platform/issues
- **Ask Auger:** Open the chat panel for help!

---

**Made with ❤️ by the GSA ASSIST Team**
