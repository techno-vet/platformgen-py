"""Cryptkeeper Widget - Encrypt/Decrypt values using Jasypt"""
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import os
import shlex
from pathlib import Path
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



class CryptkeeperWidget(tk.Frame):
    """Widget for encrypting/decrypting configuration values"""
    WIDGET_ICON_NAME = "cryptkeeper"
    
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
        for name in ('lock', 'delete', 'copy'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass
        # Header
        header = tk.Frame(self, bg=ACCENT, height=40)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        try:
            _ico = _icons.get('cryptkeeper', 22)
            tk.Label(header, image=_ico, bg=ACCENT).pack(side=tk.LEFT, padx=(15, 4), pady=8)
        except Exception:
            pass

        tk.Label(
            header,
            text="Cryptkeeper",
            font=('Segoe UI', 12, 'bold'),
            fg='#ffffff',
            bg=ACCENT
        ).pack(side=tk.LEFT, padx=(0, 5), pady=10)
        
        tk.Label(
            header,
            text="Encrypt/Decrypt configuration values",
            font=('Segoe UI', 9),
            fg=FG,
            bg=ACCENT
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
            bg=ACCENT,
            fg='#ffffff',
            activebackground='#005a9e',
            activeforeground='#ffffff',
            relief=tk.FLAT,
            cursor='hand2',
            padx=20,
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
            text="Ready",
            font=('Segoe UI', 9),
            fg='#808080',
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
    
    def _is_docker_available(self):
        """Check if Docker daemon is accessible"""
        try:
            result = subprocess.run(['docker', 'info'], capture_output=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    def _docker_login(self):
        """Login to Artifactory Docker registry"""
        registry = os.environ.get('ARTIFACTORY_URL', 'artifactory.helix.gsa.gov')
        username = os.environ.get('ARTIFACTORY_USERNAME', '')
        api_key = os.environ.get('ARTIFACTORY_API_KEY', '')
        if not username or not api_key:
            return False
        try:
            result = subprocess.run(
                ['docker', 'login', registry, '-u', username, '--password-stdin'],
                input=api_key, capture_output=True, text=True, timeout=30
            )
            return result.returncode == 0
        except Exception:
            return False

    def _encrypt_lite(self, key, value):
        """Fallback: encrypt using cryptkeeper_lite (pure Python Jasypt)"""
        import sys
        sys.path.insert(0, '/home/auger/auger-platform')
        from auger.ui.widgets.cryptkeeper_lite import CryptkeeperLiteWidget
        lite = CryptkeeperLiteWidget.__new__(CryptkeeperLiteWidget)
        return lite._encrypt_value(key, value)

    def _decrypt_lite(self, key, value):
        """Fallback: decrypt using cryptkeeper_lite (pure Python Jasypt)"""
        import sys
        sys.path.insert(0, '/home/auger/auger-platform')
        from auger.ui.widgets.cryptkeeper_lite import CryptkeeperLiteWidget
        lite = CryptkeeperLiteWidget.__new__(CryptkeeperLiteWidget)
        return lite._decrypt_value(key, value)

    def _encrypt_value(self, key, value):
        """Encrypt a value using Docker cryptkeeper or Maven"""
        docker_image = os.environ.get('CRYPTKEEPER_DOCKER_IMAGE', '')
        if docker_image:
            if not self._is_docker_available():
                raise Exception("Docker daemon not accessible. Check /var/run/docker.sock permissions.")
            try:
                return self._encrypt_docker(docker_image, key, value)
            except subprocess.TimeoutExpired:
                # Image pull timed out (Artifactory unreachable) — fall back to lite
                return self._encrypt_lite(key, value)
            except Exception as e:
                err = str(e)
                if 'Unable to find image' in err or '403' in err or 'unauthorized' in err.lower():
                    if self._docker_login():
                        return self._encrypt_docker(docker_image, key, value)
                    return self._encrypt_lite(key, value)
                raise
        else:
            return self._encrypt_lite(key, value)
    
    def _decrypt_value(self, key, value):
        """Decrypt a value using Docker cryptkeeper or Maven"""
        docker_image = os.environ.get('CRYPTKEEPER_DOCKER_IMAGE', '')
        if docker_image:
            if not self._is_docker_available():
                raise Exception("Docker daemon not accessible. Check /var/run/docker.sock permissions.")
            try:
                return self._decrypt_docker(docker_image, key, value)
            except subprocess.TimeoutExpired:
                # Image pull timed out (Artifactory unreachable) — fall back to lite
                return self._decrypt_lite(key, value)
            except Exception as e:
                err = str(e)
                if 'Unable to find image' in err or '403' in err or 'unauthorized' in err.lower():
                    if self._docker_login():
                        return self._decrypt_docker(docker_image, key, value)
                    return self._decrypt_lite(key, value)
                raise
        else:
            return self._decrypt_lite(key, value)
    
    def _encrypt_docker(self, image, key, value):
        """Encrypt using Docker"""
        cmd = [
            'docker', 'run', '--rm', '-i',
            '-e', f'CRYPTKEEPER_KEY={key}',
            '-e', f'CRYPTKEEPER_VALUE={value}',
            image,
            'encrypt-value'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            raise Exception(result.stderr or "Docker encryption failed")
        
        return result.stdout.strip()
    
    def _decrypt_docker(self, image, key, value):
        """Decrypt using Docker"""
        cmd = [
            'docker', 'run', '--rm', '-i',
            '-e', f'CRYPTKEEPER_KEY={key}',
            '-e', f'CRYPTKEEPER_VALUE={value}',
            image,
            'decrypt-value'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            raise Exception(result.stderr or "Docker decryption failed")
        
        return result.stdout.strip()
    
    def _encrypt_maven(self, key, value):
        """Encrypt using Maven (requires cryptkeeper repo)"""
        # Find cryptkeeper repo
        cryptkeeper_path = self._find_cryptkeeper_repo()
        
        if not cryptkeeper_path:
            raise Exception("Cryptkeeper repository not found. Set CRYPTKEEPER_DOCKER_IMAGE or clone cryptkeeper repo.")
        
        cmd = [
            'mvn', '--batch-mode',
            'jasypt:encrypt-value',
            f'-Djasypt.encryptor.password={key}',
            f'-Djasypt.plugin.value={value}'
        ]
        
        result = subprocess.run(
            cmd,
            cwd=cryptkeeper_path,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            raise Exception("Maven encryption failed")
        
        # Parse Maven output to find encrypted value
        for line in result.stdout.split('\n'):
            if 'ENC(' in line:
                return line.strip()
        
        raise Exception("No encrypted value found in Maven output")
    
    def _decrypt_maven(self, key, value):
        """Decrypt using Maven (requires cryptkeeper repo)"""
        cryptkeeper_path = self._find_cryptkeeper_repo()
        
        if not cryptkeeper_path:
            raise Exception("Cryptkeeper repository not found. Set CRYPTKEEPER_DOCKER_IMAGE or clone cryptkeeper repo.")
        
        cmd = [
            'mvn', '--batch-mode',
            'jasypt:decrypt-value',
            f'-Djasypt.encryptor.password={key}',
            f'-Djasypt.plugin.value={value}'
        ]
        
        result = subprocess.run(
            cmd,
            cwd=cryptkeeper_path,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            raise Exception("Maven decryption failed")
        
        # Parse Maven output - look for non-INFO lines
        output_lines = []
        for line in result.stdout.split('\n'):
            if '[INFO]' not in line and line.strip():
                output_lines.append(line.strip())
        
        if output_lines:
            return output_lines[-1]  # Return last non-INFO line
        
        raise Exception("No decrypted value found in Maven output")
    
    def _find_cryptkeeper_repo(self):
        """Find cryptkeeper repository in common locations"""
        search_paths = [
            Path.cwd() / '..' / 'cryptkeeper',
            _auger_home() / 'repos' / 'cryptkeeper',
            _auger_home() / 'workspace' / 'cryptkeeper',
            Path('/home/bobbygblair/repos/devtools-scripts/au-silver/astutl_python/prisma-repos/cryptkeeper'),
        ]
        
        for path in search_paths:
            if path.exists() and (path / 'pom.xml').exists():
                return path
        
        return None
    
    def _set_result(self, env, text, color=FG):
        """Set result text for an environment"""
        text_widget = self.result_outputs[env]
        text_widget.config(state=tk.NORMAL, fg=color)
        text_widget.delete("1.0", tk.END)
        text_widget.insert("1.0", text)
        text_widget.config(state=tk.DISABLED)
    
    def _copy_result(self, env):
        """Copy result to clipboard"""
        text_widget = self.result_outputs[env]
        text = text_widget.get("1.0", tk.END).strip()
        
        if text and not text.startswith("❌"):
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_label.config(text=f"✓ Copied {env.upper()} result to clipboard", fg=SUCCESS)
        else:
            messagebox.showinfo("Nothing to Copy", f"No valid result for {env.upper()}")
    
    def _clear_all(self):
        """Clear all inputs and outputs"""
        self.input_text.delete("1.0", tk.END)
        
        for text_widget in self.result_outputs.values():
            text_widget.config(state=tk.NORMAL)
            text_widget.delete("1.0", tk.END)
            text_widget.config(state=tk.DISABLED)
        
        for var in self.env_vars.values():
            var.set(False)
        
        self.status_label.config(text="Ready", fg='#808080')
