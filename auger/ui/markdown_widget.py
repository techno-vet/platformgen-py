"""Dark-themed Markdown rendering Text widget."""

import tkinter as tk
from tkinter import font as tkfont
import re


class MarkdownWidget(tk.Text):
    """A Text widget that renders basic Markdown with a dark theme."""
    
    def __init__(self, parent, **kwargs):
        # Dark theme defaults
        defaults = {
            'bg': '#1a1a2e',
            'fg': '#e0e0e0',
            'insertbackground': '#e0e0e0',
            'selectbackground': '#264f78',
            'selectforeground': '#ffffff',
            'relief': tk.FLAT,
            'wrap': tk.WORD,
            'font': ('Consolas', 10),
        }
        defaults.update(kwargs)
        super().__init__(parent, **defaults)
        
        self._setup_tags()
    
    def _setup_tags(self):
        """Configure text tags for markdown styling."""
        # Headers
        self.tag_config('h1', foreground='#4ec9b0', font=('Segoe UI', 22, 'bold'))
        self.tag_config('h2', foreground='#4ec9b0', font=('Segoe UI', 17, 'bold'))
        self.tag_config('h3', foreground='#9cdcfe', font=('Segoe UI', 13, 'bold'))
        
        # Text styles
        self.tag_config('bold', font=('Consolas', 10, 'bold'))
        self.tag_config('italic', font=('Consolas', 10, 'italic'))
        self.tag_config('bold_italic', font=('Consolas', 10, 'bold italic'))
        
        # Code
        self.tag_config('inline_code', 
                       foreground='#ce9178',
                       background='#2d2d2d',
                       font=('Consolas', 9))
        self.tag_config('code_block',
                       foreground='#dcdcaa',
                       background='#111111',
                       font=('Consolas', 9),
                       lmargin1=10,
                       lmargin2=10)
        
        # Lists
        self.tag_config('bullet', lmargin1=20, lmargin2=40)
        
        # Blockquote
        self.tag_config('blockquote',
                       foreground='#808080',
                       font=('Consolas', 10, 'italic'),
                       lmargin1=20,
                       lmargin2=20)
        
        # Horizontal rule
        self.tag_config('hr', foreground='#3c3c3c')
        
        # Custom tags
        self.tag_config('ok', foreground='#4ec9b0')
        self.tag_config('err', foreground='#f44747')
        self.tag_config('info', foreground='#9cdcfe')
    
    def append_markdown(self, text, scroll=True):
        """Append text with markdown rendering."""
        self.config(state=tk.NORMAL)
        
        lines = text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Code blocks
            if line.strip().startswith('```'):
                code_lines = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith('```'):
                    code_lines.append(lines[i])
                    i += 1
                if code_lines:
                    self.insert(tk.END, '\n'.join(code_lines) + '\n', 'code_block')
                i += 1
                continue
            
            # Headers
            if line.startswith('# '):
                self.insert(tk.END, line[2:] + '\n', 'h1')
            elif line.startswith('## '):
                self.insert(tk.END, line[3:] + '\n', 'h2')
            elif line.startswith('### '):
                self.insert(tk.END, line[4:] + '\n', 'h3')
            
            # Horizontal rule
            elif line.strip() in ('---', '***', '___'):
                self.insert(tk.END, '─' * 80 + '\n', 'hr')
            
            # Blockquote
            elif line.startswith('> '):
                self.insert(tk.END, line[2:] + '\n', 'blockquote')
            
            # Bullet lists
            elif line.strip().startswith(('- ', '* ')):
                content = line.strip()[2:]
                self._render_inline(f"• {content}\n", 'bullet')
            
            # Regular text with inline formatting
            else:
                self._render_inline(line + '\n')
            
            i += 1

        if scroll:
            self.see(tk.END)
        self.config(state=tk.DISABLED)
    
    def _render_inline(self, text, base_tag=''):
        """Render inline markdown styles."""
        # Inline code
        parts = re.split(r'(`[^`]+`)', text)
        for part in parts:
            if part.startswith('`') and part.endswith('`'):
                self.insert(tk.END, part[1:-1], 'inline_code')
            else:
                # Bold italic
                subparts = re.split(r'(\*\*\*[^*]+\*\*\*)', part)
                for subpart in subparts:
                    if subpart.startswith('***') and subpart.endswith('***'):
                        self.insert(tk.END, subpart[3:-3], 'bold_italic' if not base_tag else (base_tag, 'bold_italic'))
                    else:
                        # Bold
                        boldparts = re.split(r'(\*\*[^*]+\*\*)', subpart)
                        for boldpart in boldparts:
                            if boldpart.startswith('**') and boldpart.endswith('**'):
                                self.insert(tk.END, boldpart[2:-2], 'bold' if not base_tag else (base_tag, 'bold'))
                            else:
                                # Italic
                                italparts = re.split(r'(\*[^*]+\*)', boldpart)
                                for italpart in italparts:
                                    if italpart.startswith('*') and italpart.endswith('*'):
                                        self.insert(tk.END, italpart[1:-1], 'italic' if not base_tag else (base_tag, 'italic'))
                                    else:
                                        self.insert(tk.END, italpart, base_tag if base_tag else ())


    def append_raw(self, text, tag='', scroll=True):
        """Append text without markdown processing."""
        self.config(state=tk.NORMAL)
        self.insert(tk.END, text, tag)
        self.config(state=tk.DISABLED)
        if scroll:
            self.see(tk.END)

    def clear(self):
        """Clear all text."""
        self.config(state=tk.NORMAL)
        self.delete('1.0', tk.END)
        self.config(state=tk.DISABLED)
