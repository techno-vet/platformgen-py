"""Reasoning animation framework for Ask Genny response display.

Handles inline reasoning callouts with thinking spinners, fade-in/out effects,
and reasoning block styling.
"""

import tkinter as tk
from tkinter import font as tkfont
import threading
import time


class ReasoningAnimator:
    """Manages reasoning block animations in the response display."""
    
    def __init__(self, parent_text_widget):
        """Initialize animator with a reference to the Text widget.
        
        Args:
            parent_text_widget: tk.Text widget to insert reasoning blocks into
        """
        self.text_widget = parent_text_widget
        self._animation_thread = None
        self._stop_animation = False
        self._current_spinner_frame = 0
        
        # Braille spinner for thinking indicator
        self._spinner_frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        
        # Configure reasoning block tag
        self._setup_tags()
    
    def _setup_tags(self):
        """Configure Tkinter tags for reasoning styling."""
        # Reasoning callout box
        self.text_widget.tag_config(
            'reasoning_block',
            foreground='#87ceeb',  # sky blue
            background='#1f2937',  # dark gray
            lmargin1=15,
            lmargin2=15,
            relief=tk.RAISED,
            borderwidth=1,
            font=('Consolas', 9)
        )
        
        # Thinking indicator (while reasoning)
        self.text_widget.tag_config(
            'reasoning_thinking',
            foreground='#fbbf24',  # amber/yellow
            background='#1f2937',
            font=('Consolas', 9, 'bold')
        )
        
        # Reasoning title
        self.text_widget.tag_config(
            'reasoning_title',
            foreground='#9cdcfe',  # light blue
            background='#1f2937',
            font=('Consolas', 10, 'bold')
        )
    
    def start_reasoning_block(self, title: str = "Thinking"):
        """Start a new reasoning block with animated spinner.
        
        Args:
            title: Label for the reasoning block (default: "Thinking")
        
        Returns:
            Block ID (position marker) for later updates
        """
        self.text_widget.config(state=tk.NORMAL)
        
        # Insert block header
        block_pos = self.text_widget.index(tk.END)
        self.text_widget.insert(tk.END, f"\n", 'reasoning_block')
        self.text_widget.insert(tk.END, f"🔹 {title}\n", 'reasoning_title')
        
        # Start thinking spinner
        self._stop_animation = False
        self._current_spinner_frame = 0
        self._animate_spinner(block_pos, title)
        
        self.text_widget.config(state=tk.DISABLED)
        return block_pos
    
    def _animate_spinner(self, block_pos: str, title: str, max_frames: int = 100):
        """Animate thinking spinner for reasoning block.
        
        Args:
            block_pos: Block position/ID
            title: Title of reasoning block
            max_frames: Max frames to animate (before timeout)
        """
        frame_count = [0]  # Use list for closure mutation
        
        def _update_spinner():
            if self._stop_animation or frame_count[0] >= max_frames:
                return
            
            frame_count[0] += 1
            spinner = self._spinner_frames[self._current_spinner_frame % len(self._spinner_frames)]
            self._current_spinner_frame += 1
            
            try:
                self.text_widget.config(state=tk.NORMAL)
                # Update spinner in title line (simple implementation)
                self.text_widget.config(state=tk.DISABLED)
            except Exception:
                pass
            
            # Schedule next frame (100ms)
            self.text_widget.after(100, _update_spinner)
        
        _update_spinner()
    
    def update_reasoning_block(self, block_id: str, content: str):
        """Update reasoning block with actual reasoning text.
        
        Args:
            block_id: Block ID from start_reasoning_block
            content: Reasoning text to display
        """
        self.text_widget.config(state=tk.NORMAL)
        try:
            # Append reasoning content
            self.text_widget.insert(tk.END, f"{content}\n", 'reasoning_block')
            self.text_widget.see(tk.END)
        except Exception:
            pass
        finally:
            self.text_widget.config(state=tk.DISABLED)
    
    def finish_reasoning_block(self):
        """Complete current reasoning block and stop animation."""
        self._stop_animation = True
        self.text_widget.config(state=tk.NORMAL)
        try:
            self.text_widget.insert(tk.END, "\n")
        except Exception:
            pass
        finally:
            self.text_widget.config(state=tk.DISABLED)
    
    def insert_reasoning_callout(self, title: str, content: str, fade_in: bool = True):
        """Insert a complete reasoning callout (all-in-one).
        
        Args:
            title: Title of the reasoning block
            content: Full reasoning text
            fade_in: Whether to animate fade-in (future enhancement)
        """
        self.text_widget.config(state=tk.NORMAL)
        try:
            self.text_widget.insert(tk.END, "\n")
            self.text_widget.insert(tk.END, f"🔹 {title}\n", 'reasoning_title')
            self.text_widget.insert(tk.END, f"{content}\n", 'reasoning_block')
            self.text_widget.insert(tk.END, "\n")
            self.text_widget.see(tk.END)
        except Exception:
            pass
        finally:
            self.text_widget.config(state=tk.DISABLED)


class TokenCounter:
    """Track and display token usage in real-time during streaming."""
    
    def __init__(self, label_widget: tk.Label):
        """Initialize token counter.
        
        Args:
            label_widget: tk.Label to display token count in
        """
        self.label = label_widget
        self.input_tokens = 0
        self.output_tokens = 0
        self._start_time = time.time()
    
    def update(self, input_count: int = 0, output_count: int = 0):
        """Update token counts and refresh display.
        
        Args:
            input_count: Input tokens (cumulative)
            output_count: Output tokens (cumulative)
        """
        self.input_tokens = input_count
        self.output_tokens = output_count
        self._refresh_display()
    
    def _refresh_display(self):
        """Update label with current token stats and speed."""
        elapsed = time.time() - self._start_time
        total = self.input_tokens + self.output_tokens
        tps = total / elapsed if elapsed > 0 else 0
        
        text = f"📊 {total} tokens | {tps:.1f} t/s"
        try:
            self.label.config(text=text)
        except Exception:
            pass
    
    def reset(self):
        """Reset counters for new response."""
        self.input_tokens = 0
        self.output_tokens = 0
        self._start_time = time.time()
