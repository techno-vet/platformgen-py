"""
Production Release Widget
Manages production deployments with PR tracking and automation.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import sqlite3
import os
import re
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from auger.ui import icons as _icons
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu


def _shared_atlassian_session(instance_url: str):
    """Return a requests session seeded with saved Jira/Atlassian MFA cookies."""
    import requests
    from dotenv import load_dotenv

    load_dotenv(Path.home() / '.auger' / '.env', override=True)
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

# Color scheme matching the Auger platform
BG = '#1e1e1e'          # Main background
BG2 = '#252526'         # Secondary background
BG3 = '#2d2d2d'         # Input/text background
FG = '#e0e0e0'          # Foreground text
FG_DIM = '#808080'      # Dimmed text
ACCENT = '#007acc'      # Primary accent (blue)
ACCENT2 = '#4ec9b0'     # Secondary accent (teal)
BORDER = '#3e3e3e'      # Border color
SUCCESS = '#4ec9b0'     # Success green
WARNING = '#ce9178'     # Warning orange
ERROR = '#f44747'       # Error red



class ProductionReleaseWidget(ttk.Frame):
    """Widget for managing production releases"""
    WIDGET_TITLE     = "Release Manager"
    WIDGET_ICON_NAME = "release"
    
    def __init__(self, parent):
        super().__init__(parent)
        self.configure(style='Dark.TFrame')
        self.db_path = Path.home() / '.auger' / 'logs' / 'deployments.db'
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.current_deployment_id = None
        self._icons = {}
        
        self._setup_styles()
        self._init_db()
        self._create_ui()
        
    def _setup_styles(self):
        """Configure dark theme styles"""
        style = ttk.Style()
        
        # Frame styles
        style.configure('Dark.TFrame', background=BG)
        style.configure('Card.TFrame', background=BG2, relief='flat')
        
        # Label styles
        style.configure('Dark.TLabel', background=BG, foreground=FG, font=('Segoe UI', 10))
        style.configure('Header.TLabel', background=BG, foreground=ACCENT2, font=('Segoe UI', 14, 'bold'))
        style.configure('Title.TLabel', background=BG2, foreground=FG, font=('Segoe UI', 11, 'bold'))
        
        # Button styles
        style.configure('Accent.TButton', background=ACCENT, foreground='white', font=('Segoe UI', 10))
        style.map('Accent.TButton', background=[('active', '#005a9e')])
        
        # Entry styles
        style.configure('Dark.TEntry', fieldbackground=BG3, foreground=FG, bordercolor=BORDER)
        
        # Combobox styles
        style.configure('Dark.TCombobox', fieldbackground=BG3, foreground=FG, bordercolor=BORDER)
        
        # LabelFrame styles
        style.configure('Dark.TLabelframe', background=BG2, foreground=FG, bordercolor=BORDER)
        style.configure('Dark.TLabelframe.Label', background=BG2, foreground=ACCENT2, font=('Segoe UI', 11, 'bold'))
        
    def _init_db(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Tables already created via SQL tool, but verify
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deployments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                change_number TEXT NOT NULL,
                jira_story TEXT,
                release_name TEXT NOT NULL,
                release_branch TEXT,
                deployment_date TEXT NOT NULL,
                engineer TEXT NOT NULL,
                status TEXT DEFAULT 'in_progress',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deployment_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deployment_id INTEGER NOT NULL,
                service_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                current_tag TEXT,
                new_tag TEXT NOT NULL,
                deploy_order INTEGER DEFAULT 0,
                special_handling TEXT,
                FOREIGN KEY (deployment_id) REFERENCES deployments(id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deployment_prs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deployment_id INTEGER NOT NULL,
                pr_number INTEGER,
                pr_url TEXT,
                purpose TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                service_id INTEGER,
                created_at TEXT NOT NULL,
                merged_at TEXT,
                FOREIGN KEY (deployment_id) REFERENCES deployments(id),
                FOREIGN KEY (service_id) REFERENCES deployment_services(id)
            )
        """)
        
        conn.commit()
        conn.close()
        
    def _create_ui(self):
        """Create the widget UI"""
        # Pre-create icons
        for name in ('add', 'refresh', 'file', 'check', 'delete', 'play', 'settings', 'pods', 'branch'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass
        self._tab_icon_configure = _icons.get('settings', 18)
        self._tab_icon_services = _icons.get('pods', 18)
        self._tab_icon_prs = _icons.get('branch', 18)
        # Main container with dark background
        self.configure(style='Dark.TFrame')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        
        # Header with platform styling
        header = tk.Frame(self, bg=BG)
        header.grid(row=0, column=0, sticky='ew', padx=10, pady=10)

        try:
            _ico = _icons.get('release', 22)
            tk.Label(header, image=_ico, bg=BG).pack(side='left', padx=(0, 6))
        except Exception:
            pass

        title_label = ttk.Label(header, text="Release Manager", style='Header.TLabel')
        title_label.pack(side='left')
        
        # Deployment selector
        selector_frame = tk.Frame(header, bg=BG)
        selector_frame.pack(side='right')
        
        ttk.Label(selector_frame, text="Deployment:", style='Dark.TLabel').pack(side='left', padx=5)
        self.deployment_var = tk.StringVar(value="New Deployment")
        self.deployment_combo = ttk.Combobox(selector_frame, textvariable=self.deployment_var,
                                            width=30, state='readonly', style='Dark.TCombobox')
        self.deployment_combo.pack(side='left', padx=5)
        self.deployment_combo.bind('<<ComboboxSelected>>', self._on_deployment_selected)
        
        # Buttons with platform colors
        btn_new = tk.Button(selector_frame, text=" New",
                           image=self._icons.get('add'), compound=tk.LEFT,
                           command=self._new_deployment,
                           bg=ACCENT, fg='white', font=('Segoe UI', 9), relief='flat',
                           padx=10, pady=4, cursor='hand2')
        btn_new.pack(side='left', padx=2)
        
        btn_refresh = tk.Button(selector_frame, text=" Refresh",
                               image=self._icons.get('refresh'), compound=tk.LEFT,
                               command=self._load_deployments,
                               bg=BG2, fg=FG, font=('Segoe UI', 9), relief='flat',
                               padx=10, pady=4, cursor='hand2')
        btn_refresh.pack(side='left', padx=2)
        
        # Notebook for tabs with dark theme
        style = ttk.Style()
        style.configure('Dark.TNotebook', background=BG, borderwidth=0)
        style.configure('Dark.TNotebook.Tab', background=BG2, foreground=FG, padding=[12, 6])
        style.map('Dark.TNotebook.Tab', background=[('selected', BG3)], foreground=[('selected', ACCENT2)])
        
        self.notebook = ttk.Notebook(self, style='Dark.TNotebook')
        self.notebook.grid(row=1, column=0, sticky='nsew', padx=10, pady=5)
        
        # Tab 1: Configure
        self.config_tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.config_tab, image=self._tab_icon_configure, text="  Configure  ", compound=tk.LEFT)
        self._create_config_tab()
        
        # Tab 2: Services
        self.services_tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.services_tab, image=self._tab_icon_services, text="  Services  ", compound=tk.LEFT)
        self._create_services_tab()
        
        # Tab 3: PRs
        self.prs_tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.prs_tab, image=self._tab_icon_prs, text="  PRs  ", compound=tk.LEFT)
        self._create_prs_tab()
        
        # Status bar with dark theme
        self.status_var = tk.StringVar(value="Ready")
        status_bar = tk.Label(self, textvariable=self.status_var, relief='flat', anchor='w',
                             bg=BG2, fg=FG_DIM, font=('Segoe UI', 9), padx=10, pady=4)
        status_bar.grid(row=2, column=0, sticky='ew', padx=10, pady=(0, 5))
        
        # Load deployments
        self._load_deployments()
        
    def _create_config_tab(self):
        """Create the configuration tab"""
        # Main container with two columns
        main_container = tk.Frame(self.config_tab, bg=BG)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Left column: Form (60% width)
        left_frame = tk.Frame(main_container, bg=BG)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(15, 5))
        
        # Right column: Document viewer (40% width)
        right_frame = tk.Frame(main_container, bg=BG)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 15))
        
        # === LEFT COLUMN: FORM ===
        
        # Scrollable frame for form
        canvas = tk.Canvas(left_frame, highlightthickness=0, bg=BG)
        scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=BG)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Confluence URL section at the top
        confluence_section = tk.LabelFrame(scrollable_frame, text="  Load from Confluence  ", 
                                          bg=BG2, fg=ACCENT2, font=('Segoe UI', 11, 'bold'),
                                          padx=15, pady=15, relief='flat', borderwidth=2)
        confluence_section.pack(fill='x', padx=0, pady=(0, 15))
        
        # URL input row
        url_row = tk.Frame(confluence_section, bg=BG2)
        url_row.pack(fill='x', pady=(0, 10))
        
        tk.Label(url_row, text="Document URL:", bg=BG2, fg=FG, 
                font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(0, 10))
        
        self.confluence_url_var = tk.StringVar()
        url_entry = tk.Entry(url_row, textvariable=self.confluence_url_var,
                            bg=BG3, fg=FG, insertbackground=FG, font=('Consolas', 9),
                            relief='flat', borderwidth=2)
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Load button on separate row below (right-aligned)
        btn_row = tk.Frame(confluence_section, bg=BG2)
        btn_row.pack(fill='x')
        
        load_btn = tk.Button(btn_row, text=" Load & Parse Document",
                            image=self._icons.get('file'), compound=tk.LEFT,
                            command=self._load_from_confluence,
                            bg=ACCENT, fg='white', font=('Segoe UI', 10, 'bold'),
                            relief='flat', padx=20, pady=8, cursor='hand2')
        load_btn.pack(side=tk.RIGHT)
        
        # Form fields with dark styling
        form = tk.LabelFrame(scrollable_frame, text="  Deployment Information  ", 
                            bg=BG2, fg=ACCENT2, font=('Segoe UI', 11, 'bold'),
                            padx=15, pady=15, relief='flat', borderwidth=2)
        form.pack(fill='x', padx=0, pady=0)
        
        # Entry styling helper
        def create_entry(parent, var):
            entry = tk.Entry(parent, textvariable=var, width=50,
                           bg=BG3, fg=FG, insertbackground=FG,
                           font=('Consolas', 10), relief='flat', borderwidth=2)
            return entry
        
        
        # Change Number
        tk.Label(form, text="Change Number:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=0, column=0, sticky='w', pady=8)
        self.change_number_var = tk.StringVar()
        create_entry(form, self.change_number_var).grid(row=0, column=1, sticky='ew', pady=8, padx=(10, 0))
        
        # Jira Story
        tk.Label(form, text="Jira Story:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=1, column=0, sticky='w', pady=8)
        self.jira_story_var = tk.StringVar()
        create_entry(form, self.jira_story_var).grid(row=1, column=1, sticky='ew', pady=8, padx=(10, 0))
        
        # Release Name
        tk.Label(form, text="Release Name:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=2, column=0, sticky='w', pady=8)
        self.release_name_var = tk.StringVar()
        create_entry(form, self.release_name_var).grid(row=2, column=1, sticky='ew', pady=8, padx=(10, 0))
        
        # Release Branch
        tk.Label(form, text="Release Branch:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=3, column=0, sticky='w', pady=8)
        self.release_branch_var = tk.StringVar()
        create_entry(form, self.release_branch_var).grid(row=3, column=1, sticky='ew', pady=8, padx=(10, 0))
        
        # Engineer
        tk.Label(form, text="Engineer:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=4, column=0, sticky='w', pady=8)
        self.engineer_var = tk.StringVar(value=os.getenv('USER', 'Unknown'))
        create_entry(form, self.engineer_var).grid(row=4, column=1, sticky='ew', pady=8, padx=(10, 0))
        
        # Deployment Date
        tk.Label(form, text="Deployment Date:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=5, column=0, sticky='w', pady=8)
        self.deployment_date_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        create_entry(form, self.deployment_date_var).grid(row=5, column=1, sticky='ew', pady=8, padx=(10, 0))
        
        # Status
        tk.Label(form, text="Status:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=6, column=0, sticky='w', pady=8)
        self.status_combo_var = tk.StringVar(value='in_progress')
        status_combo = ttk.Combobox(form, textvariable=self.status_combo_var, width=47,
                                   values=['in_progress', 'completed', 'failed', 'rolled_back'],
                                   style='Dark.TCombobox', font=('Consolas', 10))
        status_combo.grid(row=6, column=1, sticky='ew', pady=8, padx=(10, 0))
        
        form.columnconfigure(1, weight=1)
        
        # Buttons with platform styling
        btn_frame = tk.Frame(scrollable_frame, bg=BG)
        btn_frame.pack(fill='x', padx=0, pady=10)
        
        tk.Button(btn_frame, text=" Save Deployment",
                 image=self._icons.get('check'), compound=tk.LEFT,
                 command=self._save_deployment,
                 bg=ACCENT, fg='white', font=('Segoe UI', 10, 'bold'),
                 relief='flat', padx=20, pady=8, cursor='hand2').pack(side='left', padx=5)
        
        tk.Button(btn_frame, text=" Clear Form",
                 image=self._icons.get('delete'), compound=tk.LEFT,
                 command=self._clear_form,
                 bg=BG2, fg=FG, font=('Segoe UI', 10),
                 relief='flat', padx=20, pady=8, cursor='hand2').pack(side='left', padx=5)
        
        # === RIGHT COLUMN: DOCUMENT VIEWER ===
        
        doc_frame = tk.LabelFrame(right_frame, text="  Confluence Document Preview  ",
                                 bg=BG2, fg=ACCENT2, font=('Segoe UI', 11, 'bold'),
                                 padx=10, pady=10, relief='flat', borderwidth=2)
        doc_frame.pack(fill=tk.BOTH, expand=True)
        
        # Document viewer with scrollbar
        doc_scroll = ttk.Scrollbar(doc_frame, orient='vertical')
        doc_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.doc_viewer = tk.Text(doc_frame, wrap=tk.WORD, 
                                 bg=BG3, fg=FG, font=('Segoe UI', 9),
                                 relief='flat', padx=10, pady=10,
                                 yscrollcommand=doc_scroll.set, state=tk.DISABLED)
        self.doc_viewer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        make_text_copyable(self.doc_viewer)
        doc_scroll.config(command=self.doc_viewer.yview)
        
        # Configure tags for markdown-like styling
        self.doc_viewer.tag_config('h1', font=('Segoe UI', 14, 'bold'), foreground=ACCENT2, spacing3=10)
        self.doc_viewer.tag_config('h2', font=('Segoe UI', 12, 'bold'), foreground=ACCENT2, spacing3=8)
        self.doc_viewer.tag_config('h3', font=('Segoe UI', 11, 'bold'), foreground='#9cdcfe', spacing3=5)
        self.doc_viewer.tag_config('bold', font=('Segoe UI', 9, 'bold'))
        self.doc_viewer.tag_config('code', font=('Consolas', 9), foreground='#ce9178', background='#1a1a1a')
        self.doc_viewer.tag_config('link', foreground='#9cdcfe', underline=1)
        self.doc_viewer.tag_config('success', foreground=SUCCESS)
        self.doc_viewer.tag_config('error', foreground=ERROR)
        
        # Initial message
        self._update_doc_viewer("Enter a Confluence URL above and click 'Load & Parse Document' to view deployment instructions here.\n\nExample URL:\nhttps://gsa-standard.atlassian-us-gov-mod.net/wiki/spaces/ACP/pages/633647209/")
    
    def _update_doc_viewer(self, text, clear=True):
        """Update the document viewer with text"""
        self.doc_viewer.configure(state=tk.NORMAL)
        if clear:
            self.doc_viewer.delete('1.0', tk.END)
        self.doc_viewer.insert(tk.END, text)
        self.doc_viewer.configure(state=tk.DISABLED)
    
    def _load_from_confluence(self):
        """Load and parse deployment document from Confluence"""
        url = self.confluence_url_var.get().strip()
        
        if not url:
            messagebox.showwarning("No URL", "Please enter a Confluence document URL")
            return
        
        # Extract page ID from URL
        import re
        match = re.search(r'/pages/(\d+)', url)
        if not match:
            messagebox.showerror("Invalid URL", "Could not extract page ID from URL.\nExpected format: .../pages/123456/...")
            return
        
        page_id = match.group(1)
        
        # Load credentials from ~/.auger/.env
        from dotenv import load_dotenv
        load_dotenv(Path.home() / '.auger' / '.env', override=True)

        base_url = os.getenv('CONFLUENCE_BASE_URL', 'https://gsa-standard.atlassian-us-gov-mod.net/wiki')
        token = os.getenv('CONFLUENCE_TOKEN', '')
        has_jira_cookies = bool(os.getenv('JIRA_COOKIES', '').strip())

        if not token and not has_jira_cookies:
            response = messagebox.askyesno(
                "Confluence Authentication Missing",
                "No Jira MFA cookies or Confluence token were found in ~/.auger/.env.\n\n"
                "Please authenticate with the Jira widget or configure a Confluence token in API Config."
            )
            if response:
                # Try to open API Config widget
                pass  # Widget will need to be opened by parent
            return
        
        self._update_doc_viewer("Loading document from Confluence...\nPlease wait...", clear=True)
        self.status_var.set(f"Loading page {page_id} from Confluence...")
        
        try:
            import requests

            # Fetch the page. Prefer the shared Atlassian MFA cookie session used by Jira,
            # then fall back to the legacy Confluence bearer token path if needed.
            api_url = f"{base_url}/rest/api/content/{page_id}?expand=body.storage,version"
            response = None
            auth_mode = None

            if has_jira_cookies:
                auth_mode = "Jira MFA cookies"
                response = _shared_atlassian_session(base_url).get(api_url, timeout=15, verify=True)

            if (response is None or response.status_code in (401, 403)) and token:
                auth_mode = "Confluence bearer token"
                response = requests.get(
                    api_url,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {token}"
                    },
                    timeout=15,
                    verify=True
                )

            if response.status_code != 200:
                error_msg = f"Failed to fetch document (HTTP {response.status_code})"
                if response.status_code == 401:
                    error_msg += "\nAuthentication failed - authenticate with the Jira widget or check your Confluence token in API Config"
                elif response.status_code == 403:
                    error_msg += "\nAccess denied - your Atlassian session may not include this page, or you may not have permission to view it"
                elif response.status_code == 404:
                    error_msg += "\nPage not found - check the URL"
                if auth_mode:
                    error_msg += f"\nAuth mode attempted: {auth_mode}"
                
                self._update_doc_viewer(error_msg, clear=True)
                self.status_var.set("Failed to load document")
                messagebox.showerror("Load Failed", error_msg)
                return
            
            data = response.json()
            title = data.get('title', 'Untitled')
            html_content = data.get('body', {}).get('storage', {}).get('value', '')
            version = data.get('version', {}).get('number', 'N/A')
            
            # Parse and display
            self._parse_deployment_doc(html_content, title, version)
            
            self.status_var.set(f"Loaded: {title} (v{version})")
            
        except requests.exceptions.Timeout:
            error_msg = "Connection timeout while fetching document"
            self._update_doc_viewer(error_msg, clear=True)
            self.status_var.set("Timeout")
            messagebox.showerror("Timeout", error_msg)
        except requests.exceptions.ConnectionError:
            error_msg = f"Could not connect to {base_url}"
            self._update_doc_viewer(error_msg, clear=True)
            self.status_var.set("Connection failed")
            messagebox.showerror("Connection Error", error_msg)
        except Exception as e:
            error_msg = f"Error loading document:\n{str(e)}"
            self._update_doc_viewer(error_msg, clear=True)
            self.status_var.set("Error")
            messagebox.showerror("Error", error_msg)
    
    def _parse_deployment_doc(self, html_content, title, version):
        """Parse Confluence HTML and populate form fields"""
        from bs4 import BeautifulSoup
        import html2text
        
        # Convert HTML to readable text for viewer
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.body_width = 0
        markdown_text = h.handle(html_content)
        
        # Display in viewer
        display_text = f"# {title}\nVersion: {version}\n\n{'-' * 60}\n\n{markdown_text}"
        self._update_doc_viewer(display_text, clear=True)
        
        # Parse with BeautifulSoup for data extraction
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Try to extract metadata
        # Look for Jira story link
        jira_links = soup.find_all('a', href=re.compile(r'cm-jira\.usa\.gov/browse/'))
        if jira_links:
            jira_story = jira_links[0].get_text().strip()
            self.jira_story_var.set(jira_story)
        
        # Try to extract change number from title or content
        if 'CHG' in title:
            chg_match = re.search(r'CHG\d+', title)
            if chg_match:
                self.change_number_var.set(chg_match.group(0))
        
        # Extract release name and branch from title
        release_match = re.search(r'(Release|Data Release)\s+([\d\.]+)', title, re.IGNORECASE)
        if release_match:
            release_name = release_match.group(2)
            self.release_name_var.set(f"Data {release_name}")
            self.release_branch_var.set(f"release/DATA_{release_name}_DME")
        
        # Parse services table
        self._parse_services_table(soup)
        
        messagebox.showinfo("Document Loaded", 
                          f"Successfully loaded:\n{title}\n\nCheck the Services tab for parsed data.")
    
    def _parse_services_table(self, soup):
        """Parse the services/applications table from Confluence HTML"""
        # Clear existing services
        for item in self.services_tree.get_children():
            self.services_tree.delete(item)
        
        # Find tables (look for the Applications/Components table)
        tables = soup.find_all('table')
        
        for table in tables:
            headers = [th.get_text().strip().lower() for th in table.find_all('th')]
            
            # Check if this looks like our services table
            if any('application' in h or 'service' in h for h in headers):
                rows = table.find_all('tr')[1:]  # Skip header row
                
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 4:
                        # Extract data from cells
                        service_name = cells[1].get_text().strip() if len(cells) > 1 else ''
                        
                        # Extract repo and branch from links
                        repo_link = cells[2].find('a') if len(cells) > 2 else None
                        branch = cells[3].get_text().strip() if len(cells) > 3 else ''
                        
                        # Extract image tag
                        image_tag = ''
                        if len(cells) > 4:
                            tag_link = cells[4].find('a')
                            if tag_link:
                                image_tag = tag_link.get_text().strip()
                            else:
                                image_tag = cells[4].get_text().strip()
                        
                        # Extract special instructions
                        special_handling = ''
                        if len(cells) > 5:
                            instructions = cells[5].get_text().strip().lower()
                            if 'undeploy' in instructions:
                                special_handling = 'airflow_undeploy'
                            elif 'redeploy' in instructions:
                                special_handling = 'airflow_redeploy'
                        
                        # Add to services tree
                        if service_name and image_tag:
                            # Extract file path from service name
                            file_path = self._guess_file_path(service_name)
                            
                            self.services_tree.insert('', tk.END, values=(
                                service_name,
                                file_path,
                                '',  # current tag (unknown)
                                image_tag,
                                special_handling
                            ))
    
    def _guess_file_path(self, service_name):
        """Guess the flux config file path based on service name"""
        service_paths = {
            'Data Pipeline': 'core/production/data-pipeline/utils/data-pipeline.yaml',
            'Assist Data Pipeline': 'core/production/data-pipeline/utils/data-pipeline.yaml',
            'Data API Service': 'core/production/data-api/utils/data-api-service.yaml',
            'Data-Utils': 'core/production/data-utils/utils/data-utils.yaml',
            'Data Utils': 'core/production/data-utils/utils/data-utils.yaml',
            'JupyterHub': 'core/production/data-utils/utils/data-utils.yaml',
            'Data-Catalogs': 'core/production/data-catalog/utils/data-catalog.yaml',
            'Data Catalogs': 'core/production/data-catalog/utils/data-catalog.yaml',
            'Airflow': 'core/production/data-pipeline/utils/airflow.yaml',
        }
        
        for key, path in service_paths.items():
            if key.lower() in service_name.lower():
                return path
        
        return 'unknown.yaml'
    
    def _create_services_tab(self):
        """Create the services management tab"""
        # Top frame for add service with dark styling
        top_frame = tk.LabelFrame(self.services_tab, text="  Add Service  ", 
                                 bg=BG2, fg=ACCENT2, font=('Segoe UI', 11, 'bold'),
                                 padx=15, pady=15, relief='flat', borderwidth=2)
        top_frame.pack(fill='x', padx=15, pady=15)
        
        # Service name
        tk.Label(top_frame, text="Service:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=0, column=0, sticky='w', padx=5, pady=8)
        self.service_name_var = tk.StringVar()
        service_combo = ttk.Combobox(top_frame, textvariable=self.service_name_var, width=25,
                                    values=[
                                        'Data Pipeline',
                                        'Data API Service',
                                        'Data-Utils (JupyterHub)',
                                        'Data-Catalogs',
                                        'Airflow',
                                        'Custom...'
                                    ], style='Dark.TCombobox', font=('Consolas', 10))
        service_combo.grid(row=0, column=1, sticky='ew', padx=5, pady=8)
        service_combo.bind('<<ComboboxSelected>>', self._on_service_selected)
        
        # File path
        tk.Label(top_frame, text="File Path:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=1, column=0, sticky='w', padx=5, pady=8)
        self.file_path_var = tk.StringVar()
        tk.Entry(top_frame, textvariable=self.file_path_var, width=50,
                bg=BG3, fg=FG, insertbackground=FG, font=('Consolas', 10),
                relief='flat', borderwidth=2).grid(row=1, column=1, columnspan=2, sticky='ew', padx=5, pady=8)
        
        # Current tag
        tk.Label(top_frame, text="Current Tag:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=2, column=0, sticky='w', padx=5, pady=8)
        self.current_tag_var = tk.StringVar()
        tk.Entry(top_frame, textvariable=self.current_tag_var, width=50,
                bg=BG3, fg=FG, insertbackground=FG, font=('Consolas', 10),
                relief='flat', borderwidth=2).grid(row=2, column=1, columnspan=2, sticky='ew', padx=5, pady=8)
        
        # New tag
        tk.Label(top_frame, text="New Tag:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=3, column=0, sticky='w', padx=5, pady=8)
        self.new_tag_var = tk.StringVar()
        tk.Entry(top_frame, textvariable=self.new_tag_var, width=50,
                bg=BG3, fg=FG, insertbackground=FG, font=('Consolas', 10),
                relief='flat', borderwidth=2).grid(row=3, column=1, columnspan=2, sticky='ew', padx=5, pady=8)
        
        # Special handling
        tk.Label(top_frame, text="Special Handling:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=4, column=0, sticky='w', padx=5, pady=8)
        self.special_handling_var = tk.StringVar()
        special_combo = ttk.Combobox(top_frame, textvariable=self.special_handling_var, width=25,
                                    values=['', 'airflow_undeploy', 'airflow_redeploy'],
                                    style='Dark.TCombobox', font=('Consolas', 10))
        special_combo.grid(row=4, column=1, sticky='ew', padx=5, pady=8)
        
        tk.Button(top_frame, text=" Add Service",
                 image=self._icons.get('add'), compound=tk.LEFT,
                 command=self._add_service,
                 bg=ACCENT, fg='white', font=('Segoe UI', 10),
                 relief='flat', padx=12, pady=6, cursor='hand2').grid(row=4, column=2, padx=5, pady=8)
        
        top_frame.columnconfigure(1, weight=1)
        
        # Services tree with dark styling
        tree_frame = tk.LabelFrame(self.services_tab, text="  Services to Deploy  ",
                                  bg=BG2, fg=ACCENT2, font=('Segoe UI', 11, 'bold'),
                                  padx=15, pady=15, relief='flat', borderwidth=2)
        tree_frame.pack(fill='both', expand=True, padx=15, pady=10)
        
        # Treeview styling
        style = ttk.Style()
        style.configure('Dark.Treeview', 
                       background=BG3, fieldbackground=BG3, foreground=FG,
                       font=('Consolas', 9))
        style.configure('Dark.Treeview.Heading', 
                       background=BG2, foreground=ACCENT2, font=('Segoe UI', 10, 'bold'))
        style.map('Dark.Treeview', background=[('selected', ACCENT)])
        
        # Create Treeview
        self.services_tree = ttk.Treeview(tree_frame, 
                                         columns=('service', 'file', 'current', 'new', 'special'),
                                         show='tree headings', height=10, style='Dark.Treeview')
        
        self.services_tree.heading('service', text='Service')
        self.services_tree.heading('file', text='File Path')
        self.services_tree.heading('current', text='Current Tag')
        self.services_tree.heading('new', text='New Tag')
        self.services_tree.heading('special', text='Special')
        
        self.services_tree.column('#0', width=50)
        self.services_tree.column('service', width=150)
        self.services_tree.column('file', width=300)
        self.services_tree.column('current', width=200)
        self.services_tree.column('new', width=200)
        self.services_tree.column('special', width=120)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.services_tree.yview)
        self.services_tree.configure(yscrollcommand=scrollbar.set)
        
        self.services_tree.pack(side='left', fill='both', expand=True)
        add_treeview_menu(self.services_tree)
        scrollbar.pack(side='right', fill='y')
        
        # Buttons with dark styling
        btn_frame = tk.Frame(tree_frame, bg=BG2)
        btn_frame.pack(fill='x', pady=10)
        
        tk.Button(btn_frame, text=" Remove Selected",
                 image=self._icons.get('delete'), compound=tk.LEFT,
                 command=self._remove_service,
                 bg=ERROR, fg='white', font=('Segoe UI', 10),
                 relief='flat', padx=12, pady=6, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame, text=" Clear All",
                 image=self._icons.get('delete'), compound=tk.LEFT,
                 command=self._clear_services,
                 bg=BG2, fg=FG, font=('Segoe UI', 10),
                 relief='flat', padx=12, pady=6, cursor='hand2').pack(side='left', padx=5)
        
    def _create_prs_tab(self):
        """Create the PRs tracking tab"""
        # Top frame for add PR with dark styling
        top_frame = tk.LabelFrame(self.prs_tab, text="  Add Pull Request  ", 
                                 bg=BG2, fg=ACCENT2, font=('Segoe UI', 11, 'bold'),
                                 padx=15, pady=15, relief='flat', borderwidth=2)
        top_frame.pack(fill='x', padx=15, pady=15)
        
        tk.Label(top_frame, text="Purpose:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=0, column=0, sticky='w', padx=5, pady=8)
        self.pr_purpose_var = tk.StringVar()
        tk.Entry(top_frame, textvariable=self.pr_purpose_var, width=50,
                bg=BG3, fg=FG, insertbackground=FG, font=('Consolas', 10),
                relief='flat', borderwidth=2).grid(row=0, column=1, sticky='ew', padx=5, pady=8)
        
        tk.Label(top_frame, text="PR URL:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=1, column=0, sticky='w', padx=5, pady=8)
        self.pr_url_var = tk.StringVar()
        tk.Entry(top_frame, textvariable=self.pr_url_var, width=50,
                bg=BG3, fg=FG, insertbackground=FG, font=('Consolas', 10),
                relief='flat', borderwidth=2).grid(row=1, column=1, sticky='ew', padx=5, pady=8)
        
        tk.Label(top_frame, text="Status:", bg=BG2, fg=FG, font=('Segoe UI', 10)).grid(row=2, column=0, sticky='w', padx=5, pady=8)
        self.pr_status_var = tk.StringVar(value='pending')
        pr_status_combo = ttk.Combobox(top_frame, textvariable=self.pr_status_var, width=47,
                                      values=['pending', 'open', 'merged', 'closed', 'failed'],
                                      style='Dark.TCombobox', font=('Consolas', 10))
        pr_status_combo.grid(row=2, column=1, sticky='ew', padx=5, pady=8)
        
        tk.Button(top_frame, text=" Add PR",
                 image=self._icons.get('add'), compound=tk.LEFT,
                 command=self._add_pr,
                 bg=ACCENT, fg='white', font=('Segoe UI', 10),
                 relief='flat', padx=12, pady=6, cursor='hand2').grid(row=2, column=2, padx=5, pady=8)
        
        top_frame.columnconfigure(1, weight=1)
        
        # PRs tree with dark styling
        tree_frame = tk.LabelFrame(self.prs_tab, text="  Pull Requests  ",
                                  bg=BG2, fg=ACCENT2, font=('Segoe UI', 11, 'bold'),
                                  padx=15, pady=15, relief='flat', borderwidth=2)
        tree_frame.pack(fill='both', expand=True, padx=15, pady=10)
        
        self.prs_tree = ttk.Treeview(tree_frame,
                                    columns=('num', 'purpose', 'url', 'status', 'created'),
                                    show='tree headings', height=10, style='Dark.Treeview')
        
        self.prs_tree.heading('num', text='#')
        self.prs_tree.heading('purpose', text='Purpose')
        self.prs_tree.heading('url', text='PR URL')
        self.prs_tree.heading('status', text='Status')
        self.prs_tree.heading('created', text='Created')
        
        self.prs_tree.column('#0', width=50)
        self.prs_tree.column('num', width=50)
        self.prs_tree.column('purpose', width=200)
        self.prs_tree.column('url', width=400)
        self.prs_tree.column('status', width=100)
        self.prs_tree.column('created', width=150)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.prs_tree.yview)
        self.prs_tree.configure(yscrollcommand=scrollbar.set)
        
        self.prs_tree.pack(side='left', fill='both', expand=True)
        add_treeview_menu(self.prs_tree)
        scrollbar.pack(side='right', fill='y')
        
        # Double-click to open URL
        self.prs_tree.bind('<Double-1>', self._open_pr_url)
        
        # Buttons with dark styling
        btn_frame = tk.Frame(tree_frame, bg=BG2)
        btn_frame.pack(fill='x', pady=10)
        
        tk.Button(btn_frame, text=" Open Selected",
                 image=self._icons.get('play'), compound=tk.LEFT,
                 command=self._open_pr_url,
                 bg=ACCENT, fg='white', font=('Segoe UI', 10),
                 relief='flat', padx=16, pady=6, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame, text=" Update Status",
                 image=self._icons.get('refresh'), compound=tk.LEFT,
                 command=self._update_pr_status,
                 bg=SUCCESS, fg='white', font=('Segoe UI', 10),
                 relief='flat', padx=12, pady=6, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame, text=" Remove Selected",
                 image=self._icons.get('delete'), compound=tk.LEFT,
                 command=self._remove_pr,
                 bg=ERROR, fg='white', font=('Segoe UI', 10),
                 relief='flat', padx=12, pady=6, cursor='hand2').pack(side='left', padx=5)
        
    def _on_service_selected(self, event=None):
        """Auto-fill file path based on service selection"""
        service = self.service_name_var.get()
        
        file_paths = {
            'Data Pipeline': 'core/production/data-pipeline/utils/data-pipeline.yaml',
            'Data API Service': 'core/production/data-api/utils/data-api-service.yaml',
            'Data-Utils (JupyterHub)': 'core/production/data-utils/utils/data-utils.yaml',
            'Data-Catalogs': 'core/production/data-catalog/utils/data-catalog.yaml',
            'Airflow': 'core/production/data-pipeline/utils/airflow.yaml'
        }
        
        if service in file_paths:
            self.file_path_var.set(file_paths[service])
            
    def _new_deployment(self):
        """Start a new deployment"""
        self.current_deployment_id = None
        self._clear_form()
        self._clear_services()
        self._clear_prs()
        self.deployment_var.set("New Deployment")
        self.status_var.set("Started new deployment")
        
    def _clear_form(self):
        """Clear the configuration form"""
        self.change_number_var.set('')
        self.jira_story_var.set('')
        self.release_name_var.set('')
        self.release_branch_var.set('')
        self.deployment_date_var.set(datetime.now().strftime('%Y-%m-%d'))
        self.status_combo_var.set('in_progress')
        
    def _save_deployment(self):
        """Save deployment to database"""
        # Validate
        if not self.change_number_var.get() or not self.release_name_var.get():
            messagebox.showerror("Error", "Change Number and Release Name are required")
            return
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        if self.current_deployment_id:
            # Update existing
            cursor.execute("""
                UPDATE deployments 
                SET change_number=?, jira_story=?, release_name=?, release_branch=?,
                    deployment_date=?, engineer=?, status=?, updated_at=?
                WHERE id=?
            """, (
                self.change_number_var.get(),
                self.jira_story_var.get(),
                self.release_name_var.get(),
                self.release_branch_var.get(),
                self.deployment_date_var.get(),
                self.engineer_var.get(),
                self.status_combo_var.get(),
                now,
                self.current_deployment_id
            ))
        else:
            # Insert new
            cursor.execute("""
                INSERT INTO deployments 
                (change_number, jira_story, release_name, release_branch, deployment_date, 
                 engineer, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.change_number_var.get(),
                self.jira_story_var.get(),
                self.release_name_var.get(),
                self.release_branch_var.get(),
                self.deployment_date_var.get(),
                self.engineer_var.get(),
                self.status_combo_var.get(),
                now,
                now
            ))
            self.current_deployment_id = cursor.lastrowid
            
        conn.commit()
        conn.close()
        
        self._load_deployments()
        self.status_var.set(f"Saved deployment: {self.change_number_var.get()}")
        messagebox.showinfo("Success", "Deployment saved successfully")
        
    def _add_service(self):
        """Add service to deployment"""
        if not self.current_deployment_id:
            messagebox.showerror("Error", "Please save deployment first")
            return
            
        if not self.service_name_var.get() or not self.new_tag_var.get():
            messagebox.showerror("Error", "Service name and new tag are required")
            return
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO deployment_services
            (deployment_id, service_name, file_path, current_tag, new_tag, special_handling)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            self.current_deployment_id,
            self.service_name_var.get(),
            self.file_path_var.get(),
            self.current_tag_var.get(),
            self.new_tag_var.get(),
            self.special_handling_var.get()
        ))
        
        conn.commit()
        conn.close()
        
        self._load_services()
        
        # Clear form
        self.service_name_var.set('')
        self.file_path_var.set('')
        self.current_tag_var.set('')
        self.new_tag_var.set('')
        self.special_handling_var.set('')
        
        self.status_var.set(f"Added service: {self.service_name_var.get()}")
        
    def _load_services(self):
        """Load services from database"""
        # Clear tree
        for item in self.services_tree.get_children():
            self.services_tree.delete(item)
            
        if not self.current_deployment_id:
            return
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, service_name, file_path, current_tag, new_tag, special_handling
            FROM deployment_services
            WHERE deployment_id = ?
            ORDER BY deploy_order, id
        """, (self.current_deployment_id,))
        
        for idx, row in enumerate(cursor.fetchall(), 1):
            service_id, service_name, file_path, current_tag, new_tag, special = row
            self.services_tree.insert('', 'end', iid=service_id,
                                     values=(service_name, file_path, current_tag or '', 
                                            new_tag, special or ''))
            
        conn.close()
        
    def _remove_service(self):
        """Remove selected service"""
        selected = self.services_tree.selection()
        if not selected:
            return
            
        service_id = selected[0]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM deployment_services WHERE id = ?", (service_id,))
        conn.commit()
        conn.close()
        
        self._load_services()
        self.status_var.set("Removed service")
        
    def _clear_services(self):
        """Clear all services"""
        if not self.current_deployment_id:
            return
            
        if not messagebox.askyesno("Confirm", "Clear all services?"):
            return
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM deployment_services WHERE deployment_id = ?", 
                      (self.current_deployment_id,))
        conn.commit()
        conn.close()
        
        self._load_services()
        self.status_var.set("Cleared all services")
        
    def _add_pr(self):
        """Add PR to tracking"""
        if not self.current_deployment_id:
            messagebox.showerror("Error", "Please save deployment first")
            return
            
        if not self.pr_purpose_var.get():
            messagebox.showerror("Error", "PR purpose is required")
            return
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Extract PR number from URL
        pr_number = None
        pr_url = self.pr_url_var.get()
        if '/pull/' in pr_url:
            try:
                pr_number = int(pr_url.split('/pull/')[-1].split('/')[0])
            except:
                pass
        
        cursor.execute("""
            INSERT INTO deployment_prs
            (deployment_id, pr_number, pr_url, purpose, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            self.current_deployment_id,
            pr_number,
            pr_url,
            self.pr_purpose_var.get(),
            self.pr_status_var.get(),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
        self._load_prs()
        
        # Clear form
        self.pr_purpose_var.set('')
        self.pr_url_var.set('')
        self.pr_status_var.set('pending')
        
        self.status_var.set("Added PR")
        
    def _load_prs(self):
        """Load PRs from database"""
        # Clear tree
        for item in self.prs_tree.get_children():
            self.prs_tree.delete(item)
            
        if not self.current_deployment_id:
            return
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, pr_number, purpose, pr_url, status, created_at
            FROM deployment_prs
            WHERE deployment_id = ?
            ORDER BY created_at
        """, (self.current_deployment_id,))
        
        for row in cursor.fetchall():
            pr_id, pr_number, purpose, pr_url, status, created_at = row
            self.prs_tree.insert('', 'end', iid=pr_id,
                                values=(pr_number or '', purpose, pr_url or '', status, 
                                       created_at[:19] if created_at else ''))
            
        conn.close()
        
    def _open_pr_url(self, event=None):
        """Open PR URL in browser"""
        selected = self.prs_tree.selection()
        if not selected:
            return
            
        pr_id = selected[0]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT pr_url FROM deployment_prs WHERE id = ?", (pr_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0]:
            import webbrowser
            from auger.tools.host_cmd import open_url as _open_url; _open_url(row[0])
            
    def _update_pr_status(self):
        """Update PR status"""
        selected = self.prs_tree.selection()
        if not selected:
            return
            
        # Simple dialog to update status
        new_status = tk.simpledialog.askstring("Update Status", 
                                              "Enter new status (pending/open/merged/closed/failed):")
        if not new_status:
            return
            
        pr_id = selected[0]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE deployment_prs SET status = ? WHERE id = ?", 
                      (new_status, pr_id))
        
        if new_status == 'merged':
            cursor.execute("UPDATE deployment_prs SET merged_at = ? WHERE id = ?",
                          (datetime.now().isoformat(), pr_id))
        
        conn.commit()
        conn.close()
        
        self._load_prs()
        self.status_var.set(f"Updated PR status to: {new_status}")
        
    def _remove_pr(self):
        """Remove selected PR"""
        selected = self.prs_tree.selection()
        if not selected:
            return
            
        pr_id = selected[0]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM deployment_prs WHERE id = ?", (pr_id,))
        conn.commit()
        conn.close()
        
        self._load_prs()
        self.status_var.set("Removed PR")
        
    def _clear_prs(self):
        """Clear PRs tree"""
        for item in self.prs_tree.get_children():
            self.prs_tree.delete(item)
        
    def _load_deployments(self):
        """Load deployments into combo box"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, change_number, release_name, deployment_date
            FROM deployments
            ORDER BY deployment_date DESC, created_at DESC
            LIMIT 20
        """)
        
        deployments = []
        for row in cursor.fetchall():
            dep_id, change_num, release_name, dep_date = row
            deployments.append(f"{change_num} - {release_name} ({dep_date})")
            
        conn.close()
        
        self.deployment_combo['values'] = ['New Deployment'] + deployments
        
    def _on_deployment_selected(self, event=None):
        """Load selected deployment"""
        selected = self.deployment_var.get()
        if selected == 'New Deployment':
            self._new_deployment()
            return
            
        # Extract change number
        change_number = selected.split(' - ')[0]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, change_number, jira_story, release_name, release_branch,
                   deployment_date, engineer, status
            FROM deployments
            WHERE change_number = ?
        """, (change_number,))
        
        row = cursor.fetchone()
        if not row:
            conn.close()
            return
            
        (dep_id, change_num, jira, release, branch, dep_date, engineer, status) = row
        
        self.current_deployment_id = dep_id
        self.change_number_var.set(change_num)
        self.jira_story_var.set(jira or '')
        self.release_name_var.set(release)
        self.release_branch_var.set(branch or '')
        self.deployment_date_var.set(dep_date)
        self.engineer_var.set(engineer)
        self.status_combo_var.set(status)
        
        conn.close()
        
        self._load_services()
        self._load_prs()
        
        self.status_var.set(f"Loaded deployment: {change_num}")


# For standalone testing
if __name__ == "__main__":
    import tkinter.simpledialog
    
    root = tk.Tk()
    root.title("Production Release Widget - Test")
    root.geometry("1200x800")
    
    widget = ProductionReleaseWidget(root)
    widget.pack(fill='both', expand=True)
    
    root.mainloop()
