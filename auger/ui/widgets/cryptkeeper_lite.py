"""Cryptkeeper Lite Widget - Fast, Docker-free encryption/decryption"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
from pathlib import Path

from auger.tools.cryptkeeper_lite import encrypt_value, decrypt_value, decrypt_file as decrypt_file_tool
from auger.ui import icons as _icons
try:
    from auger.ui.utils import auger_home as _auger_home
except ImportError:
    def _auger_home(): return Path.home()


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



class CryptkeeperLiteWidget(tk.Frame):
    """Lightweight widget for encrypting/decrypting - No Docker required!"""
    
    WIDGET_TITLE = "Cryptkeeper Lite"
    WIDGET_ICON_NAME = "lightning"
    
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.keys = self._load_keys()
        self._icons = {}
        self._create_ui()
    
    def _load_keys(self):
        """Load cryptkeeper keys from environment or config"""
        keys = {}
        
        # Try to load from .env file
        env_file = _auger_home() / '.auger' / '.env'
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        if 'CRYPTKEEPER_KEY' in key:
                            env_name = key.replace('_CRYPTKEEPER_KEY', '').lower()
                            keys[env_name] = value.strip("'\"")
        
        # Fallback to environment variables
        for env in ['DEV', 'TEST', 'STAGING', 'LOCAL', 'PROD']:
            env_key = f'{env}_CRYPTKEEPER_KEY'
            if env_key in os.environ and not keys.get(env.lower()):
                keys[env.lower()] = os.environ[env_key]
        
        return keys
    
    def _create_ui(self):
        """Create the widget UI"""
        for name in ('lock', 'file', 'delete', 'copy'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass
        # Header
        header = tk.Frame(self, bg='#00a86b', height=40)  # Different color to distinguish from regular
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        try:
            _ico = _icons.get('lightning', 22)
            tk.Label(header, image=_ico, bg='#00a86b').pack(side=tk.LEFT, padx=(15, 4), pady=8)
        except Exception:
            pass

        tk.Label(
            header,
            text="Cryptkeeper Lite",
            font=('Segoe UI', 12, 'bold'),
            fg='#ffffff',
            bg='#00a86b'
        ).pack(side=tk.LEFT, padx=(0, 5), pady=10)
        
        tk.Label(
            header,
            text="Fast encryption - No Docker required!",
            font=('Segoe UI', 9),
            fg='#ffffff',
            bg='#00a86b'
        ).pack(side=tk.LEFT, padx=5)
        
        # Main content area with scrollbar
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
        
        # Content
        content = scrollable_frame
        
        # Environment Selection Panel
        env_panel = tk.LabelFrame(
            content,
            text="  Select Environments  ",
            font=('Segoe UI', 10, 'bold'),
            fg=ACCENT2,
            bg=BG2,
            relief=tk.FLAT,
            borderwidth=2
        )
        env_panel.pack(fill=tk.X, padx=20, pady=(20, 10))
        
        env_inner = tk.Frame(env_panel, bg=BG2)
        env_inner.pack(fill=tk.X, padx=10, pady=10)
        
        self.env_vars = {}
        environments = ['dev', 'test', 'staging', 'local', 'prod']
        
        for env in environments:
            var = tk.BooleanVar()
            self.env_vars[env] = var
            
            # Check if key exists for this environment
            has_key = env in self.keys
            
            cb = tk.Checkbutton(
                env_inner,
                text=env.upper(),
                variable=var,
                font=('Segoe UI', 10),
                fg=FG if has_key else '#666666',
                bg=BG2,
                selectcolor=BG3,
                activebackground=BG2,
                activeforeground=ACCENT2,
                state=tk.NORMAL if has_key else tk.DISABLED
            )
            cb.pack(side=tk.LEFT, padx=10, pady=5)
            
            if not has_key:
                tk.Label(
                    env_inner,
                    text="(no key)",
                    font=('Segoe UI', 8),
                    fg='#666666',
                    bg=BG2
                ).pack(side=tk.LEFT, padx=(0, 15))
        
        # Input Panel
        input_panel = tk.LabelFrame(
            content,
            text="  Input Value  ",
            font=('Segoe UI', 10, 'bold'),
            fg=ACCENT2,
            bg=BG2,
            relief=tk.FLAT,
            borderwidth=2
        )
        input_panel.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        input_inner = tk.Frame(input_panel, bg=BG2)
        input_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        tk.Label(
            input_inner,
            text="Enter value to encrypt/decrypt:",
            font=('Segoe UI', 9),
            fg=FG,
            bg=BG2
        ).pack(anchor=tk.W, pady=(0, 5))
        
        input_frame = tk.Frame(input_inner, bg=BG2)
        input_frame.pack(fill=tk.BOTH, expand=True)
        
        self.input_text = tk.Text(
            input_frame,
            height=4,
            font=('Consolas', 10),
            bg=BG3,
            fg=FG,
            insertbackground=ACCENT2,
            relief=tk.FLAT,
            wrap=tk.WORD
        )
        input_scroll = ttk.Scrollbar(input_frame, command=self.input_text.yview)
        self.input_text.configure(yscrollcommand=input_scroll.set)
        
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        input_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Hint label
        hint = tk.Label(
            input_inner,
            text="Values starting with ENC(...) will be decrypted, others will be encrypted",
            font=('Segoe UI', 8, 'italic'),
            fg='#808080',
            bg=BG2
        )
        hint.pack(anchor=tk.W, pady=(5, 0))
        
        # Action buttons
        btn_frame = tk.Frame(content, bg=BG)
        btn_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Button(
            btn_frame,
            text=" Encrypt / Decrypt",
            image=self._icons.get('lock'),
            compound=tk.LEFT,
            command=self._process,
            font=('Segoe UI', 10, 'bold'),
            bg='#00a86b',
            fg='#ffffff',
            activebackground='#008c5a',
            activeforeground='#ffffff',
            relief=tk.FLAT,
            cursor='hand2',
            padx=20,
            pady=8
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        tk.Button(
            btn_frame,
            text=" Decrypt File",
            image=self._icons.get('file'),
            compound=tk.LEFT,
            command=self._decrypt_file,
            font=('Segoe UI', 9),
            bg=ACCENT,
            fg='#ffffff',
            activebackground='#005a9e',
            activeforeground='#ffffff',
            relief=tk.FLAT,
            cursor='hand2',
            padx=15,
            pady=8
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        tk.Button(
            btn_frame,
            text=" Clear All",
            image=self._icons.get('delete'),
            compound=tk.LEFT,
            command=self._clear_all,
            font=('Segoe UI', 9),
            bg=BG3,
            fg=FG,
            activebackground='#3d3d3d',
            activeforeground=FG,
            relief=tk.FLAT,
            cursor='hand2',
            padx=15,
            pady=8
        ).pack(side=tk.LEFT)
        
        # Results Panel
        results_panel = tk.LabelFrame(
            content,
            text="  Results  ",
            font=('Segoe UI', 10, 'bold'),
            fg=ACCENT2,
            bg=BG2,
            relief=tk.FLAT,
            borderwidth=2
        )
        results_panel.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 20))
        
        results_inner = tk.Frame(results_panel, bg=BG2)
        results_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.result_outputs = {}
        
        for env in environments:
            env_frame = tk.Frame(results_inner, bg=BG2)
            env_frame.pack(fill=tk.X, pady=5)
            
            # Label with copy button
            label_frame = tk.Frame(env_frame, bg=BG2)
            label_frame.pack(fill=tk.X)
            
            tk.Label(
                label_frame,
                text=f"{env.upper()}:",
                font=('Segoe UI', 9, 'bold'),
                fg=ACCENT2,
                bg=BG2,
                width=10,
                anchor=tk.W
            ).pack(side=tk.LEFT)
            
            copy_btn = tk.Button(
                label_frame,
                text=" Copy",
                image=self._icons.get('copy'),
                compound=tk.LEFT,
                command=lambda e=env: self._copy_result(e),
                font=('Segoe UI', 8),
                bg=BG3,
                fg=FG,
                activebackground='#3d3d3d',
                relief=tk.FLAT,
                cursor='hand2',
                padx=8,
                pady=2
            )
            copy_btn.pack(side=tk.RIGHT)
            
            # Text output
            text_widget = tk.Text(
                env_frame,
                height=3,
                font=('Consolas', 9),
                bg=BG3,
                fg=FG,
                insertbackground=ACCENT2,
                relief=tk.FLAT,
                wrap=tk.WORD,
                state=tk.DISABLED
            )
            text_widget.pack(fill=tk.X, pady=(5, 0))
            
            self.result_outputs[env] = text_widget
        
        # Status bar
        self.status_label = tk.Label(
            content,
            text="Ready - Using standalone Python (no Docker)",
            font=('Segoe UI', 9),
            fg='#00a86b',
            bg=BG,
            anchor=tk.W
        )
        self.status_label.pack(fill=tk.X, padx=20, pady=(0, 10))
    
    def _process(self):
        """Process encryption/decryption"""
        value = self.input_text.get("1.0", tk.END).strip()
        
        if not value:
            messagebox.showwarning("Input Required", "Please enter a value to encrypt/decrypt")
            return
        
        selected_envs = [env for env, var in self.env_vars.items() if var.get()]
        
        if not selected_envs:
            messagebox.showwarning("Environment Required", "Please select at least one environment")
            return
        
        # Determine if we're encrypting or decrypting
        is_decrypt = value.startswith("ENC(") and value.endswith(")")
        action = "Decrypting" if is_decrypt else "Encrypting"
        
        self.status_label.config(text=f"{action}...", fg=WARNING)
        self.update()
        
        success_count = 0
        
        for env in selected_envs:
            key = self.keys.get(env)
            if not key:
                self._set_result(env, f"❌ No key configured for {env.upper()}", ERROR)
                continue
            
            try:
                if is_decrypt:
                    result = self._decrypt_value(key, value)
                else:
                    result = self._encrypt_value(key, value)
                
                self._set_result(env, result, SUCCESS)
                success_count += 1
                
            except Exception as e:
                self._set_result(env, f"❌ Error: {str(e)}", ERROR)
        
        self.status_label.config(
            text=f"✓ Processed {success_count}/{len(selected_envs)} environments",
            fg=SUCCESS if success_count == len(selected_envs) else WARNING
        )
    
    def _encrypt_value(self, key, value):
        """Encrypt a value using auger.tools.cryptkeeper_lite"""
        result = encrypt_value(value, key)
        if not result:
            raise Exception("Encryption failed")
        return result

    def _decrypt_value(self, key, value):
        """Decrypt a value using auger.tools.cryptkeeper_lite"""
        result = decrypt_value(value, key)
        if not result:
            raise Exception("Decryption failed")
        return result
    
    def _decrypt_file(self):
        """Decrypt an entire file with ENC() values"""
        # Select environment
        selected_envs = [env for env, var in self.env_vars.items() if var.get()]
        
        if not selected_envs:
            messagebox.showwarning("Environment Required", "Please select one environment")
            return
        
        if len(selected_envs) > 1:
            messagebox.showwarning("Single Environment", "Please select only ONE environment for file decryption")
            return
        
        env = selected_envs[0]
        key = self.keys.get(env)
        
        if not key:
            messagebox.showerror("No Key", f"No key configured for {env.upper()}")
            return
        
        # Select input file
        input_file = filedialog.askopenfilename(
            title="Select encrypted file",
            filetypes=[
                ("YAML files", "*.yml *.yaml"),
                ("Properties files", "*.properties"),
                ("All files", "*.*")
            ]
        )
        
        if not input_file:
            return
        
        # Select output directory
        output_dir = filedialog.askdirectory(
            title="Select output directory for decrypted file"
        )
        
        if not output_dir:
            return
        
        self.status_label.config(text=f"Decrypting file...", fg=WARNING)
        self.update()
        
        try:
            output_file = str(Path(output_dir) / Path(input_file).name)
            decrypt_file_tool(input_file, output_file, key)

            messagebox.showinfo(
                "Success",
                f"File decrypted successfully!\n\nOutput: {output_file}"
            )
            
            self.status_label.config(text=f"✓ File decrypted to {output_file}", fg=SUCCESS)
            
        except Exception as e:
            messagebox.showerror("Decryption Failed", str(e))
            self.status_label.config(text=f"✗ File decryption failed", fg=ERROR)
    
    def _set_result(self, env, text, color):
        """Set result text for an environment"""
        widget = self.result_outputs[env]
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.tag_add("all", "1.0", tk.END)
        widget.tag_config("all", foreground=color)
        widget.config(state=tk.DISABLED)
    
    def _copy_result(self, env):
        """Copy result to clipboard"""
        widget = self.result_outputs[env]
        text = widget.get("1.0", tk.END).strip()
        
        if text and not text.startswith("❌"):
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_label.config(text=f"Copied {env.upper()} result to clipboard", fg=SUCCESS)
        else:
            messagebox.showwarning("Nothing to Copy", f"No result available for {env.upper()}")
    
    def _clear_all(self):
        """Clear all inputs and results"""
        self.input_text.delete("1.0", tk.END)
        
        for env in self.result_outputs:
            self._set_result(env, "", FG)
        
        self.status_label.config(text="Ready - Using standalone Python (no Docker)", fg='#00a86b')
