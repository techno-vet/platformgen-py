"""
K8s Explorer Widget

PlatformGen-adapted version of Trader's kubectl-first K8s explorer.
Uses kubeconfig/kubectl as the default source of truth so it works even
when Rancher is not configured in the local environment.
"""

import os
import pty
import re
import select
import subprocess
import threading
import tkinter as tk
from tkinter import ttk
from typing import Optional

from auger.ui.utils import make_text_copyable


BG = "#1e1e1e"
BG2 = "#252526"
BG3 = "#2d2d2d"
FG = "#e0e0e0"
FG2 = "#888888"
ACCENT = "#007acc"
ACCENT2 = "#4ec9b0"
SUCCESS = "#4ec9b0"
ERROR = "#f44747"
WARNING = "#f0c040"
FONT = ("Segoe UI", 10)
MONO = ("Courier New", 10)

RESOURCE_TYPES = [
    ("Pods", "pods"),
    ("Deployments", "deployments"),
    ("StatefulSets", "statefulsets"),
    ("DaemonSets", "daemonsets"),
    ("ReplicaSets", "replicasets"),
    ("Jobs", "jobs"),
    ("CronJobs", "cronjobs"),
    ("Services", "services"),
    ("Ingresses", "ingresses"),
    ("ConfigMaps", "configmaps"),
    ("Secrets", "secrets"),
    ("PVCs", "persistentvolumeclaims"),
    ("Nodes", "nodes"),
    ("Namespaces", "namespaces"),
]

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mKHABCDJrs]|\r")


def make_icon(size=18, color="#326ce5"):
    from PIL import Image, ImageDraw
    import math

    s2 = size * 2
    img = Image.new("RGBA", (s2, s2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = s2 // 2
    r_outer = s2 // 2 - 2
    r_inner = s2 // 5
    r_hub = s2 // 8
    spoke_w = max(2, s2 // 12)
    draw.ellipse(
        [cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer],
        outline=color,
        width=max(2, s2 // 14),
    )
    for i in range(7):
        angle = math.radians(i * 360 / 7 - 90)
        x1 = cx + r_inner * math.cos(angle)
        y1 = cy + r_inner * math.sin(angle)
        x2 = cx + r_outer * math.cos(angle)
        y2 = cy + r_outer * math.sin(angle)
        draw.line([(x1, y1), (x2, y2)], fill=color, width=spoke_w)
    draw.ellipse([cx - r_hub, cy - r_hub, cx + r_hub, cy + r_hub], fill=color)
    return img.resize((size, size), Image.LANCZOS)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _kubectl(*args, namespace: str | None = None, timeout: int = 12) -> tuple[str, str, int]:
    cmd = ["kubectl"]
    if namespace and namespace != "all":
        cmd += ["-n", namespace]
    elif namespace == "all":
        cmd += ["--all-namespaces"]
    cmd += list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", 1
    except Exception as e:
        return "", str(e), 1


class K8sExplorerWidget(tk.Frame):
    WIDGET_TITLE = "K8s Explorer"
    WIDGET_ICON_FUNC = staticmethod(make_icon)
    _REFRESH_MS = 15_000

    def __init__(self, parent, context_builder_callback=None, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self.context_builder_callback = context_builder_callback

        self._ns_var = tk.StringVar(value="all")
        self._resource_type = "pods"
        self._resource_label = "Pods"
        self._selected_ns: Optional[str] = None
        self._selected_name: Optional[str] = None

        self._resources: list[tuple[str, str]] = []
        self._refresh_job = None

        self._log_proc: Optional[subprocess.Popen] = None
        self._exec_proc = None
        self._exec_mfd = None
        self._exec_history: list[str] = []
        self._exec_hist_idx = 0

        self._build()
        self._load_namespaces()
        self._refresh_resources()
        self.bind("<Destroy>", self._on_destroy)

    def _build(self):
        pane = tk.PanedWindow(
            self,
            orient=tk.HORIZONTAL,
            bg="#3c3c3c",
            sashwidth=6,
            sashrelief=tk.FLAT,
            sashpad=0,
        )
        pane.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(pane, bg=BG2, width=260)
        left.pack_propagate(False)
        self._build_left(left)
        pane.add(left, minsize=180, stretch="never")

        right = tk.Frame(pane, bg=BG)
        self._build_right(right)
        pane.add(right, minsize=400, stretch="always")

        self.after(100, lambda: pane.sash_place(0, 260, 0))

    def _build_left(self, parent):
        ns_bar = tk.Frame(parent, bg=BG2)
        ns_bar.pack(fill=tk.X, padx=6, pady=(6, 2))
        tk.Label(ns_bar, text="NS:", bg=BG2, fg=FG2, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self._ns_menu = ttk.Combobox(
            ns_bar,
            textvariable=self._ns_var,
            state="readonly",
            width=20,
            font=("Segoe UI", 9),
        )
        self._ns_menu.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        self._ns_menu.bind("<<ComboboxSelected>>", lambda _: self._refresh_resources())
        tk.Button(
            ns_bar,
            text="↺",
            bg=BG2,
            fg=FG2,
            relief=tk.FLAT,
            font=("Segoe UI", 12),
            cursor="hand2",
            command=self._refresh_resources,
        ).pack(side=tk.RIGHT)

        rt_frame = tk.Frame(parent, bg=BG2)
        rt_frame.pack(fill=tk.X, padx=4, pady=2)
        self._rt_btns: dict[str, tk.Button] = {}
        for label, rtype in RESOURCE_TYPES:
            btn = tk.Button(
                rt_frame,
                text=label,
                bg=BG3,
                fg=FG2,
                relief=tk.FLAT,
                font=("Segoe UI", 8),
                pady=2,
                cursor="hand2",
                anchor="w",
                padx=8,
                command=lambda l=label, r=rtype: self._select_type(l, r),
            )
            btn.pack(fill=tk.X, pady=1)
            self._rt_btns[rtype] = btn
        self._highlight_type("pods")

        list_frame = tk.Frame(parent, bg=BG3)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))
        self._listbox = tk.Listbox(
            list_frame,
            bg=BG3,
            fg=FG,
            selectbackground=ACCENT,
            selectforeground="white",
            relief=tk.FLAT,
            font=MONO,
            activestyle="none",
            bd=0,
            highlightthickness=0,
        )
        scroll = ttk.Scrollbar(list_frame, command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._listbox.pack(fill=tk.BOTH, expand=True)
        self._listbox.bind("<<ListboxSelect>>", self._on_list_select)

        self._left_status = tk.Label(
            parent,
            text="",
            bg=BG2,
            fg=FG2,
            font=("Segoe UI", 8),
            anchor="w",
            padx=6,
        )
        self._left_status.pack(fill=tk.X, side=tk.BOTTOM)

    def _build_right(self, parent):
        self._header = tk.Label(
            parent,
            text="Select a resource ->",
            bg=BG2,
            fg=FG,
            font=("Segoe UI", 12, "bold"),
            anchor="w",
            padx=12,
            pady=6,
        )
        self._header.pack(fill=tk.X, side=tk.TOP)

        style = ttk.Style()
        style.configure("K8s.TNotebook", background=BG2, borderwidth=0)
        style.configure(
            "K8s.TNotebook.Tab",
            background=BG3,
            foreground=FG2,
            padding=[10, 4],
            font=("Segoe UI", 9),
        )
        style.map(
            "K8s.TNotebook.Tab",
            background=[("selected", BG)],
            foreground=[("selected", FG)],
        )

        self._nb = ttk.Notebook(parent, style="K8s.TNotebook")
        self._nb.pack(fill=tk.BOTH, expand=True)

        self._build_describe_tab()
        self._build_yaml_tab()
        self._build_logs_tab()
        self._build_exec_tab()
        self._build_events_tab()
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab_change)

    def _build_describe_tab(self):
        frame = tk.Frame(self._nb, bg=BG)
        self._describe_text = self._make_scrolled_text(frame)
        self._nb.add(frame, text="Describe")

    def _build_yaml_tab(self):
        frame = tk.Frame(self._nb, bg=BG)
        bar = tk.Frame(frame, bg=BG2)
        bar.pack(fill=tk.X, side=tk.TOP)
        tk.Button(
            bar,
            text="Copy",
            bg=BG2,
            fg=FG2,
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=6,
            cursor="hand2",
            command=self._copy_yaml,
        ).pack(side=tk.RIGHT, pady=3, padx=4)
        self._yaml_text = self._make_scrolled_text(frame)
        self._nb.add(frame, text="YAML")

    def _build_logs_tab(self):
        frame = tk.Frame(self._nb, bg=BG)
        bar = tk.Frame(frame, bg=BG2)
        bar.pack(fill=tk.X, side=tk.TOP)

        tk.Label(bar, text="Container:", bg=BG2, fg=FG2, font=("Segoe UI", 8)).pack(
            side=tk.LEFT, padx=(6, 2), pady=3
        )
        self._log_ctr_var = tk.StringVar()
        self._log_ctr_menu = ttk.Combobox(
            bar,
            textvariable=self._log_ctr_var,
            state="readonly",
            width=14,
            font=("Segoe UI", 9),
        )
        self._log_ctr_menu.pack(side=tk.LEFT, pady=3)
        self._log_ctr_menu.bind("<<ComboboxSelected>>", lambda _: self._start_log_stream())

        self._follow_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            bar,
            text="Follow",
            variable=self._follow_var,
            bg=BG2,
            fg=FG2,
            selectcolor=BG3,
            activebackground=BG2,
            font=("Segoe UI", 8),
            command=self._start_log_stream,
        ).pack(side=tk.LEFT, padx=4)

        self._prev_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            bar,
            text="Previous",
            variable=self._prev_var,
            bg=BG2,
            fg=FG2,
            selectcolor=BG3,
            activebackground=BG2,
            font=("Segoe UI", 8),
            command=self._start_log_stream,
        ).pack(side=tk.LEFT, padx=2)

        tk.Label(bar, text="Tail:", bg=BG2, fg=FG2, font=("Segoe UI", 8)).pack(
            side=tk.LEFT, padx=(8, 2)
        )
        self._tail_var = tk.StringVar(value="300")
        tk.Entry(
            bar,
            textvariable=self._tail_var,
            bg=BG3,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            width=5,
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT)

        tk.Button(
            bar,
            text="Stream",
            bg=ACCENT,
            fg="white",
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=8,
            cursor="hand2",
            command=self._start_log_stream,
        ).pack(side=tk.LEFT, padx=(8, 2))
        tk.Button(
            bar,
            text="Stop",
            bg=BG2,
            fg=FG2,
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=6,
            cursor="hand2",
            command=self._stop_log_stream,
        ).pack(side=tk.LEFT, padx=2)

        tk.Label(bar, text="Find:", bg=BG2, fg=FG2, font=("Segoe UI", 8)).pack(
            side=tk.LEFT, padx=(10, 2)
        )
        self._log_search_var = tk.StringVar()
        entry = tk.Entry(
            bar,
            textvariable=self._log_search_var,
            bg=BG3,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            width=14,
            font=("Segoe UI", 8),
        )
        entry.pack(side=tk.LEFT)
        entry.bind("<Return>", lambda _: self._highlight_log_search())
        tk.Button(
            bar,
            text="Go",
            bg=BG2,
            fg=FG2,
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=6,
            cursor="hand2",
            command=self._highlight_log_search,
        ).pack(side=tk.LEFT, padx=2)

        self._log_status = tk.Label(bar, text="", bg=BG2, fg=FG2, font=("Segoe UI", 8))
        self._log_status.pack(side=tk.RIGHT, padx=6)

        self._log_text = self._make_scrolled_text(frame, font=MONO)
        self._log_text.tag_configure("error", foreground=ERROR)
        self._log_text.tag_configure("match", background="#3a3d41", foreground=WARNING)
        self._nb.add(frame, text="Logs")

    def _build_exec_tab(self):
        frame = tk.Frame(self._nb, bg=BG)
        bar = tk.Frame(frame, bg=BG2)
        bar.pack(fill=tk.X, side=tk.TOP)

        tk.Label(bar, text="Container:", bg=BG2, fg=FG2, font=("Segoe UI", 8)).pack(
            side=tk.LEFT, padx=(6, 2), pady=3
        )
        self._exec_ctr_var = tk.StringVar()
        self._exec_ctr_menu = ttk.Combobox(
            bar,
            textvariable=self._exec_ctr_var,
            state="readonly",
            width=14,
            font=("Segoe UI", 9),
        )
        self._exec_ctr_menu.pack(side=tk.LEFT, pady=3)

        tk.Label(bar, text="Shell:", bg=BG2, fg=FG2, font=("Segoe UI", 8)).pack(
            side=tk.LEFT, padx=(10, 2)
        )
        self._shell_var = tk.StringVar(value="/bin/sh")
        ttk.Combobox(
            bar,
            textvariable=self._shell_var,
            values=["/bin/sh", "/bin/bash", "/bin/ash"],
            state="readonly",
            width=10,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, pady=3)

        tk.Button(
            bar,
            text="Connect",
            bg=ACCENT,
            fg="white",
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=8,
            cursor="hand2",
            command=self._start_exec,
        ).pack(side=tk.LEFT, padx=(10, 2))
        tk.Button(
            bar,
            text="Stop",
            bg=BG2,
            fg=FG2,
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=6,
            cursor="hand2",
            command=self._stop_exec,
        ).pack(side=tk.LEFT, padx=2)

        self._exec_status = tk.Label(bar, text="", bg=BG2, fg=FG2, font=("Segoe UI", 8))
        self._exec_status.pack(side=tk.RIGHT, padx=6)

        self._exec_text = self._make_scrolled_text(frame, font=MONO)
        self._exec_text.tag_configure("error", foreground=ERROR)
        self._exec_text.tag_configure("info", foreground=ACCENT2)

        input_bar = tk.Frame(frame, bg=BG2)
        input_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self._exec_input = tk.Entry(
            input_bar,
            bg=BG3,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            font=("Courier New", 10),
            bd=4,
        )
        self._exec_input.pack(fill=tk.X, expand=True, pady=4, padx=(0, 6))
        self._exec_input.bind("<Return>", self._send_exec_input)
        self._exec_input.bind("<Up>", self._exec_hist_up)
        self._exec_input.bind("<Down>", self._exec_hist_down)
        self._exec_input.bind("<Tab>", self._exec_send_tab)

        self._nb.add(frame, text="Exec")

    def _build_events_tab(self):
        frame = tk.Frame(self._nb, bg=BG)
        bar = tk.Frame(frame, bg=BG2)
        bar.pack(fill=tk.X, side=tk.TOP)
        tk.Button(
            bar,
            text="Refresh",
            bg=BG2,
            fg=FG2,
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=6,
            cursor="hand2",
            command=self._load_events,
        ).pack(side=tk.LEFT, pady=3, padx=4)
        self._events_text = self._make_scrolled_text(frame, font=MONO)
        self._nb.add(frame, text="Events")

    def _make_scrolled_text(self, parent, font=None):
        outer = tk.Frame(parent, bg=BG3)
        outer.pack(fill=tk.BOTH, expand=True)
        text = tk.Text(
            outer,
            bg=BG3,
            fg=FG,
            relief=tk.FLAT,
            insertbackground=FG,
            font=font or FONT,
            wrap=tk.NONE,
            bd=8,
            state="disabled",
        )
        vsb = ttk.Scrollbar(outer, command=text.yview)
        hsb = ttk.Scrollbar(outer, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        text.pack(fill=tk.BOTH, expand=True)
        make_text_copyable(text)
        return text

    def _set_text(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _append(self, widget, text, tag=None):
        widget.configure(state="normal")
        if tag:
            widget.insert(tk.END, text, tag)
        else:
            widget.insert(tk.END, text)
        widget.see(tk.END)
        widget.configure(state="disabled")

    def _wipe(self, widget):
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.configure(state="disabled")

    def _load_namespaces(self):
        def _go():
            out, _, rc = _kubectl("get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}")
            if rc == 0:
                namespaces = ["all"] + sorted(out.split())
                self.after(0, lambda: self._update_ns_menu(namespaces))
            else:
                self.after(0, lambda: self._left_status.configure(text="kubectl namespace load failed", fg=ERROR))

        threading.Thread(target=_go, daemon=True).start()

    def _update_ns_menu(self, namespaces):
        self._ns_menu["values"] = namespaces
        if self._ns_var.get() not in namespaces:
            self._ns_var.set("all")

    def _select_type(self, label, rtype):
        self._resource_type = rtype
        self._resource_label = label
        self._highlight_type(rtype)
        self._refresh_resources()

    def _highlight_type(self, rtype):
        for current, btn in self._rt_btns.items():
            if current == rtype:
                btn.configure(bg=ACCENT, fg="white")
            else:
                btn.configure(bg=BG3, fg=FG2)

    def _refresh_resources(self):
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        namespace = self._ns_var.get()
        rtype = self._resource_type

        def _go():
            cluster_scoped = rtype in ("nodes", "namespaces")
            if rtype == "pods":
                cols = "NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,READY:.status.containerStatuses[0].ready"
            elif cluster_scoped:
                cols = "NAME:.metadata.name,STATUS:.status.phase"
            else:
                cols = "NAMESPACE:.metadata.namespace,NAME:.metadata.name"

            kwargs = {} if cluster_scoped else {"namespace": namespace}
            out, err, rc = _kubectl(
                "get",
                rtype,
                "-o",
                f"custom-columns={cols}",
                "--no-headers",
                **kwargs,
            )
            if rc == 0:
                lines = [line for line in out.strip().splitlines() if line.strip()]
                resources, display = [], []
                for line in lines:
                    parts = line.split()
                    if cluster_scoped:
                        item_ns, item_name = "", parts[0] if parts else ""
                        display.append(item_name)
                    else:
                        item_ns = parts[0] if len(parts) > 0 else ""
                        item_name = parts[1] if len(parts) > 1 else ""
                        suffix = f"  {parts[2]}" if len(parts) > 2 else ""
                        label = f"{item_ns}/{item_name}" if namespace == "all" else f"{item_name}{suffix}"
                        display.append(label)
                    resources.append((item_ns, item_name))
                self.after(0, lambda: self._populate_list(resources, display, ""))
            else:
                self.after(0, lambda: self._populate_list([], [], err.strip()))

        threading.Thread(target=_go, daemon=True).start()
        self._refresh_job = self.after(self._REFRESH_MS, self._refresh_resources)

    def _populate_list(self, resources, display, err):
        self._resources = resources
        self._listbox.delete(0, tk.END)
        for item in display:
            self._listbox.insert(tk.END, item)
        if err:
            self._left_status.configure(text=f"WARNING {err[:60]}", fg=ERROR)
        else:
            self._left_status.configure(text=f"{len(resources)} {self._resource_label}", fg=FG2)
        if self._selected_name:
            for index, (item_ns, item_name) in enumerate(resources):
                if item_name == self._selected_name and item_ns == (self._selected_ns or ""):
                    self._listbox.selection_set(index)
                    self._listbox.see(index)
                    break

    def _on_list_select(self, event=None):
        sel = self._listbox.curselection()
        if not sel or sel[0] >= len(self._resources):
            return
        item_ns, item_name = self._resources[sel[0]]
        self._selected_ns = item_ns
        self._selected_name = item_name
        prefix = f"{item_ns}/" if item_ns else ""
        rtype = self._resource_label.rstrip("s")
        self._header.configure(text=f"{rtype}: {prefix}{item_name}")
        self._load_containers()
        self._dispatch_tab()

    def _dispatch_tab(self):
        tab = self._nb.index(self._nb.select())
        if tab == 0:
            self._load_describe()
        elif tab == 1:
            self._load_yaml()
        elif tab == 2:
            self._start_log_stream()
        elif tab == 4:
            self._load_events()

    def _on_tab_change(self, event=None):
        if self._selected_name:
            self._dispatch_tab()

    def _load_containers(self):
        if self._resource_type != "pods" or not self._selected_name:
            self._update_ctr_menus([])
            return
        namespace = self._selected_ns
        name = self._selected_name

        def _go():
            out, _, rc = _kubectl(
                "get",
                "pod",
                name,
                "-o",
                "jsonpath={.spec.containers[*].name}",
                namespace=namespace,
            )
            containers = out.split() if rc == 0 and out.strip() else []
            self.after(0, lambda: self._update_ctr_menus(containers))

        threading.Thread(target=_go, daemon=True).start()

    def _update_ctr_menus(self, containers):
        for menu, var in ((self._log_ctr_menu, self._log_ctr_var), (self._exec_ctr_menu, self._exec_ctr_var)):
            menu["values"] = containers
            if containers:
                if var.get() not in containers:
                    var.set(containers[0])
            else:
                var.set("")

    def _load_describe(self):
        if not self._selected_name:
            return
        self._set_text(self._describe_text, "Loading...")
        namespace, name, rtype = self._selected_ns, self._selected_name, self._resource_type

        def _go():
            out, err, rc = _kubectl("describe", rtype, name, namespace=namespace, timeout=15)
            self.after(0, lambda: self._set_text(self._describe_text, out if rc == 0 else f"Error:\n{err}"))

        threading.Thread(target=_go, daemon=True).start()

    def _load_yaml(self):
        if not self._selected_name:
            return
        self._set_text(self._yaml_text, "Loading...")
        namespace, name, rtype = self._selected_ns, self._selected_name, self._resource_type

        def _go():
            out, err, rc = _kubectl("get", rtype, name, "-o", "yaml", namespace=namespace, timeout=15)
            self.after(0, lambda: self._set_text(self._yaml_text, out if rc == 0 else f"Error:\n{err}"))

        threading.Thread(target=_go, daemon=True).start()

    def _copy_yaml(self):
        self.clipboard_clear()
        self.clipboard_append(self._yaml_text.get("1.0", tk.END))

    def _stop_log_stream(self):
        if self._log_proc:
            try:
                self._log_proc.terminate()
            except Exception:
                pass
            self._log_proc = None
        try:
            self._log_status.configure(text="Stopped", fg=FG2)
        except Exception:
            pass

    def _start_log_stream(self):
        if self._resource_type != "pods" or not self._selected_name:
            return
        self._stop_log_stream()
        self._wipe(self._log_text)

        namespace = self._selected_ns
        name = self._selected_name
        container = self._log_ctr_var.get()
        follow = self._follow_var.get()
        previous = self._prev_var.get()
        try:
            tail = int(self._tail_var.get())
        except ValueError:
            tail = 300

        cmd = ["kubectl", "-n", namespace, "logs", name, f"--tail={tail}"]
        if container:
            cmd += ["-c", container]
        if follow:
            cmd.append("-f")
        if previous:
            cmd.append("-p")

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
            self._log_proc = proc
            self._log_status.configure(text="Streaming...", fg=SUCCESS)
        except Exception as e:
            self._log_status.configure(text=f"Error: {e}", fg=ERROR)
            return

        def _read():
            try:
                for line in proc.stdout:
                    if proc.poll() is not None and not line:
                        break
                    self.after(0, lambda l=line: self._append(self._log_text, l))
                err_out = proc.stderr.read()
                if err_out:
                    self.after(0, lambda eo=err_out: self._append(self._log_text, f"\n[stderr]\n{eo}", "error"))
            except Exception:
                pass
            finally:
                self.after(0, lambda: self._log_status.configure(text="Ended", fg=FG2))

        threading.Thread(target=_read, daemon=True).start()

    def _highlight_log_search(self):
        self._log_text.tag_remove("match", "1.0", tk.END)
        query = self._log_search_var.get().strip()
        if not query:
            return
        start, count = "1.0", 0
        while True:
            pos = self._log_text.search(query, start, stopindex=tk.END, nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(query)}c"
            self._log_text.tag_add("match", pos, end)
            start = end
            count += 1
        self._log_status.configure(text=f"{count} match{'es' if count != 1 else ''}" if count else "")

    def _stop_exec(self):
        if self._exec_mfd is not None:
            try:
                os.close(self._exec_mfd)
            except OSError:
                pass
            self._exec_mfd = None
        if self._exec_proc:
            try:
                self._exec_proc.terminate()
            except Exception:
                pass
            self._exec_proc = None
        self._exec_status.configure(text="Disconnected", fg=ERROR)
        self._append(self._exec_text, "\n[disconnected]\n", "error")

    def _start_exec(self):
        if self._resource_type != "pods" or not self._selected_name:
            self._append(self._exec_text, "Select a Pod first.\n", "error")
            return
        self._stop_exec()
        self._wipe(self._exec_text)

        namespace = self._selected_ns
        name = self._selected_name
        container = self._exec_ctr_var.get()
        shell = self._shell_var.get().strip() or "/bin/sh"

        cmd = ["kubectl", "-n", namespace, "exec", "-it", name]
        if container:
            cmd += ["-c", container]
        cmd += ["--", shell]

        self._append(self._exec_text, f"Connecting to {namespace}/{name} [{shell}]...\n", "info")
        try:
            master_fd, slave_fd = pty.openpty()
            proc = subprocess.Popen(cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, close_fds=True)
            os.close(slave_fd)
            self._exec_proc = proc
            self._exec_mfd = master_fd
            self._exec_status.configure(text="Connected", fg=SUCCESS)
        except Exception as e:
            self._append(self._exec_text, f"Error: {e}\n", "error")
            self._exec_status.configure(text="Error", fg=ERROR)
            return

        mfd = master_fd

        def _read():
            while True:
                try:
                    readable, _, _ = select.select([mfd], [], [], 0.1)
                    if readable:
                        data = os.read(mfd, 4096)
                        if not data:
                            break
                        text = _strip_ansi(data.decode("utf-8", errors="replace"))
                        self.after(0, lambda t=text: self._append(self._exec_text, t))
                    if proc.poll() is not None:
                        break
                except OSError:
                    break
                except Exception:
                    break
            self.after(0, lambda: self._exec_status.configure(text="Disconnected", fg=ERROR))
            self.after(0, lambda: self._append(self._exec_text, "\n[session ended]\n", "error"))

        threading.Thread(target=_read, daemon=True).start()
        self._exec_input.focus_set()

    def _send_exec_input(self, event=None):
        if self._exec_mfd is None:
            return
        text = self._exec_input.get()
        if text:
            self._exec_history.append(text)
            self._exec_hist_idx = len(self._exec_history)
        self._exec_input.delete(0, tk.END)
        try:
            os.write(self._exec_mfd, (text + "\n").encode())
        except OSError:
            self._stop_exec()

    def _exec_send_tab(self, event=None):
        if self._exec_mfd is not None:
            try:
                os.write(self._exec_mfd, b"\t")
            except OSError:
                pass
        return "break"

    def _exec_hist_up(self, event=None):
        if not self._exec_history:
            return "break"
        self._exec_hist_idx = max(0, self._exec_hist_idx - 1)
        self._exec_input.delete(0, tk.END)
        self._exec_input.insert(0, self._exec_history[self._exec_hist_idx])
        return "break"

    def _exec_hist_down(self, event=None):
        if not self._exec_history:
            return "break"
        self._exec_hist_idx = min(len(self._exec_history), self._exec_hist_idx + 1)
        self._exec_input.delete(0, tk.END)
        if self._exec_hist_idx < len(self._exec_history):
            self._exec_input.insert(0, self._exec_history[self._exec_hist_idx])
        return "break"

    def _load_events(self):
        if not self._selected_name:
            return
        self._set_text(self._events_text, "Loading events...")
        namespace, name = self._selected_ns, self._selected_name

        def _go():
            out, err, rc = _kubectl(
                "get",
                "events",
                "--field-selector",
                f"involvedObject.name={name}",
                "--sort-by=.lastTimestamp",
                "-o",
                "custom-columns=TIME:.lastTimestamp,TYPE:.type,REASON:.reason,MESSAGE:.message",
                namespace=namespace,
                timeout=15,
            )
            self.after(0, lambda: self._set_text(self._events_text, out if rc == 0 else f"Error:\n{err}"))

        threading.Thread(target=_go, daemon=True).start()

    def build_context(self):
        selected = f"{self._selected_ns}/{self._selected_name}" if self._selected_ns else (self._selected_name or "")
        lines = [
            "K8S EXPLORER CONTEXT",
            "",
            f"Namespace: {self._ns_var.get()}",
            f"Resource Type: {self._resource_label}",
            f"Selected Resource: {selected or '(none)'}",
            f"Visible Resources: {len(self._resources)}",
        ]
        return "\n".join(lines)

    def _on_destroy(self, event=None):
        if event and event.widget is not self:
            return
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self._stop_log_stream()
        if self._exec_mfd is not None:
            try:
                os.close(self._exec_mfd)
            except OSError:
                pass
        if self._exec_proc:
            try:
                self._exec_proc.terminate()
            except Exception:
                pass


def create_widget(parent, context_builder_callback=None):
    return K8sExplorerWidget(parent, context_builder_callback=context_builder_callback)
