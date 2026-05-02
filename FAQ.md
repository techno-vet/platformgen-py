# Auger Platform FAQ

## GitHub Tokens

### Which GitHub token do I use for `auger init`?

**Use your Copilot token (github.com), NOT Enterprise token.**

The priority is getting **Ask Auger working first** so it can help you configure everything else.

You likely have two GitHub tokens:

1. **Copilot Token** (github.com) ✅
   - Domain: `github.com`
   - Purpose: GitHub Copilot AI, Ask Auger panel
   - ✅ USE THIS for `auger init --token`
   - Get it: https://github.com/settings/tokens

2. **Enterprise Token** (github.helix.gsa.gov) ✅
   - Domain: `github.helix.gsa.gov`
   - Purpose: Access to ASSIST repos, issues, PRs
   - ✅ The install wizard now asks for this early and stores it in `~/.auger/.env`
   - Or pre-fill it in `~/.auger/.env` before onboarding

**Why Copilot token first?**
- Ask Auger needs it to function
- Once Ask Auger works, it can guide you through setting up Enterprise GitHub, DataDog, ServiceNow, etc.
- It's the quickest path to a working system

### How do I create a GitHub Copilot token?

1. Go to: https://github.com/settings/tokens
2. Click "Generate new token (classic)"
3. Give it a name: "Auger Copilot"
4. Select scopes:
   - ✅ `user` (Read user profile)
   - ✅ `copilot` (if available)
5. Click "Generate token"
6. Copy the token immediately (you won't see it again!)

### How do I add Enterprise GitHub?

The install wizard now prompts for `GHE_TOKEN` early, but you can still add it later:

1. **Ask Auger**: "How do I configure Enterprise GitHub?"
2. **Or manually**: Edit `~/.auger/.env`:
   ```bash
   GITHUB_ENTERPRISE_TOKEN='ghp_your_enterprise_token'
   ```
3. Generate Enterprise token at: https://github.helix.gsa.gov/settings/tokens

### What permissions does the token need?

Minimum required:
- `read:user` - Read your user profile
- `repo` - Access repositories, issues, PRs

The token is stored securely in `~/.auger/.env` with 600 permissions.

## Installation

### Can I install system-wide vs user-level?

```bash
# User-level (recommended for development/testing)
pip install -e .

# System-wide (requires sudo, not recommended for alpha)
sudo pip install -e .

# Virtual environment (good for isolation)
python3 -m venv auger-venv
source auger-venv/bin/activate
pip install -e .
```

### Do I need to run as root/sudo?

**No!** Auger should always run as your regular user. Never use sudo.

### What Python versions are supported?

- **Minimum**: Python 3.10
- **Recommended**: Python 3.10 or 3.11
- **Not tested**: Python 3.12+ (might work)

Check your version:
```bash
python3 --version
```

## Configuration

### Where is my configuration stored?

All Auger configuration is in `~/.auger/`:
```
~/.auger/
├── config.yaml    # Configuration (display, widgets, etc.)
└── .env           # Secrets (tokens, API keys)
```

### Can I use a different config directory?

Yes:
```bash
auger init --config-dir /custom/path
auger start --config-dir /custom/path
```

Or set environment variable:
```bash
export AUGER_CONFIG_DIR=/custom/path
auger start
```

### How do I reset my configuration?

```bash
# Backup first (optional)
cp -r ~/.auger ~/.auger.backup

# Remove config
rm -rf ~/.auger

# Re-initialize
auger init --token YOUR_TOKEN
```

## Usage

### Can I run Auger on a remote server?

Yes, but you need X11 forwarding:

```bash
# From your local machine
ssh -X user@remote-server

# On remote server
auger start
```

The GUI will display on your local machine.

### Can I run Auger without the GUI?

Not yet. The CLI commands work without GUI, but `auger start` requires X11.

Future releases may include:
- Web UI mode
- Terminal-only mode
- API server mode

### How do I update Auger?

```bash
cd ~/auger-ai-sre-platform
git pull
pip install -e . --force-reinstall
```

## Troubleshooting

### `auger: command not found`

The `auger` command wasn't added to your PATH.

**Fix**:
```bash
# Find where pip installed it
which auger || find ~/.local/bin -name auger

# Add to PATH (add to ~/.bashrc)
export PATH="$HOME/.local/bin:$PATH"

# Reload shell
source ~/.bashrc
```

### `ModuleNotFoundError: No module named 'auger'`

The package isn't installed correctly.

**Fix**:
```bash
cd ~/auger-ai-sre-platform
pip install -e . --force-reinstall --no-deps
```

### GUI won't launch

**Check DISPLAY**:
```bash
echo $DISPLAY
# Should show something like :0 or :1

# If empty, set it:
export DISPLAY=:0
```

**Check config**:
```bash
cat ~/.auger/config.yaml | grep display
# Should match your $DISPLAY
```

### Widgets aren't loading

1. **Check they're enabled**:
   ```bash
   auger widgets
   ```

2. **Check terminal output** when starting:
   ```bash
   auger start
   # Look for "[X] Error loading..." messages
   ```

3. **Try disabling hot reload** (temporary):
   Edit `~/.auger/config.yaml`:
   ```yaml
   hot_reload: false
   ```

### Ask Auger isn't responding

1. **Test GitHub connection**:
   ```bash
   auger test github
   ```

2. **Check token in .env**:
   ```bash
   cat ~/.auger/.env | grep GITHUB_TOKEN
   # Should NOT be empty or ${GITHUB_TOKEN}
   ```

3. **Regenerate token** if expired:
   - Go to https://github.helix.gsa.gov/settings/tokens
   - Regenerate your token
   - Update `~/.auger/.env`

## Features

### Which widgets work in alpha?

✅ **Fully functional**:
- GitHub (issues, PRs, repos)
- Ask Auger panel

⚠️ **Partial** (need additional setup):
- ServiceNow (requires cookies)
- Prospector (requires Jenkins API)
- Pods (requires kubectl config)

❌ **Not yet implemented**:
- Cryptkeeper (needs AWS/KMS)
- Database (needs connection strings)
- Panner (needs Panner API)

### Can I add my own widgets?

Yes! See [Creating Custom Widgets](docs/WIDGET_DEVELOPMENT.md) (coming soon).

For now:
1. Copy an existing widget from `auger/ui/widgets/`
2. Modify it for your needs
3. Hot reload will pick it up automatically

### Does Auger work offline?

Partially:
- ✅ GUI launches
- ✅ Configuration loads
- ❌ Ask Auger won't work (needs API)
- ❌ GitHub widget won't work (needs API)
- ❌ Most integrations need internet

## Security

### Is my GitHub token secure?

Yes:
- Stored in `~/.auger/.env` with 600 permissions (only you can read)
- Never logged or printed to terminal
- Not included in any error messages
- Not sent anywhere except GitHub API

### What data does Auger collect?

**Nothing.** Auger:
- Runs entirely on your machine
- Doesn't phone home
- Doesn't send telemetry
- Doesn't track usage

All API calls go directly to the services (GitHub, DataDog, etc.), not through any Auger servers.

### Can I use Auger in production?

**Not yet.** This is alpha software:
- May have bugs
- May change significantly
- Not fully tested
- No guarantee of stability

Use for development/testing only until beta/stable release.

## Getting Help

### Where do I report bugs?

GitHub Issues: https://github.helix.gsa.gov/assist/auger-ai-sre-platform/issues

Include:
- What you were doing
- What happened vs what you expected
- Error messages from terminal
- `python3 --version` and `uname -a` output

### Where do I ask questions?

1. **Ask Auger!** (in the GUI)
2. GitHub Discussions (coming soon)
3. Email: bobby.blair@gsa.gov

### How do I contribute?

See [CONTRIBUTING.md](CONTRIBUTING.md) (coming soon).

For now:
- Test thoroughly
- Report bugs
- Suggest features
- Share with your team

---

**More questions?** Ask Auger in the GUI chat panel!
