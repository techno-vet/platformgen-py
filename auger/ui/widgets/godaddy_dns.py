"""GoDaddy DNS widget ported from Trader for PlatformGen."""

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import requests
from dotenv import load_dotenv

from auger.runtime import state_dir

ENV_FILE = state_dir() / ".env"

BG = "#1e1e1e"
BG2 = "#252526"
BG3 = "#2d2d2d"
FG = "#e0e0e0"
FG2 = "#888888"
ACC = "#007acc"
GREEN = "#4ec9b0"
RED = "#f44747"
YELLOW = "#dcdcaa"
FONT = ("Helvetica", 10)
FONT_B = ("Helvetica", 10, "bold")

GD_BASE = "https://api.godaddy.com/v1"
DNS_TYPES = ["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA"]


class GoDaddyDNSWidget(tk.Frame):
    WIDGET_TITLE = "GoDaddy DNS"
    WIDGET_ICON_NAME = "connect"

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        load_dotenv(ENV_FILE, override=True)
        self._key = os.getenv("GODADDY_API_KEY", "")
        self._secret = os.getenv("GODADDY_API_SECRET", "")
        self._domains = []
        self._records = []
        self._selected_domain = tk.StringVar()
        self._build()
        if self._key and self._secret:
            self.after(300, self._load_domains)
        else:
            self._log("No GoDaddy credentials configured in API Keys+.", "err")

    def _build(self):
        top = tk.Frame(self, bg=BG2)
        top.pack(fill=tk.X)
        tk.Label(top, text="GoDaddy DNS Manager", bg=BG2, fg=GREEN, font=("Helvetica", 15, "bold")).pack(
            side=tk.LEFT, padx=16, pady=10
        )
        tk.Button(top, text="Refresh", command=self._load_domains, bg=BG3, fg=FG, relief=tk.FLAT,
                  font=FONT_B, padx=10, pady=4, cursor="hand2").pack(side=tk.RIGHT, padx=8, pady=6)
        tk.Button(top, text="Point to This Server", command=self._point_to_server, bg="#2d5a27", fg=GREEN,
                  relief=tk.FLAT, font=FONT_B, padx=10, pady=4, cursor="hand2").pack(side=tk.RIGHT, padx=(0, 4), pady=6)

        pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg="#3c3c3c", sashwidth=4, sashrelief=tk.FLAT)
        pane.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(pane, bg=BG2, width=260)
        pane.add(left, minsize=200)
        tk.Label(left, text="Domains", bg=BG2, fg=FG2, font=FONT_B).pack(anchor="w", padx=12, pady=(10, 4))

        cols = ("domain", "status", "expires")
        self._domain_tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse", style="GD.Treeview")
        for col, width in (("domain", 150), ("status", 60), ("expires", 80)):
            self._domain_tree.heading(col, text=col.title())
            self._domain_tree.column(col, width=width, stretch=(col == "domain"))
        dsb = tk.Scrollbar(left, orient=tk.VERTICAL, command=self._domain_tree.yview, bg=BG3)
        self._domain_tree.configure(yscrollcommand=dsb.set)
        dsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._domain_tree.pack(fill=tk.BOTH, expand=True, padx=(8, 0), pady=(0, 8))
        self._domain_tree.bind("<<TreeviewSelect>>", self._on_domain_select)

        right = tk.Frame(pane, bg=BG)
        pane.add(right, minsize=400)
        rh = tk.Frame(right, bg=BG2)
        rh.pack(fill=tk.X)
        self._domain_lbl = tk.Label(rh, text="Select a domain", bg=BG2, fg=FG, font=("Helvetica", 13, "bold"))
        self._domain_lbl.pack(side=tk.LEFT, padx=12, pady=8)

        tf = tk.Frame(rh, bg=BG2)
        tf.pack(side=tk.RIGHT, padx=8)
        tk.Label(tf, text="Filter:", bg=BG2, fg=FG2, font=FONT).pack(side=tk.LEFT)
        self._type_filter = tk.StringVar(value="ALL")
        type_combo = ttk.Combobox(tf, textvariable=self._type_filter, values=["ALL"] + DNS_TYPES, width=7, state="readonly")
        type_combo.pack(side=tk.LEFT, padx=4)
        type_combo.bind("<<ComboboxSelected>>", lambda _: self._populate_records())

        rec_frame = tk.Frame(right, bg=BG)
        rec_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        rcols = ("type", "name", "value", "ttl")
        self._rec_tree = ttk.Treeview(rec_frame, columns=rcols, show="headings", selectmode="browse", style="GD.Treeview")
        self._rec_tree.heading("type", text="Type")
        self._rec_tree.heading("name", text="Name")
        self._rec_tree.heading("value", text="Value / Data")
        self._rec_tree.heading("ttl", text="TTL")
        self._rec_tree.column("type", width=55, stretch=False)
        self._rec_tree.column("name", width=140, stretch=False)
        self._rec_tree.column("value", width=300, stretch=True)
        self._rec_tree.column("ttl", width=60, stretch=False)
        rsb = tk.Scrollbar(rec_frame, orient=tk.VERTICAL, command=self._rec_tree.yview, bg=BG3)
        self._rec_tree.configure(yscrollcommand=rsb.set)
        rsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._rec_tree.pack(fill=tk.BOTH, expand=True)

        ab = tk.Frame(right, bg=BG2)
        ab.pack(fill=tk.X, padx=8, pady=6)
        self._btn(ab, "Add Record", self._add_record, ACC).pack(side=tk.LEFT, padx=(0, 6))
        self._btn(ab, "Edit Record", self._edit_record, "#555").pack(side=tk.LEFT, padx=(0, 6))
        self._btn(ab, "Delete Record", self._delete_record, "#7a2020").pack(side=tk.LEFT)
        self._btn(ab, "Copy Value", self._copy_value, "#3c3c3c").pack(side=tk.RIGHT)

        log_frame = tk.Frame(self, bg=BG)
        log_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.log = tk.Text(log_frame, height=4, bg="#111", fg=FG, font=("Courier", 9), state="disabled", relief=tk.FLAT, bd=4)
        self.log.pack(fill=tk.X)
        self.log.tag_configure("ok", foreground=GREEN)
        self.log.tag_configure("err", foreground=RED)
        self.log.tag_configure("info", foreground="#9cdcfe")

        style = ttk.Style()
        style.configure("GD.Treeview", background=BG3, foreground=FG, fieldbackground=BG3, rowheight=22, font=FONT)
        style.configure("GD.Treeview.Heading", background=BG2, foreground=FG2, relief="flat", font=FONT_B)
        style.map("GD.Treeview", background=[("selected", ACC)])

    def _headers(self):
        return {
            "Authorization": f"sso-key {self._key}:{self._secret}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _reload_creds(self):
        load_dotenv(ENV_FILE, override=True)
        self._key = os.getenv("GODADDY_API_KEY", "")
        self._secret = os.getenv("GODADDY_API_SECRET", "")

    def _load_domains(self):
        self._reload_creds()
        if not self._key or not self._secret:
            self._log("Set GODADDY_API_KEY and GODADDY_API_SECRET in API Keys+ first.", "err")
            return
        self._log("Loading domains...", "info")
        threading.Thread(target=self._do_load_domains, daemon=True).start()

    def _do_load_domains(self):
        try:
            resp = requests.get(f"{GD_BASE}/domains?limit=100&status=ACTIVE", headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                self._domains = resp.json()
                self.after(0, self._populate_domains)
                self.after(0, lambda: self._log(f"Loaded {len(self._domains)} domain(s)", "ok"))
            else:
                self.after(0, lambda: self._log(f"GoDaddy API error {resp.status_code}: {resp.text[:120]}", "err"))
        except Exception as e:
            self.after(0, lambda m=str(e): self._log(m, "err"))

    def _populate_domains(self):
        self._domain_tree.delete(*self._domain_tree.get_children())
        for d in self._domains:
            exp = d.get("expires", "")[:10] if d.get("expires") else "-"
            status = d.get("status", "")
            tag = "ok" if status == "ACTIVE" else "warn"
            self._domain_tree.insert("", tk.END, values=(d["domain"], status, exp), tags=(tag,))
        self._domain_tree.tag_configure("ok", foreground=GREEN)
        self._domain_tree.tag_configure("warn", foreground=YELLOW)

    def _on_domain_select(self, _event=None):
        sel = self._domain_tree.selection()
        if not sel:
            return
        domain = self._domain_tree.item(sel[0])["values"][0]
        self._selected_domain.set(domain)
        self._domain_lbl.configure(text=domain)
        self._log(f"Loading DNS records for {domain}...", "info")
        threading.Thread(target=self._do_load_records, args=(domain,), daemon=True).start()

    def _do_load_records(self, domain: str):
        try:
            resp = requests.get(f"{GD_BASE}/domains/{domain}/records", headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                self._records = resp.json()
                self.after(0, self._populate_records)
                self.after(0, lambda: self._log(f"Loaded {len(self._records)} record(s) for {domain}", "ok"))
            else:
                self.after(0, lambda: self._log(f"Records error {resp.status_code}: {resp.text[:120]}", "err"))
        except Exception as e:
            self.after(0, lambda m=str(e): self._log(m, "err"))

    def _populate_records(self):
        self._rec_tree.delete(*self._rec_tree.get_children())
        filt = self._type_filter.get()
        for record in self._records:
            if filt != "ALL" and record.get("type") != filt:
                continue
            self._rec_tree.insert("", tk.END, values=(
                record.get("type", ""),
                record.get("name", ""),
                record.get("data", ""),
                record.get("ttl", ""),
            ))

    def _add_record(self):
        domain = self._selected_domain.get()
        if not domain:
            messagebox.showwarning("No Domain", "Select a domain first.")
            return
        dlg = RecordDialog(self, title=f"Add DNS Record - {domain}")
        if dlg.result:
            threading.Thread(target=self._do_add_record, args=(domain, dlg.result), daemon=True).start()

    def _do_add_record(self, domain: str, record: dict):
        try:
            resp = requests.patch(f"{GD_BASE}/domains/{domain}/records", headers=self._headers(), json=[record], timeout=10)
            if resp.status_code in (200, 204):
                self.after(0, lambda: self._log(f"Added {record['type']} record '{record['name']}'", "ok"))
                threading.Thread(target=self._do_load_records, args=(domain,), daemon=True).start()
            else:
                self.after(0, lambda: self._log(f"Add failed {resp.status_code}: {resp.text[:120]}", "err"))
        except Exception as e:
            self.after(0, lambda m=str(e): self._log(m, "err"))

    def _edit_record(self):
        domain = self._selected_domain.get()
        sel = self._rec_tree.selection()
        if not domain or not sel:
            messagebox.showwarning("No Selection", "Select a domain and a record.")
            return
        vals = self._rec_tree.item(sel[0])["values"]
        existing = {"type": vals[0], "name": vals[1], "data": vals[2], "ttl": vals[3]}
        dlg = RecordDialog(self, title=f"Edit DNS Record - {domain}", prefill=existing)
        if dlg.result:
            threading.Thread(target=self._do_put_record, args=(domain, existing["type"], existing["name"], dlg.result), daemon=True).start()

    def _do_put_record(self, domain: str, rtype: str, name: str, record: dict):
        try:
            resp = requests.put(f"{GD_BASE}/domains/{domain}/records/{rtype}/{name}", headers=self._headers(), json=[record], timeout=10)
            if resp.status_code in (200, 204):
                self.after(0, lambda: self._log(f"Updated {rtype} record '{name}'", "ok"))
                threading.Thread(target=self._do_load_records, args=(domain,), daemon=True).start()
            else:
                self.after(0, lambda: self._log(f"Update failed {resp.status_code}: {resp.text[:120]}", "err"))
        except Exception as e:
            self.after(0, lambda m=str(e): self._log(m, "err"))

    def _delete_record(self):
        domain = self._selected_domain.get()
        sel = self._rec_tree.selection()
        if not domain or not sel:
            messagebox.showwarning("No Selection", "Select a domain and a record.")
            return
        vals = self._rec_tree.item(sel[0])["values"]
        rtype, name = vals[0], vals[1]
        if not messagebox.askyesno("Confirm Delete", f"Delete {rtype} record '{name}' from {domain}?"):
            return
        threading.Thread(target=self._do_delete_record, args=(domain, rtype, name), daemon=True).start()

    def _do_delete_record(self, domain: str, rtype: str, name: str):
        try:
            resp = requests.delete(f"{GD_BASE}/domains/{domain}/records/{rtype}/{name}", headers=self._headers(), timeout=10)
            if resp.status_code in (200, 204):
                self.after(0, lambda: self._log(f"Deleted {rtype} record '{name}'", "ok"))
                threading.Thread(target=self._do_load_records, args=(domain,), daemon=True).start()
            else:
                self.after(0, lambda: self._log(f"Delete failed {resp.status_code}: {resp.text[:120]}", "err"))
        except Exception as e:
            self.after(0, lambda m=str(e): self._log(m, "err"))

    def _point_to_server(self):
        domain = self._selected_domain.get()
        if not domain:
            messagebox.showwarning("No Domain", "Select a domain first.")
            return
        threading.Thread(target=self._do_point_to_server, args=(domain,), daemon=True).start()

    def _do_point_to_server(self, domain: str):
        try:
            ip = requests.get("https://ifconfig.me", timeout=5).text.strip()
        except Exception:
            self.after(0, lambda: self._log("Could not determine server IP", "err"))
            return

        def _confirm():
            if messagebox.askyesno("Confirm", f"Set A record for {domain} -> {ip}?\n\nThis updates the root (@) A record."):
                threading.Thread(
                    target=self._do_put_record,
                    args=(domain, "A", "@", {"type": "A", "name": "@", "data": ip, "ttl": 600}),
                    daemon=True,
                ).start()

        self.after(0, _confirm)

    def _copy_value(self):
        sel = self._rec_tree.selection()
        if not sel:
            return
        value = self._rec_tree.item(sel[0])["values"][2]
        self.clipboard_clear()
        self.clipboard_append(str(value))
        self._log(f"Copied: {value}", "info")

    def _btn(self, parent, text, cmd, color):
        return tk.Button(parent, text=text, command=cmd, bg=color, fg="#ffffff", activebackground="#005fa3",
                         activeforeground="#ffffff", relief=tk.FLAT, font=FONT_B, padx=10, pady=5, cursor="hand2")

    def _log(self, msg: str, tag: str = ""):
        self.log.configure(state="normal")
        self.log.insert(tk.END, f"  {msg}\n", tag)
        self.log.see(tk.END)
        self.log.configure(state="disabled")


class RecordDialog(tk.Toplevel):
    def __init__(self, parent, title="DNS Record", prefill=None):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=BG2)
        self.resizable(False, False)
        self.result = None
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        prefill = prefill or {}
        self._type = tk.StringVar(value=prefill.get("type", "A"))
        self._name = tk.StringVar(value=prefill.get("name", "@"))
        self._data = tk.StringVar(value=prefill.get("data", ""))
        self._ttl = tk.StringVar(value=str(prefill.get("ttl", 600)))

        body = tk.Frame(self, bg=BG2, padx=14, pady=12)
        body.pack(fill=tk.BOTH, expand=True)

        self._row(body, "Type", ttk.Combobox(body, textvariable=self._type, values=DNS_TYPES, state="readonly", width=20), 0)
        self._row(body, "Name", tk.Entry(body, textvariable=self._name, bg=BG3, fg=FG, insertbackground=FG, relief=tk.FLAT, width=24), 1)
        self._row(body, "Value", tk.Entry(body, textvariable=self._data, bg=BG3, fg=FG, insertbackground=FG, relief=tk.FLAT, width=32), 2)
        self._row(body, "TTL", tk.Entry(body, textvariable=self._ttl, bg=BG3, fg=FG, insertbackground=FG, relief=tk.FLAT, width=12), 3)

        buttons = tk.Frame(body, bg=BG2)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        tk.Button(buttons, text="Cancel", command=self.destroy, bg="#555", fg="white", relief=tk.FLAT, padx=12, pady=4).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Save", command=self._save, bg=ACC, fg="white", relief=tk.FLAT, padx=12, pady=4).pack(side=tk.RIGHT, padx=(0, 8))

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _row(self, parent, label, widget, row):
        tk.Label(parent, text=f"{label}:", bg=BG2, fg=FG, font=FONT).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        parent.grid_columnconfigure(1, weight=1)

    def _save(self):
        name = self._name.get().strip()
        data = self._data.get().strip()
        ttl = self._ttl.get().strip()
        if not name or not data:
            messagebox.showwarning("Missing Data", "Name and value are required.", parent=self)
            return
        try:
            ttl_value = int(ttl)
        except ValueError:
            messagebox.showwarning("Invalid TTL", "TTL must be an integer.", parent=self)
            return
        self.result = {"type": self._type.get(), "name": name, "data": data, "ttl": ttl_value}
        self.destroy()
