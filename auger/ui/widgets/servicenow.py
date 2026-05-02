"""ServiceNow Widget - Manage ServiceNow incidents, changes, and more"""
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import threading
from pathlib import Path
from datetime import datetime
import sys

from auger.tools.servicenow_session import ServiceNowSession
from auger.ui import icons as _icons
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu

# Auger Platform Colors
BG = '#1e1e1e'
BG2 = '#252526'
BG3 = '#2d2d2d'
FG = '#e0e0e0'
ACCENT = '#007acc'
ACCENT2 = '#4ec9b0'
SUCCESS = '#4ec9b0'
ERROR = '#f44747'
WARNING = '#ce9178'



class ServiceNowWidget(tk.Frame):
    """ServiceNow integration widget"""
    
    WIDGET_TITLE = "ServiceNow"
    WIDGET_ICON_NAME = "servicenow"
    
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.sn = None
        self._icons = {}
        self._create_ui()
        self._check_session()
    
    def _create_ui(self):
        """Create the widget UI"""
        for name in ('login', 'refresh', 'check'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass
        # Header
        header = tk.Frame(self, bg='#d93025', height=40)  # ServiceNow red
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        try:
            _ico = _icons.get('servicenow', 22)
            tk.Label(header, image=_ico, bg='#d93025').pack(side=tk.LEFT, padx=(15, 4), pady=8)
        except Exception:
            pass

        tk.Label(
            header,
            text="ServiceNow",
            font=('Segoe UI', 12, 'bold'),
            fg='#ffffff',
            bg='#d93025'
        ).pack(side=tk.LEFT, padx=(0, 5), pady=10)
        
        tk.Label(
            header,
            text="Incidents, Changes, and CMDB",
            font=('Segoe UI', 9),
            fg='#ffffff',
            bg='#d93025'
        ).pack(side=tk.LEFT, padx=5)
        
        # Main content with scrollbar
        main_frame = tk.Frame(self, bg=BG)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(main_frame, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=BG)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        content = scrollable_frame
        
        # Session Status Panel
        self._create_status_panel(content)
        
        # Incidents Panel
        self._create_incidents_panel(content)
        
        # Changes Panel
        self._create_changes_panel(content)
        
        # Status bar
        self.status_var = tk.StringVar(value="Checking connection...")
        status_bar = tk.Label(
            content,
            textvariable=self.status_var,
            font=('Segoe UI', 9),
            fg='#808080',
            bg=BG,
            anchor=tk.W
        )
        status_bar.pack(fill=tk.X, padx=20, pady=(0, 10))
    
    def _create_status_panel(self, parent):
        """Create session status panel"""
        panel = tk.LabelFrame(
            parent,
            text="  Connection Status  ",
            font=('Segoe UI', 10, 'bold'),
            fg=ACCENT2,
            bg=BG2,
            relief=tk.FLAT,
            borderwidth=2
        )
        panel.pack(fill=tk.X, padx=20, pady=(20, 10))
        
        inner = tk.Frame(panel, bg=BG2)
        inner.pack(fill=tk.X, padx=10, pady=10)
        
        # Status label
        self.connection_label = tk.Label(
            inner,
            text="Checking connection...",
            font=('Segoe UI', 10),
            fg=WARNING,
            bg=BG2
        )
        self.connection_label.pack(side=tk.LEFT, padx=(0, 15))
        
        # Login button
        self.login_btn = tk.Button(
            inner,
            text=" Login with MFA",
            image=self._icons.get('login'),
            compound=tk.LEFT,
            command=self._start_auto_login,
            font=('Segoe UI', 9, 'bold'),
            bg=ACCENT,
            fg='#ffffff',
            activebackground='#005a9e',
            activeforeground='#ffffff',
            relief=tk.FLAT,
            cursor='hand2',
            padx=15,
            pady=5
        )
        self.login_btn.pack(side=tk.LEFT, padx=5)
        
        # Refresh button
        tk.Button(
            inner,
            text=" Refresh",
            image=self._icons.get('refresh'),
            compound=tk.LEFT,
            command=self._refresh_data,
            font=('Segoe UI', 9),
            bg=BG3,
            fg=FG,
            activebackground='#3d3d3d',
            activeforeground=FG,
            relief=tk.FLAT,
            cursor='hand2',
            padx=15,
            pady=5
        ).pack(side=tk.LEFT, padx=5)
    
    def _create_incidents_panel(self, parent):
        """Create incidents display panel"""
        panel = tk.LabelFrame(
            parent,
            text="  Recent Incidents  ",
            font=('Segoe UI', 10, 'bold'),
            fg=ACCENT2,
            bg=BG2,
            relief=tk.FLAT,
            borderwidth=2
        )
        panel.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        inner = tk.Frame(panel, bg=BG2)
        inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Treeview for incidents
        columns = ('Number', 'Priority', 'State', 'Short Description')
        self.incidents_tree = ttk.Treeview(
            inner,
            columns=columns,
            show='headings',
            height=8
        )
        
        # Column headings
        self.incidents_tree.heading('Number', text='Number')
        self.incidents_tree.heading('Priority', text='Priority')
        self.incidents_tree.heading('State', text='State')
        self.incidents_tree.heading('Short Description', text='Description')
        
        # Column widths
        self.incidents_tree.column('Number', width=100)
        self.incidents_tree.column('Priority', width=80)
        self.incidents_tree.column('State', width=100)
        self.incidents_tree.column('Short Description', width=400)
        
        # Scrollbar
        incidents_scroll = ttk.Scrollbar(inner, orient=tk.VERTICAL, command=self.incidents_tree.yview)
        self.incidents_tree.configure(yscrollcommand=incidents_scroll.set)
        
        self.incidents_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        add_treeview_menu(self.incidents_tree)
        incidents_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    
    def _create_changes_panel(self, parent):
        """Create changes display panel"""
        panel = tk.LabelFrame(
            parent,
            text="  Recent Change Requests  ",
            font=('Segoe UI', 10, 'bold'),
            fg=ACCENT2,
            bg=BG2,
            relief=tk.FLAT,
            borderwidth=2
        )
        panel.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        inner = tk.Frame(panel, bg=BG2)
        inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Treeview for changes
        columns = ('Number', 'Type', 'State', 'Short Description')
        self.changes_tree = ttk.Treeview(
            inner,
            columns=columns,
            show='headings',
            height=8
        )
        
        # Column headings
        self.changes_tree.heading('Number', text='Number')
        self.changes_tree.heading('Type', text='Type')
        self.changes_tree.heading('State', text='State')
        self.changes_tree.heading('Short Description', text='Description')
        
        # Column widths
        self.changes_tree.column('Number', width=120)
        self.changes_tree.column('Type', width=100)
        self.changes_tree.column('State', width=100)
        self.changes_tree.column('Short Description', width=400)
        
        # Scrollbar
        changes_scroll = ttk.Scrollbar(inner, orient=tk.VERTICAL, command=self.changes_tree.yview)
        self.changes_tree.configure(yscrollcommand=changes_scroll.set)
        
        self.changes_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        add_treeview_menu(self.changes_tree)
        changes_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    
    def _check_session(self):
        """Check if ServiceNow session is valid using cookie expiry, then a page probe."""
        def check():
            try:
                self.sn = ServiceNowSession()
                # Primary check: are non-expired cookies loaded?
                if not self.sn.session.cookies:
                    self.after(0, lambda: self.connection_label.config(
                        text="[X] Not authenticated - Login required", fg=ERROR))
                    self.after(0, lambda: self.status_var.set("Login required"))
                    return

                # Secondary check: probe main page (not API) to confirm session is live
                probe_url = f"{self.sn.instance_url}/nav_to.do"
                r = self.sn.session.get(probe_url, timeout=15, allow_redirects=True)
                # If we land on a login page we're not authenticated
                if r.status_code == 200 and 'login' not in r.url.lower():
                    self.after(0, lambda: self.connection_label.config(
                        text="[OK] Connected to ServiceNow", fg=SUCCESS))
                    self.after(0, lambda: self.status_var.set("Connected"))
                    self.after(0, self._load_data)
                else:
                    self.after(0, lambda: self.connection_label.config(
                        text="[X] Session expired - Login required", fg=ERROR))
                    self.after(0, lambda: self.status_var.set("Login required"))
            except Exception as e:
                print(f"[DEBUG] Session check error: {e}")
                self.after(0, lambda: self.connection_label.config(
                    text=f"❌ Error: {str(e)[:50]}", fg=ERROR))
                self.after(0, lambda: self.status_var.set("Connection error"))

        threading.Thread(target=check, daemon=True).start()
    
    def _start_auto_login(self):
        """Launch ServiceNow MFA login via host daemon with streaming progress."""
        self.login_btn.config(state=tk.DISABLED, text=" Logging in...")
        self.status_var.set("Contacting host daemon...")
        self._show_login_progress_window()

    def _show_login_progress_window(self):
        """Show streaming progress window and kick off login thread."""
        win = tk.Toplevel(self)
        win.title("ServiceNow Login")
        win.configure(bg='#1e1e1e')
        win.geometry("680x420")
        win.resizable(True, True)

        tk.Label(win, text="  ServiceNow MFA Login",
                 font=('Segoe UI', 13, 'bold'), fg='#4ec9b0', bg='#1e1e1e'
                 ).pack(pady=(14, 4))
        tk.Label(win,
                 text="Chrome will open on your host. Complete login + MFA, then wait for the homepage.\nThis window shows live progress.",
                 font=('Segoe UI', 9), fg='#888', bg='#1e1e1e', justify='center'
                 ).pack(pady=(0, 8))

        log_frame = tk.Frame(win, bg='#1e1e1e')
        log_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 8))
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        log_text = tk.Text(log_frame, bg='#0d0d0d', fg='#c8c8c8',
                           font=('Consolas', 9), relief=tk.FLAT,
                           yscrollcommand=scrollbar.set, state=tk.DISABLED)
        log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        make_text_copyable(log_text)
        scrollbar.config(command=log_text.yview)

        status_var = tk.StringVar(value="Starting...")
        tk.Label(win, textvariable=status_var, font=('Segoe UI', 9),
                 fg='#888', bg='#1e1e1e').pack(pady=(0, 6))

        close_btn = tk.Button(win, text="Close", state=tk.DISABLED,
                              command=win.destroy,
                              bg='#2d2d2d', fg='#e0e0e0', font=('Segoe UI', 9),
                              relief=tk.FLAT, padx=16, pady=4)
        close_btn.pack(pady=(0, 12))

        def append_log(msg, color='#c8c8c8'):
            log_text.config(state=tk.NORMAL)
            log_text.insert(tk.END, msg + '\n')
            log_text.tag_add(f'c{hash(color)}', f'end-{len(msg)+2}c', 'end-1c')
            log_text.tag_config(f'c{hash(color)}', foreground=color)
            log_text.see(tk.END)
            log_text.config(state=tk.DISABLED)

        def login_thread():
            try:
                from auger.tools.host_cmd import servicenow_login_stream
                for event in servicenow_login_stream():
                    evt_type = event.get('type', 'progress')
                    msg = event.get('message', '')
                    if evt_type == 'progress':
                        self.after(0, lambda m=msg: append_log(m))
                        self.after(0, lambda m=msg: status_var.set(m[:80]))
                    elif evt_type == 'done':
                        self.after(0, lambda m=msg: append_log(f'\n{m}', '#4ec9b0'))
                        self.after(0, lambda: status_var.set('✅ Login complete'))
                        self.after(0, lambda: close_btn.config(state=tk.NORMAL))
                        self.after(0, self._check_session)
                    elif evt_type == 'error':
                        self.after(0, lambda m=msg: append_log(f'\n❌ {m}', '#f44747'))
                        self.after(0, lambda m=msg: status_var.set(f'❌ {m[:60]}'))
                        self.after(0, lambda: close_btn.config(state=tk.NORMAL))
            except Exception as e:
                self.after(0, lambda: append_log(f'\n❌ {e}', '#f44747'))
                self.after(0, lambda: close_btn.config(state=tk.NORMAL))
            finally:
                self.after(0, lambda: self.login_btn.config(
                    state=tk.NORMAL, text=" Login with MFA"))
                self.after(0, lambda: self.status_var.set("Ready"))

        threading.Thread(target=login_thread, daemon=True).start()
    
    def _load_data(self):
        """Load ServiceNow data using web scraping"""
        self.status_var.set("Loading incidents and changes...")
        
        def load():
            try:
                # Load incidents via scraping (API doesn't work with cookies)
                print("[DEBUG] Scraping incidents...")
                incidents = self.sn.scrape_incidents(limit=20)
                self.after(0, lambda: self._populate_incidents(incidents))
                
                # Load changes via scraping
                print("[DEBUG] Scraping changes...")
                changes = self.sn.scrape_changes(limit=20)
                self.after(0, lambda: self._populate_changes(changes))
                
                self.after(0, lambda: self.status_var.set(
                    f"Loaded {len(incidents)} incidents, {len(changes)} changes"
                ))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "Load Error",
                    f"Failed to load data:\n{str(e)}"
                ))
                self.after(0, lambda: self.status_var.set("Load failed"))
        
        thread = threading.Thread(target=load, daemon=True)
        thread.start()
    
    def _populate_incidents(self, incidents):
        """Populate incidents treeview"""
        # Clear existing
        for item in self.incidents_tree.get_children():
            self.incidents_tree.delete(item)
        
        # Priority mapping
        priority_map = {'1': 'Critical', '2': 'High', '3': 'Moderate', '4': 'Low', '5': 'Planning'}
        
        # State mapping (simplified)
        state_map = {
            '1': 'New', '2': 'In Progress', '3': 'On Hold',
            '6': 'Resolved', '7': 'Closed', '8': 'Canceled'
        }
        
        # Add incidents
        for inc in incidents:
            number = inc.get('number', 'N/A')
            priority = priority_map.get(inc.get('priority', ''), inc.get('priority', 'N/A'))
            state = state_map.get(inc.get('state', ''), inc.get('state', 'N/A'))
            desc = inc.get('short_description', 'No description')[:80]
            
            self.incidents_tree.insert('', tk.END, values=(number, priority, state, desc))
    
    def _populate_changes(self, changes):
        """Populate changes treeview"""
        # Clear existing
        for item in self.changes_tree.get_children():
            self.changes_tree.delete(item)
        
        # Type mapping
        type_map = {'standard': 'Standard', 'normal': 'Normal', 'emergency': 'Emergency'}
        
        # State mapping
        state_map = {
            '-5': 'New', '-4': 'Assess', '-3': 'Authorize', '-2': 'Scheduled',
            '-1': 'Implement', '0': 'Review', '3': 'Closed', '4': 'Canceled'
        }
        
        # Add changes
        for chg in changes:
            number = chg.get('number', 'N/A')
            chg_type = type_map.get(chg.get('type', ''), chg.get('type', 'N/A'))
            state = state_map.get(chg.get('state', ''), chg.get('state', 'N/A'))
            desc = chg.get('short_description', 'No description')[:80]
            
            self.changes_tree.insert('', tk.END, values=(number, chg_type, state, desc))
    
    def _refresh_data(self):
        """Refresh all data"""
        if self.sn:
            self._load_data()
        else:
            messagebox.showwarning(
                "Not Connected",
                "Please login first before refreshing."
            )
