"""Shared PIL-based icon factory for Auger UI widgets.

Keeps a module-level cache so PhotoImage objects are not garbage collected.
"""

from PIL import Image, ImageDraw, ImageFont
from PIL import ImageTk
import math
from pathlib import Path

# Module-level cache: (name, size) -> PhotoImage
_cache: dict = {}
_ASSET_DIR = Path(__file__).resolve().parent / "assets"
_APP_ICON_ASSET = _ASSET_DIR / "auger_app_icon.png"


def get(name: str, size: int = 16) -> "ImageTk.PhotoImage":
    """Return a cached PhotoImage for the given icon name and size."""
    key = (name, size)
    if key not in _cache:
        img = _draw(name, size)
        _cache[key] = ImageTk.PhotoImage(img)
    return _cache[key]


# ---------------------------------------------------------------------------
# Internal drawing helpers
# ---------------------------------------------------------------------------

def _new(size):
    return Image.new("RGBA", (size, size), (0, 0, 0, 0))


def _draw(name: str, size: int) -> Image.Image:
    fn = _ICONS.get(name)
    if fn is None:
        return _icon_placeholder(size, name[:2].upper())
    return fn(size)


# ---------------------------------------------------------------------------
# Color palette (VS Code Dark+ inspired)
# ---------------------------------------------------------------------------
BLUE   = "#4fc1ff"
DBLUE  = "#007acc"
GREEN  = "#4ec9b0"
DGREEN = "#6a9955"
YELLOW = "#dcdcaa"
ORANGE = "#ce9178"
RED    = "#f44747"
GRAY   = "#858585"
LGRAY  = "#cccccc"
PURPLE = "#c586c0"
TEAL   = "#4ec9b0"
WHITE  = "#ffffff"
BG     = "#252526"


# ---------------------------------------------------------------------------
# Widget / tab icons  (22 px default)
# ---------------------------------------------------------------------------

def _icon_terminal(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    # dark rectangle background
    d.rounded_rectangle([1, 1, s-2, s-2], radius=3, fill="#1e1e1e", outline=DBLUE, width=1)
    # "> " prompt
    m = max(2, s // 8)
    d.polygon([(m+1, s//3), (m+1, s*2//3), (s//2-m, s//2)], fill=GREEN)
    # underline cursor
    cx = s//2
    d.rectangle([cx, s//2+1, cx+s//4, s//2+2], fill=LGRAY)
    return img


def _icon_key(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    r = s // 4
    # circle (bow)
    d.ellipse([2, 2, 2+r*2, 2+r*2], outline=YELLOW, width=2)
    # shaft
    cx = 2 + r
    d.rectangle([cx, 2+r, s-3, 2+r+2], fill=YELLOW)
    # teeth
    d.rectangle([s-5, 2+r, s-3, 2+r+s//6], fill=YELLOW)
    d.rectangle([s-8, 2+r, s-6, 2+r+s//8], fill=YELLOW)
    return img


def _icon_box(s):
    """Package/box icon for Artifactory."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = s // 6
    # bottom box
    d.rectangle([m, s//2, s-m, s-m], outline=BLUE, fill="#1a3a55", width=1)
    # top lid
    d.polygon([(m, s//2), (s//2, s//4), (s-m, s//2), (s//2, s*3//4)], outline=BLUE, fill="#1a3a55", width=1)
    # shine line on lid
    d.line([(s//2, s//4+2), (s-m-2, s//2-2)], fill=BLUE, width=1)
    return img


def _icon_wrench(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    # wrench body (rotated rectangle at 45°)
    cx, cy = s//2, s//2
    hw = max(2, s//8)
    pts = [
        (cx - hw, cy - s//3),
        (cx + hw, cy - s//3),
        (cx + hw + s//4, cy + s//3),
        (cx - hw + s//4, cy + s//3),
    ]
    d.polygon(pts, fill=GRAY)
    # head circle
    d.ellipse([2, 2, s//2+1, s//2+1], outline=GRAY, fill="#3a3a3a", width=2)
    # handle diagonal
    d.line([(s//2-1, s//2-1), (s-3, s-3)], fill=GRAY, width=max(2, s//6))
    return img


def _icon_ticket(s):
    """ServiceNow ticket icon."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = s // 8
    # ticket shape with notch
    d.rounded_rectangle([m, m*2, s-m, s-m*2], radius=2, fill="#1a3050", outline=DBLUE, width=1)
    # horizontal lines (text)
    for y in [m*3, m*4+1, m*5+2]:
        if y < s - m*2:
            d.rectangle([m*2, y, s-m*2, y+1], fill=BLUE)
    # small ticket notch
    nw = s // 5
    d.ellipse([s-m-nw, s//2-nw//2, s-m, s//2+nw//2], fill=BG)
    d.ellipse([m-nw//2, s//2-nw//2, m+nw//2, s//2+nw//2], fill=BG)
    return img


def _icon_rocket(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    cx = s // 2
    # body
    d.polygon([(cx, 1), (cx+s//4, s*2//3), (cx-s//4, s*2//3)], fill=ORANGE)
    # nose
    d.polygon([(cx, 1), (cx+s//5, s//3), (cx-s//5, s//3)], fill=LGRAY)
    # fins
    d.polygon([(cx-s//4, s*2//3), (cx-s//3, s-3), (cx-s//8, s*2//3)], fill=RED)
    d.polygon([(cx+s//4, s*2//3), (cx+s//3, s-3), (cx+s//8, s*2//3)], fill=RED)
    # flame
    d.ellipse([cx-s//8, s*2//3-1, cx+s//8, s-2], fill=YELLOW)
    return img


def _icon_search(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    r = s * 5 // 16
    cx, cy = s * 5 // 12, s * 5 // 12
    d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=BLUE, width=max(2, s//8))
    hw = max(1, s//8)
    d.line([(cx+r-hw, cy+r-hw), (s-3, s-3)], fill=BLUE, width=max(2, s//8))
    return img


def _icon_radar(s):
    """Panner/radar icon."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    cx, cy = s//2, s//2
    for r, alpha in [(s//2-2, 60), (s//3, 100), (s//6, 160)]:
        d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=GREEN+"aa", width=1)
    # sweep line
    d.line([(cx, cy), (cx+s//3, cy-s//3)], fill=GREEN, width=1)
    d.ellipse([cx-2, cy-2, cx+2, cy+2], fill=GREEN)
    return img


def _icon_pods(s):
    """Pods/containers icon."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = s // 6
    hw = (s - m*3) // 2
    # three small boxes
    for i, (x, y) in enumerate([(m, m), (m+hw+m, m), (m, m+hw+m)]):
        d.rounded_rectangle([x, y, x+hw, y+hw], radius=1,
                             fill="#1a3050", outline=BLUE, width=1)
    # plus in bottom-right
    cx2, cy2 = m+hw+m + hw//2, m+hw+m + hw//2
    d.rectangle([cx2-1, cy2-hw//3, cx2+1, cy2+hw//3], fill=GREEN)
    d.rectangle([cx2-hw//3, cy2-1, cx2+hw//3, cy2+1], fill=GREEN)
    return img


def _icon_branch(s):
    """GitHub branch/fork icon."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    r = max(2, s//8)
    # two commit dots + merge
    d.ellipse([s//4-r, r, s//4+r, r+r*2], fill=GREEN)
    d.ellipse([s*3//4-r, r, s*3//4+r, r+r*2], fill=GREEN)
    d.ellipse([s//4-r, s-r*3, s//4+r, s-r], fill=GREEN)
    # connecting lines
    d.line([(s//4, r+r*2), (s//4, s-r*3)], fill=GREEN, width=1)
    d.line([(s//4, r+r), (s*3//4, r+r)], fill=DGREEN, width=1)
    d.line([(s*3//4, r+r), (s//4, s-r*2)], fill=DGREEN, width=1)
    return img


def _icon_database(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = s // 6
    h = s // 4
    # cylinder: top ellipse + rect body + bottom ellipse
    d.ellipse([m, m, s-m, m+h], fill="#1a4040", outline=TEAL, width=1)
    d.rectangle([m, m+h//2, s-m, s-m-h//2], fill="#1a4040")
    d.rectangle([m, m+h//2, s-m, m+h//2+1], fill=TEAL)  # rim line
    d.ellipse([m, s-m-h, s-m, s-m], fill="#1a4040", outline=TEAL, width=1)
    # highlight stripes
    for i in range(2):
        y = m + h + i * (s // 5)
        if y < s - m - h:
            d.rectangle([m+2, y, s-m-2, y+1], fill=TEAL)
    return img


def _icon_docker(s):
    """Docker whale icon."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    # body of whale (simplified)
    bw = s * 2 // 3
    bh = s // 3
    bx = s // 8
    by = s // 3
    d.rounded_rectangle([bx, by, bx+bw, by+bh], radius=bh//3, fill=BLUE)
    # containers on top
    cw = bw // 4
    ch = bh // 2
    for i in range(3):
        cx2 = bx + i * (cw + 2) + 2
        d.rectangle([cx2, by-ch, cx2+cw-2, by], outline=WHITE, fill=DBLUE, width=1)
    # spout
    d.ellipse([bx+bw-4, by-s//5, bx+bw+2, by], fill=BLUE)
    # tail
    d.polygon([(bx, by+bh//2), (1, by+bh+2), (bx+s//6, by+bh-2)], fill=BLUE)
    return img


def _icon_placeholder(s, text="??"):
    img = _new(s)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, s-2, s-2], radius=3, fill=BG, outline=GRAY, width=1)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                                  max(7, s // 3))
    except Exception:
        font = ImageFont.load_default()
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((s - tw) // 2, (s - th) // 2 - bb[1]), text, font=font, fill=LGRAY)
    return img


# ---------------------------------------------------------------------------
# Action / button icons  (16 px default)
# ---------------------------------------------------------------------------

def _icon_refresh(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    r = s // 2 - 2
    cx = cy = s // 2
    d.arc([cx-r, cy-r, cx+r, cy+r], 50, 310, fill=BLUE, width=max(2, s//7))
    # arrowhead
    ang = math.radians(50)
    ax = int(cx + r * math.cos(ang))
    ay = int(cy + r * math.sin(ang))
    d.polygon([(ax-3, ay-1), (ax+2, ay-3), (ax+1, ay+3)], fill=BLUE)
    return img


def _icon_download(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    cx = s // 2
    # vertical line
    d.rectangle([cx-1, 2, cx+1, s*2//3], fill=GREEN)
    # arrowhead pointing down
    hw = s // 3
    d.polygon([(cx-hw, s//2), (cx+hw, s//2), (cx, s*3//4)], fill=GREEN)
    # base line
    d.rectangle([2, s-3, s-2, s-1], fill=GREEN)
    return img


def _icon_upload(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    cx = s // 2
    # vertical line
    d.rectangle([cx-1, s//4, cx+1, s-4], fill=ORANGE)
    # arrowhead pointing up
    hw = s // 3
    d.polygon([(cx-hw, s//2), (cx+hw, s//2), (cx, s//4)], fill=ORANGE)
    # base line
    d.rectangle([2, s-3, s-2, s-1], fill=ORANGE)
    return img


def _icon_play(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = s // 5
    d.polygon([(m, m), (m, s-m), (s-m, s//2)], fill=GREEN)
    return img


def _icon_edit(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    # pencil body (diagonal rectangle)
    pts = [
        (s//4, s-s//4),
        (s*3//4, s//4),
        (s-s//4, s//2),
        (s//2, s-s//8),
    ]
    d.polygon(pts, fill=YELLOW)
    # tip
    d.polygon([(s//4, s-s//4), (s//2, s-s//8), (s//3, s-2)], fill=LGRAY)
    # top rectangle (eraser area)
    d.rectangle([s*3//4-1, s//4-2, s*3//4+3, s//4+4], fill=RED)
    return img


def _icon_delete(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = s // 5
    # trash can body
    d.rectangle([m, m*2, s-m, s-m], outline=RED, fill="#3a1a1a", width=1)
    # lid
    d.rectangle([m-1, m, s-m+1, m*2], fill=RED)
    # handle on lid
    d.rectangle([s//2-s//6, m-2, s//2+s//6, m], outline=RED, width=1)
    # vertical lines inside
    for x in [s//3, s//2, s*2//3]:
        d.line([(x, m*2+2), (x, s-m-2)], fill=RED, width=1)
    return img


def _icon_copy(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    o = s // 4  # offset
    # back rectangle
    d.rectangle([o, o, s-2, s-2], outline=BLUE, fill="#1a2a3a", width=1)
    # front rectangle (offset)
    d.rectangle([2, 2, s-o-1, s-o-1], outline=BLUE, fill="#1e2a40", width=1)
    return img


def _icon_add(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    r = s // 2 - 2
    cx = cy = s // 2
    d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=GREEN, width=1)
    hw = r - 2
    d.rectangle([cx-1, cy-hw, cx+1, cy+hw], fill=GREEN)
    d.rectangle([cx-hw, cy-1, cx+hw, cy+1], fill=GREEN)
    return img


def _icon_check(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    r = s // 2 - 1
    cx = cy = s // 2
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill="#1a3a1a", outline=GREEN, width=1)
    hw = r - 2
    d.line([(cx-hw, cy), (cx-1, cy+hw-1), (cx+hw, cy-hw+1)], fill=GREEN, width=2)
    return img


def _icon_error(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    r = s // 2 - 1
    cx = cy = s // 2
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill="#3a1a1a", outline=RED, width=1)
    m = r - 2
    d.line([(cx-m, cy-m), (cx+m, cy+m)], fill=RED, width=2)
    d.line([(cx+m, cy-m), (cx-m, cy+m)], fill=RED, width=2)
    return img


def _icon_warning(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    cx = s // 2
    # triangle
    d.polygon([(cx, 1), (s-2, s-2), (2, s-2)], fill="#3a2a00", outline=YELLOW, width=1)
    # exclamation
    d.rectangle([cx-1, s//3, cx+1, s*2//3], fill=YELLOW)
    d.ellipse([cx-1, s*3//4, cx+1, s*3//4+2], fill=YELLOW)
    return img


def _icon_connect(s):
    """Login / connect icon."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    # person silhouette
    r = s // 5
    cx = s // 3
    d.ellipse([cx-r, 1, cx+r, 1+r*2], fill=BLUE)
    d.rounded_rectangle([cx-r-1, r*2+2, cx+r+1, s-2], radius=r, fill=BLUE)
    # arrow pointing right (login arrow)
    ax = s*2//3
    d.line([(ax, s//2), (s-2, s//2)], fill=GREEN, width=2)
    d.polygon([(s-4, s//2-3), (s-1, s//2), (s-4, s//2+3)], fill=GREEN)
    return img


def _icon_folder(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = s // 8
    # tab
    d.rectangle([m, m*2, s//3, m*3], fill="#2a2000", outline=YELLOW, width=1)
    # body
    d.rectangle([m, m*3, s-m, s-m], fill="#2a2000", outline=YELLOW, width=1)
    return img


def _icon_explorer(s):
    """Explorer widget icon — folder tree with branch lines."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = max(2, s // 10)
    col_x = m + s // 5       # vertical spine x
    fold = max(2, s // 6)    # folder tab width

    # ── Root folder (top) ─────────────────────────────────────────
    fy = m
    fh = s // 5
    fw = s - m - col_x - m
    # tab
    d.rectangle([col_x + m, fy, col_x + m + fold, fy + max(2, fh//3)],
                fill="#2a2000", outline=YELLOW, width=1)
    # body
    d.rectangle([col_x + m, fy + max(2, fh//3), col_x + m + fw, fy + fh],
                fill="#2a2000", outline=YELLOW, width=1)

    # ── Branch lines from spine ────────────────────────────────────
    mid_root = fy + fh // 2
    row2_y = m + s * 2 // 5
    row3_y = m + s * 3 // 5
    row4_y = m + s * 4 // 5

    # Vertical spine
    d.rectangle([col_x, mid_root, col_x + 1, row4_y], fill=GREEN)

    for row_y in (row2_y, row3_y, row4_y):
        # horizontal branch to item
        d.rectangle([col_x, row_y, col_x + m + 2, row_y + 1], fill=GREEN)
        ix = col_x + m + 3
        iw = s - m - ix
        ih = max(3, s // 7)

        if row_y == row2_y:
            # Sub-folder
            d.rectangle([ix, row_y - 1, ix + iw // 2, row_y],
                        fill="#2a2000", outline=YELLOW, width=1)
            d.rectangle([ix, row_y, ix + iw, row_y + ih],
                        fill="#2a2000", outline=YELLOW, width=1)
        else:
            # File
            fold2 = max(2, iw // 4)
            pts = [(ix, row_y - 1), (ix + iw - fold2, row_y - 1),
                   (ix + iw, row_y + fold2), (ix + iw, row_y + ih),
                   (ix, row_y + ih)]
            d.polygon(pts, fill="#1e2a3a", outline=LGRAY, width=1)
    return img


def _icon_file(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = s // 6
    fold = s // 4
    # page with folded corner
    pts = [(m, m), (s-m-fold, m), (s-m, m+fold), (s-m, s-m), (m, s-m)]
    d.polygon(pts, fill="#1e2a3a", outline=LGRAY, width=1)
    # fold triangle
    d.polygon([(s-m-fold, m), (s-m-fold, m+fold), (s-m, m+fold)], fill=GRAY)
    # lines
    for y in [m*3, m*4, m*5]:
        if y < s - m:
            d.rectangle([m+2, y, s-m-2, y+1], fill=GRAY)
    return img


def _icon_shield(s):
    """Shield / security / cryptkeeper icon."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    cx = s // 2
    m = max(2, s // 8)
    # shield outline
    pts = [(cx, m), (s-m, m*2), (s-m, s*3//5), (cx, s-m), (m, s*3//5), (m, m*2)]
    d.polygon(pts, fill="#1a1a40", outline=DBLUE, width=1)
    # lock symbol inside
    kr = s // 6
    kx, ky = cx, s * 2 // 5
    d.ellipse([kx-kr, ky-kr*2, kx+kr, ky-kr//2], outline=YELLOW, width=max(1, s//10))
    d.rectangle([kx-kr, ky-kr//2, kx+kr, ky+kr], fill="#1a1a40", outline=YELLOW, width=1)
    d.ellipse([kx-2, ky-2, kx+2, ky+2], fill=YELLOW)
    return img


def _icon_lightning(s):
    """Lightning bolt for Cryptkeeper Lite."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = s // 5
    # bolt shape
    pts = [
        (s*2//3, m),          # top right
        (s//2, s//2),         # middle
        (s*3//4-1, s//2),     # middle right notch
        (s//3, s-m),          # bottom left
        (s//2, s//2+1),       # middle again
        (s//4+1, s//2+1),     # middle left notch
    ]
    d.polygon(pts, fill="#ffe000", outline="#cc9900", width=1)
    return img


def _icon_home(s):
    """House / home icon."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    cx = s // 2
    m = max(2, s // 8)
    # roof (triangle)
    d.polygon([(cx, m), (s-m, s//2), (m, s//2)], fill="#1a3050", outline=BLUE, width=1)
    # body (rectangle)
    w = s * 3 // 8
    d.rectangle([cx-w//2, s//2, cx+w//2, s-m], fill="#1a3050", outline=BLUE, width=1)
    # door
    dw = s // 6
    d.rectangle([cx-dw//2, s*3//4, cx+dw//2, s-m], fill=DBLUE)
    return img


def _icon_cve(s):
    """CVE / magnifier + bug icon for Prospector."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    # magnifier
    r = s * 5 // 16
    cx, cy = s * 4 // 10, s * 4 // 10
    d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=ORANGE, width=max(2, s//8))
    d.line([(cx+r-1, cy+r-1), (s-3, s-3)], fill=ORANGE, width=max(2, s//8))
    # bug dot inside lens
    br = max(2, r//3)
    d.ellipse([cx-br, cy-br, cx+br, cy+br], fill=RED)
    return img


def _icon_release(s):
    """Rocket icon - same as _icon_rocket, alias."""
    return _icon_rocket(s)


def _icon_bash(s):
    """Bash/shell prompt icon."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, s-2, s-2], radius=3, fill="#0d1117", outline=GREEN, width=1)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            max(6, s * 5 // 12))
    except Exception:
        font = ImageFont.load_default()
    text = "$"
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((s - tw) // 2 - bb[0], (s - th) // 2 - bb[1]), text, font=font, fill=GREEN)
    return img


def _icon_lock(s):
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = s // 5
    bh = s // 3
    # shackle arc
    d.arc([m+2, m-2, s-m-2, s//2], 180, 0, fill=YELLOW, width=max(2, s//7))
    # body
    d.rectangle([m, s//2, s-m, s-m], fill="#2a2000", outline=YELLOW, width=1)
    # keyhole
    cx = s//2
    kr = s//8
    d.ellipse([cx-kr, s//2+kr, cx+kr, s//2+kr*3], fill=YELLOW)
    d.rectangle([cx-1, s//2+kr*2, cx+1, s-m-2], fill=YELLOW)
    return img


def _icon_settings(s):
    """Gear/settings icon."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    cx = cy = s // 2
    r_outer = s // 2 - 2
    r_inner = s // 2 - 2 - max(2, s//6)
    r_hole = s // 5
    # gear teeth (8 teeth via polygon)
    pts = []
    teeth = 8
    for i in range(teeth * 2):
        angle = math.radians(i * 180 / teeth)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d.polygon(pts, fill=GRAY)
    # center hole
    d.ellipse([cx-r_hole, cy-r_hole, cx+r_hole, cy+r_hole], fill=(0, 0, 0, 0))
    return img


def _icon_apps_grid(s):
    """2x2 app launcher grid — represents 'host applications/tools'."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    pad = max(2, s // 8)
    gap = max(2, s // 8)
    cell = (s - 2 * pad - gap) // 2
    # 4 rounded tiles in a 2x2 grid, each a different accent color
    tile_colors = [DBLUE, GREEN, ORANGE, PURPLE]
    positions = [
        (pad,           pad),
        (pad + cell + gap, pad),
        (pad,           pad + cell + gap),
        (pad + cell + gap, pad + cell + gap),
    ]
    r = max(2, cell // 5)
    for (x, y), col in zip(positions, tile_colors):
        d.rounded_rectangle([x, y, x + cell, y + cell], radius=r, fill=col)
    return img


def _icon_book(s):
    """Open book icon — for Help widget."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    pad = max(1, s // 10)
    cx = s // 2
    # Book cover: two pages side by side with a spine in the center
    # Left page
    d.rounded_rectangle([pad, pad, cx - 1, s - pad - 1], radius=max(1, s//10), fill=DBLUE)
    # Right page
    d.rounded_rectangle([cx + 1, pad, s - pad - 1, s - pad - 1], radius=max(1, s//10), fill=BLUE)
    # Spine
    d.rectangle([cx - 1, pad, cx + 1, s - pad - 1], fill=LGRAY)
    # Lines on right page (text lines)
    lpad = cx + max(2, s // 8)
    for row in range(3):
        y = pad + max(3, s // 5) + row * max(3, s // 6)
        if y + 1 < s - pad:
            d.rectangle([lpad, y, s - pad - max(3, s//8), y + max(1, s//16)], fill=LGRAY)
    # Lines on left page
    for row in range(3):
        y = pad + max(3, s // 5) + row * max(3, s // 6)
        if y + 1 < s - pad:
            d.rectangle([pad + max(2, s//8), y, cx - max(3, s//8), y + max(1, s//16)], fill=LGRAY)
    return img


def _icon_prompts(s):
    """Prompts widget icon — document with a lightning bolt overlay."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = max(2, s // 8)
    fold = max(3, s // 5)

    # Page body with folded corner
    pts = [(m, m), (s - m - fold, m), (s - m, m + fold),
           (s - m, s - m), (m, s - m)]
    d.polygon(pts, fill="#1e2a3a", outline=LGRAY, width=1)
    d.polygon([(s - m - fold, m), (s - m - fold, m + fold), (s - m, m + fold)],
              fill=GRAY)

    # Text lines (left side of page, leaving room for bolt on right)
    lx1 = m + max(2, s // 8)
    lx2 = s * 5 // 10
    for i, y in enumerate([m * 4, m * 5, m * 6, m * 7]):
        if y + 1 < s - m:
            d.rectangle([lx1, y, lx2 if i < 3 else lx2 - m, y + max(1, s // 18)],
                        fill=GRAY)

    # Lightning bolt (right half, centered)
    bx = s * 6 // 10
    by = m * 3
    bw = s - m - 2 - bx
    bh = s - m - 2 - by
    # Top half of bolt (pointing down-left)
    top = [(bx + bw // 2, by),
           (bx, by + bh // 2),
           (bx + bw * 2 // 3, by + bh // 2)]
    # Bottom half of bolt (pointing down-left)
    bot = [(bx + bw * 2 // 3, by + bh // 2),
           (bx + bw, by + bh // 2),
           (bx + bw // 2, by + bh)]
    d.polygon(top + bot, fill=YELLOW, outline=YELLOW)
    return img



def _icon_jira(s):
    """Jira icon — blue rounded square with white 'J' inside."""
    img = _new(s)
    d = ImageDraw.Draw(img)
    m = max(1, s // 8)
    r = max(3, s // 5)   # corner radius
    # Blue rounded rectangle background (#0052CC Jira blue)
    # Draw as filled rounded rect via ellipses + rectangles
    fill = "#0052CC"
    d.rounded_rectangle([m, m, s - m, s - m], radius=r, fill=fill)
    # White 'J' shape: vertical bar + bottom curl
    jx = s * 3 // 8      # left x of J stem
    jx2 = s * 5 // 8     # right x of J stem
    jy1 = s * 2 // 8     # top of J
    jy2 = s * 7 // 8     # bottom of J arc
    jmid = s * 5 // 8    # mid y where curl starts
    thick = max(2, s // 6)
    # Vertical bar of J
    d.rectangle([jx, jy1, jx + thick, jmid], fill=WHITE)
    # Bottom arc / curl of J (as a filled arc)
    arc_box = [m + max(1, s // 8), jmid - thick // 2,
               jx + thick + max(2, s // 6), jy2]
    d.arc(arc_box, start=180, end=360, fill=WHITE, width=max(2, s // 6))
    return img


# ---------------------------------------------------------------------------
# Auger app icon — drill bit, used for window titlebar + dock
# ---------------------------------------------------------------------------

def make_drill_icon(size: int = 64, color: str = "#2ea043") -> Image.Image:
    """Auger A-lettermark icon with drill tip — works at 16px to 256px.
    Rendered at 2x then scaled for natural anti-aliasing.
    Tagline: Drill Down With Auger.
    """
    RENDER = size * 2
    img = Image.new("RGBA", (RENDER, RENDER), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    sc  = RENDER / 64.0

    def p(x, y): return (int(x * sc), int(y * sc))
    def s(v):    return max(1, int(v * sc))

    # Dark navy rounded-square background
    d.rounded_rectangle([s(2), s(2), RENDER-s(2), RENDER-s(2)],
                        radius=s(10), fill="#1a2332")

    cx = RENDER // 2
    apex   = p(32, 10)
    bl     = p(10, 53)
    br     = p(54, 53)
    stroke = s(7)

    d.line([apex, bl], fill=color, width=stroke)   # left leg
    d.line([apex, br], fill=color, width=stroke)   # right leg

    # Crossbar at 50% height
    t  = 0.50
    lx = int(apex[0] + (bl[0] - apex[0]) * t)
    ly = int(apex[1] + (bl[1] - apex[1]) * t)
    rx = int(apex[0] + (br[0] - apex[0]) * t)
    ry = int(apex[1] + (br[1] - apex[1]) * t)
    d.line([(lx, ly), (rx, ry)], fill=color, width=s(5))

    # Drill shaft + tip below A baseline
    base_y = p(32, 53)[1]
    shft_y = p(32, 58)[1]
    tip_y  = RENDER - s(3)
    d.line([(cx, base_y), (cx, shft_y)], fill=color, width=s(5))
    d.polygon([
        (cx - s(5), shft_y),
        (cx + s(5), shft_y),
        (cx,        tip_y),
    ], fill="#ffffff")

    return img.resize((size, size), Image.LANCZOS)


def install_app_icon(icon_path: str = None) -> str:
    """Save the bundled Auger app icon to icon_path (default ~/.local/share/icons/)."""
    if icon_path is None:
        dest = Path.home() / ".local" / "share" / "icons" / "auger-platform.png"
    else:
        dest = Path(icon_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _APP_ICON_ASSET.exists():
        with Image.open(_APP_ICON_ASSET) as img:
            img.convert("RGBA").resize((256, 256), Image.LANCZOS).save(str(dest))
    else:
        make_drill_icon(256, "#2ea043").save(str(dest))
    return str(dest)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_ICONS = {
    # Widget/tab icons
    "terminal":    _icon_terminal,
    "key":         _icon_key,
    "box":         _icon_box,
    "artifactory": _icon_box,
    "wrench":      _icon_wrench,
    "tools":       _icon_apps_grid,
    "host_tools":  _icon_apps_grid,
    "apps":        _icon_apps_grid,
    "grid":        _icon_apps_grid,
    "ticket":      _icon_ticket,
    "servicenow":  _icon_ticket,
    "rocket":      _icon_rocket,
    "release":     _icon_rocket,
    "search":      _icon_search,
    "prospector":  _icon_docker,
    "radar":       _icon_radar,
    "panner":      _icon_radar,
    "pods":        _icon_pods,
    "github":      _icon_branch,
    "branch":      _icon_branch,
    "database":    _icon_database,
    "docker":      _icon_docker,
    "lock":        _icon_lock,
    "settings":    _icon_settings,
    "shield":      _icon_shield,
    "cryptkeeper": _icon_shield,
    "lightning":   _icon_lightning,
    "bolt":        _icon_lightning,
    "home":        _icon_home,
    "cve":         _icon_cve,
    "prospector":  _icon_cve,
    "release":     _icon_release,
    "production":  _icon_release,
    "book":        _icon_book,
    "help":        _icon_book,
    "docs":        _icon_book,
    # Action icons
    "refresh":     _icon_refresh,
    "reload":      _icon_refresh,
    "download":    _icon_download,
    "pull":        _icon_download,
    "upload":      _icon_upload,
    "push":        _icon_upload,
    "play":        _icon_play,
    "run":         _icon_play,
    "bash":        _icon_bash,
    "edit":        _icon_edit,
    "pencil":      _icon_edit,
    "delete":      _icon_delete,
    "trash":       _icon_delete,
    "copy":        _icon_copy,
    "add":         _icon_add,
    "plus":        _icon_add,
    "check":       _icon_check,
    "ok":          _icon_check,
    "error":       _icon_error,
    "fail":        _icon_error,
    "warning":     _icon_warning,
    "warn":        _icon_warning,
    "connect":     _icon_connect,
    "login":       _icon_connect,
    "folder":      _icon_folder,
    "file":        _icon_file,
    "explorer":    _icon_explorer,
    "jira":        _icon_jira,
    "tasks":       _icon_ticket,
    "prompts":     _icon_prompts,
}
