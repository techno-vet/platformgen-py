"""API Key Configurator Widget - Improved version with icons and better layout."""

import tkinter as tk
from tkinter import ttk, messagebox
import os
import subprocess
import json
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv, set_key
import requests
from PIL import Image, ImageDraw, ImageTk
from auger.runtime import state_dir
try:
    from auger.ui.utils import auger_home as _auger_home
except ImportError:
    def _auger_home(): return Path.home()


ENV_FILE = state_dir() / ".env"


def _shared_atlassian_session(instance_url: str):
    """Return a requests session seeded with saved Jira/Atlassian MFA cookies."""
    load_dotenv(ENV_FILE, override=True)
    session = requests.Session()
    session.headers.update({'Accept': 'application/json'})

    cookies_json = os.getenv('JIRA_COOKIES', '').strip()
    if not cookies_json:
        return session

    try:
        cookies = json.loads(cookies_json)
        domain = urlparse(instance_url.rstrip('/')).netloc
        for name, value in cookies.items():
            session.cookies.set(name, value, domain=domain)
    except Exception:
        pass

    return session



class IconFactory:
    """Creates simple icon images using PIL."""
    
    @staticmethod
    def create_key_icon(size=16):
        """Create a key icon."""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Key shape: circle + rectangle
        draw.ellipse([2, 2, 8, 8], fill='#4ec9b0')
        draw.rectangle([7, 4, size-3, 6], fill='#4ec9b0')
        draw.rectangle([size-5, 2, size-3, 8], fill='#4ec9b0')
        return ImageTk.PhotoImage(img)
    
    @staticmethod
    def create_eye_icon(size=16):
        """Create an eye icon."""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Eye shape: ellipse + circle
        draw.ellipse([1, 6, size-1, 10], outline='#808080', width=1)
        draw.ellipse([6, 5, 10, 11], fill='#808080')
        return ImageTk.PhotoImage(img)
    
    @staticmethod
    def create_save_icon(size=16):
        """Create a save/disk icon."""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Floppy disk shape
        draw.rectangle([2, 2, size-2, size-2], outline='#007acc', fill='#007acc', width=1)
        draw.rectangle([4, 2, size-4, 6], fill='#003d66')
        draw.rectangle([6, size-6, size-6, size-3], fill='#ffffff')
        return ImageTk.PhotoImage(img)
    
    @staticmethod
    def create_reload_icon(size=16):
        """Create a reload/refresh icon."""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Circular arrow
        draw.arc([3, 3, size-3, size-3], 45, 315, fill='#808080', width=2)
        draw.polygon([(size-4, 4), (size-2, 2), (size-2, 6)], fill='#808080')
        return ImageTk.PhotoImage(img)
    
    @staticmethod
    def create_test_icon(size=16):
        """Create a test/beaker icon."""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Flask/beaker shape
        draw.polygon([(6, 2), (10, 2), (12, size-3), (4, size-3)], outline='#4ec9b0', fill='#2d5d4e', width=1)
        draw.rectangle([5, size-4, 11, size-2], fill='#4ec9b0')
        return ImageTk.PhotoImage(img)
    
    @staticmethod
    def create_link_icon(size=12):
        """Create an external link icon."""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Arrow pointing up-right
        draw.line([2, size-2, size-2, 2], fill='#9cdcfe', width=2)
        draw.polygon([(size-4, 2), (size-1, 2), (size-1, 5)], fill='#9cdcfe')
        return ImageTk.PhotoImage(img)


class APIConfigWidget(tk.Frame):
    """Widget for configuring and testing API keys."""
    
    # Widget metadata
    WIDGET_NAME = "api_config"
    WIDGET_TITLE = "API Keys+"
    WIDGET_ICON = "🔑"
    WIDGET_ICON_NAME = "key"
    
    def __init__(self, parent):
        super().__init__(parent, bg='#1e1e1e')
        
        self.entries = {}  # key -> tk.StringVar
        self.masked_vars = {}  # key -> bool (is masked)
        self.icons = {}  # Store icons to prevent garbage collection
        
        self._create_icons()
        self._build_ui()
        self._load_from_env()
    
    def _create_icons(self):
        """Pre-create all icons."""
        self.icons['key'] = IconFactory.create_key_icon(16)
        self.icons['eye'] = IconFactory.create_eye_icon(16)
        self.icons['save'] = IconFactory.create_save_icon(16)
        self.icons['reload'] = IconFactory.create_reload_icon(16)
        self.icons['test'] = IconFactory.create_test_icon(16)
        self.icons['link'] = IconFactory.create_link_icon(12)
    
    def _build_ui(self):
        """Build the widget UI."""
        # Title and subtitle
        title_frame = tk.Frame(self, bg='#1e1e1e')
        title_frame.pack(fill=tk.X, padx=20, pady=(15, 5))
        
        # Title with icon
        title_inner = tk.Frame(title_frame, bg='#1e1e1e')
        title_inner.pack(anchor=tk.W)
        
        tk.Label(
            title_inner,
            image=self.icons['key'],
            bg='#1e1e1e'
        ).pack(side=tk.LEFT, padx=(0, 8))
        
        tk.Label(
            title_inner,
            text="API Key Configurator",
            font=('Segoe UI', 16, 'bold'),
            fg='#4ec9b0',
            bg='#1e1e1e'
        ).pack(side=tk.LEFT)
        
        tk.Label(
            title_frame,
            text=f"Configuration file: {ENV_FILE.absolute()}",
            font=('Consolas', 9),
            fg='#808080',
            bg='#1e1e1e'
        ).pack(anchor=tk.W, padx=(24, 0))
        
        # Scrollable canvas for sections
        canvas_frame = tk.Frame(self, bg='#1e1e1e')
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        canvas = tk.Canvas(canvas_frame, bg='#1e1e1e', highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        
        self.scroll_frame = tk.Frame(canvas, bg='#1e1e1e')
        self.scroll_frame.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        
        canvas.create_window((0, 0), window=self.scroll_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Add all sections
        self._add_jenkins_section()
        self._add_openai_section()
        self._add_redux_section()
        self._add_local_ai_section()
        self._add_cloudflare_section()
        self._add_youtube_section()
        self._add_godaddy_section()
        self._add_datadog_section()
        self._add_aws_section()
        self._add_rancher_section()
        self._add_github_section()
        self._add_github_oauth_section()
        self._add_github_enterprise_section()
        self._add_jira_section()
        self._add_artifactory_section()
        self._add_confluence_section()
        self._add_prisma_cloud_section()
        self._add_cryptkeeper_section()
        
        # Bottom buttons
        btn_frame = tk.Frame(self, bg='#1e1e1e')
        btn_frame.pack(fill=tk.X, padx=20, pady=10)
        
        # Save button with icon
        save_btn = tk.Frame(btn_frame, bg='#007acc', cursor='hand2')
        save_btn.pack(side=tk.LEFT, padx=(0, 10))
        save_btn.bind('<Button-1>', lambda e: self._save_to_env())
        
        inner = tk.Frame(save_btn, bg='#007acc', cursor='hand2')
        inner.pack(padx=20, pady=8)
        inner.bind('<Button-1>', lambda e: self._save_to_env())
        
        save_icon = tk.Label(inner, image=self.icons['save'], bg='#007acc', cursor='hand2')
        save_icon.pack(side=tk.LEFT, padx=(0, 8))
        save_icon.bind('<Button-1>', lambda e: self._save_to_env())
        
        save_text = tk.Label(inner, text="Save to .env", font=('Segoe UI', 10, 'bold'), fg='white', bg='#007acc', cursor='hand2')
        save_text.pack(side=tk.LEFT)
        save_text.bind('<Button-1>', lambda e: self._save_to_env())
        
        # Reload button with icon
        reload_btn = tk.Frame(btn_frame, bg='#3c3c3c', cursor='hand2')
        reload_btn.pack(side=tk.LEFT)
        reload_btn.bind('<Button-1>', lambda e: self._load_from_env())
        
        inner2 = tk.Frame(reload_btn, bg='#3c3c3c', cursor='hand2')
        inner2.pack(padx=20, pady=8)
        inner2.bind('<Button-1>', lambda e: self._load_from_env())
        
        reload_icon = tk.Label(inner2, image=self.icons['reload'], bg='#3c3c3c', cursor='hand2')
        reload_icon.pack(side=tk.LEFT, padx=(0, 8))
        reload_icon.bind('<Button-1>', lambda e: self._load_from_env())
        
        reload_text = tk.Label(inner2, text="Reload", font=('Segoe UI', 10), fg='#e0e0e0', bg='#3c3c3c', cursor='hand2')
        reload_text.pack(side=tk.LEFT)
        reload_text.bind('<Button-1>', lambda e: self._load_from_env())
        
        # Status log
        log_frame = tk.Frame(self, bg='#1e1e1e')
        log_frame.pack(fill=tk.X, padx=20, pady=(0, 10))
        
        tk.Label(
            log_frame,
            text="Status Log:",
            font=('Segoe UI', 9, 'bold'),
            fg='#e0e0e0',
            bg='#1e1e1e'
        ).pack(anchor=tk.W)
        
        self.log = tk.Text(
            log_frame,
            height=6,
            bg='#1a1a2e',
            fg='#e0e0e0',
            font=('Consolas', 9),
            wrap=tk.WORD,
            relief=tk.FLAT
        )
        self.log.pack(fill=tk.X)
        
        # Log tags
        self.log.tag_config('ok', foreground='#4ec9b0')
        self.log.tag_config('err', foreground='#f44747')
        self.log.tag_config('info', foreground='#9cdcfe')
    
    def _add_section_header(self, title, url):
        """Add a section header with clickable link."""
        frame = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        frame.pack(fill=tk.X, pady=(15, 5))
        
        # Header label with link icon
        header_frame = tk.Frame(frame, bg='#1e1e1e', cursor='hand2')
        header_frame.pack(side=tk.LEFT)
        header_frame.bind('<Button-1>', lambda e: self._open_url(url))
        
        title_label = tk.Label(
            header_frame,
            text=title,
            font=('Segoe UI', 12, 'bold', 'underline'),
            fg='#9cdcfe',
            bg='#1e1e1e',
            cursor='hand2'
        )
        title_label.pack(side=tk.LEFT)
        title_label.bind('<Button-1>', lambda e: self._open_url(url))
        
        link_icon = tk.Label(
            header_frame,
            image=self.icons['link'],
            bg='#1e1e1e',
            cursor='hand2'
        )
        link_icon.pack(side=tk.LEFT, padx=(5, 0))
        link_icon.bind('<Button-1>', lambda e: self._open_url(url))
        
        return frame
    
    def _add_divider(self):
        """Add a horizontal divider."""
        tk.Frame(self.scroll_frame, bg='#3c3c3c', height=1).pack(fill=tk.X, pady=10)
    
    def _open_url(self, url):
        """Open URL in browser."""
        try:
            env = os.environ.copy()
            env['DISPLAY'] = os.environ.get('DISPLAY', ':0')
            subprocess.Popen(['xdg-open', url], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._log(f"Failed to open URL: {e}", 'err')
    
    def _add_field(self, parent, label_text, key, is_masked=False, default=''):
        """Add a labeled input field."""
        row = tk.Frame(parent, bg='#1e1e1e')
        row.pack(fill=tk.X, pady=3)
        
        tk.Label(
            row,
            text=label_text,
            font=('Segoe UI', 10),
            fg='#e0e0e0',
            bg='#1e1e1e',
            width=20,
            anchor=tk.W
        ).pack(side=tk.LEFT)
        
        var = tk.StringVar(value=default)
        self.entries[key] = var
        
        entry_frame = tk.Frame(row, bg='#1e1e1e')
        entry_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        entry = tk.Entry(
            entry_frame,
            textvariable=var,
            bg='#2d2d2d',
            fg='#e0e0e0',
            insertbackground='#e0e0e0',
            font=('Consolas', 10),
            relief=tk.FLAT,
            show='●' if is_masked else ''
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        if is_masked:
            self.masked_vars[key] = True
            toggle_btn = tk.Label(
                entry_frame,
                image=self.icons['eye'],
                bg='#1e1e1e',
                cursor='hand2',
                padx=5
            )
            toggle_btn.pack(side=tk.LEFT)
            toggle_btn.bind('<Button-1>', lambda e, ent=entry: self._toggle_mask(ent))
    
    def _toggle_mask(self, entry):
        """Toggle password masking."""
        current = entry.cget('show')
        entry.config(show='' if current else '●')
    
    def _add_test_button(self, parent, callback):
        """Add a green test button at the bottom of the section."""
        btn_frame = tk.Frame(parent, bg='#1e1e1e')
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        
        # Green test button with icon
        test_btn = tk.Frame(btn_frame, bg='#4ec9b0', cursor='hand2')
        test_btn.pack(side=tk.RIGHT)
        
        # Bind click to the frame AND all children
        test_btn.bind('<Button-1>', lambda e: callback())
        
        inner = tk.Frame(test_btn, bg='#4ec9b0', cursor='hand2')
        inner.pack(padx=15, pady=6)
        inner.bind('<Button-1>', lambda e: callback())
        
        icon_label = tk.Label(inner, image=self.icons['test'], bg='#4ec9b0', cursor='hand2')
        icon_label.pack(side=tk.LEFT, padx=(0, 8))
        icon_label.bind('<Button-1>', lambda e: callback())
        
        text_label = tk.Label(inner, text="Test Connection", font=('Segoe UI', 9, 'bold'), fg='#1e1e1e', bg='#4ec9b0', cursor='hand2')
        text_label.pack(side=tk.LEFT)
        text_label.bind('<Button-1>', lambda e: callback())
    
    def _add_jenkins_section(self):
        """Add Jenkins section."""
        self._add_section_header("Jenkins", "https://jenkins-mcaas.helix.gsa.gov/user/YOUR_USERNAME/configure")
        
        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)
        
        self._add_field(section, "Jenkins URL:", "JENKINS_URL", default="https://jenkins-mcaas.helix.gsa.gov")
        self._add_field(section, "Username:", "JENKINS_USER")
        self._add_field(section, "Password:", "JENKINS_PASSWORD", is_masked=True)
        self._add_field(section, "API Token:", "JENKINS_API_TOKEN", is_masked=True)

        help_label = tk.Label(
            section,
            text="Supports either password auth or API token auth. PlatformGen was missing the password field.",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))
        
        self._add_test_button(section, self._test_jenkins)
        self._add_divider()
    
    def _test_jenkins(self):
        """Test Jenkins connection."""
        url = self.entries['JENKINS_URL'].get().strip()
        user = self.entries['JENKINS_USER'].get().strip()
        token = self.entries['JENKINS_API_TOKEN'].get().strip()
        password = self.entries['JENKINS_PASSWORD'].get().strip()
        secret = token or password
        
        if not url or not user or not secret:
            self._log("Jenkins: URL, username, and API token or password required", 'err')
            return
        
        try:
            self._log("Jenkins: Testing...", 'info')
            
            # Test with /api/json endpoint (basic authentication)
            resp = requests.get(
                f"{url.rstrip('/')}/api/json",
                auth=(user, secret),
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                version = data.get('version', 'unknown')
                self._log(f"Jenkins: ✓ Connected to Jenkins v{version}", 'ok')
            elif resp.status_code == 401:
                self._log("Jenkins: ✗ Invalid username or API token", 'err')
            elif resp.status_code == 403:
                self._log("Jenkins: ✗ Access forbidden (check permissions)", 'err')
            else:
                self._log(f"Jenkins: ✗ Unexpected response (HTTP {resp.status_code})", 'err')
        except requests.exceptions.ConnectionError:
            self._log(f"Jenkins: ✗ Cannot connect to {url}", 'err')
        except requests.exceptions.Timeout:
            self._log("Jenkins: ✗ Connection timeout", 'err')
        except Exception as e:
            self._log(f"Jenkins: ✗ Error: {str(e)[:80]}", 'err')

    def _add_openai_section(self):
        """Add OpenAI section."""
        self._add_section_header("OpenAI", "https://platform.openai.com/api-keys")

        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)

        self._add_field(section, "API Key:", "OPENAI_API_KEY", is_masked=True)

        help_label = tk.Label(
            section,
            text="Used by PlatformGen AI widgets and demos that target OpenAI-compatible models.",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))

        self._add_test_button(section, self._test_openai)
        self._add_divider()

    def _test_openai(self):
        """Test OpenAI API key."""
        api_key = self.entries['OPENAI_API_KEY'].get().strip()

        if not api_key:
            self._log("OpenAI: API key required", 'err')
            return

        try:
            self._log("OpenAI: Testing...", 'info')
            resp = requests.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            if resp.status_code == 200:
                self._log("OpenAI: ✓ Connection successful", 'ok')
            elif resp.status_code == 401:
                self._log("OpenAI: ✗ Invalid API key", 'err')
            else:
                self._log(f"OpenAI: ✗ Unexpected response (HTTP {resp.status_code})", 'err')
        except requests.exceptions.ConnectionError:
            self._log("OpenAI: ✗ Cannot reach api.openai.com", 'err')
        except requests.exceptions.Timeout:
            self._log("OpenAI: ✗ Connection timeout", 'err')
        except Exception as e:
            self._log(f"OpenAI: ✗ Error: {str(e)[:80]}", 'err')

    def _add_redux_section(self):
        """Add ReDuX section."""
        self._add_section_header("ReDuX", "")

        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)

        self._add_field(section, "API URL:", "REDUX_API_URL")
        self._add_field(section, "API Key:", "REDUX_API_KEY", is_masked=True)
        self._add_field(section, "Email:", "REDUX_EMAIL")
        self._add_field(section, "Password:", "REDUX_PASSWORD", is_masked=True)

        help_label = tk.Label(
            section,
            text=(
                "ReDuX modernization platform integration. PlatformGen will likely care most about "
                "API URL and API Key first; email/password are included until the required auth flow is confirmed."
            ),
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))

        self._add_test_button(section, self._test_redux)
        self._add_divider()

    def _test_redux(self):
        """Test ReDuX connectivity with a generic API probe."""
        base_url = self.entries['REDUX_API_URL'].get().strip().rstrip('/')
        api_key = self.entries['REDUX_API_KEY'].get().strip()
        email = self.entries['REDUX_EMAIL'].get().strip()
        password = self.entries['REDUX_PASSWORD'].get().strip()

        if not base_url:
            self._log("ReDuX: API URL required", 'err')
            return

        if not api_key and not (email and password):
            self._log("ReDuX: API Key or email/password required", 'err')
            return

        candidate_urls = [
            base_url,
            f"{base_url}/health",
            f"{base_url}/api/health",
            f"{base_url}/api/v1/health",
        ]
        candidate_headers = []
        if api_key:
            candidate_headers.extend([
                {'Authorization': f'Bearer {api_key}'},
                {'X-API-Key': api_key},
                {'x-api-key': api_key},
                {'api-key': api_key},
            ])
        else:
            candidate_headers.append({})

        self._log("ReDuX: Testing...", 'info')

        for endpoint in candidate_urls:
            for headers in candidate_headers:
                try:
                    response = requests.get(endpoint, headers=headers, timeout=10, allow_redirects=True)
                    if response.status_code == 200:
                        auth_mode = next(iter(headers.keys()), 'no auth')
                        self._log(f"ReDuX: ✓ Connected to {endpoint} via {auth_mode}", 'ok')
                        return
                    if response.status_code in (401, 403):
                        self._log(
                            f"ReDuX: Reached {endpoint} but credentials were rejected (HTTP {response.status_code})",
                            'err'
                        )
                        return
                except requests.exceptions.ConnectionError:
                    continue
                except requests.exceptions.Timeout:
                    self._log(f"ReDuX: Timeout reaching {endpoint}", 'err')
                    return
                except Exception as e:
                    self._log(f"ReDuX: Error probing {endpoint}: {str(e)[:80]}", 'err')
                    return

        self._log(
            "ReDuX: Could not confirm connectivity. Verify the API URL and auth method, then retry.",
            'err'
        )

    def _add_local_ai_section(self):
        """Add local AI runtime section."""
        self._add_section_header("Local AI", "")

        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)

        self._add_field(section, "Ollama Base URL:", "OLLAMA_BASE_URL", default="http://localhost:11434")
        self._add_field(section, "ComfyUI Base URL:", "COMFYUI_BASE_URL", default="http://localhost:8188")
        self._add_field(section, "Default Checkpoint:", "COMFYUI_CHECKPOINT", default="v1-5-pruned-emaonly-fp16.safetensors")

        help_label = tk.Label(
            section,
            text="Used by Ask AImee and the ComfyUI widget. Point these at localhost, a port-forward, or a K8s/ingress endpoint when the services move off-box.",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))

        btn_frame = tk.Frame(section, bg='#1e1e1e')
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        self._add_inline_test_button(btn_frame, "Test Ollama", self._test_ollama_runtime)
        self._add_inline_test_button(btn_frame, "Test ComfyUI", self._test_comfyui_runtime)
        self._add_divider()

    def _add_inline_test_button(self, parent, label, callback):
        btn = tk.Button(
            parent,
            text=label,
            command=callback,
            bg='#4ec9b0',
            fg='#1e1e1e',
            activebackground='#4ec9b0',
            activeforeground='#1e1e1e',
            relief=tk.FLAT,
            cursor='hand2',
            font=('Segoe UI', 9, 'bold'),
            padx=12,
            pady=4,
        )
        btn.pack(side=tk.RIGHT, padx=(8, 0))

    def _test_ollama_runtime(self):
        """Test the configured Ollama runtime."""
        base_url = self.entries['OLLAMA_BASE_URL'].get().strip().rstrip('/')

        if not base_url:
            self._log("Local AI: Ollama base URL required", 'err')
            return

        try:
            self._log(f"Local AI: Testing Ollama at {base_url} ...", 'info')
            resp = requests.get(f"{base_url}/api/tags", timeout=10)
            if resp.status_code == 200:
                models = resp.json().get('models', [])
                self._log(f"Local AI: ✓ Ollama reachable ({len(models)} model(s))", 'ok')
            else:
                self._log(f"Local AI: ✗ Ollama unexpected response (HTTP {resp.status_code})", 'err')
        except requests.exceptions.ConnectionError:
            self._log(f"Local AI: ✗ Cannot reach Ollama at {base_url}", 'err')
        except requests.exceptions.Timeout:
            self._log("Local AI: ✗ Ollama connection timeout", 'err')
        except Exception as e:
            self._log(f"Local AI: ✗ Ollama error: {str(e)[:80]}", 'err')

    def _test_comfyui_runtime(self):
        """Test the configured ComfyUI runtime."""
        base_url = self.entries['COMFYUI_BASE_URL'].get().strip().rstrip('/')

        if not base_url:
            self._log("Local AI: ComfyUI base URL required", 'err')
            return

        try:
            self._log(f"Local AI: Testing ComfyUI at {base_url} ...", 'info')
            resp = requests.get(f"{base_url}/system_stats", timeout=10)
            if resp.status_code == 200:
                devices = resp.json().get('devices', [])
                device_names = ", ".join(d.get('name', 'device') for d in devices[:2]) or "no device metadata"
                self._log(f"Local AI: ✓ ComfyUI reachable ({device_names})", 'ok')
            else:
                self._log(f"Local AI: ✗ ComfyUI unexpected response (HTTP {resp.status_code})", 'err')
        except requests.exceptions.ConnectionError:
            self._log(f"Local AI: ✗ Cannot reach ComfyUI at {base_url}", 'err')
        except requests.exceptions.Timeout:
            self._log("Local AI: ✗ ComfyUI connection timeout", 'err')
        except Exception as e:
            self._log(f"Local AI: ✗ ComfyUI error: {str(e)[:80]}", 'err')

    def _add_cloudflare_section(self):
        """Add Cloudflare section."""
        self._add_section_header("Cloudflare", "https://dash.cloudflare.com/profile/api-tokens")

        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)

        self._add_field(section, "API Token:", "CLOUDFLARE_API_TOKEN", is_masked=True)
        self._add_field(section, "Account ID:", "CLOUDFLARE_ACCOUNT_ID")

        help_label = tk.Label(
            section,
            text="Used for DNS and related Cloudflare operations. Token should include the scopes your flows need.",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))

        self._add_test_button(section, self._test_cloudflare)
        self._add_divider()

    def _test_cloudflare(self):
        """Test Cloudflare API token."""
        token = self.entries['CLOUDFLARE_API_TOKEN'].get().strip()

        if not token:
            self._log("Cloudflare: API token required", 'err')
            return

        try:
            self._log("Cloudflare: Testing...", 'info')
            resp = requests.get(
                "https://api.cloudflare.com/client/v4/user/tokens/verify",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200 and resp.json().get("success"):
                self._log("Cloudflare: ✓ Token verified", 'ok')
            elif resp.status_code == 403:
                self._log("Cloudflare: ✗ Token rejected", 'err')
            else:
                self._log(f"Cloudflare: ✗ Unexpected response (HTTP {resp.status_code})", 'err')
        except requests.exceptions.ConnectionError:
            self._log("Cloudflare: ✗ Cannot reach Cloudflare API", 'err')
        except requests.exceptions.Timeout:
            self._log("Cloudflare: ✗ Connection timeout", 'err')
        except Exception as e:
            self._log(f"Cloudflare: ✗ Error: {str(e)[:80]}", 'err')

    def _add_youtube_section(self):
        """Add YouTube API section."""
        self._add_section_header("YouTube", "https://console.cloud.google.com/apis/credentials")

        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)

        self._add_field(section, "API Key:", "YOUTUBE_API_KEY", is_masked=True)

        help_label = tk.Label(
            section,
            text="Used by OpenJuke and related video-search flows. This fixes the missing/hidden key field from Trader sync.",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))

        self._add_test_button(section, self._test_youtube)
        self._add_divider()

    def _test_youtube(self):
        """Test YouTube Data API key."""
        api_key = self.entries['YOUTUBE_API_KEY'].get().strip()

        if not api_key:
            self._log("YouTube: API key required", 'err')
            return

        try:
            self._log("YouTube: Testing...", 'info')
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/videoCategories",
                params={"part": "snippet", "regionCode": "US", "key": api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                self._log("YouTube: ✓ API key accepted", 'ok')
            elif resp.status_code == 400:
                self._log("YouTube: ✗ Invalid API key or API not enabled", 'err')
            else:
                self._log(f"YouTube: ✗ Unexpected response (HTTP {resp.status_code})", 'err')
        except requests.exceptions.ConnectionError:
            self._log("YouTube: ✗ Cannot reach Google APIs", 'err')
        except requests.exceptions.Timeout:
            self._log("YouTube: ✗ Connection timeout", 'err')
        except Exception as e:
            self._log(f"YouTube: ✗ Error: {str(e)[:80]}", 'err')

    def _add_godaddy_section(self):
        """Add GoDaddy section."""
        self._add_section_header("GoDaddy DNS", "https://developer.godaddy.com/keys")

        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)

        self._add_field(section, "API Key:", "GODADDY_API_KEY", is_masked=True)
        self._add_field(section, "API Secret:", "GODADDY_API_SECRET", is_masked=True)

        help_label = tk.Label(
            section,
            text="Shared with the GoDaddy DNS widget for listing domains and editing DNS records.",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))

        self._add_test_button(section, self._test_godaddy)
        self._add_divider()

    def _test_godaddy(self):
        """Test GoDaddy API credentials."""
        api_key = self.entries['GODADDY_API_KEY'].get().strip()
        api_secret = self.entries['GODADDY_API_SECRET'].get().strip()

        if not api_key or not api_secret:
            self._log("GoDaddy: API key and secret required", 'err')
            return

        try:
            self._log("GoDaddy: Testing...", 'info')
            resp = requests.get(
                "https://api.godaddy.com/v1/domains",
                headers={
                    "Authorization": f"sso-key {api_key}:{api_secret}",
                    "Accept": "application/json",
                },
                params={"limit": 1},
                timeout=10,
            )
            if resp.status_code == 200:
                self._log("GoDaddy: ✓ Connection successful", 'ok')
            elif resp.status_code in (401, 403):
                self._log("GoDaddy: ✗ Invalid credentials", 'err')
            else:
                self._log(f"GoDaddy: ✗ Unexpected response (HTTP {resp.status_code})", 'err')
        except requests.exceptions.ConnectionError:
            self._log("GoDaddy: ✗ Cannot reach GoDaddy API", 'err')
        except requests.exceptions.Timeout:
            self._log("GoDaddy: ✗ Connection timeout", 'err')
        except Exception as e:
            self._log(f"GoDaddy: ✗ Error: {str(e)[:80]}", 'err')
    
    def _add_datadog_section(self):
        """Add Datadog section."""
        self._add_section_header("Datadog", "https://app.datadoghq.com/organization-settings/api-keys")
        
        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)
        
        self._add_field(section, "API Key:", "DATADOG_API_KEY", is_masked=True)
        self._add_field(section, "App Key:", "DATADOG_APP_KEY", is_masked=True)
        self._add_field(section, "Site:", "DATADOG_SITE", default="datadoghq.com")
        
        self._add_test_button(section, self._test_datadog)
        self._add_divider()
    
    def _test_datadog(self):
        """Test Datadog connection."""
        api_key = self.entries['DATADOG_API_KEY'].get().strip()
        site = self.entries['DATADOG_SITE'].get().strip()
        
        if not api_key:
            self._log("Datadog: API key required", 'err')
            return
        
        try:
            self._log("Datadog: Testing...", 'info')
            resp = requests.get(
                f"https://api.{site}/api/v1/validate",
                headers={'DD-API-KEY': api_key},
                timeout=5
            )
            
            if resp.status_code == 200:
                self._log("Datadog: ✓ Connection successful", 'ok')
            else:
                self._log(f"Datadog: ✗ Invalid key (HTTP {resp.status_code})", 'err')
        except Exception as e:
            self._log(f"Datadog: ✗ Error: {e}", 'err')
    
    def _add_aws_section(self):
        """Add AWS section with support for multiple credential sets."""
        self._add_section_header("AWS", "https://console.aws.amazon.com/iam/home#/security_credentials")
        
        # Container for all AWS credential sets
        self.aws_container = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        self.aws_container.pack(fill=tk.X, padx=10)
        
        # Track AWS credential sets
        self.aws_credentials = []  # List of (name_var, access_var, secret_var, region_var, frame)
        
        # Load existing credentials from .env
        self._load_aws_credentials()
        
        # Add button
        add_btn_frame = tk.Frame(self.aws_container, bg='#1e1e1e')
        add_btn_frame.pack(fill=tk.X, pady=(10, 5))
        
        add_btn = tk.Frame(add_btn_frame, bg='#4ec9b0', cursor='hand2')
        add_btn.pack(side=tk.LEFT)
        
        # Bind to all parts
        add_btn.bind('<Button-1>', lambda e: self._add_aws_credential_set())
        
        add_inner = tk.Frame(add_btn, bg='#4ec9b0', cursor='hand2')
        add_inner.pack(padx=10, pady=4)
        add_inner.bind('<Button-1>', lambda e: self._add_aws_credential_set())
        
        add_text = tk.Label(add_inner, text="+ Add AWS Credentials", font=('Segoe UI', 9, 'bold'), 
                           fg='#1e1e1e', bg='#4ec9b0', cursor='hand2')
        add_text.pack()
        add_text.bind('<Button-1>', lambda e: self._add_aws_credential_set())
        
        self._add_divider()
    
    def _load_aws_credentials(self):
        """Load AWS credentials from .env file."""
        # Check for numbered credential sets
        i = 1
        while True:
            name_key = f"AWS_{i}_NAME"
            if name_key in os.environ:
                name = os.getenv(name_key, f"AWS Profile {i}")
                access = os.getenv(f"AWS_{i}_ACCESS_KEY_ID", "")
                secret = os.getenv(f"AWS_{i}_SECRET_ACCESS_KEY", "")
                region = os.getenv(f"AWS_{i}_REGION", "us-east-1")
                self._add_aws_credential_set(name, access, secret, region)
                i += 1
            else:
                break
        
        # If no credentials found, add one default set
        if not self.aws_credentials:
            self._add_aws_credential_set()
    
    def _add_aws_credential_set(self, name="", access_key="", secret_key="", region="us-east-1"):
        """Add a new AWS credential set to the UI."""
        # Create frame for this credential set
        cred_frame = tk.Frame(self.aws_container, bg='#252526', relief=tk.SOLID, borderwidth=1)
        cred_frame.pack(fill=tk.X, pady=(5, 5))
        
        # Header with name and remove button
        header_frame = tk.Frame(cred_frame, bg='#252526')
        header_frame.pack(fill=tk.X, padx=10, pady=(8, 5))
        
        # Name field
        name_label = tk.Label(header_frame, text="Profile Name:", font=('Segoe UI', 9, 'bold'),
                             fg='#e0e0e0', bg='#252526')
        name_label.pack(side=tk.LEFT, padx=(0, 5))
        
        name_var = tk.StringVar(value=name or f"AWS Profile {len(self.aws_credentials) + 1}")
        name_entry = tk.Entry(header_frame, textvariable=name_var, bg='#2d2d2d', fg='#e0e0e0',
                             insertbackground='#e0e0e0', font=('Segoe UI', 10), relief=tk.FLAT, width=20)
        name_entry.pack(side=tk.LEFT, padx=(0, 10))
        
        # Remove button
        remove_btn = tk.Frame(header_frame, bg='#f44747', cursor='hand2')
        remove_btn.pack(side=tk.RIGHT)
        
        def remove_this():
            self._remove_aws_credential_set(cred_frame, (name_var, access_var, secret_var, region_var, cred_frame))
        
        remove_btn.bind('<Button-1>', lambda e: remove_this())
        
        remove_inner = tk.Frame(remove_btn, bg='#f44747', cursor='hand2')
        remove_inner.pack(padx=10, pady=4)
        remove_inner.bind('<Button-1>', lambda e: remove_this())
        
        remove_text = tk.Label(remove_inner, text="Remove", font=('Segoe UI', 9, 'bold'),
                              fg='white', bg='#f44747', cursor='hand2')
        remove_text.pack()
        remove_text.bind('<Button-1>', lambda e: remove_this())
        
        # Fields container
        fields_frame = tk.Frame(cred_frame, bg='#252526')
        fields_frame.pack(fill=tk.X, padx=10, pady=(0, 8))
        
        # Access Key ID
        access_row = tk.Frame(fields_frame, bg='#252526')
        access_row.pack(fill=tk.X, pady=3)
        tk.Label(access_row, text="Access Key ID:", font=('Segoe UI', 9), fg='#e0e0e0',
                bg='#252526', width=18, anchor=tk.W).pack(side=tk.LEFT)
        
        access_var = tk.StringVar(value=access_key)
        access_entry = tk.Entry(access_row, textvariable=access_var, bg='#2d2d2d', fg='#e0e0e0',
                               insertbackground='#e0e0e0', font=('Consolas', 9), relief=tk.FLAT)
        access_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Secret Access Key
        secret_row = tk.Frame(fields_frame, bg='#252526')
        secret_row.pack(fill=tk.X, pady=3)
        tk.Label(secret_row, text="Secret Access Key:", font=('Segoe UI', 9), fg='#e0e0e0',
                bg='#252526', width=18, anchor=tk.W).pack(side=tk.LEFT)
        
        secret_var = tk.StringVar(value=secret_key)
        secret_entry = tk.Entry(secret_row, textvariable=secret_var, bg='#2d2d2d', fg='#e0e0e0',
                               insertbackground='#e0e0e0', font=('Consolas', 9), relief=tk.FLAT, show='●')
        secret_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        # Eye toggle for secret
        eye_btn = tk.Label(secret_row, image=self.icons['eye'], bg='#252526', cursor='hand2')
        eye_btn.pack(side=tk.LEFT)
        eye_btn.bind('<Button-1>', lambda e, ent=secret_entry: self._toggle_mask(ent))
        
        # Region
        region_row = tk.Frame(fields_frame, bg='#252526')
        region_row.pack(fill=tk.X, pady=3)
        tk.Label(region_row, text="Region:", font=('Segoe UI', 9), fg='#e0e0e0',
                bg='#252526', width=18, anchor=tk.W).pack(side=tk.LEFT)
        
        region_var = tk.StringVar(value=region)
        region_entry = tk.Entry(region_row, textvariable=region_var, bg='#2d2d2d', fg='#e0e0e0',
                               insertbackground='#e0e0e0', font=('Consolas', 9), relief=tk.FLAT)
        region_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Test button for this credential set
        test_frame = tk.Frame(fields_frame, bg='#252526')
        test_frame.pack(fill=tk.X, pady=(8, 0))
        
        test_btn = tk.Frame(test_frame, bg='#4ec9b0', cursor='hand2')
        test_btn.pack(side=tk.RIGHT)
        
        def test_this():
            self._test_aws_credentials(name_var.get(), access_var.get(), secret_var.get(), region_var.get())
        
        test_btn.bind('<Button-1>', lambda e: test_this())
        
        test_inner = tk.Frame(test_btn, bg='#4ec9b0', cursor='hand2')
        test_inner.pack(padx=15, pady=6)
        test_inner.bind('<Button-1>', lambda e: test_this())
        
        test_icon = tk.Label(test_inner, image=self.icons['test'], bg='#4ec9b0', cursor='hand2')
        test_icon.pack(side=tk.LEFT, padx=(0, 8))
        test_icon.bind('<Button-1>', lambda e: test_this())
        
        test_text = tk.Label(test_inner, text="Test Connection", font=('Segoe UI', 9, 'bold'),
                            fg='#1e1e1e', bg='#4ec9b0', cursor='hand2')
        test_text.pack(side=tk.LEFT)
        test_text.bind('<Button-1>', lambda e: test_this())
        
        # Store reference
        self.aws_credentials.append((name_var, access_var, secret_var, region_var, cred_frame))
    
    def _remove_aws_credential_set(self, frame, cred_tuple):
        """Remove an AWS credential set."""
        if len(self.aws_credentials) <= 1:
            messagebox.showwarning("Cannot Remove", "You must have at least one AWS credential set.")
            return
        
        if messagebox.askyesno("Remove Credentials", f"Remove '{cred_tuple[0].get()}' credentials?"):
            frame.destroy()
            self.aws_credentials.remove(cred_tuple)
    
    def _test_aws_credentials(self, name, access_key, secret_key, region):
        """Test a specific AWS credential set."""
        if not access_key or not secret_key:
            self._log(f"AWS ({name}): Access key and secret required", 'err')
            return
        
        try:
            self._log(f"AWS ({name}): Testing...", 'info')
            import boto3
            
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            sts = session.client('sts')
            identity = sts.get_caller_identity()
            
            self._log(f"AWS ({name}): ✓ Authenticated as {identity['Arn']}", 'ok')
        except Exception as e:
            self._log(f"AWS ({name}): ✗ Error: {str(e)[:80]}", 'err')
    
    def _add_rancher_section(self):
        """Add Rancher section."""
        self._add_section_header("Rancher", "https://rancher.staging.core.mcaas.fcs.gsa.gov/")
        
        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)
        
        self._add_field(section, "Rancher URL:", "RANCHER_URL", default="https://rancher.staging.core.mcaas.fcs.gsa.gov")
        
        # Bearer Token field (convenience field that auto-populates access/secret)
        bearer_row = tk.Frame(section, bg='#1e1e1e')
        bearer_row.pack(fill=tk.X, pady=3)
        
        tk.Label(
            bearer_row,
            text="Bearer Token:",
            font=('Segoe UI', 10),
            fg='#e0e0e0',
            bg='#1e1e1e',
            width=20,
            anchor=tk.W
        ).pack(side=tk.LEFT)
        
        bearer_var = tk.StringVar()
        self.entries['RANCHER_BEARER_TOKEN'] = bearer_var
        
        bearer_entry_frame = tk.Frame(bearer_row, bg='#1e1e1e')
        bearer_entry_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        bearer_entry = tk.Entry(
            bearer_entry_frame,
            textvariable=bearer_var,
            bg='#2d2d2d',
            fg='#e0e0e0',
            insertbackground='#e0e0e0',
            font=('Consolas', 10),
            relief=tk.FLAT
        )
        bearer_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Auto-parse bearer token when it changes
        def parse_bearer_token(*args):
            token = bearer_var.get().strip()
            if ':' in token:
                parts = token.split(':', 1)
                if len(parts) == 2:
                    access_key, secret_key = parts
                    self.entries['RANCHER_ACCESS_KEY'].set(access_key)
                    self.entries['RANCHER_SECRET_KEY'].set(secret_key)
        
        bearer_var.trace_add('write', parse_bearer_token)
        
        # Help text
        help_label = tk.Label(
            section,
            text="Paste bearer token (format: token-xxxxx:secret) or fill Access/Secret keys below",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))
        
        # Access and Secret Key fields
        self._add_field(section, "Access Key:", "RANCHER_ACCESS_KEY")
        self._add_field(section, "Secret Key:", "RANCHER_SECRET_KEY", is_masked=True)
        
        self._add_test_button(section, self._test_rancher)
        self._add_divider()
    
    def _test_rancher(self):
        """Test Rancher connection."""
        url = self.entries['RANCHER_URL'].get().strip()
        access_key = self.entries['RANCHER_ACCESS_KEY'].get().strip()
        secret_key = self.entries['RANCHER_SECRET_KEY'].get().strip()
        
        if not url:
            self._log("Rancher: URL required", 'err')
            return
        
        if not access_key or not secret_key:
            self._log("Rancher: Access key and secret key required", 'err')
            return
        
        try:
            self._log("Rancher: Testing...", 'info')
            
            # Test Rancher API with basic auth
            resp = requests.get(
                f"{url.rstrip('/')}/v3/users?me=true",
                auth=(access_key, secret_key),
                timeout=10,
                verify=True
            )
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get('data') and len(data['data']) > 0:
                    username = data['data'][0].get('username', 'unknown')
                    self._log(f"Rancher: ✓ Authenticated as {username}", 'ok')
                else:
                    self._log("Rancher: ✓ Connection successful", 'ok')
            elif resp.status_code == 401:
                self._log("Rancher: ✗ Invalid credentials", 'err')
            elif resp.status_code == 403:
                self._log("Rancher: ✗ Access forbidden", 'err')
            else:
                self._log(f"Rancher: ✗ Unexpected response (HTTP {resp.status_code})", 'err')
        except requests.exceptions.SSLError:
            self._log("Rancher: ✗ SSL certificate verification failed", 'err')
        except requests.exceptions.ConnectionError:
            self._log(f"Rancher: ✗ Cannot connect to {url}", 'err')
        except requests.exceptions.Timeout:
            self._log("Rancher: ✗ Connection timeout", 'err')
        except Exception as e:
            self._log(f"Rancher: ✗ Error: {str(e)[:80]}", 'err')
    
    def _add_github_section(self):
        """Add GitHub / Copilot section."""
        self._add_section_header("GitHub / Copilot", "https://github.com/settings/tokens")
        
        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)
        
        self._add_field(section, "GitHub Token:", "GITHUB_TOKEN", is_masked=True)
        self._add_field(section, "GitHub API URL:", "GITHUB_API_URL", default="https://api.github.com")
        
        # Help text
        help_label = tk.Label(
            section,
            text="Create token at github.com/settings/tokens with 'repo', 'read:org', 'read:user' scopes",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))
        
        self._add_test_button(section, self._test_github)
        self._add_divider()

    def _add_github_oauth_section(self):
        """Add GitHub OAuth app section for PlatformGen web login."""
        self._add_section_header("GitHub OAuth App (PlatformGen Login)", "https://github.com/organizations/techno-vet/settings/applications")

        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)

        self._add_field(section, "Client ID:", "GITHUB_OAUTH_CLIENT_ID")
        self._add_field(section, "Client Secret:", "GITHUB_OAUTH_CLIENT_SECRET", is_masked=True)

        help_label = tk.Label(
            section,
            text="Used by PlatformGen /hub login flows. Callback URL should match the deployed web app configuration.",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))

        button_frame = tk.Frame(section, bg='#1e1e1e')
        button_frame.pack(fill=tk.X, pady=(4, 0))

        oauth_btn = tk.Frame(button_frame, bg='#3c3c3c', cursor='hand2')
        oauth_btn.pack(side=tk.RIGHT)
        oauth_btn.bind('<Button-1>', lambda e: self._open_url("https://github.com/organizations/techno-vet/settings/applications"))

        oauth_inner = tk.Frame(oauth_btn, bg='#3c3c3c', cursor='hand2')
        oauth_inner.pack(padx=15, pady=6)
        oauth_inner.bind('<Button-1>', lambda e: self._open_url("https://github.com/organizations/techno-vet/settings/applications"))

        oauth_text = tk.Label(oauth_inner, text="Open OAuth App Settings", font=('Segoe UI', 9, 'bold'),
                              fg='#e0e0e0', bg='#3c3c3c', cursor='hand2')
        oauth_text.pack(side=tk.LEFT)
        oauth_text.bind('<Button-1>', lambda e: self._open_url("https://github.com/organizations/techno-vet/settings/applications"))

        self._add_divider()
    
    def _test_github(self):
        """Test GitHub connection."""
        token = self.entries['GITHUB_TOKEN'].get().strip()
        api_url = self.entries['GITHUB_API_URL'].get().strip()
        
        if not token:
            self._log("GitHub: Token required", 'err')
            return
        
        try:
            self._log("GitHub: Testing...", 'info')
            
            # Test with /user endpoint
            resp = requests.get(
                f"{api_url.rstrip('/')}/user",
                headers={
                    'Authorization': f'Bearer {token}',
                    'Accept': 'application/vnd.github.v3+json'
                },
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                username = data.get('login', 'unknown')
                name = data.get('name', username)
                self._log(f"GitHub: ✓ Authenticated as {name} (@{username})", 'ok')
                
                # Check Copilot access
                try:
                    copilot_resp = requests.get(
                        f"{api_url.rstrip('/')}/copilot_internal/v2/token",
                        headers={
                            'Authorization': f'Bearer {token}',
                            'Accept': 'application/vnd.github.v3+json'
                        },
                        timeout=5
                    )
                    if copilot_resp.status_code == 200:
                        self._log("GitHub: ✓ Copilot access confirmed", 'ok')
                    else:
                        self._log("GitHub: ℹ Copilot access not available (may need subscription)", 'info')
                except:
                    pass  # Copilot check is optional
                    
            elif resp.status_code == 401:
                self._log("GitHub: ✗ Invalid or expired token", 'err')
            elif resp.status_code == 403:
                self._log("GitHub: ✗ Access forbidden (check token scopes)", 'err')
            else:
                self._log(f"GitHub: ✗ Unexpected response (HTTP {resp.status_code})", 'err')
                
        except requests.exceptions.ConnectionError:
            self._log(f"GitHub: ✗ Cannot connect to {api_url}", 'err')
        except requests.exceptions.Timeout:
            self._log("GitHub: ✗ Connection timeout", 'err')
        except Exception as e:
            self._log(f"GitHub: ✗ Error: {str(e)[:80]}", 'err')
    
    def _add_github_enterprise_section(self):
        """Add GitHub Enterprise section with SSH support."""
        self._add_section_header("GitHub Enterprise (SSH)", "https://github.helix.gsa.gov/")
        
        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)
        
        self._add_field(section, "GitHub URL:", "GHE_URL", default="https://github.helix.gsa.gov")
        self._add_field(section, "API Token:", "GHE_TOKEN", is_masked=True)
        self._add_field(section, "SSH Key Path:", "GHE_SSH_KEY", default=f"{_auger_home()}/.ssh/id_rsa")
        self._add_field(section, "Username:", "GHE_USERNAME")
        self._add_field(section, "Default Org:", "GHE_ORG")
        
        # Help text
        help_label = tk.Label(
            section,
            text="Uses SSH for git operations. Token needed for API access. Create at: Settings → Developer settings → Personal access tokens",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))
        
        self._add_test_button(section, self._test_github_enterprise)
        self._add_divider()
    
    def _test_github_enterprise(self):
        """Test GitHub Enterprise connection (SSH + API)."""
        url = self.entries['GHE_URL'].get().strip()
        token = self.entries['GHE_TOKEN'].get().strip()
        ssh_key = self.entries['GHE_SSH_KEY'].get().strip()
        username = self.entries['GHE_USERNAME'].get().strip()
        
        if not url:
            self._log("GHE: URL required", 'err')
            return
        
        try:
            self._log("GHE: Testing...", 'info')
            
            # Test 1: SSH key exists
            if ssh_key:
                ssh_path = Path(ssh_key).expanduser()
                if ssh_path.exists():
                    self._log(f"GHE: ✓ SSH key found at {ssh_key}", 'ok')
                else:
                    self._log(f"GHE: ⚠ SSH key not found: {ssh_key}", 'info')
            
            # Test 2: SSH connectivity (test git ls-remote)
            if ssh_key:
                try:
                    # Extract hostname from URL
                    hostname = url.replace('https://', '').replace('http://', '').split('/')[0]
                    test_repo = f"git@{hostname}:test/test.git"  # Dummy repo for connection test
                    
                    # Set up SSH command with custom key
                    ssh_cmd = f'ssh -i {ssh_key} -o StrictHostKeyChecking=no -o ConnectTimeout=5'
                    env = os.environ.copy()
                    env['GIT_SSH_COMMAND'] = ssh_cmd
                    
                    # Test SSH connection (this will fail on repo not found, but confirms SSH works)
                    result = subprocess.run(
                        ['git', 'ls-remote', test_repo],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    
                    # Check for authentication vs. repo errors
                    if 'Permission denied' in result.stderr or 'publickey' in result.stderr:
                        self._log("GHE: ✗ SSH authentication failed (check key permissions)", 'err')
                    elif 'Could not resolve hostname' in result.stderr:
                        self._log(f"GHE: ✗ Cannot resolve {hostname}", 'err')
                    else:
                        # Any other error likely means SSH works but repo doesn't exist (which is fine)
                        self._log(f"GHE: ✓ SSH connection successful to {hostname}", 'ok')
                        
                except subprocess.TimeoutExpired:
                    self._log("GHE: ✗ SSH connection timeout", 'err')
                except Exception as e:
                    self._log(f"GHE: ⚠ SSH test inconclusive: {str(e)[:60]}", 'info')
            
            # Test 3: API token
            if token:
                api_url = f"{url.rstrip('/')}/api/v3/user"
                try:
                    resp = requests.get(
                        api_url,
                        headers={
                            'Authorization': f'token {token}',
                            'Accept': 'application/vnd.github.v3+json'
                        },
                        timeout=10
                    )
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        login = data.get('login', 'unknown')
                        name = data.get('name', login)
                        self._log(f"GHE: ✓ API authenticated as {name} (@{login})", 'ok')
                    elif resp.status_code == 401:
                        self._log("GHE: ✗ Invalid API token", 'err')
                    else:
                        self._log(f"GHE: ✗ API error (HTTP {resp.status_code})", 'err')
                        
                except requests.exceptions.ConnectionError:
                    self._log(f"GHE: ✗ Cannot connect to {api_url}", 'err')
                except requests.exceptions.Timeout:
                    self._log("GHE: ✗ API connection timeout", 'err')
            else:
                self._log("GHE: ℹ No API token provided (SSH-only mode)", 'info')
                
        except Exception as e:
            self._log(f"GHE: ✗ Error: {str(e)[:80]}", 'err')
    
    def _add_jira_section(self):
        """Add Jira section for API token authentication."""
        self._add_section_header("Jira", "https://id.atlassian.com/manage-profile/security/api-tokens")
        
        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)
        
        self._add_field(section, "Jira Base URL:", "JIRA_BASE_URL", default="")
        self._add_field(section, "Jira Username (email):", "JIRA_USERNAME", default="")
        self._add_field(section, "Jira API Token:", "JIRA_API_TOKEN", is_masked=True)
        
        # Help text
        help_label = tk.Label(
            section,
            text="Generate API token at: https://id.atlassian.com/manage-profile/security/api-tokens",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))
        
        self._add_test_button(section, self._test_jira)
        self._add_divider()
    
    def _test_jira(self):
        """Test Jira API token authentication."""
        base_url = self.entries.get('JIRA_BASE_URL', tk.StringVar()).get().strip()
        username = self.entries.get('JIRA_USERNAME', tk.StringVar()).get().strip()
        api_token = self.entries.get('JIRA_API_TOKEN', tk.StringVar()).get().strip()
        
        if not base_url or not username or not api_token:
            self._log("Jira: All fields required (Base URL, Username, API Token)", 'err')
            return
        
        try:
            self._log("Jira: Testing API token authentication...", 'info')
            
            # Test with /myself endpoint (doesn't require specific permissions)
            import base64
            auth_str = base64.b64encode(f"{username}:{api_token}".encode()).decode()
            
            resp = requests.get(
                f"{base_url.rstrip('/')}/rest/api/3/myself",
                headers={
                    'Authorization': f'Basic {auth_str}',
                    'Accept': 'application/json'
                },
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                display_name = data.get('displayName', 'unknown')
                jira_email = data.get('emailAddress', username)
                self._log(f"Jira: ✓ Authenticated as {display_name} ({jira_email})", 'ok')
            elif resp.status_code == 401:
                self._log("Jira: ✗ Invalid username or API token", 'err')
            elif resp.status_code == 403:
                self._log("Jira: ✗ Access forbidden (check token permissions)", 'err')
            else:
                self._log(f"Jira: ✗ Unexpected response (HTTP {resp.status_code})", 'err')
                
        except requests.exceptions.ConnectionError:
            self._log(f"Jira: ✗ Cannot connect to {base_url}", 'err')
        except requests.exceptions.Timeout:
            self._log("Jira: ✗ Connection timeout", 'err')
        except Exception as e:
            self._log(f"Jira: ✗ Error: {str(e)[:80]}", 'err')
    
    def _add_artifactory_section(self):
        """Add Artifactory section."""
        self._add_section_header("Artifactory", "https://artifactory.helix.gsa.gov/")
        
        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)
        
        self._add_field(section, "Artifactory URL:", "ARTIFACTORY_URL", default="https://artifactory.helix.gsa.gov")
        self._add_field(section, "Username:", "ARTIFACTORY_USERNAME")
        self._add_field(section, "Identity Token:", "ARTIFACTORY_IDENTITY_TOKEN", is_masked=True)
        self._add_field(section, "API Key:", "ARTIFACTORY_API_KEY", is_masked=True)
        self._add_field(section, "Password:", "ARTIFACTORY_PASSWORD", is_masked=True)
        
        # Help text
        help_label = tk.Label(
            section,
            text="Priority: Identity Token > API Key > Password. Create tokens at: User Profile → Authentication Settings",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))
        
        self._add_test_button(section, self._test_artifactory)
        self._add_divider()
    
    def _test_artifactory(self):
        """Test Artifactory connection."""
        url = self.entries['ARTIFACTORY_URL'].get().strip()
        username = self.entries['ARTIFACTORY_USERNAME'].get().strip()
        identity_token = self.entries['ARTIFACTORY_IDENTITY_TOKEN'].get().strip()
        api_key = self.entries['ARTIFACTORY_API_KEY'].get().strip()
        password = self.entries['ARTIFACTORY_PASSWORD'].get().strip()
        
        if not url:
            self._log("Artifactory: URL required", 'err')
            return
        
        if not identity_token and not api_key and not password:
            self._log("Artifactory: Identity Token, API Key, or Password required", 'err')
            return
        
        try:
            self._log("Artifactory: Testing...", 'info')
            
            # Test 1: System ping
            ping_url = f"{url.rstrip('/')}/api/system/ping"
            try:
                ping_resp = requests.get(ping_url, timeout=10)
                if ping_resp.status_code == 200:
                    self._log("Artifactory: ✓ Server is reachable", 'ok')
                else:
                    self._log(f"Artifactory: ⚠ Server returned HTTP {ping_resp.status_code}", 'info')
            except:
                self._log("Artifactory: ⚠ Server ping failed", 'info')
            
            # Test 2: Authentication - Priority: Identity Token > API Key > Password
            headers = {}
            auth_method = None
            
            if identity_token:
                # Identity tokens use Bearer authentication
                headers['Authorization'] = f'Bearer {identity_token}'
                auth_method = 'Identity Token'
            elif api_key:
                # API keys use X-JFrog-Art-Api header
                headers['X-JFrog-Art-Api'] = api_key
                auth_method = 'API Key'
            else:
                # Password uses X-JFrog-Art-Api header
                headers['X-JFrog-Art-Api'] = password
                auth_method = 'Password'
            
            self._log(f"Artifactory: Using {auth_method} for authentication", 'info')
            
            # Test with system/version endpoint (works without specific user permissions)
            version_url = f"{url.rstrip('/')}/api/system/version"
            resp = requests.get(version_url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                version = data.get('version', 'unknown')
                self._log(f"Artifactory: ✓ Authenticated successfully (v{version})", 'ok')
                
                # Try to get user info if username provided
                if username:
                    user_url = f"{url.rstrip('/')}/api/security/users/{username}"
                    user_resp = requests.get(user_url, headers=headers, timeout=10)
                    if user_resp.status_code == 200:
                        user_data = user_resp.json()
                        email = user_data.get('email', 'N/A')
                        realm = user_data.get('realm', 'internal')
                        self._log(f"Artifactory: ✓ User: {username} ({email})", 'ok')
                        self._log(f"Artifactory: ℹ Auth realm: {realm}", 'info')
                    
            elif resp.status_code == 401:
                self._log(f"Artifactory: ✗ Invalid {auth_method}", 'err')
            elif resp.status_code == 403:
                # Try alternative: get repositories (less privileged)
                repos_url = f"{url.rstrip('/')}/api/repositories"
                repos_resp = requests.get(repos_url, headers=headers, timeout=10)
                
                if repos_resp.status_code == 200:
                    repos = repos_resp.json()
                    self._log(f"Artifactory: ✓ Authenticated (found {len(repos)} repositories)", 'ok')
                else:
                    self._log("Artifactory: ✗ Access forbidden (check permissions)", 'err')
            else:
                self._log(f"Artifactory: ✗ Unexpected response (HTTP {resp.status_code})", 'err')
                
        except requests.exceptions.ConnectionError:
            self._log(f"Artifactory: ✗ Cannot connect to {url}", 'err')
        except requests.exceptions.Timeout:
            self._log("Artifactory: ✗ Connection timeout", 'err')
        except Exception as e:
            self._log(f"Artifactory: ✗ Error: {str(e)[:80]}", 'err')
    
    def _add_confluence_section(self):
        """Add Confluence section."""
        self._add_section_header("Confluence", "https://gsa-standard.atlassian-us-gov-mod.net/wiki/home")
        
        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)
        
        self._add_field(section, "Base URL:", 'CONFLUENCE_BASE_URL', 
                       default='https://gsa-standard.atlassian-us-gov-mod.net/wiki')
        self._add_field(section, "Username:", 'CONFLUENCE_USERNAME')
        self._add_field(section, "Personal Token:", 'CONFLUENCE_TOKEN', is_masked=True)
        self._add_field(section, "Test Page ID:", 'CONFLUENCE_TEST_PAGE_ID', 
                       default='633647209')
        
        # Help text
        help_label = tk.Label(
            section,
            text="Can use shared Jira MFA cookies for gsa-standard.atlassian-us-gov-mod.net; personal token remains optional fallback",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))
        
        self._add_test_button(section, self._test_confluence)
        self._add_divider()
    
    def _test_confluence(self):
        """Test Confluence connection."""
        base_url = self.entries.get('CONFLUENCE_BASE_URL', tk.StringVar()).get().strip()
        username = self.entries.get('CONFLUENCE_USERNAME', tk.StringVar()).get().strip()
        token = self.entries.get('CONFLUENCE_TOKEN', tk.StringVar()).get().strip()
        page_id = self.entries.get('CONFLUENCE_TEST_PAGE_ID', tk.StringVar()).get().strip()
        jira_cookies = self.entries.get('JIRA_COOKIES', tk.StringVar()).get().strip()
        
        if not base_url:
            self._log("Confluence: Base URL is required", 'err')
            return
        if not token and not jira_cookies:
            self._log("Confluence: Jira MFA cookies or Confluence token required", 'err')
            return
        
        if not page_id:
            page_id = '633647209'  # Default test page
        
        self._log(f"Confluence: Testing connection to {base_url}...", 'info')
        
        try:
            url = f"{base_url}/rest/api/content/{page_id}?expand=version"
            response = None
            auth_mode = None

            if jira_cookies:
                auth_mode = "Jira MFA cookies"
                response = _shared_atlassian_session(base_url).get(url, timeout=10, verify=True)

            if (response is None or response.status_code in (401, 403)) and token:
                auth_mode = "Confluence bearer token"
                response = requests.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {token}"
                    },
                    timeout=10,
                    verify=True
                )
            
            if response.status_code == 200:
                data = response.json()
                title = data.get('title', 'N/A')
                version = data.get('version', {}).get('number', 'N/A')
                self._log(f"Confluence: ✓ Connection successful!", 'ok')
                self._log(f"Confluence:   Auth: {auth_mode}", 'info')
                self._log(f"Confluence:   Page: {title}", 'info')
                self._log(f"Confluence:   Version: {version}", 'info')
                if username:
                    self._log(f"Confluence:   Username: {username}", 'info')
            elif response.status_code == 401:
                self._log("Confluence: ✗ Authentication failed - Jira session may be expired or Confluence token invalid", 'err')
            elif response.status_code == 403:
                self._log("Confluence: ✗ Access denied - User may not have permission to view page", 'err')
            elif response.status_code == 404:
                self._log(f"Confluence: ✗ Page not found - Page ID {page_id} may be incorrect", 'err')
            else:
                self._log(f"Confluence: ✗ Connection failed (HTTP {response.status_code})", 'err')
                
        except requests.exceptions.Timeout:
            self._log("Confluence: ✗ Connection timeout", 'err')
        except requests.exceptions.ConnectionError:
            self._log(f"Confluence: ✗ Could not connect to {base_url}", 'err')
        except Exception as e:
            self._log(f"Confluence: ✗ Error: {str(e)[:80]}", 'err')

    def _add_prisma_cloud_section(self):
        """Add Prisma Cloud section."""
        self._add_section_header("Prisma Cloud", "https://docs.prismacloud.io/")

        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)

        self._add_field(section, "Console/API URL:", "PRISMA_CLOUD_URL", default="https://app.gov.prismacloud.io")
        self._add_field(section, "Access Key:", "PRISMA_CLOUD_ACCESS_KEY", is_masked=True)
        self._add_field(section, "Secret Key:", "PRISMA_CLOUD_SECRET_KEY", is_masked=True)

        help_label = tk.Label(
            section,
            text=(
                "Supports both Prisma Cloud Gov tenant auth and Runtime Security/Compute auth. "
                "Use Access Key in the Access Key field and Secret Key in the Secret Key field. "
                "If you were given Compute/CWPP docs, the console path may be under /compute."
            ),
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        )
        help_label.pack(fill=tk.X, pady=(2, 5), padx=(140, 0))

        self._add_test_button(section, self._test_prisma_cloud)
        self._add_divider()

    def _test_prisma_cloud(self):
        """Test Prisma Cloud connection."""
        raw_url = self.entries.get('PRISMA_CLOUD_URL', tk.StringVar()).get().strip()
        access_key = self.entries.get('PRISMA_CLOUD_ACCESS_KEY', tk.StringVar()).get().strip()
        secret_key = self.entries.get('PRISMA_CLOUD_SECRET_KEY', tk.StringVar()).get().strip()

        if not raw_url:
            self._log("Prisma Cloud: Console URL is required", 'err')
            return
        if not access_key or not secret_key:
            self._log("Prisma Cloud: Access key and secret key are required", 'err')
            return

        candidates = self._prisma_cloud_auth_candidates(raw_url)
        if not candidates:
            self._log("Prisma Cloud: Could not parse Prisma Cloud URL", 'err')
            return

        self._log(
            "Prisma Cloud: Testing standard mapping "
            "(username=Access Key, password=Secret Key)...",
            'info'
        )

        for name, endpoint in candidates:
            self._log(f"Prisma Cloud: Trying {name} endpoint {endpoint}", 'info')

            try:
                response = requests.post(
                    endpoint,
                    json={
                        "username": access_key,
                        "password": secret_key,
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=10,
                    verify=True,
                )

                if response.status_code == 200:
                    token_preview = response.text.strip()
                    self._log(f"Prisma Cloud: ✓ Authentication successful via {name}", 'ok')
                    if token_preview:
                        self._log(f"Prisma Cloud:   Received auth token ({len(token_preview)} chars)", 'info')
                    return
                if response.status_code == 401:
                    self._log(
                        f"Prisma Cloud: {name} rejected the credentials (HTTP 401)",
                        'err'
                    )
                    continue
                if response.status_code == 403:
                    self._log(
                        f"Prisma Cloud: {name} reached the service but access was forbidden (HTTP 403)",
                        'err'
                    )
                    continue
                if response.status_code == 404:
                    self._log(
                        f"Prisma Cloud: {name} endpoint not found (HTTP 404)",
                        'err'
                    )
                    continue

                self._log(
                    f"Prisma Cloud: {name} returned unexpected response (HTTP {response.status_code})",
                    'err'
                )
            except requests.exceptions.ConnectionError:
                self._log(f"Prisma Cloud: Cannot connect to {endpoint}", 'err')
            except requests.exceptions.Timeout:
                self._log(f"Prisma Cloud: Timeout reaching {endpoint}", 'err')
            except requests.exceptions.SSLError:
                self._log(f"Prisma Cloud: SSL verification failed for {endpoint}", 'err')
            except Exception as e:
                self._log(f"Prisma Cloud: {name} error: {str(e)[:80]}", 'err')

        self._log(
            "Prisma Cloud: No tested auth endpoint accepted the credentials. "
            "If the API team labeled them as username/password, confirm whether they meant "
            "username=Access Key and password=Secret Key, and whether your Runtime Security console path is /compute.",
            'err'
        )

    def _prisma_cloud_auth_candidates(self, value: str) -> list[tuple[str, str]]:
        """Return likely Prisma Cloud auth endpoints for the provided tenant/console URL."""
        candidate = value.strip()
        if not candidate:
            return []
        if "://" not in candidate:
            candidate = f"https://{candidate}"

        parsed = urlparse(candidate)
        if not parsed.netloc:
            return []

        scheme = parsed.scheme or 'https'
        host = parsed.netloc.lower()
        path = parsed.path.rstrip('/')
        results: list[tuple[str, str]] = []

        if host.startswith("app"):
            api_host = host.replace("app", "api", 1)
            results.append(("Prisma Cloud Gov", f"{scheme}://{api_host}/login"))
            results.append(("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v34.03/authenticate"))

        if path.startswith("/compute"):
            results.insert(0, ("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v34.03/authenticate"))
        elif host.startswith("api"):
            results.append(("Prisma Cloud Gov", f"{scheme}://{host}/login"))

        deduped: list[tuple[str, str]] = []
        seen = set()
        for item in results:
            if item[1] not in seen:
                deduped.append(item)
                seen.add(item[1])
        return deduped

    
    def _add_cryptkeeper_section(self):
        """Add Cryptkeeper keys section for all environments (PROD, STAGING, TEST, DEV, LOCAL)."""
        self._add_section_header(
            "Cryptkeeper",
            "https://artifactory.helix.gsa.gov/ui/repos/tree/General/gs-assist-docker-repo/cryptkeeper"
        )
        section = tk.Frame(self.scroll_frame, bg='#1e1e1e')
        section.pack(fill=tk.X, padx=10)
        self._add_field(section, "PROD Key:", "PROD_CRYPTKEEPER_KEY", is_masked=True)
        self._add_field(section, "STAGING Key:", "STAGING_CRYPTKEEPER_KEY", is_masked=True)
        self._add_field(section, "TEST Key:", "TEST_CRYPTKEEPER_KEY", is_masked=True)
        self._add_field(section, "DEV Key:", "DEV_CRYPTKEEPER_KEY", is_masked=True)
        self._add_field(section, "LOCAL Key:", "LOCAL_CRYPTKEEPER_KEY", is_masked=True)
        self._add_field(
            section,
            "Docker Image:",
            "CRYPTKEEPER_DOCKER_IMAGE",
            default="artifactory.helix.gsa.gov/gs-assist-docker-repo/cryptkeeper:release-main-latest"
        )
        tk.Label(
            section,
            text=(
                "Shared by Cryptkeeper and Cryptkeeper Lite widgets. "
                "Saved as PROD_CRYPTKEEPER_KEY, STAGING_CRYPTKEEPER_KEY, TEST_CRYPTKEEPER_KEY, "
                "DEV_CRYPTKEEPER_KEY, LOCAL_CRYPTKEEPER_KEY in ~/.auger/.env. "
                "Obtain keys from your team’s secure vault."
            ),
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg='#1e1e1e',
            anchor=tk.W,
            wraplength=800
        ).pack(fill=tk.X, pady=(2, 5), padx=(140, 0))
        self._add_test_button(section, self._test_cryptkeeper)
        self._add_divider()

    def _test_cryptkeeper(self):
        """Test Cryptkeeper keys via round-trip encrypt/decrypt using Cryptkeeper Lite."""
        try:
            from auger.tools.cryptkeeper_lite import encrypt_value, decrypt_value
        except ImportError as e:
            self._log(f"Cryptkeeper: \u2717 Cannot import cryptkeeper_lite: {e}", 'err')
            return
        test_value = "auger-key-test-123"
        tested = 0
        for env_label, env_key in [
            ("PROD", "PROD_CRYPTKEEPER_KEY"),
            ("STAGING", "STAGING_CRYPTKEEPER_KEY"),
            ("TEST", "TEST_CRYPTKEEPER_KEY"),
            ("DEV", "DEV_CRYPTKEEPER_KEY"),
            ("LOCAL", "LOCAL_CRYPTKEEPER_KEY"),
        ]:
            key = self.entries.get(env_key, tk.StringVar()).get().strip()
            if not key:
                self._log(f"Cryptkeeper ({env_label}): \u26a0 No key set \u2014 skipping", 'info')
                continue
            try:
                encrypted = encrypt_value(test_value, key)
                decrypted = decrypt_value(encrypted, key)
                if decrypted == test_value:
                    self._log(f"Cryptkeeper ({env_label}): \u2713 Round-trip encrypt/decrypt OK", 'ok')
                else:
                    self._log(f"Cryptkeeper ({env_label}): \u2717 Decrypt mismatch", 'err')
            except Exception as e:
                self._log(f"Cryptkeeper ({env_label}): \u2717 Error: {str(e)[:80]}", 'err')
            tested += 1
        if tested == 0:
            self._log("Cryptkeeper: No keys set \u2014 enter at least one key (PROD/STAGING/TEST/DEV/LOCAL) to test", 'err')

    def _write_env_key(self, key: str, value: str):
        """Write a single key=value to .env in-place without creating temp files.

        python-dotenv set_key() creates a temp file in the same directory, which
        fails when the directory is owned by a different UID. This reads the file
        into memory, updates the key, and writes it back directly.
        """
        import re as _re
        path = str(ENV_FILE)
        try:
            with open(path, 'r') as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            lines = []
        pattern = _re.compile(rf'^{_re.escape(key)}\s*=')
        new_line = f'{key}="{value}"' if value else f'{key}='
        found = False
        for idx, line in enumerate(lines):
            if pattern.match(line):
                lines[idx] = new_line
                found = True
                break
        if not found:
            lines.append(new_line)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

    def _save_to_env(self):
        """Save all entries to .env file."""
        try:
            ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
            if not ENV_FILE.exists():
                ENV_FILE.touch()

            # Save regular entries
            for key, var in self.entries.items():
                value = var.get().strip()
                if value:
                    self._write_env_key(key, value)

            # Save AWS credentials
            for i, (name_var, access_var, secret_var, region_var, _) in enumerate(self.aws_credentials, 1):
                self._write_env_key(f"AWS_{i}_NAME", name_var.get().strip())
                self._write_env_key(f"AWS_{i}_ACCESS_KEY_ID", access_var.get().strip())
                self._write_env_key(f"AWS_{i}_SECRET_ACCESS_KEY", secret_var.get().strip())
                self._write_env_key(f"AWS_{i}_REGION", region_var.get().strip())

            # Clear old AWS entries if we have fewer now
            i = len(self.aws_credentials) + 1
            while f"AWS_{i}_NAME" in os.environ:
                for suffix in ['NAME', 'ACCESS_KEY_ID', 'SECRET_ACCESS_KEY', 'REGION']:
                    key = f"AWS_{i}_{suffix}"
                    if key in os.environ:
                        self._write_env_key(key, '')
                i += 1

            self._log("✓ Saved to .env", 'ok')
            messagebox.showinfo("Saved", "API keys saved to .env")
        except Exception as e:
            self._log(f"✗ Save failed: {e}", 'err')
            messagebox.showerror("Error", f"Failed to save: {e}")
    
    def _load_from_env(self):
        """Load entries from .env file."""
        try:
            load_dotenv(ENV_FILE, override=True)
            
            # Load regular entries, preserving defaults if not in .env
            for key, var in self.entries.items():
                # Get current value as default (preserves field defaults)
                current_default = var.get()
                value = os.getenv(key, current_default)
                var.set(value)
            
            # Reload AWS section (clear and rebuild)
            for _, _, _, _, frame in self.aws_credentials:
                frame.destroy()
            self.aws_credentials.clear()
            self._load_aws_credentials()
            
            self._log("✓ Reloaded from .env", 'ok')
        except Exception as e:
            self._log(f"✗ Load failed: {e}", 'err')
    
    def _log(self, message, tag='info'):
        """Add message to log."""
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, f"{message}\n", tag)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)
