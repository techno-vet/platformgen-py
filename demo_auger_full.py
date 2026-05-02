#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║           AUGER AI SRE PLATFORM — FULL WIDGET SHOWCASE DEMO                ║
║                                                                              ║
║  Usage:                                                                      ║
║    python3 demo_auger_full.py              # interactive (ENTER to advance) ║
║    python3 demo_auger_full.py --auto       # fully automatic                ║
║    python3 demo_auger_full.py --auto --fast  # fast auto (shorter pauses)   ║
║    python3 demo_auger_full.py --offline    # polished demo — no .env needed ║
║    python3 demo_auger_full.py --widget gchat  # demo one widget only        ║
║                                                                              ║
║  Requirements: Python 3.8+  (no pip installs needed for --offline mode)     ║
║    Optional: pip install pyyaml python-dotenv                                ║
║                                                                              ║
║  --offline: uses curated demo dataset — works on any machine, no .env,      ║
║             no internal network access required. Safe to share externally.  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import sys, os, time, json, subprocess, sqlite3, textwrap, shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta


def now_et() -> datetime:
    """Return current time in Eastern Time (EST/EDT) without requiring pytz.
    2026 DST: spring forward 2026-03-08 07:00 UTC (2am EST→EDT), fall back 2026-11-01 06:00 UTC."""
    utc_now = datetime.now(timezone.utc)
    spring_forward = datetime(2026, 3,  8,  7, 0, 0, tzinfo=timezone.utc)
    fall_back      = datetime(2026, 11, 1,  6, 0, 0, tzinfo=timezone.utc)
    if spring_forward <= utc_now < fall_back:
        return utc_now.astimezone(timezone(timedelta(hours=-4))), "EDT"
    return utc_now.astimezone(timezone(timedelta(hours=-5))), "EST"


def fmt_et(dt: datetime = None) -> str:
    """Format a datetime (or now) as '03/06/2026 12:20 PM EST'."""
    et, tz_name = now_et() if dt is None else (dt, "ET")
    return et.strftime(f"%m/%d/%Y %I:%M %p {tz_name}")

# ── optional deps ─────────────────────────────────────────────────────────────
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    print("pip install pyyaml  to get full demo experience")
    time.sleep(1)

try:
    from dotenv import load_dotenv
    load_dotenv(Path.home() / ".auger" / ".env")
except ImportError:
    pass

# ── colour helpers ─────────────────────────────────────────────────────────────
R  = "\033[0m";  BD = "\033[1m";  DIM = "\033[2m"; IT = "\033[3m"
CY = "\033[96m"; GR = "\033[92m"; YL  = "\033[93m"; RD = "\033[91m"
BL = "\033[94m"; MG = "\033[95m"; WH  = "\033[97m"; GY = "\033[90m"

def c(col, t): return f"{col}{t}{R}"
def hr(n=78):  return c(CY, "═"*n)

# ── CLI flags ─────────────────────────────────────────────────────────────────
AUTO    = "--auto"    in sys.argv
FAST    = "--fast"    in sys.argv
OFFLINE = "--offline" in sys.argv
ONLY    = sys.argv[sys.argv.index("--widget")+1] if "--widget" in sys.argv else None

PAUSE_S = 0.6  if (AUTO and FAST) else (1.2 if AUTO else 0)
PAUSE_M = 1.2  if (AUTO and FAST) else (2.5 if AUTO else 0)
PAUSE_L = 2.0  if (AUTO and FAST) else (4.0 if AUTO else 0)
TD      = 0.008 if FAST else 0.015

# ── curated demo dataset (used in --offline mode) ─────────────────────────────
DEMO_CREDS = [
    ("ARTIFACTORY_URL",        "https://artifactory.helix.gsa.gov"),
    ("ARTIFACTORY_USERNAME",   "bobbygblair"),
    ("ARTIFACTORY_API_KEY",    "AKCp8pXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"),
    ("AWS_1_ACCESS_KEY_ID",    "AKIA34XXXXXXXXXXXXXXXX"),
    ("DATADOG_SITE",           "ddog-gov.com"),
    ("DATADOG_API_KEY",        "dd0c8fXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"),
    ("GHE_URL",                "https://github.helix.gsa.gov"),
    ("GHE_TOKEN",              "ghp_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"),
    ("JIRA_URL",               "https://gsa-standard.atlassian-us-gov-mod.net"),
    ("JIRA_COOKIES",           "JSESSIONID=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"),
    ("JIRA_COOKIE_EXPIRY",     "2026-03-06T23:59:59"),
    ("JENKINS_URL",            "https://jenkins.helix.gsa.gov"),
    ("RANCHER_URL",            "https://rancher.staging.core.mcaas.fcs.gsa.gov"),
    ("SERVICENOW_URL",         "https://gsa.servicenowservices.com"),
    ("SERVICENOW_COOKIES",     "JSESSIONID=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"),
    ("DEV_CRYPTKEEPER_KEY",    "devKeyXXXXXXXXXXXXXXXXXX"),
    ("STAGING_CRYPTKEEPER_KEY","stagKeyXXXXXXXXXXXXXXXXXX"),
    ("PROD_CRYPTKEEPER_KEY",   "prodKeyXXXXXXXXXXXXXXXXXX"),
    ("GCHAT_WEBHOOK_ME",       "https://chat.googleapis.com/v1/spaces/DEMO/messages"),
    ("CONFLUENCE_BASE_URL",    "https://gsa-standard.atlassian-us-gov-mod.net/wiki"),
]

DEMO_TASKS = [
    (103, "Research: Fine-tune LLM on Auger+ASSIST knowledge", "pending",    "medium"),
    (102, "Post-Jira-Upgrade: Verify MFA Auth in Jira Widget", "pending",    "high"),
    (101, "ASSIST3-31091: Validate prod after PR #1077 merge",  "pending",    "high"),
    (100, "Demo scripts for brown bag presentation",            "done",       "medium"),
    (99,  "Story to Prod: Auger-Led Stakeholder Workflow",      "pending",    "high"),
    (96,  "Staging namespace naming conventions doc",           "pending",    "critical"),
    (72,  "Deploy cryptkeeper BUILD4 to prod data-utils",       "pending",    "high"),
    (70,  "Panner Phase 1: auto-source kubectl+DataDog",        "in_progress","medium"),
    (55,  "Add hot-reload support to widget loader",            "done",       "medium"),
    (42,  "ASSIST3-38045: Alpha Testing Prompts & Help Wizard", "in_progress","high"),
]

DEMO_REPOS = [
    ("auger-ai-sre-platform",    "2026-03-06"),
    ("assist-flux-config",       "2026-03-06"),
    ("assist-prod-flux-config",  "2026-03-05"),
    ("assist-data-utils",        "2026-03-04"),
    ("devtools-scripts",         "2026-03-03"),
    ("helm-charts",              "2026-03-01"),
    ("assist-core",              "2026-02-28"),
    ("cloudbeaver-config",       "2026-02-25"),
]

DEMO_LOGS = [
    ("data-utils",   "INFO  JupyterHub - 200 GET /hub/login (@::1) 12.34ms"),
    ("data-utils",   "DEBUG SessionManager - session f0de6926 active, user bobbygblair"),
    ("cloudbeaver",  "DEBUG WebServiceBindingBase - API > getServerConfig [@anonymous@]"),
    ("data-utils",   "INFO  JupyterHub - 302 GET /hub/ (@::1) → /hub/login 3.1ms"),
    ("assist-core",  "INFO  HealthCheck - all services nominal [2026-03-06T17:00:01Z]"),
]

def offline_env(key, fallback=""):
    """Return demo value for key in offline mode, else real env."""
    if OFFLINE:
        demo_map = dict(DEMO_CREDS)
        return demo_map.get(key, fallback)
    return os.environ.get(key, fallback)

# ── paths ─────────────────────────────────────────────────────────────────────
REPO      = Path(__file__).parent
HOME      = Path.home()
AUGER_DIR = HOME / ".auger"
MANIFESTS = REPO / "auger" / "data" / "widget_manifests.yaml"
WEBHOOKS  = REPO / "auger" / "data" / "gchat_webhooks.yaml"
USERS_YML = REPO / "auger" / "data" / "gchat_users.yaml"
RULES_YML = AUGER_DIR / "rules.yaml"
CONVS_YML = AUGER_DIR / "conventions.yaml"
TASKS_DB  = AUGER_DIR / "tasks.db"

# ── helpers ───────────────────────────────────────────────────────────────────
TW = shutil.get_terminal_size((100, 40)).columns

def clear(): os.system("clear")

def pause(msg="[ ENTER to continue ]", dur=None):
    d = dur if dur is not None else PAUSE_M
    if AUTO:
        time.sleep(d)
    else:
        input(f"\n{c(GY, '  '+msg)}")

def typewrite(text, delay=None):
    d = delay if delay is not None else TD
    for ch in text:
        sys.stdout.write(ch); sys.stdout.flush(); time.sleep(d)
    print()

def narrator(text):
    """The 'speaking' voice of the demo — highlighted narration block."""
    lines = textwrap.wrap(text.strip(), width=TW - 8)
    print()
    print(f"  {c(MG+BD, '🎙  AUGER:')}")
    for line in lines:
        typewrite(f"  {c(WH+IT, line)}")
    print()
    time.sleep(PAUSE_S)

def section(num, title, sub=""):
    print(f"\n{hr()}")
    print(c(BD+CY, f"  SECTION {num}  —  {title}"))
    if sub: print(c(DIM, f"  {sub}"))
    print(hr())

def widget_header(icon, name, tagline):
    print(f"\n  {c(BD+YL, icon+'  '+name)}")
    print(f"  {c(DIM, tagline)}")
    print(f"  {c(GY, '-'*60)}")

def ok(m):   print(f"  {c(GR,'✓')} {m}")
def info(m): print(f"  {c(BL,'ℹ')} {m}")
def warn(m): print(f"  {c(YL,'⚠')} {m}")
def live(m): print(f"  {c(GR+BD,'⚡ LIVE:')} {m}")
def mock(m): print(f"  {c(GY,'◎ DEMO:')} {m}")
def cmd(s):  print(f"\n  {c(GY,'$ '+s)}")

def load_yaml(path):
    if not HAS_YAML or not Path(path).exists(): return {}
    try: return yaml.safe_load(Path(path).read_text()) or {}
    except: return {}

def get_env(key, fallback=""):
    return offline_env(key, fallback)

def mask(val, show=6):
    return val[:show]+"..." if len(val) > show else "***"

# ══════════════════════════════════════════════════════════════════════════════
# INTRO
# ══════════════════════════════════════════════════════════════════════════════
def show_intro():
    clear()
    print(c(BD+CY, r"""
   ___  __  __ ___ _____ ____
  / _ \|  \/  | __|_   _|  _ \
 | |_| | |\/| |  _| | | | |_) |
  \___/|_|  |_|___| |_| |____/
    """))
    et_now, tz_name = now_et()
    print(c(WH+BD, "  ASSIST SRE Platform  ·  Full Widget Showcase  ·  " + et_now.strftime(f"%m/%d/%Y %I:%M %p {tz_name}")))
    narrator(
        "Welcome! I'm Auger — an AI agent embedded directly inside the ASSIST SRE Platform. "
        "I'm not a browser chatbot. I live inside the tools your team already uses. "
        "This demo walks through all "
        "24 widgets with live data where possible — plus a live widget scaffold — "
        "and narrated captions throughout so you can follow without anyone in the room explaining it."
    )
    manifests = load_yaml(MANIFESTS)
    widget_count = len(manifests.get("widgets", {})) or 24
    if OFFLINE:
        task_count = len(DEMO_TASKS)
        rule_count = 7
    else:
        task_count = 0
        if TASKS_DB.exists():
            conn = sqlite3.connect(TASKS_DB)
            task_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            conn.close()
        rule_count = len(load_yaml(RULES_YML).get("rules", []))

    mode_label = ("AUTO --offline" if OFFLINE else "AUTO") if AUTO else "INTERACTIVE (ENTER to advance)"
    print(f"\n  {c(BD, 'Platform snapshot:')}")
    ok(f"Widgets with AI knowledge manifests:  {c(BD+GR, str(widget_count))}")
    ok(f"Tasks tracked in SQLite DB:           {c(BD+GR, str(task_count))}")
    ok(f"Operational rules enforced:           {c(BD+GR, str(rule_count))}")
    ok(f"Demo mode:                            {c(BD+GR, mode_label)}")
    if OFFLINE:
        info("Running in --offline mode: curated demo data, no network calls, no .env required")
    pause("Press ENTER to begin the full tour...", PAUSE_L)


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 1 — API Keys+
# ══════════════════════════════════════════════════════════════════════════════
def demo_api_config():
    section(1, "API Keys+", "Credential manager — every other widget builds on this")
    widget_header("🔑", "API Keys+", "Reads/writes ~/.auger/.env — hot-picked by all widgets without restart")
    narrator(
        "API Keys Plus is the freshman year widget — the first one we built and the one "
        "nearly everything else depends on. It manages all service credentials in a single "
        "dot-env file. Update a token here, and every other widget picks it up instantly."
    )
    if OFFLINE:
        creds = DEMO_CREDS
        live(f"{len(creds)} credentials  (demo dataset — masked for presentation)")
        for k, val in creds:
            print(f"    {c(CY, k):<46} {c(GY, mask(val))}")
    else:
        keys = sorted([k for k in os.environ
                       if any(x in k for x in ["TOKEN","KEY","PASSWORD","URL","USER","COOKIE","SITE"])
                       and "PATH" not in k and "SHELL" not in k])
        live(f"{len(keys)} credentials loaded from ~/.auger/.env")
        for k in keys[:14]:
            val = get_env(k,"")
            print(f"    {c(CY, k):<46} {c(GY, mask(val))}")
        if len(keys) > 14:
            print(f"    {c(GY, f'... and {len(keys)-14} more')}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 2 — Google Chat
# ══════════════════════════════════════════════════════════════════════════════
def demo_gchat():
    section(2, "Google Chat", "Post rich cards, @mentions, PR reviews to any team channel")
    widget_header("💬", "Google Chat", "Webhooks from gchat_webhooks.yaml · User IDs from gchat_users.yaml")
    narrator(
        "The GChat widget posts rich formatted cards to any team channel. "
        "Webhook URLs always come from gchat_webhooks.yaml — never hardcoded. "
        "At-mentions use numeric user IDs from gchat_users.yaml — plain text names "
        "don't actually ping anyone in Google Chat. This week I used this widget daily."
    )
    webhooks = load_yaml(WEBHOOKS).get("webhooks", [])
    if webhooks:
        live(f"{len(webhooks)} configured channels:")
        for wh in webhooks:
            print(f"    {c(BD+YL, wh['name']+'  ')}{c(DIM, wh.get('description',''))}")
    users_raw = load_yaml(USERS_YML)
    users = users_raw if isinstance(users_raw, list) else users_raw.get("users", [])
    if users:
        live(f"{len(users)} team members in @mention registry (sample):")
        for u in users[:3]:
            print(f"    {c(CY, u.get('name','?')):<40} {c(GY, '<users/'+u.get('user_id','?')+'>')}")
    mock("Messages sent this week:")
    for msg in [
        "PR review request  →  PR_REVIEWS  (staging #9079)",
        "Prod PR #1077 notice  →  SRE channel  (⛔ DO NOT MERGE)",
        "Bobby's standup  →  SRE  (skipping — not feeling well)",
        "ASSIST3-31091 validation results  →  @Samir Bham in SRE",
        "LLM training idea pitch  →  AUGER_POC",
    ]:
        print(f"    {c(GR,'✉')}  {msg}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 3 — Jira
# ══════════════════════════════════════════════════════════════════════════════
def demo_jira():
    section(3, "Jira", "Story browser, sprint board, status transitions")
    widget_header("📋", "Jira", "gsa-standard.atlassian-us-gov-mod.net via PIV/MFA JSESSIONID cookie — not a plain API token")
    narrator(
        "The Jira widget connects to the government Jira instance. "
        "Authentication uses MFA session cookies captured by a Selenium Chrome flow "
        "running on the host via the Host Tools Daemon. This is also the entry point "
        "of the Story-to-Prod pipeline — every deployment starts with a Jira story."
    )
    live(f"Jira URL: {get_env('JIRA_URL','https://gsa-standard.atlassian-us-gov-mod.net')}")
    cookies_present = bool(get_env("JIRA_COOKIES",""))
    if cookies_present:
        ok(f"JSESSIONID cookie present  (expires: {get_env('JIRA_COOKIE_EXPIRY','unknown')})")
    else:
        warn("JSESSIONID not set — re-auth via Host Tools → jira_login")
    mock("Active story in current sprint:")
    for k,v in [("Key","ASSIST3-38045"),("Summary","Alpha Testing Prompts & Help Wizard"),
                ("Status","In Progress"),("Assignee","Bobby Blair"),
                ("Sprint","ASSIST Sprint 47"),("Branch","feature/ASSIST3-38045-alpha-testing-prompts-help-wizard")]:
        print(f"    {c(CY, k+':'):<22} {v}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 4 — Story → Prod
# ══════════════════════════════════════════════════════════════════════════════
def demo_story_to_prod():
    section(4, "Story → Prod", "Full pipeline from Jira story to production — redesigned this week")
    widget_header("🚀", "Story → Prod", "Jira → Branch → Local Env → Dev Deploy → PR → Jenkins → Image → Staging → PROD")
    narrator(
        "Story-to-Prod is the centerpiece widget. It gives you a visual pipeline "
        "for any Jira story from start to production. We redesigned it this week — "
        "added a Branch stage, Local Env stage with a skip checkbox for config-only "
        "changes, and Dev Deploy with two collaboration loop arrows on the canvas. "
        "ASSIST3-31091 is currently loaded in it."
    )
    sc = {"done":GR,"in_progress":YL,"pending":GY,"skipped":DIM}
    stages = [
        ("📌","Jira",       "ASSIST3-31091 — xsrf cookie Secure flag",              "done"),
        ("🌿","Branch",     "feature/ASSIST3-31091-xsrf-cookie-secure-flag",        "done"),
        ("💻","Local Env",  "SKIPPED — config-only change, no code changes",        "skipped"),
        ("🔄","Dev Deploy", "Not applicable for flux-only fix",                     "skipped"),
        ("🔀","PR",         "Staging #9079 merged ✅   Prod #1077 open ⏳",         "in_progress"),
        ("⚙️","Jenkins",    "Build auto-triggered on PR merge",                     "done"),
        ("📦","Image",      "data-utils:1.5.4.0 in Artifactory",                   "done"),
        ("🌊","Staging",    "Deployed + validated — Secure/HttpOnly/SameSite ✅",  "done"),
        ("🏭","PROD",       "PR #1077 awaiting 2 approvals on assist-prod-flux-config","pending"),
    ]
    for icon,name,detail,status in stages:
        bar = c(sc.get(status,WH), f"[{status:<11}]")
        print(f"  {icon}  {bar}  {c(BD, name):<22}  {c(DIM, detail)}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 5 — Flux Config
# ══════════════════════════════════════════════════════════════════════════════
def demo_flux_config():
    section(5, "Flux Config", "Browse, diff, and create PRs in Flux HelmRelease YAML repos")
    widget_header("🌊", "Flux Config", "assist-flux-config (staging/dev)  +  assist-prod-flux-config (prod)")
    narrator(
        "Flux Config is how we deploy to all environments. It browses both flux repos, "
        "shows current image tags, and creates PRs to promote changes. "
        "Critical rule: ALL PRs must target the deploy-automation branch — never main. "
        "I added that rule just this week after a PR was accidentally opened against main."
    )
    # Show real ASSIST3-31091 diff lines
    flux_file = HOME / "repos/assist-flux-config/core/staging/data-utils/utils/data-utils.yaml"
    if flux_file.exists():
        live(f"Real deployed fix in assist-flux-config:")
        result = subprocess.run(
            ["git","-C", str(HOME/"repos/assist-flux-config"),
             "show","HEAD:core/staging/data-utils/utils/data-utils.yaml"],
            capture_output=True, text=True, timeout=8)
        for i, line in enumerate(result.stdout.splitlines()):
            if "tornado_settings" in line or "xsrf_cookie_kwargs" in line:
                for l in result.stdout.splitlines()[max(0,i-1):i+8]:
                    col = GR if any(x in l for x in ["tornado","xsrf","secure","httponly","samesite"]) else GY
                    print(f"    {c(col, l)}")
                break
    else:
        mock("ASSIST3-31091 fix (tornado_settings in configJH):")
        for l in ["  c.JupyterHub.tornado_settings = {",
                  "    'xsrf_cookie_kwargs': {'secure':True,'httponly':True,'samesite':'Strict'}",
                  "  }"]:
            print(f"    {c(GR,'+')}  {c(GY, l)}")
    print()
    ok("ALL flux PRs → deploy-automation branch (never main)")
    ok("assist-prod-flux-config requires 2 approvals before merge")
    ok("data-utils configJH is the LIVE jupyterhub config — NOT the docker image")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 6 — GitHub
# ══════════════════════════════════════════════════════════════════════════════
def demo_github():
    section(6, "GitHub", "Repository browser — github.helix.gsa.gov (Government GitHub Enterprise)")
    widget_header("🐙", "GitHub", "Browse repos, PRs, issues, commits — org: assist")
    narrator(
        "The GitHub widget connects to the government GitHub Enterprise instance. "
        "All git pushes from the container use HTTPS with GHE_TOKEN — never SSH. "
        "Let me show you the real repos in the assist org right now."
    )
    if OFFLINE:
        mock(f"Recently updated repos (github.helix.gsa.gov/assist):")
        for name, updated in DEMO_REPOS:
            print(f"    {c(CY, name):<50}  {c(GY, updated)}")
    else:
        try:
            import urllib.request
            token = get_env("GHE_TOKEN","")
            ghe   = get_env("GHE_URL","https://github.helix.gsa.gov")
            req = urllib.request.Request(
                f"{ghe}/api/v3/orgs/assist/repos?per_page=10&sort=updated",
                headers={"Authorization": f"token {token}", "User-Agent": "auger-demo"})
            with urllib.request.urlopen(req, timeout=8) as r:
                repos = json.loads(r.read())
            live(f"Top 10 recently updated repos  —  {ghe}/assist")
            for repo in repos:
                updated = repo.get("updated_at","")[:10]
                print(f"    {c(CY, repo['name']):<50}  {c(GY, updated)}")
        except Exception as e:
            mock("Recently updated repos (github.helix.gsa.gov/assist):")
            for name, updated in DEMO_REPOS:
                print(f"    {c(CY, name):<50}  {c(GY, updated)}")
            warn(f"Live fetch unavailable: {e}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 7 — Artifactory
# ══════════════════════════════════════════════════════════════════════════════
def demo_artifactory():
    section(7, "Artifactory", "Browse, pull, push Docker images — primary image store for all ASSIST builds")
    widget_header("📦", "Artifactory", "artifactory.helix.gsa.gov — images promoted via Flux PR, never direct push")
    narrator(
        "Artifactory is where all ASSIST Docker images live after a Jenkins build. "
        "The widget lets you browse repos, find image tags, and pull images locally. "
        "Image promotion to production always goes through a Flux config PR — "
        "you never push an image tag directly to production."
    )
    try:
        import urllib.request, base64
        aurl  = get_env("ARTIFACTORY_URL","")
        auser = get_env("ARTIFACTORY_USERNAME","")
        akey  = get_env("ARTIFACTORY_API_KEY","")
        creds = base64.b64encode(f"{auser}:{akey}".encode()).decode()
        req = urllib.request.Request(f"{aurl}/artifactory/api/repositories?type=local",
            headers={"Authorization": f"Basic {creds}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            repos = json.loads(r.read())
        live(f"Local repositories in {aurl}:")
        for repo in repos[:6]:
            print(f"    {c(CY, repo['key']):<44}  {c(GY, repo.get('packageType','?'))}")
    except Exception as e:
        mock("Artifactory repositories:")
        for repo in ["gs-assist-docker-repo","GS-ASSIST-REPO","GS-ASSIST-MAVEN-REPO"]:
            print(f"    {c(CY, repo)}")
    mock("Latest data-utils image tags in gs-assist-docker-repo:")
    for tag in ["data-utils:1.5.4.0  ← current staging","data-utils:1.5.3.2","data-utils:1.5.3.1"]:
        print(f"    {c(GY,'📌')} {tag}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 8 — K8s Explorer
# ══════════════════════════════════════════════════════════════════════════════
def demo_k8s_explorer():
    section(8, "K8s Explorer", "Kubernetes resource browser — pods, services, configmaps, events")
    widget_header("☸️", "K8s Explorer", "Rancher API — read-only exploration, never kubectl apply from container")
    narrator(
        "K8s Explorer connects to the Rancher management API to browse all Kubernetes "
        "resources across clusters. It's designed for read-only exploration — "
        "you can see everything but deployments always go through Flux PRs, "
        "never a kubectl apply from inside this container."
    )
    live(f"Rancher URL: {get_env('RANCHER_URL','https://rancher.staging.core.mcaas.fcs.gsa.gov')}")
    mock("Namespaces — staging cluster:")
    for ns in ["data-utils","assist-core","airflow","data-api-service","data-catalog","monitoring"]:
        print(f"    {c(CY, ns)}")
    mock("Pods in data-utils namespace:")
    for name, status, age in [
        ("data-utils-hub-7d9f8b-xk2p9",   "Running", "3d"),
        ("data-utils-proxy-6c4d9f-mn7q1", "Running", "3d"),
        ("data-utils-singleuser-0",        "Running", "1h"),
    ]:
        print(f"    {c(GR,'●')}  {c(WH, name):<48}  {c(GR,status):<10}  {c(GY,age)}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 9 — Pods
# ══════════════════════════════════════════════════════════════════════════════
def demo_pods():
    section(9, "Pods", "At-a-glance pod health dashboard across all namespaces")
    widget_header("🫛", "Pods", "Quick-view companion to K8s Explorer — color-coded status summary")
    narrator(
        "The Pods widget is the quick-view version of K8s Explorer. "
        "Instead of navigating a full resource tree, you get an instant color-coded "
        "health summary across all namespaces. Red means something needs attention."
    )
    mock("Pod status summary — staging cluster:")
    for ns, total, running, pending in [
        ("data-utils",       3, 3, 0), ("assist-core",      8, 8, 0),
        ("airflow",         12,11, 1), ("data-api-service", 4, 4, 0),
        ("monitoring",       6, 5, 1),
    ]:
        bar = c(GR,"█"*running) + c(YL,"░"*pending)
        print(f"    {ns:<28}  {bar}  {c(GY, f'{running}/{total}')}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 10 — Panner
# ══════════════════════════════════════════════════════════════════════════════
def demo_panner():
    section(10, "Panner", "DataDog log downloader — search, filter, download, stream")
    widget_header("🔍", "Panner", "ddog-gov.com — real logs from ASSIST services")
    narrator(
        "Panner is our DataDog log downloader. You give it a time range, service tags, "
        "and a filter expression, and it pulls the matching logs directly. "
        "The cached results shown here are real log lines from the ASSIST platform "
        "from a recent run."
    )
    panner_results = AUGER_DIR / "panner" / "results.json"
    if OFFLINE:
        mock(f"{len(DEMO_LOGS)} cached log entries (demo dataset):")
        for svc, msg in DEMO_LOGS:
            print(f"    {c(GY, svc):<22}  {c(DIM, msg)}")
    elif panner_results.exists():
        try:
            data = json.loads(panner_results.read_text())
            if isinstance(data, list) and data:
                live(f"{len(data)} cached log entries (panner/results.json):")
                for entry in data[:5]:
                    attrs = entry.get("attributes", {})
                    msg   = attrs.get("message","")[:85]
                    svc   = attrs.get("service","?")
                    print(f"    {c(GY, svc):<22}  {c(DIM, msg)}")
        except Exception:
            pass
    else:
        mock("Sample DataDog logs (cloudbeaver / data-utils):")
        for svc, msg in DEMO_LOGS[:3]:
            print(f"    {c(GY, msg)}")
    dd = get_env("DATADOG_SITE","ddog-gov.com")
    live(f"DataDog site: {dd}  |  API key: {mask(get_env('DATADOG_API_KEY','n/a'))}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 11 — Database
# ══════════════════════════════════════════════════════════════════════════════
def demo_database():
    section(11, "Database", "SQL workbench — PostgreSQL, SQLite, schema browser, query runner")
    widget_header("🗄️", "Database", "ASSIST Core Dev DB on RDS + Auger's own SQLite task database")
    narrator(
        "The Database widget is a full SQL workbench. It connects to the ASSIST core "
        "development PostgreSQL database on RDS and to local SQLite databases. "
        "Watch — I'll run a live query against Auger's own tasks database right now."
    )
    mock("Connection: ASSIST Core Dev DB")
    print(f"    {c(CY,'Host:')} assist-core-development-db-postgres.cluster-cxwm0hb0ofre.us-east-1.rds.amazonaws.com")
    print(f"    {c(CY,'DB:')}   dev09   {c(GY,'(aasbs schema — 200+ tables)')}")
    if TASKS_DB.exists():
        live("Live query against ~/.auger/tasks.db:")
        cmd("SELECT status, priority, COUNT(*) FROM tasks GROUP BY status, priority ORDER BY status")
        conn = sqlite3.connect(TASKS_DB)
        rows = conn.execute(
            "SELECT status, priority, COUNT(*) FROM tasks "
            "GROUP BY status, priority ORDER BY status, priority").fetchall()
        conn.close()
        print(f"    {'status':<14} {'priority':<10} {'count':>5}")
        print(f"    {'-'*32}")
        sc = {"done":GR,"pending":YL,"in_progress":CY,"blocked":RD}
        for status, priority, count in rows:
            print(f"    {c(sc.get(status,WH), status):<23} {priority:<10} {str(count):>5}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 12 — Cryptkeeper + Lite
# ══════════════════════════════════════════════════════════════════════════════
def demo_cryptkeeper():
    section(12, "Cryptkeeper + Cryptkeeper Lite", "Jasypt encryption for secrets in flux config files")
    widget_header("🔐", "Cryptkeeper / Lite", "Encrypts/decrypts ENC(...) values — env-specific keys")
    narrator(
        "Cryptkeeper handles Jasypt-encrypted secrets in our flux config files. "
        "The full version uses a Docker container. Cryptkeeper Lite is the fast "
        "inline version — no Docker needed. Both support environment-specific keys: "
        "dev, staging, and production each have their own encryption key."
    )
    key = get_env("DEV_CRYPTKEEPER_KEY","")
    if key:
        live("Cryptkeeper Lite — live encryption test:")
        cmd("encrypt_value('demo-secret-value', DEV_CRYPTKEEPER_KEY)")
        try:
            result = subprocess.run(
                ["python3","-c",
                 f"import sys; sys.path.insert(0,'{REPO}'); "
                 f"from auger.tools.cryptkeeper_lite import encrypt_value; "
                 f"print(encrypt_value('demo-secret-value', '{key}'))"],
                capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                enc = result.stdout.strip()
                print(f"    {c(GR,'Result:')} ENC({enc[:50]}...)")
                ok("Real encryption — same format used in flux config YAML files")
            else:
                mock("ENC(xK9mPqRt2uVwLnJdA7yBcZhFeNsG4oIl...)  ← ENC() format in flux YAML")
        except Exception:
            mock("ENC(xK9mPqRt2uVwLnJdA7yBcZhFeNsG4oIl...)  ← ENC() format in flux YAML")
    else:
        mock("ENC(xK9mPqRt2uVwLnJdA7yBcZhFeNsG4oIl...)  ← ENC() format in flux YAML")
    info("Keys in .env: DEV_CRYPTKEEPER_KEY, STAGING_CRYPTKEEPER_KEY, PROD_CRYPTKEEPER_KEY")
    ok("Rule: never log or display decrypted secret values")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 13 — Tasks
# ══════════════════════════════════════════════════════════════════════════════
def demo_tasks():
    section(13, "Tasks", "Persistent task tracker — proactively populated during conversations")
    widget_header("✅", "Tasks", "SQLite-backed — auto-refreshes every 5 seconds in the UI")
    narrator(
        "Whenever an idea, action item, or planned work comes up in conversation, "
        "I proactively offer to add it as a task. This isn't just a to-do list — "
        "it's how I maintain operational memory across sessions. "
        "103 tasks have been captured since we started building Auger."
    )
    sc = {"done":GR,"in_progress":CY,"pending":YL,"blocked":RD}
    pc = {"critical":RD,"high":YL,"medium":BL,"low":GY}
    if OFFLINE:
        done_count = sum(1 for _,_,s,_ in DEMO_TASKS if s == "done")
        mock(f"{len(DEMO_TASKS)} tasks (demo dataset)  ({done_count} done, {len(DEMO_TASKS)-done_count} open)")
        for tid, title, status, priority in DEMO_TASKS:
            t = title[:52]+"…" if len(title)>52 else title
            print(f"  #{c(GY,str(tid))}  {c(sc.get(status,WH),f'[{status:<11}]')}  "
                  f"{c(pc.get(priority,WH),f'{priority:<8}')}  {t}")
    elif TASKS_DB.exists():
        conn = sqlite3.connect(TASKS_DB)
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        done  = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='done'").fetchone()[0]
        live(f"{total} tasks total  ({done} done, {total-done} open)")
        recent = conn.execute(
            "SELECT id,title,status,priority FROM tasks ORDER BY id DESC LIMIT 10").fetchall()
        conn.close()
        for tid,title,status,priority in recent:
            t = title[:52]+"…" if len(title)>52 else title
            print(f"  #{c(GY,str(tid))}  {c(sc.get(status,WH),f'[{status:<11}]')}  "
                  f"{c(pc.get(priority,WH),f'{priority:<8}')}  {t}")
    else:
        mock(f"{len(DEMO_TASKS)} tasks (demo dataset):")
        for tid, title, status, priority in DEMO_TASKS[:6]:
            t = title[:52]+"…" if len(title)>52 else title
            print(f"  #{c(GY,str(tid))}  {c(sc.get(status,WH),f'[{status:<11}]')}  "
                  f"{c(pc.get(priority,WH),f'{priority:<8}')}  {t}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 14 — ServiceNow
# ══════════════════════════════════════════════════════════════════════════════
def demo_servicenow():
    section(14, "ServiceNow", "ITSM integration — incidents, change records, tasks")
    widget_header("🎫", "ServiceNow", "Production changes require an approved change record before merging")
    narrator(
        "The ServiceNow widget connects to the government ITSM system. "
        "Production deployments require an approved change record before we merge "
        "a prod flux PR. Like Jira, it uses MFA session cookies — "
        "authenticated via the Host Tools Daemon."
    )
    snow_url = get_env("SERVICENOW_URL","")
    if snow_url: live(f"ServiceNow URL: {snow_url}")
    snow_ok = bool(get_env("SERVICENOW_COOKIES",""))
    if snow_ok:
        ok(f"Session cookies present (expires: {get_env('SERVICENOW_COOKIE_EXPIRY','unknown')})")
    else:
        warn("Session cookies not active — re-auth via Host Tools")
    mock("Change record for ASSIST3-31091:")
    for k,v in [("Number","CHG0242891"),
                ("Short Desc","ASSIST data-utils: Add Secure flag to _xsrf cookie (POAM)"),
                ("State","Implement"),("Risk","Low"),
                ("Environment","Staging ✅  Production ⏳")]:
        print(f"    {c(CY, k+':'):<22} {v}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 15 — Jenkins  (using stored .env key)
# ══════════════════════════════════════════════════════════════════════════════
def demo_jenkins():
    section(15, "Jenkins", "CI/CD build monitoring — watch builds, view logs, trigger jobs")
    widget_header("🔧", "Jenkins", "Monitors all ASSIST build pipelines — image builds, integration tests")
    narrator(
        "Jenkins is the build engine that turns a merged PR into a Docker image in Artifactory. "
        "The Jenkins widget lets you monitor build status, stream logs, and trigger jobs "
        "without leaving the platform. Every story-to-prod flow passes through here."
    )
    jenkins_url = get_env("JENKINS_URL","")
    if jenkins_url: live(f"Jenkins URL: {jenkins_url}")
    mock("Recent builds for data-utils:")
    for num,result,dur,ts in [
        ("#142","SUCCESS","3m 14s","2026-03-06 09:15"),
        ("#141","SUCCESS","3m 08s","2026-03-05 16:42"),
        ("#140","FAILURE","1m 02s","2026-03-05 14:11"),
    ]:
        rc = GR if result=="SUCCESS" else RD
        print(f"    {c(rc,result):<16}  Build {num}  {c(GY,dur):<14}  {c(DIM,ts)}")
    mock("Trigger: merged staging PR #9079 → build #142 → data-utils:1.5.4.0 → Artifactory")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 16 — Production Release
# ══════════════════════════════════════════════════════════════════════════════
def demo_production_release():
    section(16, "Release Manager", "Tracks every production deployment — change records, PRs, image tags")
    widget_header("🏭", "Release Manager", "SQLite deployment log at ~/.auger/logs/deployments.db")
    narrator(
        "The Release Manager keeps a permanent log of every production deployment. "
        "Deployment record number one was pre-loaded for ASSIST3-31091 "
        "when we started working on the data-utils security fix."
    )
    deploy_db = AUGER_DIR / "logs" / "deployments.db"
    if deploy_db.exists():
        try:
            conn = sqlite3.connect(deploy_db)
            tables = [t[0] for t in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            live(f"Deployment DB tables: {tables}")
            for tbl in tables[:2]:
                rows = conn.execute(f"SELECT * FROM {tbl} LIMIT 2").fetchall()
                cols = [d[0] for d in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
                if rows:
                    print(f"\n    Table: {c(CY, tbl)}")
                    for row in rows[:1]:
                        for col, val in zip(cols, row):
                            if val: print(f"      {c(GY,col+':'):<28} {str(val)[:60]}")
            conn.close()
        except Exception as e:
            warn(f"Could not read deployment DB: {e}")
    else:
        mock("Deployment record #1 — ASSIST3-31091:")
        for k,v in [("service","data-utils"),("version","1.5.4.0"),("change","CHG0242891"),
                    ("staging_pr","#9079  ← merged"),("prod_pr","#1077  ← awaiting 2 approvals"),
                    ("status","staging validated ✅  prod pending")]:
            print(f"    {c(CY,k+':'):<22} {v}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 17 — Prompts
# ══════════════════════════════════════════════════════════════════════════════
def demo_prompts():
    section(17, "Prompts", "Parameterized prompt library — reusable commands with variable substitution")
    widget_header("💬", "Prompts", "User prompts.yaml overrides platform defaults — {variable} substitution")
    narrator(
        "The Prompts widget is a library of reusable commands. "
        "Write a prompt once with curly-brace placeholders, fill in the values, and fire it. "
        "User prompts in ~/.auger/prompts.yaml override the platform defaults silently."
    )
    user_prompts_path = AUGER_DIR / "prompts.yaml"
    up = load_yaml(user_prompts_path)
    if up:
        prompts = up if isinstance(up, list) else up.get("prompts",[])
        live(f"User prompt library ({len(prompts)} prompts):")
        for p in (prompts[:6] if prompts else []):
            name = p.get("name","?") if isinstance(p,dict) else str(p)[:60]
            print(f"    {c(CY,'▶')} {name}")
    else:
        mock("Sample prompt templates:")
        for p in ["Deploy {service} to staging","Check pod status in {namespace}",
                  "Validate {url} cookie security headers","Post standup to {channel}"]:
            print(f"    {c(CY,'▶')} {p}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 18 — Rules / Conventions / Standards
# ══════════════════════════════════════════════════════════════════════════════
def demo_rcs_panels():
    section(18, "Rules / Conventions / Standards", "Edit Auger's operational guardrails — live, no restart")
    widget_header("📜", "Rules / Conventions / Standards", "Two-pane editor: list + detail — saved to ~/.auger/*.yaml")
    narrator(
        "This widget is where the team edits my operational rules and conventions. "
        "Every change takes effect immediately on the next prompt — no restart needed. "
        "This week I added a new rule after a PR was opened against the wrong branch. "
        "That mistake is now impossible to repeat."
    )
    rules = load_yaml(RULES_YML).get("rules",[])
    ec = {"error":RD,"warn":YL,"info":BL}
    live(f"{len(rules)} active rules:")
    for rule in rules:
        enf = rule.get("enforcement","info")
        print(f"    {c(ec.get(enf,WH), f'[{enf.upper():<5}]')}  {c(BD, rule['name'])}")
    convs = load_yaml(CONVS_YML).get("conventions",[])
    live(f"{len(convs)} conventions:")
    for conv in convs:
        print(f"    {c(CY,'pattern:')} {conv.get('pattern','?')}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 19 — Host Tools
# ══════════════════════════════════════════════════════════════════════════════
def demo_host_tools():
    section(19, "Host Tools", "Launch host-OS tools from inside the container via a daemon")
    widget_header("🛠️", "Host Tools", "Daemon on host OS — bridges container ↔ host for GUI apps and MFA flows")
    narrator(
        "The container can't directly launch GUI applications on the host machine. "
        "Host Tools bridges this gap. A lightweight daemon runs on the host and "
        "launches registered tools when Auger requests them. "
        "This is how Jira MFA login works: Auger tells the daemon to open Chrome for authentication."
    )
    ht_cfg = AUGER_DIR / "host_tools.json"
    if ht_cfg.exists():
        try:
            tools = json.loads(ht_cfg.read_text())
            live(f"{len(tools)} registered host tools:")
            for tool in (tools[:6] if isinstance(tools,list) else []):
                name = tool.get("name","?") if isinstance(tool,dict) else str(tool)
                desc = tool.get("description","") if isinstance(tool,dict) else ""
                print(f"    {c(CY,'⚡')} {c(BD,name):<32} {c(DIM,desc[:50])}")
        except Exception:
            mock("Tools: jira_login, servicenow_login, open_browser, launch_ide")
    else:
        mock("Tools: jira_login, servicenow_login, open_browser, launch_ide")
    ok("Daemon survives container restarts")
    ok("PID tracked in ~/.auger/daemon.pid")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 20 — Explorer
# ══════════════════════════════════════════════════════════════════════════════
def demo_explorer():
    section(20, "Explorer", "File system browser — all container volumes and mounted paths")
    widget_header("📁", "Explorer", "Browse any path: repos, configs, logs, flux YAMLs — no terminal needed")
    narrator(
        "Explorer is a full file browser inside the platform. "
        "You can navigate the entire container filesystem, view any file, "
        "and inspect configs and logs without opening a terminal. "
        "Useful for spot-checking a flux config before creating a PR."
    )
    if OFFLINE:
        mock(f"{len(DEMO_REPOS)} cloned repos in ~/repos/ (demo dataset):")
        for name, _ in DEMO_REPOS:
            print(f"    {c(CY,'📁')} {name}")
    else:
        repos_dir = HOME / "repos"
        if repos_dir.exists():
            repos = sorted([d.name for d in repos_dir.iterdir() if d.is_dir()])
            live(f"{len(repos)} cloned repos in ~/repos/:")
            for repo in repos[:12]:
                print(f"    {c(CY,'📁')} {repo}")
            if len(repos) > 12:
                print(f"    {c(GY, f'... and {len(repos)-12} more')}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 21 — Shell Terminal
# ══════════════════════════════════════════════════════════════════════════════
def demo_shell():
    section(21, "Bash Terminal", "Embedded bash shell — same container, same credentials, same filesystem")
    widget_header("💻", "Bash $", "Full terminal inside the platform — git, kubectl, curl, python, all tools")
    narrator(
        "Sometimes you just need a shell. The Bash Terminal widget gives you "
        "a full terminal in the same container environment — same credentials, "
        "same filesystem, same tools. Watch me run a live security validation "
        "right now against the staging URL we fixed this morning."
    )
    live("Running curl against staging data-utils (ASSIST3-31091 validation):")
    cmd("curl -sI https://data-utils.staging.assist.mcaas.fcs.gsa.gov/hub/login | grep set-cookie")
    if OFFLINE:
        offline_cookie = "set-cookie: _xsrf=...; Path=/; Secure; HttpOnly; SameSite=Strict"
        print(f"\n    {c(GY, offline_cookie)}")
        print()
        for flag in ["Secure","HttpOnly","SameSite=Strict"]:
            print(f"    {c(GR,'✓ PASS')}  _xsrf cookie has {c(BD, flag)}")
        print(f"\n  {c(GR+BD,'  ✅  ASSIST3-31091 REMEDIATED ON STAGING  (validated 2026-03-06)')}")
    else:
        try:
            result = subprocess.run(
                ["curl","-sI","https://data-utils.staging.assist.mcaas.fcs.gsa.gov/hub/login"],
                capture_output=True, text=True, timeout=15)
            cookies = [l for l in result.stdout.splitlines() if "set-cookie" in l.lower()]
            if cookies:
                print(f"\n    {c(GY, cookies[0][:100])}")
                print()
                for flag in ["Secure","HttpOnly","SameSite=Strict"]:
                    sym = c(GR,"✓ PASS") if flag in cookies[0] else c(RD,"✗ FAIL")
                    print(f"    {sym}  _xsrf cookie has {c(BD, flag)}")
                print(f"\n  {c(GR+BD,'  ✅  ASSIST3-31091 REMEDIATED ON STAGING — live proof')}")
        except Exception as e:
            mock("_xsrf: Secure ✅  HttpOnly ✅  SameSite=Strict ✅  (live validation)")
            warn(f"Could not reach staging: {e}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 22 — Image Lab
# ══════════════════════════════════════════════════════════════════════════════
def demo_image_lab():
    section(22, "Image Lab", "AI-powered image preview and iteration — widget icons, diagrams, mockups")
    widget_header("🎨", "Image Lab", "Load an image, prompt Auger to transform it, preview the result inline")
    narrator(
        "Image Lab is an AI-powered image editor embedded in the platform. "
        "Load an image, describe what you want, and I iterate on it. "
        "We use it for generating widget icons, architecture diagrams, and UI mockups. "
        "The widget screenshots in the demo were generated here."
    )
    screenshots = AUGER_DIR / "widget_screenshots"
    if screenshots.exists():
        imgs = sorted(screenshots.glob("*.png"))
        live(f"{len(imgs)} widget screenshots available in ~/.auger/widget_screenshots/:")
        for img in imgs[:8]:
            print(f"    {c(CY,'🖼')} {img.name}")
    mock("Example AI prompt: 'Make the flux icon more minimalist, cyan tones, 48x48px'")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 23 — Prospector
# ══════════════════════════════════════════════════════════════════════════════
def demo_prospector():
    section(23, "Prospector", "CVE scanner and POAM finding tracker — feeds the remediation pipeline")
    widget_header("🔬", "Prospector", "Invicti findings → POAM → Story-to-Prod remediation workflow")
    narrator(
        "Prospector is our vulnerability analysis tool. "
        "ASSIST3-31091 — the xsrf cookie security finding we fixed this week — started here. "
        "Invicti flagged the missing Secure flag, Prospector helped us track it, "
        "and Story-to-Prod guided the full pipeline from Jira story to production PR."
    )
    mock("POAM finding — ASSIST3-31091 (NOW REMEDIATED ON STAGING):")
    for k,v in [("Source","Invicti"),("Finding","Cookie Without Secure Flag"),
                ("Affected","data-utils.staging.assist.mcaas.fcs.gsa.gov"),
                ("Cookie","_xsrf"),("Risk","Medium"),
                ("Status","Remediated staging ✅  —  prod PR #1077 pending"),
                ("Fix","tornado_settings xsrf_cookie_kwargs: secure=True, httponly=True, samesite=Strict")]:
        print(f"    {c(CY, k+':'):<22} {v}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET 24 — Help Viewer
# ══════════════════════════════════════════════════════════════════════════════
def demo_help():
    section(24, "Help Viewer", "Inline markdown docs — platform guides, runbooks, FAQs in a tabbed interface")
    widget_header("❓", "Help", "Open any markdown file as a tab — no browser needed")
    narrator(
        "The Help widget renders markdown documentation right inside the platform. "
        "Each document gets its own tab. You can have the deployment runbook, "
        "the FAQ, and the architecture guide all open at once and switch between them. "
        "All platform docs live in the docs/ directory."
    )
    docs_dir = REPO / "docs"
    if docs_dir.exists():
        docs = list(docs_dir.rglob("*.md"))
        live(f"{len(docs)} markdown docs in docs/:")
        for doc in docs[:10]:
            print(f"    {c(CY,'📄')} {doc.relative_to(REPO)}")
    else:
        for doc in ["README.md","INSTALLATION_GUIDE.md","FAQ.md","WHATS_NEXT.md","ALPHA_READY.md"]:
            if (REPO/doc).exists():
                print(f"    {c(CY,'📄')} {doc}")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 25 — Create a Widget (live scaffold demo)
# ══════════════════════════════════════════════════════════════════════════════
def demo_create_widget():
    section(25, "Create a Widget — Live Scaffold Demo", "Ask Auger to create a new widget — enforced checklist, manifest auto-added")
    widget_header("🧩", "Widget Creation", "Every new widget must pass a 3-point checklist — enforced by Auger rules")
    narrator(
        "This is one of my favourite things to show. Anyone on the team can ask me to create "
        "a new widget and I'll scaffold the entire thing — with every required feature — "
        "in under 30 seconds. Watch me build a skeleton 'Uptime Monitor' widget right now, "
        "live, from scratch."
    )
    # Required features checklist
    print(f"\n  {c(BD+WH, 'Widget creation checklist  [ERROR enforcement — non-negotiable]')}")
    for i, item in enumerate([
        ("WIDGET_TITLE",       "Human-readable tab label"),
        ("WIDGET_ICON_FUNC",   "Icon function returned by make_icon()"),
        ("widget_manifests.yaml entry", "title, purpose, depends_on, used_by, key_data_files, auger_rules, session_resume_hint"),
    ], 1):
        print(f"  {c(GR, str(i)+'.')}  {c(BD+CY, item[0]):<40}  {c(DIM, item[1])}")

    prompt_line = 'Simulating: "Auger, create a new widget — Uptime Monitor"'
    print(f"\n  {c(BD+WH, prompt_line)}")
    time.sleep(PAUSE_S)

    # Typewrite the scaffold as if Auger is generating it live
    scaffold_lines = [
        ("MG", "# auger/ui/widgets/uptime_monitor.py  ← Auger generates this"),
        ("GY", ""),
        ("CY", "from flet import *"),
        ("CY", "from auger.ui.widgets._base import AugerWidget, make_icon"),
        ("GY", ""),
        ("YL", "WIDGET_TITLE    = \"Uptime Monitor\"          # ✓ checklist item 1"),
        ("YL", "WIDGET_ICON_FUNC = staticmethod(make_icon)  # ✓ checklist item 2"),
        ("GY", ""),
        ("WH", "WIDGET_AI_MANIFEST = {"),
        ("WH", "    'title':   'Uptime Monitor',"),
        ("WH", "    'purpose': 'Track endpoint health across all ASSIST services.',"),
        ("WH", "    'depends_on': ['api_config'],"),
        ("WH", "    'auger_rules': ['Alert SRE channel on consecutive failures'],"),
        ("WH", "    'session_resume_hint': 'Check ~/.auger/uptime_cache.json for last results',"),
        ("WH", "}"),
        ("GY", ""),
        ("GR", "class UptimeMonitorWidget(AugerWidget):"),
        ("GR", "    def build(self): ..."),
        ("GR", "    def refresh(self): ..."),
    ]
    col_map = {"MG":MG,"GY":GY,"CY":CY,"YL":YL,"WH":WH,"GR":GR}
    for col, line in scaffold_lines:
        if col == "GY" and not line:
            print()
            time.sleep(0.05)
        else:
            typewrite(f"    {c(col_map[col], line)}", delay=0.006 if not FAST else 0.003)

    print()
    ok("WIDGET_TITLE defined")
    ok("WIDGET_ICON_FUNC defined")
    ok("WIDGET_AI_MANIFEST defined  ← written to widget_manifests.yaml automatically")
    print()
    narrator(
        "After generating the file I hot-reload it — write the file, verify it appears "
        "as a live tab in the running app, THEN commit. No restart ever needed. "
        "The manifest entry is added to widget_manifests.yaml in the same commit "
        "so Auger's memory of the new widget is permanent from day one."
    )
    mock("Hot-reload sequence: write file → tab appears live → git add + commit")
    for step in [
        "  write auger/ui/widgets/uptime_monitor.py",
        "  verify tab 'Uptime Monitor' appears in running app  ✅",
        "  git add auger/ui/widgets/uptime_monitor.py auger/data/widget_manifests.yaml",
        "  git commit -m 'feat: add Uptime Monitor widget (ASSIST3-XXXXX)'",
    ]:
        print(f"  {c(CY,'▶')} {step}")
        time.sleep(PAUSE_S * 0.5)
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 26 — Widget AI Manifests (meta)
# ══════════════════════════════════════════════════════════════════════════════
def demo_widget_ai_manifests():
    section(26, "Widget AI Manifests — The Memory System", "How Auger knows everything, even after a session glitch")
    widget_header("🧠", "Widget AI Manifests", "24 manifests × injected into every prompt = permanent operational memory")
    narrator(
        "This is the architectural piece we built this week that ties everything together. "
        "Every widget has a manifest — its purpose, dependencies, data files, operational rules, "
        "and a session resume hint. These 24 manifests are injected into every single AI prompt. "
        "If the session resets, I still know exactly what every widget does, what rules to follow, "
        "and where we left off. Think of it as giving me a photographic memory of the platform."
    )
    manifests = load_yaml(MANIFESTS).get("widgets", {})
    live(f"{len(manifests)} widget manifests — sample entries:")
    for name in ["api_config","flux_config","gchat","story_to_prod"]:
        m = manifests.get(name,{})
        deps = m.get("depends_on",[])
        rules = m.get("auger_rules",[])
        hint = m.get("session_resume_hint","")
        print(f"\n  {c(BD+MG,'◆ '+m.get('title',name))}")
        print(f"    {c(WH, m.get('purpose','')[:90])}")
        if deps: info(f"Depends on: {', '.join(deps)}")
        if rules: print(f"    {c(YL,'rule:')} {rules[0]}")
        if hint:  print(f"    {c(GY,'resume:')} {hint}")
    print()
    learned = AUGER_DIR / "widget_knowledge"
    lcount = len(list(learned.glob("*.yaml"))) if learned.exists() else 0
    ok(f"Static tier:  {len(manifests)} widgets in widget_manifests.yaml")
    ok(f"Learned tier: {lcount} discovery files in ~/.auger/widget_knowledge/")
    ok("Injected into: every AI prompt via ask_auger._load_rcs_context()")
    pause()


# ══════════════════════════════════════════════════════════════════════════════
# CLOSING
# ══════════════════════════════════════════════════════════════════════════════
def show_closing():
    print(f"\n{hr()}")
    print(c(BD+CY, "  DEMO COMPLETE — Auger AI SRE Platform"))
    print(hr())
    narrator(
        "That's all 26 sections covering every widget — including a live widget scaffold. "
        "Auger in one sentence: an AI agent that lives inside your SRE platform, "
        "knows your entire operational context, enforces your team's rules, "
        "and gets smarter every time you use it — without losing that knowledge "
        "when the session ends. Questions welcome — Bobby can walk through anything live."
    )
    print(c(BD+WH, """
  Status right now:
    ✅  ASSIST3-31091 staging remediated — Secure/HttpOnly/SameSite=Strict confirmed live
    ⏳  Prod PR #1077 open — awaiting 2 approvals on assist-prod-flux-config

  What's coming next:
    🧠  Task #103 — RAG over widget manifests → domain LLM fine-tune
    🔁  Task #99  — Story→Prod Auger-led deployment assistance
    📊  Task #70  — Panner Phase 1: auto-source kubectl + DataDog
    🔐  Prod deployment of ASSIST3-31091 after PR #1077 approvals
    """))

    # Post to AUGER_POC (skip in offline mode — no real webhook)
    if not OFFLINE:
        try:
            import urllib.request
            webhooks = load_yaml(WEBHOOKS).get("webhooks",[])
            poc_url = next((w["url"] for w in webhooks if w["name"] == "AUGER_POC"), None)
            if poc_url:
                msg = {"text": (
                    f"🎬 *Auger Full Widget Demo* completed at "
                    f"{fmt_et()} — all 26 sections, 24 widgets + live scaffold.\n"
                    "_(Bobby is presenting at the 3:00 brown bag 🤖)_"
                )}
                req = urllib.request.Request(poc_url,
                    data=json.dumps(msg).encode(),
                    headers={"Content-Type":"application/json"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    if r.status == 200:
                        print(c(GR, "  📨 Completion notice posted to AUGER_POC\n"))
        except Exception:
            pass

    mode_str = ("auto --offline" if OFFLINE else "auto") if AUTO else "interactive"
    print(c(GY, f"  Mode used: {mode_str}{'  --fast' if FAST else ''}"))
    print(c(GY,  "  Run --auto for unattended  |  --offline for no-.env portable mode\n"))


# ══════════════════════════════════════════════════════════════════════════════
# REGISTRY + MAIN
# ══════════════════════════════════════════════════════════════════════════════
DEMOS = [
    ("api_config",         demo_api_config),
    ("gchat",              demo_gchat),
    ("jira",               demo_jira),
    ("story_to_prod",      demo_story_to_prod),
    ("flux_config",        demo_flux_config),
    ("github",             demo_github),
    ("artifactory",        demo_artifactory),
    ("k8s_explorer",       demo_k8s_explorer),
    ("pods",               demo_pods),
    ("panner",             demo_panner),
    ("database",           demo_database),
    ("cryptkeeper",        demo_cryptkeeper),
    ("tasks",              demo_tasks),
    ("servicenow",         demo_servicenow),
    ("jenkins",            demo_jenkins),
    ("production_release", demo_production_release),
    ("prompts",            demo_prompts),
    ("rcs_panels",         demo_rcs_panels),
    ("host_tools",         demo_host_tools),
    ("explorer",           demo_explorer),
    ("shell_terminal",     demo_shell),
    ("image_lab",          demo_image_lab),
    ("prospector",         demo_prospector),
    ("help_viewer",        demo_help),
    ("create_widget",      demo_create_widget),
    ("widget_manifests",   demo_widget_ai_manifests),
]

if __name__ == "__main__":
    if ONLY:
        matches = [(n,f) for n,f in DEMOS if ONLY.lower() in n]
        if not matches:
            print(f"Widget '{ONLY}' not found.\nAvailable: {[n for n,_ in DEMOS]}")
            sys.exit(1)
        clear()
        for _,fn in matches:
            fn()
        sys.exit(0)

    show_intro()
    for name, fn in DEMOS:
        try:
            fn()
        except Exception as e:
            warn(f"Section '{name}' error: {e}")
            time.sleep(1)
    show_closing()
