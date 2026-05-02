"""
Pods Widget - Kubernetes Pod Status Monitor for Auger
Quick view of pod statuses across clusters and namespaces
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import json
import os
from pathlib import Path
from dotenv import load_dotenv
import threading
import urllib.parse
import re
from auger.ui import icons as _icons
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu
import requests
from datetime import datetime, timezone

# Color scheme (matching Auger theme)
BG = '#1e1e1e'
BG2 = '#252526'
BG3 = '#2d2d2d'
FG = '#e0e0e0'
ACCENT = '#007acc'
ACCENT2 = '#4ec9b0'
ERROR = '#f44747'
WARNING = '#ce9178'
SUCCESS = '#4ec9b0'



class PodsWidget(tk.Frame):
    """Kubernetes pod status monitor widget"""
    
    # Widget metadata
    WIDGET_NAME = "pods"
    WIDGET_TITLE = "Pods"
    WIDGET_ICON = "🎯"
    WIDGET_ICON_NAME = "pods"
    
    def __init__(self, parent, context_builder_callback=None, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        
        self.context_builder_callback = context_builder_callback
        self.pod_data = []
        
        # Get widget directory for resources
        self.widget_dir = Path(__file__).parent
        self.resources_dir = self.widget_dir / "panner_resources"  # Reuse Panner resources
        
        # Load environment for credentials
        load_dotenv(Path.home() / '.auger' / '.env')
        
        # Load options from resource files
        self.cluster_options = self._load_options("ddog_assist_clusters")
        self.namespace_options = self._load_options("ddog_assist_namespaces")
        self.service_options = self._load_options("ddog_assist_services")
        self.dockerfile_service_options = self._load_options("ddog_dockerfile_services")
        self.all_service_options = self.service_options + self.dockerfile_service_options
        
        self._create_ui()

    def _load_options(self, filename):
        """Load options from resource file"""
        filepath = self.resources_dir / filename
        try:
            with open(filepath, "r") as f:
                return [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            print(f"Resource file not found: {filepath}")
            return []
    
    def _create_ui(self):
        """Create the widget UI"""
        self._icons = {}
        for name in ('delete', 'refresh', 'download', 'search', 'play'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass

        # Main container
        main_frame = tk.Frame(self, bg=BG)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Top: Filters
        self._create_filter_section(main_frame)
        
        # Buttons
        self._create_button_section(main_frame)
        
        # Pods table
        self._create_pods_table(main_frame)
        
        # Status bar
        self._create_status_bar(main_frame)
    
    def _create_filter_section(self, parent):
        """Create filter section"""
        filter_frame = tk.Frame(parent, bg=BG2)
        filter_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Header
        tk.Label(
            filter_frame, text="Pod Filters", font=('Segoe UI', 11, 'bold'),
            fg=ACCENT2, bg=BG2
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=5, pady=(5, 10))
        
        # Cluster listbox
        tk.Label(
            filter_frame, text="Cluster:", font=('Segoe UI', 10, 'bold'),
            fg=FG, bg=BG2
        ).grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        
        cluster_scroll = tk.Frame(filter_frame, bg=BG2)
        cluster_scroll.grid(row=2, column=0, sticky=tk.NSEW, padx=5, pady=2)
        
        cluster_vsb = tk.Scrollbar(cluster_scroll, orient=tk.VERTICAL)
        cluster_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.cluster_listbox = tk.Listbox(
            cluster_scroll, selectmode=tk.MULTIPLE, height=8, exportselection=False,
            bg=BG3, fg=FG, font=('Segoe UI', 9), yscrollcommand=cluster_vsb.set
        )
        for option in self.cluster_options:
            self.cluster_listbox.insert(tk.END, option)
        self.cluster_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cluster_vsb.config(command=self.cluster_listbox.yview)
        add_listbox_menu(self.cluster_listbox)
        
        # Namespace listbox
        tk.Label(
            filter_frame, text="Namespace:", font=('Segoe UI', 10, 'bold'),
            fg=FG, bg=BG2
        ).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        namespace_scroll = tk.Frame(filter_frame, bg=BG2)
        namespace_scroll.grid(row=2, column=1, sticky=tk.NSEW, padx=5, pady=2)
        
        namespace_vsb = tk.Scrollbar(namespace_scroll, orient=tk.VERTICAL)
        namespace_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.namespace_listbox = tk.Listbox(
            namespace_scroll, selectmode=tk.MULTIPLE, height=8, exportselection=False,
            bg=BG3, fg=FG, font=('Segoe UI', 9), yscrollcommand=namespace_vsb.set
        )
        for option in self.namespace_options:
            self.namespace_listbox.insert(tk.END, option)
        self.namespace_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        namespace_vsb.config(command=self.namespace_listbox.yview)
        add_listbox_menu(self.namespace_listbox)
        
        # Service listbox (optional)
        tk.Label(
            filter_frame, text="Service (optional):", font=('Segoe UI', 10, 'bold'),
            fg=FG, bg=BG2
        ).grid(row=1, column=2, sticky=tk.W, padx=5, pady=2)
        
        service_scroll = tk.Frame(filter_frame, bg=BG2)
        service_scroll.grid(row=2, column=2, sticky=tk.NSEW, padx=5, pady=2)
        
        service_vsb = tk.Scrollbar(service_scroll, orient=tk.VERTICAL)
        service_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.service_listbox = tk.Listbox(
            service_scroll, selectmode=tk.MULTIPLE, height=8, exportselection=False,
            bg=BG3, fg=FG, font=('Segoe UI', 9), yscrollcommand=service_vsb.set
        )
        for option in self.all_service_options:
            self.service_listbox.insert(tk.END, option)
        self.service_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        service_vsb.config(command=self.service_listbox.yview)
        add_listbox_menu(self.service_listbox)
        
        # Configure column weights
        filter_frame.columnconfigure(0, weight=1)
        filter_frame.columnconfigure(1, weight=1)
        filter_frame.columnconfigure(2, weight=1)
        filter_frame.rowconfigure(2, weight=1)
    
    def _create_button_section(self, parent):
        """Create action buttons"""
        button_frame = tk.Frame(parent, bg=BG2)
        button_frame.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Button(
            button_frame, text=" Check Pods (DataDog API)",
            image=self._icons.get('search'), compound=tk.LEFT,
            command=self.check_pods_datadog,
            bg=ACCENT, fg='white', font=('Segoe UI', 10, 'bold'),
            relief=tk.FLAT, padx=20, pady=8
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            button_frame, text=" Open in DataDog",
            image=self._icons.get('play'), compound=tk.LEFT,
            command=self._open_in_datadog,
            bg=ACCENT2, fg='black', font=('Segoe UI', 10, 'bold'),
            relief=tk.FLAT, padx=20, pady=8
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            button_frame, text=" Clear",
            image=self._icons.get('delete'), compound=tk.LEFT,
            command=self._clear_results,
            bg=BG3, fg=FG, font=('Segoe UI', 10),
            relief=tk.FLAT, padx=20, pady=8
        ).pack(side=tk.LEFT, padx=5)
    
    def _create_pods_table(self, parent):
        """Create pods status table"""
        table_frame = tk.Frame(parent, bg=BG2)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        tk.Label(
            table_frame, text="Pod Status", font=('Segoe UI', 11, 'bold'),
            fg=FG, bg=BG2
        ).pack(fill=tk.X, padx=5, pady=(5, 2))
        
        # Scrollbars
        scroll_frame = tk.Frame(table_frame, bg=BG2)
        scroll_frame.pack(fill=tk.BOTH, expand=True)
        
        v_scroll = tk.Scrollbar(scroll_frame, orient=tk.VERTICAL)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        h_scroll = tk.Scrollbar(scroll_frame, orient=tk.HORIZONTAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Treeview
        self.table = ttk.Treeview(
            scroll_frame,
            columns=("cluster", "namespace", "pod_name", "status", "ready", "restarts", "age", "node"),
            show="headings",
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set
        )
        
        # Configure columns
        self.table.heading("cluster", text="Cluster")
        self.table.heading("namespace", text="Namespace")
        self.table.heading("pod_name", text="Pod Name")
        self.table.heading("status", text="Status")
        self.table.heading("ready", text="Ready")
        self.table.heading("restarts", text="Restarts")
        self.table.heading("age", text="Age")
        self.table.heading("node", text="Node")
        
        self.table.column("cluster", width=150)
        self.table.column("namespace", width=150)
        self.table.column("pod_name", width=300)
        self.table.column("status", width=100)
        self.table.column("ready", width=80)
        self.table.column("restarts", width=80)
        self.table.column("age", width=100)
        self.table.column("node", width=200)
        
        self.table.pack(fill=tk.BOTH, expand=True)
        add_treeview_menu(self.table)
        
        v_scroll.config(command=self.table.yview)
        h_scroll.config(command=self.table.xview)
        
        # Style
        style = ttk.Style()
        style.configure("Treeview", background=BG3, foreground=FG, fieldbackground=BG3, rowheight=25)
        style.configure("Treeview.Heading", background=BG2, foreground=FG)
        style.map("Treeview", background=[('selected', ACCENT)])
        
        # Configure status tags
        self.table.tag_configure('running', background='#1a4d2e')
        self.table.tag_configure('pending', background='#4a4a00')
        self.table.tag_configure('error', background=ERROR)
        self.table.tag_configure('crashloop', background='#8b0000')
    
    def _create_status_bar(self, parent):
        """Create status bar"""
        status_frame = tk.Frame(parent, bg=BG2)
        status_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.status_var = tk.StringVar(value="Select cluster and namespace, then click 'Check Pods'")
        tk.Label(
            status_frame, textvariable=self.status_var, font=('Segoe UI', 9),
            fg=FG, bg=BG2, anchor=tk.W
        ).pack(side=tk.LEFT, padx=5, pady=3)
        
        self.count_var = tk.StringVar(value="")
        tk.Label(
            status_frame, textvariable=self.count_var, font=('Segoe UI', 9),
            fg=ACCENT, bg=BG2, anchor=tk.E
        ).pack(side=tk.RIGHT, padx=5, pady=3)
    
    def _clear_results(self):
        """Clear pods table"""
        for item in self.table.get_children():
            self.table.delete(item)
        self.pod_data = []
        self.count_var.set("")
        self.status_var.set("Results cleared")
    
    def _open_in_datadog(self):
        """Open DataDog pods view in browser"""
        # Get selected values
        selected_clusters = [self.cluster_options[i] for i in self.cluster_listbox.curselection()]
        selected_namespaces = [self.namespace_options[i] for i in self.namespace_listbox.curselection()]
        selected_services = [self.all_service_options[i] for i in self.service_listbox.curselection()]
        
        if not selected_clusters or not selected_namespaces:
            messagebox.showwarning("Missing Selection", "Please select at least one Cluster and Namespace")
            return
        
        url = self._build_datadog_url(selected_clusters, selected_namespaces, selected_services)
        
        try:
            from auger.tools.host_cmd import open_url as host_open_url
            host_open_url(url)
            self.status_var.set("✓ Opened DataDog Pods view in browser")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open URL:\n{str(e)}")
    
    def _build_datadog_url(self, clusters, namespaces, services):
        """Build DataDog pods URL"""
        base_url = "https://fcs-mcaas-assist.ddog-gov.com/orchestration/explorer/pod"
        
        # Build query
        query_parts = []
        
        if clusters:
            if len(clusters) == 1:
                query_parts.append(f"kube_cluster_name:{clusters[0]}")
            else:
                query_parts.append(f"kube_cluster_name:({' OR '.join(clusters)})")
        
        if namespaces:
            if len(namespaces) == 1:
                query_parts.append(f"kube_namespace:{namespaces[0]}")
            else:
                query_parts.append(f"kube_namespace:({' OR '.join(namespaces)})")
        
        if services:
            if len(services) == 1:
                query_parts.append(f"kube_service:{services[0]}")
            else:
                query_parts.append(f"kube_service:({' OR '.join(services)})")
        
        query = " ".join(query_parts)
        
        # Build URL
        params = {
            "query": query,
            "live": "false"
        }
        
        url = base_url + "?" + urllib.parse.urlencode(params)
        return url
    
    def check_pods_datadog(self):
        """Check pod status using DataDog API"""
        # Check credentials
        dd_api_key = os.getenv('DATADOG_API_KEY')
        dd_app_key = os.getenv('DATADOG_APP_KEY')
        
        if not dd_api_key or not dd_app_key:
            messagebox.showerror(
                "Missing Credentials",
                "DataDog API Key or App Key not found in .env file.\n\n"
                "Please configure them in the API Config widget:\n"
                "- DATADOG_API_KEY\n"
                "- DATADOG_APP_KEY"
            )
            return
        
        # Get selected values
        selected_clusters = [self.cluster_options[i] for i in self.cluster_listbox.curselection()]
        selected_namespaces = [self.namespace_options[i] for i in self.namespace_listbox.curselection()]
        selected_services = [self.all_service_options[i] for i in self.service_listbox.curselection()]
        
        if not selected_clusters or not selected_namespaces:
            messagebox.showwarning("Missing Selection", "Please select at least one Cluster and Namespace")
            return
        
        self.status_var.set("Querying DataDog API for pods...")
        threading.Thread(
            target=self._check_pods_datadog_thread,
            args=(selected_clusters, selected_namespaces, selected_services),
            daemon=True
        ).start()
    
    def _check_pods_datadog_thread(self, clusters, namespaces, services):
        """Query DataDog API for pod information"""
        try:
            dd_api_key = os.getenv('DATADOG_API_KEY')
            dd_app_key = os.getenv('DATADOG_APP_KEY')
            dd_site = os.getenv('DATADOG_SITE', 'ddog-gov.com')
            
            # CRITICAL WORKAROUND: DataDog Containers API filtering is COMPLETELY BROKEN!
            # - When you filter by namespace, it returns DIFFERENT namespaces
            # - When you filter by cluster, it returns DIFFERENT clusters
            # Solution: Query with NO filters, get ALL containers, filter client-side
            
            print(f"[DEBUG] Querying with NO filters (API filtering is broken)")
            print(f"[DEBUG] Will filter CLIENT-SIDE for: clusters={clusters}, namespaces={namespaces}, services={services}")
            
            # Show in status bar
            self.after(0, lambda: self.status_var.set(f"Querying all containers (API filtering broken)..."))
            
            # Query DataDog containers API with NO filter
            url = f"https://api.{dd_site}/api/v2/containers"
            
            headers = {
                'DD-API-KEY': dd_api_key,
                'DD-APPLICATION-KEY': dd_app_key,
                'Content-Type': 'application/json'
            }
            
            # No filter query - get everything, filter client-side
            params = {
                'page[limit]': 1000  # Get up to 1000 containers
            }
            
            print(f"[DEBUG] ACTUAL URL: {url}")
            print(f"[DEBUG] ACTUAL PARAMS: {params}")
            print(f"[DEBUG] Has API keys: DD-API-KEY={bool(dd_api_key)}, DD-APP-KEY={bool(dd_app_key)}")
            
            # Fetch ALL containers using pagination
            all_containers = []
            page_cursor = None
            page_num = 0
            
            while True:
                page_num += 1
                if page_cursor:
                    params['page[cursor]'] = page_cursor
                
                self.after(0, lambda p=page_num: self.status_var.set(f"Fetching page {p}..."))
                
                response = requests.get(url, headers=headers, params=params, timeout=30)
                
                if response.status_code != 200:
                    self.after(0, lambda: self.status_var.set(f"✗ DataDog API error: {response.status_code}"))
                    self.after(0, lambda: messagebox.showerror(
                        "API Error",
                        f"DataDog API returned {response.status_code}:\n{response.text}"
                    ))
                    return
                
                data = response.json()
                page_containers = data.get('data', [])
                all_containers.extend(page_containers)
                
                print(f"[DEBUG] Page {page_num}: {len(page_containers)} containers (total: {len(all_containers)})")
                
                # Check if there's more data
                meta = data.get('meta', {})
                pagination = meta.get('pagination', {})
                next_cursor = pagination.get('next_cursor')
                
                if not next_cursor or len(page_containers) == 0:
                    break  # No more pages
                
                page_cursor = next_cursor
                
                # Safety limit - don't fetch more than 10 pages (10,000 containers)
                if page_num >= 10:
                    print(f"[DEBUG] Reached page limit, stopping pagination")
                    break
            
            containers = all_containers
            print(f"[DEBUG] Total containers fetched: {len(containers)} across {page_num} pages")
            
            # Check what clusters are actually in the response
            unique_clusters = set()
            unique_namespaces = set()
            for c in containers:  # Check ALL containers, not just first 50
                tags = c.get('attributes', {}).get('tags', [])
                for tag in tags:
                    if tag.startswith('kube_cluster_name:'):
                        unique_clusters.add(tag.split(':', 1)[1])
                    elif tag.startswith('kube_namespace:'):
                        unique_namespaces.add(tag.split(':', 1)[1])
            
            print(f"[DEBUG] Clusters in response (ALL {len(containers)}): {unique_clusters}")
            print(f"[DEBUG] Namespaces in response (ALL {len(containers)}): {unique_namespaces}")
            
            # Save debug info to file (keep for troubleshooting)
            debug_msg = f"Query: NO FILTER (API filtering is broken!)\n\n"
            debug_msg += f"API returned: {len(containers)} containers\n"
            debug_msg += f"Clusters in response: {unique_clusters}\n"
            debug_msg += f"Namespaces in response: {unique_namespaces}\n"
            debug_msg += f"\nYou selected:\nClusters: {clusters}\nNamespaces: {namespaces}\n"
            debug_msg += f"Services: {services}"
            
            # Write debug info to writable location (widget dir is read-only in container)
            debug_file = Path.home() / '.auger' / 'pods_debug.txt'
            debug_file.parent.mkdir(parents=True, exist_ok=True)
            with open(debug_file, 'w') as f:
                f.write(debug_msg)
            
            # Parse containers into pod information
            pods_dict = {}
            filtered_out = []
            
            for container in containers:
                attributes = container.get('attributes', {})
                tags = attributes.get('tags', [])
                
                # Extract info from tags - ONLY trust what's in the tags
                pod_name = None
                cluster = None
                namespace = None
                node = None
                container_name = attributes.get('container_name', '')
                
                for tag in tags:
                    if tag.startswith('pod_name:'):
                        pod_name = tag.split(':', 1)[1]
                    elif tag.startswith('kube_cluster_name:'):
                        cluster = tag.split(':', 1)[1]
                    elif tag.startswith('kube_namespace:'):
                        namespace = tag.split(':', 1)[1]
                    elif tag.startswith('host:'):
                        node = tag.split(':', 1)[1]
                
                # Try to extract pod name from container_name if missing
                if not pod_name and container_name:
                    pod_name = container_name
                
                # MUST have all required tags - don't assume!
                if not pod_name:
                    continue
                if not cluster:
                    continue
                if not namespace:
                    continue
                
                # Client-side filtering
                # If selections made, MUST match them
                if clusters and cluster not in clusters:
                    filtered_out.append(f"{cluster}/{namespace}/{pod_name} (wrong cluster)")
                    continue
                
                if namespaces and namespace not in namespaces:
                    filtered_out.append(f"{cluster}/{namespace}/{pod_name} (wrong namespace)")
                    continue
                
                # DON'T filter by service here - only if explicitly selected
                # This was causing pods without service tags to be filtered out
                if services:
                    # Check if pod belongs to selected service
                    service_tag = None
                    for tag in tags:
                        if tag.startswith('kube_service:') or tag.startswith('service:'):
                            service_tag = tag.split(':', 1)[1]
                            break
                    
                    if service_tag and service_tag not in services:
                        filtered_out.append(f"{namespace}/{pod_name} (service mismatch)")
                        continue  # Skip pods not matching selected services
                
                # Group by pod (multiple containers per pod)
                pod_key = f"{cluster}/{namespace}/{pod_name}"
                
                if pod_key not in pods_dict:
                    pods_dict[pod_key] = {
                        'cluster': cluster,
                        'namespace': namespace,
                        'pod_name': pod_name,
                        'node': node or 'Unknown',
                        'containers': [],
                        'created_at': attributes.get('created_at')
                    }
                
                # Add container info
                container_info = {
                    'name': attributes.get('container_name', 'unknown'),
                    'state': attributes.get('state', 'unknown'),
                    'restart_count': attributes.get('restart_count', 0)
                }
                pods_dict[pod_key]['containers'].append(container_info)
            
            print(f"[DEBUG] Found {len(pods_dict)} unique pods")
            if filtered_out:
                print(f"[DEBUG] Filtered out: {filtered_out[:10]}")  # Show first 10
            
            # Convert to pod list
            all_pods = []
            for pod_data in pods_dict.values():
                pod_info = self._parse_datadog_pod_info(pod_data)
                all_pods.append(pod_info)
            
            # Update UI
            self.after(0, lambda: self._display_pods(all_pods))
            self.after(0, lambda: self.status_var.set(f"✓ Found {len(all_pods)} pods"))
            self.after(0, lambda: self.count_var.set(f"{len(all_pods)} pods"))
        
        except requests.exceptions.Timeout:
            self.after(0, lambda: self.status_var.set("✗ DataDog API timeout"))
            self.after(0, lambda: messagebox.showerror("Timeout", "DataDog API request timed out"))
        except Exception as e:
            import traceback
            print(f"[ERROR] {traceback.format_exc()}")
            self.after(0, lambda: self.status_var.set(f"✗ Error: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("Error", f"Failed to query DataDog:\n{str(e)}"))
    
    def _parse_datadog_pod_info(self, pod_data):
        """Parse pod information from DataDog container data"""
        cluster = pod_data['cluster']
        namespace = pod_data['namespace']
        pod_name = pod_data['pod_name']
        node = pod_data['node']
        
        containers = pod_data['containers']
        
        # Calculate ready containers
        running_count = sum(1 for c in containers if c['state'] == 'running')
        total_count = len(containers)
        ready = f"{running_count}/{total_count}"
        
        # Calculate restarts
        restarts = sum(c['restart_count'] for c in containers)
        
        # Determine overall status
        if all(c['state'] == 'running' for c in containers):
            status = 'Running'
            tag = 'running'
        elif any(c['state'] == 'waiting' for c in containers):
            status = 'Pending'
            tag = 'pending'
        elif any(c['state'] == 'terminated' for c in containers):
            status = 'Failed'
            tag = 'error'
        else:
            status = 'Unknown'
            tag = ''
        
        # Check for crashloop (high restart count)
        if restarts > 5:
            status = 'CrashLoopBackOff'
            tag = 'crashloop'
        
        # Calculate age
        age = self._calculate_age(pod_data['created_at'])
        
        return {
            'cluster': cluster,
            'namespace': namespace,
            'pod_name': pod_name,
            'status': status,
            'ready': ready,
            'restarts': str(restarts),
            'age': age,
            'node': node,
            'tag': tag
        }
    
    def _calculate_age(self, created_at):
        """Calculate age from timestamp"""
        if not created_at:
            return 'Unknown'
        
        try:
            # Parse ISO timestamp
            if isinstance(created_at, str):
                created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            else:
                created = datetime.fromtimestamp(created_at, tz=timezone.utc)
            
            now = datetime.now(timezone.utc)
            delta = now - created
            
            days = delta.days
            hours = delta.seconds // 3600
            minutes = (delta.seconds % 3600) // 60
            
            if days > 0:
                return f"{days}d{hours}h"
            elif hours > 0:
                return f"{hours}h{minutes}m"
            else:
                return f"{minutes}m"
        except:
            return 'Unknown'
    
    def _display_pods(self, pods):
        """Display pods in table"""
        # Clear existing
        for item in self.table.get_children():
            self.table.delete(item)
        
        # Store data
        self.pod_data = pods
        
        # Sort by cluster, namespace, pod name
        pods.sort(key=lambda p: (p['cluster'], p['namespace'], p['pod_name']))
        
        # Populate
        for pod in pods:
            values = (
                pod['cluster'],
                pod['namespace'],
                pod['pod_name'],
                pod['status'],
                pod['ready'],
                pod['restarts'],
                pod['age'],
                pod['node']
            )
            
            tag = (pod['tag'],) if pod['tag'] else ()
            self.table.insert("", tk.END, values=values, tags=tag)
    
    def build_context(self):
        """Build context for Ask Auger panel"""
        context = "PODS WIDGET CONTEXT\n\n"
        
        if self.pod_data:
            context += f"Pod Status: {len(self.pod_data)} pods loaded\n\n"
            
            # Count by status
            status_counts = {}
            for pod in self.pod_data:
                status = pod['status']
                status_counts[status] = status_counts.get(status, 0) + 1
            
            context += "Status Summary:\n"
            for status, count in status_counts.items():
                context += f"  {status}: {count}\n"
            
            context += "\n"
            
            # Show problem pods
            problem_pods = [p for p in self.pod_data if p['tag'] in ['error', 'crashloop', 'pending']]
            if problem_pods:
                context += f"Problem Pods ({len(problem_pods)}):\n"
                for pod in problem_pods[:5]:
                    context += f"  {pod['namespace']}/{pod['pod_name']} - {pod['status']}\n"
        else:
            context += "No pods loaded yet\n"
        
        return context


# Widget registration
def create_widget(parent, context_builder_callback=None):
    """Factory function for widget creation"""
    return PodsWidget(parent, context_builder_callback)
