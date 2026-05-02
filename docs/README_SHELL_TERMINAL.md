# Shell Terminal Widget

The Shell Terminal widget provides a full-featured terminal emulator embedded in the Auger SRE Platform.

## Features

### Enhanced with TkTerm Library

The terminal now uses **TkTerm** (https://github.com/dhanoosu/TkTerm), a mature terminal emulator library with 60+ GitHub stars.

**Key Features:**
- ✅ **Tabbed Terminal** - Multiple terminal tabs (middle-click to close, drag to reorder)
- ✅ **Process Control** - Ctrl-C to kill running processes
- ✅ **Search** - Ctrl-F for text search with regex support
- ✅ **Tab Completion** - Auto-complete files and directories
- ✅ **Command History** - Up/Down arrows to cycle through history
- ✅ **Multiline Commands** - Use `^` or `\` for multi-line input
- ✅ **ANSI Colors** - Full ANSI escape sequence support
- ✅ **Return Codes** - Shows exit code in status bar
- ✅ **Cross-Platform** - Works on Windows (cmd.exe) and Unix (bash/sh)

## Usage

1. Open from **Widgets → Shell Terminal** menu
2. Type commands just like a regular terminal
3. Use keyboard shortcuts for enhanced functionality

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl-C` | Kill current running process |
| `Ctrl-F` | Open search dialog |
| `Up` / `Down` | Navigate command history |
| `Tab` | Auto-complete files/directories |
| `Middle-Click` | Close terminal tab |
| `Double-Click Tab` | Rename tab |

## Multiline Commands

Use `^` or `\` at the end of a line to continue on next line:

```bash
echo "This is a very long command that \
spans multiple lines"
```

## Theming

The terminal is pre-configured with Auger's dark theme:
- Background: `#0c0c0c` (near-black)
- Foreground: `#e0e0e0` (light gray)
- Cursor: `#00ff00` (green)
- Selection: `#264f78` (blue highlight)
- Font: Consolas 10pt

Colors are configured in `ui/widgets/shell_terminal.py` via `TkTermConfig`.

## Technical Details

**Library:** tkterm==0.0.0b2  
**Source:** https://github.com/dhanoosu/TkTerm  
**License:** MIT  
**Installation:** `pip install tkterm`

**Architecture:**
- Terminal widget is a `tk.Frame` subclass
- TkTerm provides tabbed notebook interface internally
- Uses subprocess module with threading for command execution
- Proper cleanup on widget destruction

**Configuration:**
```python
from tkterm import TkTermConfig

config = TkTermConfig.get_default()
config['bg'] = '#0c0c0c'              # Background
config['fg'] = '#e0e0e0'              # Foreground
config['cursor_color'] = '#00ff00'    # Cursor
config['fontfamily'] = 'Consolas'     # Font
config['fontsize'] = 10               # Size
TkTermConfig.set_default(config)
```

## Comparison: Before vs After

### Before (Custom Implementation)
- 154 lines of code
- Basic command execution via subprocess
- Manual command history (up/down)
- Manual directory tracking (cd command)
- No ANSI color support
- No tab completion
- No search functionality
- No process control (Ctrl-C)
- Single terminal only

### After (TkTerm)
- 93 lines of code (40% reduction)
- Full terminal emulator
- Built-in command history
- Native shell behavior
- Full ANSI colors
- Tab completion on files
- Search with regex (Ctrl-F)
- Process kill (Ctrl-C)
- Tabbed terminals
- Multi-line command support

## Troubleshooting

**Terminal not loading?**
- Check that tkterm is installed: `pip show tkterm`
- Check logs: `tail -20 logs/app.log`

**Colors not working?**
- Ensure terminal supports ANSI escape codes
- Check TkTermConfig settings in code

**Tab completion not working?**
- Tab completion works on files/directories only
- Ensure you're in a valid directory

**Process won't stop?**
- Use Ctrl-C to send interrupt signal
- Some processes may ignore SIGINT

## Future Enhancements

Potential improvements:
- Custom shell selection (bash, zsh, fish, etc.)
- Persistent terminal sessions across widget reloads
- Custom color schemes via settings panel
- Command aliases and shortcuts
- Integration with Auger command history database
