"""Hot reload system for watching and reloading widget files."""

import queue
import sys
import threading
import time
import importlib
import importlib.util
from pathlib import Path


class HotReloader:
    """Watches ui/widgets/*.py for changes and reloads them."""
    
    def __init__(self, watch_dir='ui/widgets', interval=1.0, root=None):
        self.watch_dir = Path(watch_dir)
        self.interval = interval
        self._mtimes = {}
        self._callbacks = []
        self._ui_callbacks = []   # fired only for ui/ (non-widget) file changes
        self._first_scan_callbacks = []
        self._first_scan_done = False
        self._running = False
        self._thread = None
        self._root = root  # Tk root for thread-safe dispatch via after()
        self._q: queue.Queue = queue.Queue()
        # Start queue poll from main thread (safe to call before mainloop)
        if root is not None:
            root.after(50, self._poll_q)

        # Also watch the editable source tree (auger/ symlink) if it differs from watch_dir.
        # This ensures `git`-committed changes in auger/ui/widgets/ trigger hot-reload
        # even when watch_dir points at auger_baked/ui/widgets/ (which may be read-only).
        _src = Path(watch_dir).resolve().parent.parent.parent / 'auger' / 'ui' / 'widgets'
        self._src_watch_dir = _src if _src.exists() and _src.resolve() != self.watch_dir.resolve() else None

        # Watch the parent ui/ directory for non-widget files (e.g. ask_auger.py).
        # Callbacks receive (path, module) same as for widgets.
        _ui_baked = self.watch_dir.parent          # auger_baked/ui/
        _ui_src   = _src.parent if _src.exists() else None  # auger/ui/
        self._ui_watch_dirs = []
        for d in filter(None, [_ui_baked, _ui_src]):
            d = d.resolve()
            if d.exists() and d not in [x.resolve() for x in self._ui_watch_dirs]:
                self._ui_watch_dirs.append(d)
    
    def register_callback(self, callback):
        """Register a callback(path, module) to be called on widget file change."""
        self._callbacks.append(callback)

    def register_ui_callback(self, callback):
        """Register a callback(path, module) fired only for ui/-level file changes."""
        self._ui_callbacks.append(callback)

    def register_first_scan_callback(self, callback):
        """Register a callback() fired once after the initial file scan completes."""
        self._first_scan_callbacks.append(callback)
    
    def _poll_q(self):
        """Drain the pending-callback queue on the main thread."""
        try:
            while True:
                fn, args = self._q.get_nowait()
                try:
                    fn(*args)
                except Exception as e:
                    print(f"Hot reload callback error: {e}")
        except queue.Empty:
            pass
        if self._root is not None and self._running:
            self._root.after(50, self._poll_q)

    def _dispatch(self, fn, *args):
        """Queue fn(*args) for execution on the main thread (never calls Tk from a bg thread)."""
        if self._root is not None:
            self._q.put((fn, args))
        else:
            fn(*args)

    def start(self):
        """Start the hot reload watcher thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        # Ensure poll loop is running (may have been stopped if start() called late)
        if self._root is not None:
            self._root.after(50, self._poll_q)
        print(f"[*] Hot reload started, watching {self.watch_dir}")
    
    def stop(self):
        """Stop the watcher thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
    
    def _watch_loop(self):
        """Main watch loop running in background thread."""
        while self._running:
            try:
                self._check_files()
            except Exception as e:
                print(f"Hot reload error: {e}")
            if not self._first_scan_done:
                self._first_scan_done = True
                for cb in self._first_scan_callbacks:
                    try:
                        self._dispatch(cb)
                    except Exception as e:
                        print(f"First scan callback error: {e}")
            time.sleep(self.interval)
    
    def _check_files(self):
        """Check all .py files for changes."""
        dirs_to_check = [self.watch_dir]
        if self._src_watch_dir:
            dirs_to_check.append(self._src_watch_dir)

        for watch_dir in dirs_to_check:
            if not watch_dir.exists():
                continue

            for path in watch_dir.glob('*.py'):
                if path.name.startswith('__'):
                    continue

                try:
                    mtime = path.stat().st_mtime

                    # Track new files and trigger callback for initial load
                    if path not in self._mtimes:
                        self._mtimes[path] = mtime
                        print(f"[+] Tracking {path.name} ({watch_dir.name})")
                        # Load and notify callbacks for new widgets
                        module = self._reload_module(path)
                        if module:
                            for callback in self._callbacks:
                                self._dispatch(callback, path, module)
                        continue

                    # Changed file - reload and notify
                    if self._mtimes[path] != mtime:
                        self._mtimes[path] = mtime
                        module = self._reload_module(path)

                        if module:
                            # Notify all callbacks
                            for callback in self._callbacks:
                                self._dispatch(callback, path, module)

                except Exception as e:
                    print(f"Error checking {path}: {e}")

        # Check ui/ parent dir for non-widget files (ask_auger.py, etc.)
        # Use a deduped set of already-seen resolved inodes to avoid double-firing
        # when baked/ and src/ point to the same inode.
        seen_inodes: set = set()
        for ui_dir in self._ui_watch_dirs:
            if not ui_dir.exists():
                continue
            for path in ui_dir.glob('*.py'):
                # Skip hot_reload.py itself and content_area.py — the latter defines
                # live Tkinter widget classes; reloading it from the background thread
                # while instances are running causes a SIGSEGV (exit 139).
                if (path.name.startswith('__')
                        or path.name in ('hot_reload.py', 'content_area.py')):
                    continue
                try:
                    st = path.stat()
                    if st.st_ino in seen_inodes:
                        continue
                    seen_inodes.add(st.st_ino)
                    mtime = st.st_mtime
                    key = ('ui', path.name)
                    if key not in self._mtimes:
                        self._mtimes[key] = mtime
                        print(f"[+] Tracking {path.name} (ui)")
                        # Do NOT reload on initial scan — ui/ modules are already
                        # loaded by app.py and live as active Tkinter classes.
                        # Reloading them from the background thread causes SIGSEGV.
                        continue
                    if self._mtimes[key] != mtime:
                        self._mtimes[key] = mtime
                        module = self._reload_ui_module(path)
                        if module:
                            for cb in self._ui_callbacks:
                                self._dispatch(cb, path, module)
                except Exception as e:
                    print(f"Error checking ui/{path.name}: {e}")
    
    def _reload_ui_module(self, path):
        """Reload or import a ui-level module (e.g. auger.ui.ask_auger)."""
        try:
            if 'auger.ui' not in sys.modules:
                import auger.ui
            module_name = f"auger.ui.{path.stem}"
            if module_name in sys.modules:
                print(f"[*] Reloading {module_name}")
                return importlib.reload(sys.modules[module_name])
            else:
                print(f"[+] Loading {module_name}")
                spec = importlib.util.spec_from_file_location(module_name, path)
                if not spec or not spec.loader:
                    return None
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                return module
        except SyntaxError as e:
            print(f"[X] Syntax error in {path.name}:\n  {e}")
            return None
        except Exception as e:
            print(f"[X] Error loading {path.name}: {e}")
            return None

    def _reload_module(self, path):
        """Reload or import a widget module from file path."""
        try:
            # Ensure parent packages are loaded
            if 'auger.ui' not in sys.modules:
                import auger.ui
            if 'auger.ui.widgets' not in sys.modules:
                import auger.ui.widgets

            # Convert path to module name
            module_name = f"auger.ui.widgets.{path.stem}"

            # If already loaded, reload it
            if module_name in sys.modules:
                print(f"[*] Reloading {module_name}")
                module = importlib.reload(sys.modules[module_name])
            else:
                # Load fresh
                print(f"[+] Loading {module_name}")
                spec = importlib.util.spec_from_file_location(module_name, path)
                if not spec or not spec.loader:
                    return None

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

            return module

        except SyntaxError as e:
            print(f"[X] Syntax error in {path.name}:\n  {e}")
            return None
        except Exception as e:
            print(f"[X] Error loading {path.name}: {e}")
            return None
