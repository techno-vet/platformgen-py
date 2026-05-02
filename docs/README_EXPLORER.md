# Explorer Widget

The **Explorer** widget is a file system browser that gives you a unified view of all volumes mounted in the Auger container — including your full host filesystem, git repos, kubeconfig, and Auger config.

## Mounted Paths

| Mount | Description |
|-------|-------------|
| `/host` | Full host root filesystem (read-only) |
| `~/repos` | Your git repositories (`$HOME/repos` on the host) |
| `~/.auger` | Auger config, `.env`, tasks DB, logs |
| `~/.copilot` | GitHub Copilot session state |
| `~/.kube` | Kubernetes config files |
| `/` | Container root (installed packages, Auger source) |

## Features

- **Lazy tree loading** — directories expand on demand; large trees don't block the UI
- **File preview** — click a file to view its contents in the right pane
- **Syntax highlighting** — for `.py`, `.yaml`, `.json`, `.md`, `.sh`, `.tf` files
- **Copy path** — right-click to copy the full path to clipboard
- **Open in terminal** — right-click a directory to `cd` to it in the Shell Terminal widget

## Use Cases

- Browse log files in `~/.auger/logs/`
- Inspect kubeconfig at `~/.kube/config`
- View repo structure before making changes
- Check Auger widget source code at `~/repos/auger-ai-sre-platform/auger/ui/widgets/`

> **Tip:** The host filesystem is at `/host` — so `/host/etc/hosts` is your host's `/etc/hosts`.
