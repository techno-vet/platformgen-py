# Host Tools Widget

The Host Tools widget lets you launch and manage applications installed on your **host machine** directly from inside the Auger container.

## Overview

Since Auger runs in a Docker container with `--network host`, it communicates with a lightweight **Host Tools Daemon** running on your host to launch GUI apps, open URLs, and manage registered tools.

## Features

- **Auto-detect** — automatically finds well-known tools (VS Code, IntelliJ, Postman, etc.) on first open
- **Real app icons** — fetches actual icons from your host system (snap packages, .desktop files)
- **Launch tools** — click Launch to open any registered tool on your host
- **Add from Launcher** — browse all `.desktop` apps installed on your host and add them
- **Custom tools** — register any binary or shell command as a tool

## Auto-Detection

When you open the widget for the first time, it automatically scans for:

| Tool | Detection |
|------|-----------|
| VS Code | `/snap/bin/code` |
| IntelliJ Community / Ultimate | `/snap/bin/intellij-idea-community` |
| PyCharm | `/snap/bin/pycharm` |
| Postman | `/snap/bin/postman` |
| DataGrip | `/snap/bin/datagrip` |
| Chrome | `google-chrome` |
| Terminal | `gnome-terminal`, `xterm` |
| Nautilus (Files) | `nautilus` |

Click **Auto-Detect** at any time to re-scan.

## Adding Custom Tools

1. Click **+ Add Tool** to register a known tool or enter a custom command
2. Or click **From Launcher** to browse all `.desktop` apps on your host
3. Tools are saved to `~/.auger/host_tools.json`

## Tool Icons

Icons are loaded in priority order:
1. **Host system icon** — from snap package or `.desktop` `Icon=` field
2. **PIL icon** — category-appropriate drawn icon
3. **Colored initials** — distinctive rounded box with tool abbreviation

## Requirements

The **Host Tools Daemon** must be running on your host. It is started automatically by `docker-run.sh`. To start it manually:

```bash
python3 scripts/host_tools_daemon.py
```

## Ask Auger

> "add a custom tool to host tools"
> "why isn't my tool launching?"
> "how do I register a new app in host tools?"
