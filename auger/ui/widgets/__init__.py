"""Auger UI Widgets package.

Widget Convention
-----------------
Every widget module must define:

    WIDGET_TITLE = "Human Readable Name"

And should define a PIL icon function for tab and header display:

    def make_icon(size=18, color="#2ea043"):
        \"\"\"Return a PIL RGBA Image at the given size/color.
        Used automatically for the tab icon and any widget header icon.
        Render at 2x and scale down for clean anti-aliasing (see make_drill_icon).
        \"\"\"
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ...
        return img

    class MyWidget(tk.Frame):
        WIDGET_TITLE    = "My Widget"
        WIDGET_ICON_FUNC = staticmethod(make_icon)

Optional attributes:
    WIDGET_ICON_COLOR  = "#hex"   # override the default green icon color
    WIDGET_SKIP_AUTO_OPEN = True  # don't auto-open on startup
"""
