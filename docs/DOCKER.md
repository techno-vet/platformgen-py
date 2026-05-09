# PlatformGen - Docker Guide

Run PlatformGen in Docker for testing, development, or isolated environments.

## Quick Start

```bash
# 1. Setup environment
make setup
# Edit .env and add your GITHUB_COPILOT_TOKEN

# 2. Run automated test
make test

# 3. Run PlatformGen
make run
make shell
```

## Two Container Modes

### Production Mode (`docker-compose.yml`)
- Uses your actual configurations
- Mounts `~/.platformgen`, `~/.kube`, `~/.ssh`
- Full access to host resources
- Persistent data

```bash
make build        # Build image
make run          # Start container
make shell        # Access shell
```

### Test Mode (`docker-compose.test.yml`)
- Clean environment
- No pre-existing configs
- Tests installation from scratch
- Automated test script

```bash
make test         # Run full automated test
make test-shell   # Manual testing
```

## Requirements

### Host System
- Docker and Docker Compose installed
- X11 server running (for GUI)
- `.env` file with tokens (copy from `.env.example`)

### X11 Setup

**Linux:**
```bash
# Allow Docker to access X11
xhost +local:docker
```

**macOS:**
```bash
# Install XQuartz
brew install --cask xquartz

# Start XQuartz and enable "Allow connections from network clients"
# Then:
xhost +localhost
```

**Windows (WSL2):**
```bash
# Install VcXsrv or X410
# Configure to allow localhost connections
export DISPLAY=:0
```

## Environment Variables

Required in `.env` file:

```bash
# Required for Ask Genny
GH_TOKEN=<fine-grained github.com token with Copilot requests permission>

# Optional Helix GitHub access (separate token)
GHE_TOKEN=<github.helix.gsa.gov token>
GHE_URL=https://github.helix.gsa.gov
DATADOG_API_KEY=your_key
DATADOG_APP_KEY=your_key
SERVICENOW_INSTANCE=https://your-instance.service-now.com
```

## Makefile Commands

### Setup
- `make setup` - Create `.env` from template
- `make build` - Build production image

### Development
- `make run` - Start the PlatformGen container with your configs
- `make shell` - Open bash in running container
- `make logs` - View container logs
- `make stop` - Stop containers

### Testing
- `make test` - Run automated test in clean environment
- `make test-shell` - Manual testing in clean container
- `make test-build` - Build test image only
- `make quick-test` - Fast test using .env token

### Maintenance
- `make clean` - Remove containers and images
- `make reset` - Full reset including volumes

## Manual Docker Commands

### Production Run
```bash
# Build
docker-compose build

# Run with shell access
docker-compose up -d
docker-compose exec auger bash

# Inside container
auger start
```

### Test Run
```bash
# Automated test
docker-compose -f docker-compose.test.yml up --build

# Manual test
docker-compose -f docker-compose.test.yml run --rm auger-test bash

# Inside test container
cd /home/testuser/platformgen-platform
./install.sh
source ~/.bashrc
auger init --token $GITHUB_COPILOT_TOKEN
auger doctor
```

## What's Included

The Docker image includes:

**System Tools:**
- Python 3.10
- Git, curl, wget
- X11 libraries (for GUI)
- Docker CLI
- kubectl
- k9s

**GitHub Tools:**
- GitHub CLI (`gh`) - for git operations
- Standalone Copilot CLI (`copilot`) - for AI assistance
  - Install with: `curl -fsSL https://gh.io/copilot-install | bash`
  - Or: `brew install copilot-cli`

**PlatformGen runtime:**
- Installed in development mode
- All Python dependencies
- CLI commands available

## Volume Mounts

### Production Mode
```
./                          → /home/auger/auger-platform  (code)
~/.platformgen              → /home/auger/.auger         (runtime state, legacy in-container path)
~/.kube                     → /home/auger/.kube          (kubectl)
~/.ssh                      → /home/auger/.ssh           (git keys)
~/.gitconfig                → /home/auger/.gitconfig     (git config)
/var/run/docker.sock        → /var/run/docker.sock       (docker)
/tmp/.X11-unix              → /tmp/.X11-unix             (display)
```

### Test Mode
```
./                          → /home/testuser/platformgen-platform  (code only)
/tmp/.X11-unix              → /tmp/.X11-unix                 (display)
/var/run/docker.sock        → /var/run/docker.sock           (docker)
```

## Troubleshooting

### GUI Not Working
```bash
# Linux
xhost +local:docker
echo $DISPLAY  # Should be :0 or :1

# macOS
# Make sure XQuartz is running
# Enable "Allow connections from network clients"
xhost +localhost
```

### Permission Denied on Docker Socket
```bash
# Add your user to docker group
sudo usermod -aG docker $USER
# Log out and back in
```

### PlatformGen CLI Not Found
```bash
# Inside container
echo $PATH  # Should include /home/auger/.local/bin
ls -la ~/.local/bin/auger
source ~/.bashrc
```

### Test Failures
```bash
# Run test with verbose output
docker-compose -f docker-compose.test.yml run --rm auger-test bash
cd /home/testuser/auger-platform
bash -x scripts/docker-test.sh
```

## Development Workflow

```bash
# 1. Make code changes on host
vim auger/cli.py

# 2. Changes are immediately available in container (volume mount)
make shell

# 3. Test changes
auger doctor
auger start

# 4. Run full test
exit
make test
```

## CI/CD Integration

Use test mode for CI pipelines:

```yaml
# GitHub Actions example
- name: Test PlatformGen Installation
  run: |
    make setup
    echo "GITHUB_COPILOT_TOKEN=${{ secrets.COPILOT_TOKEN }}" >> .env
    make test
```

## Security Notes

- Container runs as non-root user (`auger` or `testuser`)
- SSH keys mounted read-only
- Kubeconfig mounted read-only
- Docker socket access (required for k9s/kubectl) - use with caution
- Secrets stored in `.env` (gitignored)

## Clean Up

```bash
# Stop containers
make stop

# Remove images
make clean

# Full reset (including volumes)
make reset
```
