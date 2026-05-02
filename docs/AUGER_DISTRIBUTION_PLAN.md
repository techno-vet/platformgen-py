# Auger Platform Distribution Plan
**Making Auger Platform easily installable for SREs, Developers, BAs, and POs**

---

## 🎯 Primary Goals

1. **Easy Installation** - `pip install auger` or one command setup
2. **Ask Auger First** - Get chat panel working with token to help users configure everything else
3. **Containerization** - Docker/Podman for testing and deployment
4. **Self-Service** - Users can Ask Auger for help setting up widgets and integrations
5. **Secure** - Proper secrets management, no hardcoded credentials

---

## 📋 Current State Analysis

### What Works Great
- ✅ Widget system with hot reload
- ✅ Virtual environment management
- ✅ Dynamic widget loading
- ✅ Cryptkeeper Lite (standalone encryption)
- ✅ ServiceNow auto-login with Selenium
- ✅ DataDog integrations (Pods, metrics)
- ✅ GitHub widgets
- ✅ Prospector CVE scanning
- ✅ Chat panel with context awareness

### What Needs Work
- ❌ Hardcoded paths (`/home/bobbygblair/repos/...`)
- ❌ Environment-specific configuration (`.env` file not portable)
- ❌ Dependencies scattered (some in requirements.txt, some manual)
- ❌ No setup.py/pyproject.toml for pip installation
- ❌ API keys/tokens need initial configuration
- ❌ Documentation spread across many README files

---

## 🚀 Distribution Options

### Option 1: PyPI Package (Recommended for SREs/Developers)
**Goal:** `pip install auger-platform`

**Pros:**
- ✅ Standard Python distribution
- ✅ Version management
- ✅ Easy updates (`pip install --upgrade`)
- ✅ Works in any Python environment
- ✅ Can include CLI commands

**Cons:**
- ❌ Still needs GUI dependencies (tkinter)
- ❌ Requires initial configuration
- ❌ Platform-specific issues (Windows/Mac/Linux)

**Installation Flow:**
```bash
# 1. Install via pip
pip install auger-platform

# 2. Initialize configuration
auger init
# Creates ~/.auger/config.yaml
# Prompts for GitHub token (required for Ask Auger)
# Optional: prompts for DataDog, ServiceNow, etc.

# 3. Start Auger
auger start
# Opens GUI with Ask Auger chat panel
# User can ask: "Help me set up DataDog integration"
```

### Option 2: Container (Docker/Podman) - Best for Testing
**Goal:** `docker run -p 6000:6000 auger-platform`

**Pros:**
- ✅ Consistent environment
- ✅ All dependencies included
- ✅ Easy testing/CI
- ✅ X11 forwarding for GUI
- ✅ Volume mounts for config

**Cons:**
- ❌ GUI requires X11 forwarding or VNC
- ❌ Browser automation (Selenium) tricky in container
- ❌ Larger download size
- ❌ Some users unfamiliar with containers

**Dockerfile approach:**
```dockerfile
FROM python:3.10-slim
RUN apt-get update && apt-get install -y \
    python3-tk \
    google-chrome-stable \
    chromium-driver
COPY . /app
RUN pip install -e /app
CMD ["auger", "start", "--web"]
```

### Option 3: GitHub Release with Install Script
**Goal:** `curl -sSL https://raw.githubusercontent.com/org/auger/main/install.sh | bash`

**Pros:**
- ✅ One-command install
- ✅ Can handle system dependencies
- ✅ Platform detection (Linux/Mac)
- ✅ No PyPI account needed
- ✅ Direct from source

**Cons:**
- ❌ Less discoverable than PyPI
- ❌ Security concerns (piping to bash)
- ❌ Manual updates required

**Install script flow:**
```bash
#!/bin/bash
# install.sh
echo "🔧 Installing Auger Platform..."

# Check Python version
# Install system dependencies (tk, chrome)
# Clone repo or download release
# Create venv
# Install requirements
# Create ~/.auger directory
# Generate default config
# Add auger command to PATH

echo "✅ Installation complete!"
echo "Run: auger init"
```

### Option 4: Hybrid Approach (Recommended)
**Combine PyPI + Container + Install Script**

1. **PyPI for core functionality**
2. **Container for testing/CI**
3. **Install script for quick setup**

---

## 🎨 Recommended Architecture

### Repository Structure
```
auger-platform/
├── README.md                      # Quick start guide
├── INSTALL.md                     # Detailed installation
├── LICENSE                        # Open source license
├── setup.py                       # PyPI packaging
├── pyproject.toml                 # Modern Python packaging
├── requirements.txt               # Core dependencies
├── install.sh                     # One-command installer
├── Dockerfile                     # Container build
├── docker-compose.yml             # Easy container setup
│
├── auger/                         # Main package
│   ├── __init__.py
│   ├── __main__.py                # Entry point (auger command)
│   ├── app.py                     # Main GUI application
│   ├── config.py                  # Configuration management
│   ├── cli.py                     # CLI commands
│   │
│   ├── ui/                        # UI components
│   │   ├── __init__.py
│   │   ├── main_window.py
│   │   ├── chat_panel.py          # Ask Auger
│   │   ├── widgets/               # All widgets
│   │   │   ├── __init__.py
│   │   │   ├── base.py            # Widget base class
│   │   │   ├── pods.py
│   │   │   ├── github.py
│   │   │   ├── servicenow.py
│   │   │   ├── cryptkeeper_lite.py
│   │   │   └── ...
│   │   └── themes.py
│   │
│   ├── tools/                     # Standalone tools
│   │   ├── cryptkeeper_lite.py
│   │   ├── servicenow_auto_login.py
│   │   └── jenkins_cli.py
│   │
│   ├── integrations/              # External integrations
│   │   ├── __init__.py
│   │   ├── datadog.py
│   │   ├── github.py
│   │   ├── servicenow.py
│   │   └── prospector.py
│   │
│   └── utils/                     # Utilities
│       ├── __init__.py
│       ├── config_manager.py
│       ├── secrets.py             # Secrets management
│       └── logger.py
│
├── tests/                         # Unit tests
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_widgets.py
│   └── test_integrations.py
│
├── docs/                          # Documentation
│   ├── quickstart.md
│   ├── configuration.md
│   ├── widgets/                   # Widget docs
│   │   ├── pods.md
│   │   ├── github.md
│   │   └── servicenow.md
│   ├── integrations.md
│   └── troubleshooting.md
│
└── examples/                      # Example configs
    ├── config.yaml.example
    ├── .env.example
    └── custom_widget.py
```

---

## 🔐 Configuration Strategy

### Three-Tier Config System

#### 1. Default Config (Built-in)
```yaml
# auger/config/defaults.yaml
display: ":1"
port: 6000
theme: "dark"
log_level: "INFO"
hot_reload: true
widgets_enabled:
  - chat
  - github
  - pods
  - cryptkeeper_lite
```

#### 2. User Config (Managed)
```yaml
# ~/.auger/config.yaml
github:
  token: "${GITHUB_TOKEN}"  # References env var
  
datadog:
  api_key: "${DATADOG_API_KEY}"
  app_key: "${DATADOG_APP_KEY}"
  site: "ddog-gov.com"

servicenow:
  url: "https://gsassistprod.servicenowservices.com"
  cookies: "${SERVICENOW_COOKIES}"

widgets:
  pods:
    enabled: true
    clusters:
      - assist-core-development
      - assist-core-staging
      - assist-core-production
```

#### 3. Environment Variables (Secrets)
```bash
# ~/.auger/.env (git-ignored)
GH_TOKEN=<fine-grained github.com token with Copilot requests permission>
GHE_TOKEN=<github.helix.gsa.gov token>
GHE_URL=https://github.helix.gsa.gov
DATADOG_API_KEY=xxxxxxxxxxxxx
DATADOG_APP_KEY=xxxxxxxxxxxxx
SERVICENOW_COOKIES={"JSESSIONID": "..."}
```

### Config Management Class
```python
# auger/config.py
class AugerConfig:
    """Manages configuration with defaults, user config, and env vars"""
    
    def __init__(self):
        self.defaults = self._load_defaults()
        self.user_config = self._load_user_config()
        self.env_vars = self._load_env_vars()
    
    def get(self, key, default=None):
        """Get config value with precedence: env > user > defaults"""
        # Check env vars first
        if key in self.env_vars:
            return self.env_vars[key]
        
        # Check user config (with env var substitution)
        if key in self.user_config:
            value = self.user_config[key]
            if isinstance(value, str) and value.startswith("${"):
                env_key = value[2:-1]
                return os.getenv(env_key)
            return value
        
        # Fall back to defaults
        return self.defaults.get(key, default)
```

---

## 🎯 Phase 1: Ask Auger First (MVP)

**Goal:** Get users up and running with just GitHub token, then Auger helps with the rest.

### Minimal Installation Flow
```bash
# 1. Install
pip install auger-platform

# 2. Initialize (only asks for GitHub token)
auger init
# Enter GitHub token: ghp_xxxxxxxxxxxxx
# ✅ Config saved to ~/.auger/config.yaml

# 3. Start
auger start
# Opens GUI with Ask Auger chat panel

# 4. User asks Auger for help
"Help me set up DataDog integration"
"How do I configure ServiceNow?"
"Show me my GitHub PRs"
```

### Ask Auger Capabilities
```python
# auger/ui/chat_panel.py
class ChatPanel:
    """Ask Auger - AI assistant for Auger Platform"""
    
    SYSTEM_COMMANDS = {
        "setup datadog": self._guide_datadog_setup,
        "setup servicenow": self._guide_servicenow_setup,
        "configure widget": self._guide_widget_config,
        "show config": self._show_config,
        "test integration": self._test_integration,
    }
    
    def _guide_datadog_setup(self):
        """Interactive DataDog setup wizard"""
        # 1. Ask user for API keys
        # 2. Validate keys with test API call
        # 3. Save to ~/.auger/.env
        # 4. Update config.yaml
        # 5. Enable Pods widget
        # 6. Show success message
```

### Setup Wizard in Chat
```
User: "Help me set up DataDog"

Auger: I'll help you configure DataDog integration! I need two API keys:
       1. DataDog API Key
       2. DataDog Application Key
       
       You can create them at: https://app.ddog-gov.com/organization-settings/api-keys
       
       Please paste your API key:

User: [pastes key]

Auger: ✅ API key validated!
       Now paste your Application key:

User: [pastes key]

Auger: ✅ Application key validated!
       
       🧪 Testing connection...
       ✅ Successfully connected to DataDog!
       
       📝 Saved credentials to ~/.auger/.env
       🔧 Enabled Pods widget
       
       Your Pods widget is now active! Try asking:
       - "Show pods in production"
       - "What pods are running in staging?"
```

---

## 📦 PyPI Package Setup

### pyproject.toml (Modern Python Packaging)
```toml
[build-system]
requires = ["setuptools>=65.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "auger-platform"
version = "1.0.0"
description = "AI-powered SRE platform with dynamic widgets and chat assistant"
readme = "README.md"
authors = [
    {name = "Your Team", email = "team@example.com"}
]
license = {text = "MIT"}
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Intended Audience :: System Administrators",
    "Topic :: Software Development :: Build Tools",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
]
keywords = ["sre", "devops", "monitoring", "widgets", "ai-assistant"]
dependencies = [
    "requests>=2.31.0",
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0.1",
    "boto3>=1.34.0",
    "rich>=13.7.0",
    "click>=8.1.7",
    "Pillow>=10.0.0",
    "pycryptodome>=3.20.0",
    "selenium>=4.0.0",
    "webdriver-manager>=4.0.0",
    "beautifulsoup4>=4.12.0",
]
requires-python = ">=3.10"

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-cov>=4.1.0",
    "black>=23.0.0",
    "flake8>=6.0.0",
    "mypy>=1.0.0",
]

[project.urls]
Homepage = "https://github.com/your-org/auger-platform"
Documentation = "https://auger-platform.readthedocs.io"
Repository = "https://github.com/your-org/auger-platform"
Issues = "https://github.com/your-org/auger-platform/issues"

[project.scripts]
auger = "auger.cli:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["auger*"]
exclude = ["tests*", "docs*", "examples*"]

[tool.setuptools.package-data]
auger = [
    "config/*.yaml",
    "ui/themes/*.json",
    "ui/assets/*.png",
]
```

### CLI Entry Point
```python
# auger/cli.py
import click
from auger.config import AugerConfig
from auger.app import AugerApp

@click.group()
@click.version_option()
def main():
    """Auger Platform - AI-powered SRE tools"""
    pass

@main.command()
@click.option('--token', prompt='GitHub token', help='GitHub personal access token')
@click.option('--config-dir', default=None, help='Custom config directory')
def init(token, config_dir):
    """Initialize Auger configuration"""
    config = AugerConfig()
    config.init(token, config_dir)
    click.echo("✅ Auger initialized successfully!")
    click.echo(f"📁 Config: {config.config_file}")
    click.echo("\nRun: auger start")

@main.command()
@click.option('--port', default=6000, help='Web server port')
@click.option('--display', default=None, help='X11 DISPLAY')
@click.option('--debug', is_flag=True, help='Enable debug mode')
def start(port, display, debug):
    """Start Auger Platform GUI"""
    app = AugerApp(port=port, display=display, debug=debug)
    app.run()

@main.command()
def config():
    """Show current configuration"""
    config = AugerConfig()
    click.echo(config.to_yaml())

@main.command()
@click.argument('integration')
def test(integration):
    """Test an integration (datadog, github, servicenow)"""
    from auger.integrations import test_integration
    result = test_integration(integration)
    if result:
        click.echo(f"✅ {integration} integration working")
    else:
        click.echo(f"❌ {integration} integration failed")

@main.command()
def widgets():
    """List available widgets"""
    from auger.ui.widgets import list_widgets
    for widget in list_widgets():
        click.echo(f"- {widget.name}: {widget.description}")

if __name__ == '__main__':
    main()
```

---

## 🐳 Containerization Strategy

### Dockerfile
```dockerfile
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-tk \
    x11-apps \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome for Selenium
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -s /bin/bash auger

# Copy application
WORKDIR /app
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Switch to app user
USER auger

# Create config directory
RUN mkdir -p /home/auger/.auger

# Expose port for web UI (future)
EXPOSE 6000

# Set display
ENV DISPLAY=:0

# Entry point
ENTRYPOINT ["auger"]
CMD ["start"]
```

### docker-compose.yml
```yaml
version: '3.8'

services:
  auger:
    build: .
    image: auger-platform:latest
    container_name: auger
    volumes:
      - ~/.auger:/home/auger/.auger  # Config persistence
      - /tmp/.X11-unix:/tmp/.X11-unix:rw  # X11 socket
    environment:
      - DISPLAY=${DISPLAY}
      - GITHUB_TOKEN=${GITHUB_TOKEN}
    network_mode: host
    stdin_open: true
    tty: true
```

### Usage
```bash
# Build
docker build -t auger-platform .

# Run with X11
xhost +local:docker
docker run -it \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v ~/.auger:/home/auger/.auger \
    auger-platform

# Or with docker-compose
docker-compose up
```

---

## 🔒 Security Considerations

### 1. Token/Secret Storage
```python
# auger/utils/secrets.py
import keyring
from cryptography.fernet import Fernet

class SecretsManager:
    """Secure storage for API keys and tokens"""
    
    def __init__(self):
        self.keyring_available = self._check_keyring()
        self.encryption_key = self._get_or_create_key()
    
    def store(self, service, key, value):
        """Store secret securely"""
        if self.keyring_available:
            # Use system keyring (macOS Keychain, Windows Credential Manager, etc.)
            keyring.set_password(service, key, value)
        else:
            # Fall back to encrypted file
            self._store_encrypted(service, key, value)
    
    def get(self, service, key):
        """Retrieve secret"""
        if self.keyring_available:
            return keyring.get_password(service, key)
        return self._get_encrypted(service, key)
```

### 2. .env File Protection
```python
# Ensure .env is not world-readable
import os
import stat

env_file = os.path.expanduser("~/.auger/.env")
if os.path.exists(env_file):
    os.chmod(env_file, stat.S_IRUSR | stat.S_IWUSR)  # 0600
```

### 3. GitHub Token Scopes
**Minimal required scopes:**
- `repo` - For GitHub widget (read repo info)
- `read:user` - For user info
- `read:org` - For organization repos

**Do NOT require:**
- `admin:*` scopes
- Write access unless needed

---

## 📚 Documentation Structure

### README.md (Quick Start)
```markdown
# Auger Platform

AI-powered SRE platform with dynamic widgets and chat assistant.

## Quick Start

### Install
```bash
pip install auger-platform
```

### Initialize
```bash
auger init
# Enter GitHub token when prompted
```

### Run
```bash
auger start
```

### Ask Auger for Help
Open the chat panel and ask:
- "Help me set up DataDog"
- "Show my GitHub PRs"
- "How do I configure ServiceNow?"

## Features
- 🤖 AI Chat Assistant
- 📊 Dynamic Widgets (Pods, GitHub, ServiceNow, etc.)
- 🔐 Secure Credential Management
- 🔄 Hot Reload
- 🎨 Dark/Light Themes
- 🐳 Container Support
```

### INSTALL.md (Detailed)
- System requirements
- Platform-specific instructions
- Troubleshooting
- Manual installation
- Offline installation

### docs/configuration.md
- Config file structure
- Environment variables
- Widget configuration
- Integration setup
- Secrets management

---

## 🧪 Testing Strategy

### Unit Tests
```python
# tests/test_config.py
def test_config_defaults():
    config = AugerConfig()
    assert config.get('theme') == 'dark'
    assert config.get('port') == 6000

def test_config_env_override():
    os.environ['AUGER_PORT'] = '7000'
    config = AugerConfig()
    assert config.get('port') == 7000
```

### Integration Tests
```python
# tests/test_integrations.py
@pytest.mark.integration
def test_github_integration():
    token = os.getenv('GITHUB_TOKEN')
    github = GitHubIntegration(token)
    assert github.test_connection()

@pytest.mark.integration
def test_datadog_integration():
    api_key = os.getenv('DATADOG_API_KEY')
    app_key = os.getenv('DATADOG_APP_KEY')
    datadog = DataDogIntegration(api_key, app_key)
    assert datadog.test_connection()
```

### Container Tests
```bash
# Test in container
docker build -t auger-test .
docker run --rm auger-test pytest
```

---

## 🚀 Release Process

### 1. Version Tagging
```bash
git tag v1.0.0
git push origin v1.0.0
```

### 2. GitHub Actions CI/CD
```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          pip install build twine
      
      - name: Build package
        run: python -m build
      
      - name: Publish to PyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}
        run: twine upload dist/*
      
      - name: Build Docker image
        run: docker build -t auger-platform:${{ github.ref_name }} .
      
      - name: Push to registry
        run: docker push auger-platform:${{ github.ref_name }}
```

### 3. Release Checklist
- [ ] Update version in pyproject.toml
- [ ] Update CHANGELOG.md
- [ ] Run tests
- [ ] Build package locally
- [ ] Test installation in clean environment
- [ ] Create GitHub release with notes
- [ ] Tag version
- [ ] Publish to PyPI
- [ ] Build and push container
- [ ] Update documentation

---

## 📊 Rollout Plan

### Phase 1: Internal Alpha (Week 1-2)
- ✅ Core functionality working
- ✅ Ask Auger chat panel
- ✅ GitHub widget (requires token only)
- ✅ Config management
- ✅ Basic documentation
- 👥 5-10 alpha testers

### Phase 2: Internal Beta (Week 3-4)
- ✅ All widgets functional
- ✅ DataDog, ServiceNow, Prospector
- ✅ PyPI package
- ✅ Container support
- ✅ Complete documentation
- 👥 20-30 beta testers

### Phase 3: Public Release (Week 5-6)
- ✅ Production-ready
- ✅ Full test coverage
- ✅ CI/CD pipeline
- ✅ Security audit
- ✅ Performance optimization
- 👥 All SREs, Developers, BAs, POs

---

## 🎯 Success Metrics

### Installation Success
- Time to first run < 5 minutes
- Setup completion rate > 90%
- Zero-config for Ask Auger

### User Adoption
- Daily active users
- Widgets enabled per user
- Ask Auger queries per day

### Reliability
- Uptime > 99%
- Error rate < 1%
- Load time < 2 seconds

---

## 💡 Future Enhancements

### Web UI Option
```bash
auger start --web
# Starts web server on http://localhost:6000
# React/Vue frontend
# WebSocket for real-time updates
```

### Plugin System
```python
# Custom widget
from auger.ui.widgets import Widget

class MyCustomWidget(Widget):
    def __init__(self):
        super().__init__("My Widget", "Custom widget")
    
    def render(self, frame):
        # Your widget UI
        pass

# Install
auger plugin install my-custom-widget
```

### Multi-User Support
- Team configurations
- Shared dashboards
- Role-based access

### Cloud Deployment
- Kubernetes deployment
- Helm chart
- Cloud-native features

---

## 📝 Next Steps

### Immediate (This Week)
1. Create GitHub repository structure
2. Implement config management
3. Create pyproject.toml
4. Test Ask Auger with minimal setup
5. Document minimal installation

### Short Term (Next 2 Weeks)
1. Build PyPI package
2. Create Dockerfile
3. Write comprehensive docs
4. Set up CI/CD
5. Alpha testing

### Medium Term (Next Month)
1. Beta release
2. Container registry
3. Security audit
4. Performance optimization
5. Public release

---

## 🤔 Open Questions

1. **Licensing:** MIT, Apache 2.0, or proprietary?
2. **Package name:** `auger-platform`, `auger-sre`, or just `auger`?
3. **Repository:** Public or private GitHub repo?
4. **Distribution:** PyPI only or also conda-forge?
5. **Support:** GitHub Issues, Slack, or internal ticketing?
6. **Updates:** Auto-update or manual?
7. **Telemetry:** Anonymous usage stats or opt-in only?

---

## Summary

**Recommended Approach:**

1. **Phase 1: PyPI Package**
   - Focus on `pip install auger-platform`
   - Minimal config (GitHub token only)
   - Ask Auger helps with everything else
   
2. **Phase 2: Containerization**
   - Docker image for testing/CI
   - Easy deployment option
   
3. **Phase 3: Enhanced Distribution**
   - Install script for one-command setup
   - Web UI option
   - Plugin system

**Key Success Factor:**
Get Ask Auger working first with just a GitHub token. Then users can ask Auger to help set up everything else. This makes onboarding seamless and self-service.
