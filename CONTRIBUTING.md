# Contributing to platformgen

Thanks for your interest in contributing! We love community contributions to the platform generator.

## Getting Started

1. **Fork the repo**: `github.com/techno-vet/platformgen-py`
2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/platformgen-py.git
   cd platformgen-py
   ```
3. **Create a branch**: `git checkout -b feat/my-feature`
4. **Read [DEVELOPMENT.md](DEVELOPMENT.md)** for setup instructions

## Development Environment

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run linter
black platformgen/ auger/ && flake8 platformgen/ auger/

# Run the platform locally
auger start
```

## Code Style

- **Python**: Follow [PEP 8](https://pep8.org/) and use [Black](https://black.readthedocs.io/) for formatting (88-char line length)
- **Type hints**: Required for all public methods
- **Docstrings**: Google style format
- **Testing**: All features must have accompanying tests
- **Tkinter notes**: Do NOT use emoji in `.insert()` calls (causes segfault on Tk 8.6)

## Widget Development

New widgets go in `auger/ui/widgets/` or `platformgen/widgets/`.

**Required for every widget:**

1. `WIDGET_TITLE = "Human Readable Name"` — Tab label
2. `WIDGET_ICON_FUNC = staticmethod(icon_function)` — Icon generator
3. Entry in `auger/data/widget_manifests.yaml` with metadata:
   - `title`, `purpose`, `depends_on`, `used_by`, `key_data_files`
4. `WIDGET_DEMO_DATA = {...}` — Sample data for demo mode (AUGER_DEMO=1)
5. `refresh()` method — Called on hot reload (no restart needed)

**Example widget:**

```python
# platformgen/widgets/my_widget.py
import tkinter as tk

WIDGET_TITLE = "My Platform Widget"
WIDGET_ICON_FUNC = staticmethod(lambda: "🎨")

class MyWidget(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs, bg='#1a1a2e')
        self._build_ui()
    
    def _build_ui(self):
        label = tk.Label(
            self, 
            text="Hello from platformgen!", 
            bg='#1a1a2e', 
            fg='#e0e0e0'
        )
        label.pack(padx=10, pady=10)
    
    def refresh(self):
        """Called on hot reload — no app restart needed."""
        pass

WIDGET_DEMO_DATA = {
    "example_key": "example_value",
    "items": ["item1", "item2", "item3"],
}
```

## Submitting Changes

### Branch Naming
- `feat/xyz` — New feature
- `fix/xyz` — Bug fix
- `docs/xyz` — Documentation
- `refactor/xyz` — Code refactoring
- `test/xyz` — Test improvements

### Commit Messages
```
Short summary (50 chars max)

Longer description if needed (wrap at 72 chars).
- Bullet point 1
- Bullet point 2
- Reference issue: Closes #123
```

### Pull Request Checklist
- [ ] Tests pass locally (`pytest tests/`)
- [ ] Code follows style guide (`black --check`, `flake8`)
- [ ] No new warnings or errors
- [ ] Docstrings updated
- [ ] CHANGELOG.md updated (if applicable)
- [ ] Screenshots added (if UI-related)

### PR Description Template
```markdown
## Description
Brief description of changes.

## Related Issue
Closes #123

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Widget
- [ ] Breaking change

## Testing
How to test these changes:
1. ...
2. ...

## Screenshots (if applicable)
[Attach images here]
```

## Reporting Issues

Use [GitHub Issues](https://github.com/techno-vet/platformgen-py/issues) with:

- **Title**: Clear, concise description
- **Description**: What happened? Expected behavior? Actual behavior?
- **Environment**: 
  - Python version
  - OS (Linux, macOS, Windows)
  - Tkinter version
  - Docker or venv?
- **Reproduction Steps**: Step-by-step to reproduce
- **Screenshots**: If UI-related

**Example:**
```markdown
## Description
Ask Genny widget fails to load when token is expired.

## Environment
- Python 3.10.5
- Ubuntu 22.04
- Tkinter 8.6
- Docker container

## Reproduction
1. Start platform with expired GH_TOKEN
2. Click "Ask Genny" tab
3. Widget shows blank screen

## Expected
Show token renewal prompt or error message
```

## Architecture & Codebase

### Key Directories

```
platformgen-py/
├─ platformgen/          ← Core platform generator library
│  ├─ core/             ← Base classes, widget system
│  ├─ agents/           ← AI agent implementations (Ask Genny)
│  └─ widgets/          ← Pre-built platform widgets
├─ auger/               ← Auger SRE platform (example using platformgen)
│  ├─ ui/               ← Tkinter UI, widgets
│  ├─ data/             ← Configuration, manifests
│  └─ cli/              ← Command-line interface
├─ tests/               ← Pytest test suite
├─ docs/                ← Architecture, API docs
├─ scripts/             ← Setup and utility scripts
└─ k8s/                 ← Kubernetes deployment configs
```

### How platformgen Works

1. **Extensible Widget System**: Widgets are Python classes with metadata
2. **AI-Driven**: Ask Genny understands your platform and generates code/configs
3. **Hot Reload**: Change widget files, see changes in 1 second (no restart)
4. **Dark Theme**: Professional UI with markdown support, animations
5. **Self-Bootstrapping**: Genny can improve platformgen itself

### Testing

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_widgets.py

# Run with coverage
pytest --cov=platformgen tests/

# Run with verbose output
pytest -v tests/
```

## Documentation

- [DEVELOPMENT.md](DEVELOPMENT.md) — Dev environment setup
- [INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md) — Installation instructions
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — System architecture
- [docs/QUICKSTART.md](docs/QUICKSTART.md) — Quick start guide
- [FAQ.md](FAQ.md) — Frequently asked questions

## Community

- 💬 [Discussions](https://github.com/techno-vet/platformgen-py/discussions) — Ask questions, share ideas
- 🐛 [Issues](https://github.com/techno-vet/platformgen-py/issues) — Report bugs or request features
- 💬 [Discord](https://discord.gg/platformgen) — Real-time community chat
- 🌟 [GitHub Sponsors](https://github.com/sponsors/techno-vet) — Support the project

## Code of Conduct

This project adheres to the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Questions?

- **Need help?** Open a [Discussion](https://github.com/techno-vet/platformgen-py/discussions)
- **Found a bug?** Create an [Issue](https://github.com/techno-vet/platformgen-py/issues)
- **Want to chat?** Join our [Discord](https://discord.gg/platformgen)

---

**Thank you for contributing to platformgen! We're excited to see what you build.** 🚀
