"""Shared help-doc catalogue used by app.py menu and HelpViewerWidget dropdown."""
from pathlib import Path

DOCS_DIR = Path(__file__).parent.parent.parent / 'docs'

# (display label, filename)  — widget-specific docs
WIDGET_DOCS = [
    ("Ask Auger / Copilot", "AUGER_ASK.md"),
    ("Tasks",            "README_TASKS.md"),
    ("Prompts",          "README_PROMPTS.md"),
    ("API Keys+",        "README_API_CONFIG.md"),
    ("Host Tools",       "README_HOST_TOOLS.md"),
    ("Bash Terminal",    "README_SHELL_TERMINAL.md"),
    ("Explorer",         "README_EXPLORER.md"),
    ("Database",         "README_DATABASE.md"),
    ("Pods",             "README_PODS.md"),
    ("Flux Config",      "README_FLUX_CONFIG.md"),
    ("Release Manager",  "README_PRODUCTION_RELEASE.md"),
    ("Jira",             "README_JIRA.md"),
    ("GitHub",           "README_GITHUB_WIDGET.md"),
    ("Panner",           "README_PANNER_WIDGET.md"),
    ("Prospector",       "README_PROSPECTOR_WIDGET.md"),
    ("Prisma Cloud",     "README_PRISMA_WIDGET.md"),
    ("Cryptkeeper",      "README_CRYPTKEEPER.md"),
    ("Cryptkeeper Lite", "README_CRYPTKEEPER_LITE.md"),
    ("ServiceNow",       "README_SERVICENOW.md"),
    ("Artifactory",      "README_ARTIFACTORY.md"),
    ("Confluence",       "README_CONFLUENCE_WIDGET.md"),
    ("Image Lab",        "README_IMAGE_LAB.md"),
    ("Google Chat",       "README_GCHAT.md"),
]

# Top-level / general docs
GENERAL_DOCS = [
    ("Quick Start",    "QUICKSTART.md"),
    ("Docker Setup",   "DOCKER.md"),
    ("Project Summary","PROJECT_SUMMARY.md"),
]

# Combined flat list: (label, full_path)
def all_docs():
    """Return [(label, Path), ...] for every doc that exists on disk."""
    result = []
    for label, fname in GENERAL_DOCS + WIDGET_DOCS:
        p = DOCS_DIR / fname
        if p.exists():
            result.append((label, p))
    return result
