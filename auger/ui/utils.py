"""Shared Tkinter UX utilities — copy/paste, right-click menus, mouse wheel."""
import os
import tkinter as tk
from tkinter import ttk
from pathlib import Path


def auger_home() -> Path:
    """Return the real user home directory.

    Inside the Docker container the personalized image sets AUGER_HOST_HOME
    and HOME correctly. This reads AUGER_HOST_HOME first (most reliable),
    then HOME, then falls back to Path.home() for venv/dev use.
    Never returns /home/auger — that is the legacy base-image path.
    """
    for var in ('AUGER_HOST_HOME', 'HOME'):
        val = os.environ.get(var)
        if val and val != '/home/auger':
            return Path(val)
    return Path.home()


def make_text_copyable(widget):
    """
    Make a tk.Text or scrolledtext.ScrolledText widget user-friendly:
    - Ctrl+C copies selection even in DISABLED state
    - Ctrl+A selects all
    - Right-click context menu: Copy / Select All
    - Mouse wheel scrolls
    Works on both editable and read-only (DISABLED) widgets.
    """
    def _copy(event=None):
        try:
            sel = widget.get(tk.SEL_FIRST, tk.SEL_LAST)
            widget.clipboard_clear()
            widget.clipboard_append(sel)
        except tk.TclError:
            pass
        return 'break'

    def _select_all(event=None):
        widget.tag_add(tk.SEL, '1.0', tk.END)
        widget.mark_set(tk.INSERT, '1.0')
        widget.see(tk.INSERT)
        return 'break'

    def _show_menu(event):
        menu = tk.Menu(widget, tearoff=0, bg='#2d2d2d', fg='#d4d4d4',
                       activebackground='#094771', activeforeground='white',
                       font=('Segoe UI', 9))
        menu.add_command(label='Copy',       command=_copy,       accelerator='Ctrl+C')
        menu.add_command(label='Select All', command=_select_all, accelerator='Ctrl+A')
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    widget.bind('<Control-c>', _copy)
    widget.bind('<Control-C>', _copy)
    widget.bind('<Control-a>', _select_all)
    widget.bind('<Control-A>', _select_all)
    widget.bind('<Button-3>', _show_menu)
    _bind_mousewheel(widget)


def bind_mousewheel(widget, target=None):
    """
    Bind mouse wheel scrolling to a widget. 
    `target` is the widget that actually scrolls (defaults to widget itself).
    Useful for Treeview/Listbox where the scroll target is the widget itself.
    """
    _bind_mousewheel(widget, target)


def _bind_mousewheel(widget, target=None):
    if target is None:
        target = widget

    def _on_wheel(event):
        # Linux uses Button-4 (up) and Button-5 (down)
        if event.num == 4:
            target.yview_scroll(-2, 'units')
        elif event.num == 5:
            target.yview_scroll(2, 'units')
        else:
            # Windows/Mac delta
            target.yview_scroll(int(-1 * (event.delta / 120)), 'units')

    widget.bind('<Button-4>', _on_wheel, add='+')
    widget.bind('<Button-5>', _on_wheel, add='+')
    widget.bind('<MouseWheel>', _on_wheel, add='+')


def add_listbox_menu(listbox):
    """Right-click context menu for Listbox: Copy selected item(s)."""
    def _copy(event=None):
        try:
            items = [listbox.get(i) for i in listbox.curselection()]
            if items:
                listbox.clipboard_clear()
                listbox.clipboard_append('\n'.join(items))
        except tk.TclError:
            pass

    def _show_menu(event):
        menu = tk.Menu(listbox, tearoff=0, bg='#2d2d2d', fg='#d4d4d4',
                       activebackground='#094771', activeforeground='white',
                       font=('Segoe UI', 9))
        menu.add_command(label='Copy', command=_copy, accelerator='Ctrl+C')
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    listbox.bind('<Button-3>', _show_menu)
    listbox.bind('<Control-c>', lambda e: _copy())
    listbox.bind('<Control-C>', lambda e: _copy())
    _bind_mousewheel(listbox)


def add_treeview_menu(tree):
    """Right-click context menu for Treeview: Copy selected row values."""
    def _copy(event=None):
        try:
            items = []
            for iid in tree.selection():
                vals = tree.item(iid, 'values')
                items.append('\t'.join(str(v) for v in vals))
            if items:
                tree.clipboard_clear()
                tree.clipboard_append('\n'.join(items))
        except tk.TclError:
            pass

    def _show_menu(event):
        menu = tk.Menu(tree, tearoff=0, bg='#2d2d2d', fg='#d4d4d4',
                       activebackground='#094771', activeforeground='white',
                       font=('Segoe UI', 9))
        menu.add_command(label='Copy Row', command=_copy, accelerator='Ctrl+C')
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    tree.bind('<Button-3>', _show_menu)
    tree.bind('<Control-c>', lambda e: _copy())
    tree.bind('<Control-C>', lambda e: _copy())
    _bind_mousewheel(tree)
