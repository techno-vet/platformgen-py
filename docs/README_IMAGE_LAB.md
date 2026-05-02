# Image Lab Widget

The **Image Lab** widget is a PIL-powered image sandbox for generating, editing, and iterating on programmatic images directly inside Auger. It's primarily used for creating widget tab icons, platform artwork, and SRE dashboards.

## Features

| Feature | Detail |
|---------|--------|
| **Live preview** | See the image render in real time as you edit the code |
| **Code editor** | Edit PIL Python code directly in the widget |
| **Run** | Execute code and preview the result immediately |
| **Reset** | Return to the built-in SRE health gauge seed image |
| **Ask Auger** | Describe what you want; Auger writes the PIL code and runs it |
| **Copy code** | Copy generated code to use in a widget's `make_icon()` function |

## Seed Image

The default seed is an **SRE health gauge** — a dark-themed circular gauge with:
- Glowing ring and tick marks
- 75% sweep arc in green
- White needle
- Status labels (OK, WARN, CRIT)

## Generating Widget Icons

All Auger widgets can define a `make_icon(size, color)` function for their tab icon. Use Image Lab to develop and test icon code, then paste it into your widget:

```python
# Convention: every widget must define WIDGET_ICON_FUNC
def make_icon(size=18, color="#2ea043"):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0,0,0,0))
    d = ImageDraw.Draw(img)
    # ... your drawing code ...
    return img

class MyWidget(tk.Frame):
    WIDGET_ICON_FUNC = staticmethod(make_icon)
```

## Using Ask Auger

> *"Create a PIL icon for a Kubernetes pod — green circle with a 'k8s' hexagon"*
> *"Make a warning triangle icon in orange for a monitoring widget"*
> *"Iterate the health gauge to show 40% instead of 75%"*

Auger will generate the PIL code, execute it in Image Lab, and show you the result.
