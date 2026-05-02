"""Shell Terminal Widget - Enhanced with TkTerm"""
import tkinter as tk
from tkinter import ttk
from tkterm import Terminal, TkTermConfig
from auger.ui import icons as _icons



class ShellTerminalWidget(tk.Frame):
    """Enhanced shell terminal using TkTerm library"""
    
    # Widget metadata
    WIDGET_NAME = "shell_terminal"
    WIDGET_TITLE = "Bash $"
    WIDGET_ICON = "🖥️"
    WIDGET_ICON_NAME = "bash"
    
    def __init__(self, parent):
        super().__init__(parent, bg='#1e1e1e')
        self._create_ui()
    
    def _create_ui(self):
        """Create the terminal UI with Auger dark theme"""
        # Header bar
        header = tk.Frame(self, bg='#007acc', height=35)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        try:
            _ico = _icons.get('bash', 20)
            tk.Label(header, image=_ico, bg='#007acc').pack(side=tk.LEFT, padx=(10, 4))
        except Exception:
            pass

        tk.Label(
            header,
            text="Shell Terminal",
            font=('Segoe UI', 11, 'bold'),
            fg='#ffffff',
            bg='#007acc'
        ).pack(side=tk.LEFT)
        
        tk.Label(
            header,
            text="Ctrl-C: Kill  |  Ctrl-F: Search  |  Tab: Complete  |  Up/Down: History",
            font=('Segoe UI', 9),
            fg='#e0e0e0',
            bg='#007acc'
        ).pack(side=tk.RIGHT, padx=10)
        
        # Terminal container with padding
        terminal_frame = tk.Frame(self, bg='#1e1e1e')
        terminal_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Apply dark theme configuration before creating Terminal
        self._configure_theme()
        
        # Create TkTerm Terminal widget
        try:
            self.terminal = Terminal(terminal_frame, relief=tk.FLAT, borderwidth=0)
            self.terminal.pack(fill=tk.BOTH, expand=True)
            
        except Exception as e:
            # Fallback error display
            error_label = tk.Label(
                terminal_frame,
                text=f"❌ Failed to initialize terminal:\n{str(e)}",
                font=('Consolas', 10),
                fg='#f44747',
                bg='#1e1e1e',
                justify=tk.LEFT
            )
            error_label.pack(padx=20, pady=20)
            print(f"Terminal init error: {e}")
    
    def _configure_theme(self):
        """Configure TkTerm with Auger dark theme"""
        try:
            # Get default config and customize for dark theme
            config = TkTermConfig.get_default()
            
            # Auger dark theme colors
            config['bg'] = '#0c0c0c'              # Background (darker than platform)
            config['fg'] = '#e0e0e0'              # Foreground text
            config['cursor_color'] = '#00ff00'    # Cursor (green)
            config['select_bg'] = '#264f78'       # Selection background
            config['select_fg'] = '#ffffff'       # Selection text
            config['fontfamily'] = 'Consolas'     # Monospace font
            config['fontsize'] = 10               # Font size
            
            # Set as default so Terminal picks it up
            TkTermConfig.set_default(config)
            
        except Exception as e:
            print(f"Theme configuration warning: {e}")
    
    def destroy(self):
        """Clean up terminal resources"""
        try:
            if hasattr(self, 'terminal'):
                self.terminal.destroy()
        except:
            pass
        super().destroy()
