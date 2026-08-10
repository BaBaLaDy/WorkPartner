"""Desktop control tools: screenshot, mouse, keyboard, window management.

Uses pyautogui + Pillow + pygetwindow for Windows GUI automation.
Designed to work with multimodal LLMs: screenshot → agent sees screen → act.
"""

import os
import re
import json
import base64
import ctypes
from io import BytesIO

# ---------------------------------------------------------------------------
# DPI awareness — must be set BEFORE importing pyautogui / PIL.ImageGrab
# Without this, screenshots produce physical pixels but pyautogui uses
# logical (DPI-virtualised) coords → clicks land in the wrong place on
# high-DPI displays (125%, 150%, etc.).
# ---------------------------------------------------------------------------
_DPI_AWARE = False
try:
    # Prefer per-monitor DPI awareness (Windows 8.1+)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    _DPI_AWARE = True
except Exception:
    try:
        # Fallback: system DPI awareness (Windows Vista+)
        ctypes.windll.user32.SetProcessDPIAware()
        _DPI_AWARE = True
    except Exception:
        pass


def _get_dpi_scale():
    """Return the DPI scale factor (logical / physical) for diagnostics.
    1.0 = 100 % scaling, 0.8 = 125 %, etc."""
    try:
        _hdc = ctypes.windll.user32.GetDC(0)
        phy_w = ctypes.windll.gdi32.GetDeviceCaps(_hdc, 118)  # DESKTOPHORZRES
        ctypes.windll.user32.ReleaseDC(0, _hdc)
        log_w = ctypes.windll.user32.GetSystemMetrics(0)  # SM_CXSCREEN
        return log_w / phy_w if phy_w else 1.0
    except Exception:
        return 1.0


import pyautogui
import pygetwindow as gw
import pyperclip
from PIL import ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Safety defaults
# ---------------------------------------------------------------------------
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

# Fixed screenshot path — always overwrite so history doesn't accumulate images
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "temp")
SCREENSHOT_PATH = os.path.abspath(os.path.join(SCREENSHOT_DIR, "desktop_screenshot.png"))

# Configurable defaults — set via apply_desktop_config()
GRID_SPACING = 70
VISION_CONFIG = None  # set via apply_desktop_config from config.yaml


def _parse_region(region_str: str | None):
    """Parse 'x,y,w,h' into a 4-tuple, or return None for full screen."""
    if not region_str:
        return None
    parts = region_str.replace(" ", "").split(",")
    if len(parts) != 4:
        raise ValueError(f"Region must be 'x,y,w,h', got: {region_str!r}")
    x, y, w, h = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return (x, y, w, h)


# ---------------------------------------------------------------------------
# 1. Screenshot
# ---------------------------------------------------------------------------

def _draw_grid_overlay(img, region_offset=(0, 0), grid_spacing=50):
    """Draw a coordinate grid + cursor marker on the screenshot.

    Grid lines and coordinate labels help the multimodal model read exact
    pixel positions from the image. Red crosshair marks current cursor.
    """
    draw = ImageDraw.Draw(img)
    w, h = img.size
    ox, oy = region_offset

    # ---- Grid lines (semi-transparent white) ----
    for x in range(0, w, grid_spacing):
        draw.line([(x, 0), (x, h)], fill=(180, 180, 180), width=1)
        actual_x = ox + x
        # Text with dark background for readability
        bbox = draw.textbbox((x + 2, 1), str(actual_x))
        draw.rectangle(bbox, fill=(0, 0, 0, 160))
        draw.text((x + 2, 1), str(actual_x), fill=(255, 255, 0))

    for y in range(0, h, grid_spacing):
        draw.line([(0, y), (w, y)], fill=(180, 180, 180), width=1)
        actual_y = oy + y
        bbox = draw.textbbox((1, y + 2), str(actual_y))
        draw.rectangle(bbox, fill=(0, 0, 0, 160))
        draw.text((1, y + 2), str(actual_y), fill=(255, 255, 0))

    # ---- Four corners marked ----
    for cx, cy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ax, ay = ox + cx, oy + cy
        label = f"({ax},{ay})"
        draw.text((cx + 3, cy + 3), label, fill=(255, 200, 0))

    # ---- Mouse cursor position (red crosshair) ----
    mx, my = pyautogui.position()
    local_x = mx - ox
    local_y = my - oy
    if 0 <= local_x < w and 0 <= local_y < h:
        r = 16
        # Thick red crosshair
        draw.line([(local_x - r, local_y), (local_x + r, local_y)], fill=(255, 0, 0), width=3)
        draw.line([(local_x, local_y - r), (local_x, local_y + r)], fill=(255, 0, 0), width=3)
        # Red circle
        draw.ellipse(
            [local_x - r, local_y - r, local_x + r, local_y + r],
            outline=(255, 0, 0), width=2,
        )
        # Coordinate text with background
        coord_text = f"({mx},{my})"
        tbbox = draw.textbbox((local_x + 18, local_y - 8), coord_text)
        draw.rectangle(tbbox, fill=(0, 0, 0, 180))
        draw.text((local_x + 18, local_y - 8), coord_text, fill=(255, 50, 50))


def apply_desktop_config(config: dict):
    """Apply desktop configuration from config.yaml."""
    global GRID_SPACING, VISION_CONFIG
    GRID_SPACING = config.get("grid_spacing", 70)

    if config.get("fail_safe", True):
        pyautogui.FAILSAFE = True
    if "pause" in config:
        pyautogui.PAUSE = float(config["pause"])

    # Vision model config for desktop_locate
    VISION_CONFIG = config.get("vision")

    scale = _get_dpi_scale()
    status = "enabled" if _DPI_AWARE else "DISABLED — clicks may miss on high-DPI"
    vision_info = f"| vision model: {VISION_CONFIG['model']}" if VISION_CONFIG else ""
    print(f"[Desktop] DPI aware: {status} | scale: {scale:.4f} | pyautogui size: {pyautogui.size()} {vision_info}")


def desktop_screenshot(region: str | None = None, grid: int | None = None) -> str:
    """Capture the full screen or a region with an overlaid coordinate grid.

    Args:
        region: Optional region string in 'x,y,w,h' format for partial capture.
        grid: Grid line spacing in pixels (0 to disable, default from config).
    """
    spacing = grid if grid is not None else GRID_SPACING
    try:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        rect = _parse_region(region)
        if rect:
            img = pyautogui.screenshot(region=rect)
            if spacing > 0:
                _draw_grid_overlay(img, region_offset=(rect[0], rect[1]), grid_spacing=spacing)
        else:
            img = pyautogui.screenshot()
            if spacing > 0:
                _draw_grid_overlay(img, grid_spacing=spacing)

        img.save(SCREENSHOT_PATH, "PNG")

        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        region_desc = f"region {region}" if region else "full screen"
        mx, my = pyautogui.position()
        screen_w, screen_h = pyautogui.size()
        grid_info = (
            f"Grid: {spacing}px spacing. "
            f"Yellow numbers = coordinates. Red crosshair = cursor at ({mx},{my}). "
            f"Corners marked with absolute coordinates."
            if spacing > 0 else
            f"Cursor at ({mx},{my}). No grid."
        )
        return json.dumps({
            "text": (
                f"Screenshot ({region_desc}). Screen {screen_w}x{screen_h}. "
                f"{grid_info}"
            ),
            "image": {"base64": b64, "mime": "image/png", "path": SCREENSHOT_PATH},
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"text": f"Error taking screenshot: {e}"})


# ---------------------------------------------------------------------------
# 2. Mouse — click
# ---------------------------------------------------------------------------

def desktop_click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    """Click at the specified screen coordinates.

    Args:
        x: Horizontal pixel coordinate.
        y: Vertical pixel coordinate.
        button: Mouse button — 'left' (default), 'right', or 'middle'.
        clicks: Number of clicks — 1 (default) or 2 for double-click.
    """
    try:
        if button not in ("left", "right", "middle"):
            return f"Error: button must be 'left', 'right', or 'middle', got {button!r}"
        if clicks not in (1, 2):
            return f"Error: clicks must be 1 or 2, got {clicks}"
        pyautogui.click(x, y, clicks=clicks, button=button)
        click_desc = f"{'double-' if clicks == 2 else ''}{button} click"
        return f"{click_desc} at ({x}, {y})"
    except pyautogui.FailSafeException:
        return "Error: FAILSAFE triggered — mouse moved to (0,0)"
    except Exception as e:
        return f"Error clicking: {e}"


# ---------------------------------------------------------------------------
# 3. Mouse — move
# ---------------------------------------------------------------------------

def desktop_move(x: int, y: int) -> str:
    """Move the mouse cursor to (x, y) without clicking.

    Args:
        x: Horizontal pixel coordinate.
        y: Vertical pixel coordinate.
    """
    try:
        pyautogui.moveTo(x, y)
        return f"Cursor moved to ({x}, {y})"
    except pyautogui.FailSafeException:
        return "Error: FAILSAFE triggered — mouse moved to (0,0)"
    except Exception as e:
        return f"Error moving cursor: {e}"


# ---------------------------------------------------------------------------
# 4. Mouse — drag
# ---------------------------------------------------------------------------

def desktop_drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    """Drag from (x1, y1) to (x2, y2) on screen.

    Args:
        x1: Starting horizontal pixel coordinate.
        y1: Starting vertical pixel coordinate.
        x2: Ending horizontal pixel coordinate.
        y2: Ending vertical pixel coordinate.
        duration: How long the drag takes in seconds (default: 0.5).
    """
    try:
        pyautogui.moveTo(x1, y1)
        pyautogui.dragTo(x2, y2, duration=duration)
        return f"Dragged from ({x1}, {y1}) to ({x2}, {y2})"
    except pyautogui.FailSafeException:
        return "Error: FAILSAFE triggered — mouse moved to (0,0)"
    except Exception as e:
        return f"Error dragging: {e}"


# ---------------------------------------------------------------------------
# 5. Mouse — scroll
# ---------------------------------------------------------------------------

def desktop_scroll(amount: int, x: int | None = None, y: int | None = None) -> str:
    """Scroll the mouse wheel at the current or specified position.

    Args:
        amount: Scroll amount (positive = up, negative = down).
        x: Optional horizontal pixel coordinate to move to first.
        y: Optional vertical pixel coordinate to move to first.
    """
    try:
        if x is not None and y is not None:
            pyautogui.moveTo(x, y)
        pyautogui.scroll(amount)
        where = f"at ({x}, {y})" if x is not None else "at current position"
        direction = "up" if amount > 0 else "down"
        return f"Scrolled {direction} {abs(amount)} clicks {where}"
    except pyautogui.FailSafeException:
        return "Error: FAILSAFE triggered — mouse moved to (0,0)"
    except Exception as e:
        return f"Error scrolling: {e}"


# ---------------------------------------------------------------------------
# 6. Keyboard — type text
# ---------------------------------------------------------------------------

def desktop_type(text: str, interval: float = 0.02) -> str:
    """Type text at the current cursor position.

    ASCII text is typed character by character. Non-ASCII text
    (e.g. Chinese) is pasted via clipboard.

    Args:
        text: The text to type or paste.
        interval: Seconds between keystrokes for ASCII text (default: 0.02).
    """
    try:
        if not text:
            return "Error: empty text"
        if text.isascii():
            pyautogui.write(text, interval=interval)
            return f"Typed {len(text)} characters"
        # Non-ASCII: use clipboard paste
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        return f"Pasted text ({len(text)} chars) via clipboard"
    except Exception as e:
        return f"Error typing: {e}"


# ---------------------------------------------------------------------------
# 7. Keyboard — press keys / combos
# ---------------------------------------------------------------------------

def desktop_press(keys: str) -> str:
    """Press a single key or key combination.

    Args:
        keys: Key or combination using '+' separator (e.g. 'enter', 'ctrl+c', 'win+e').
              Special keys: ctrl, alt, shift, win, enter, esc, tab, space,
              backspace, delete, up, down, left, right, f1-f12, etc.
    """
    try:
        parts = [k.strip().lower() for k in keys.split("+")]
        if len(parts) == 1:
            pyautogui.press(parts[0])
            return f"Pressed key: {parts[0]}"
        else:
            pyautogui.hotkey(*parts)
            return f"Pressed combo: {'+'.join(parts)}"
    except Exception as e:
        return f"Error pressing keys: {e}"


# ---------------------------------------------------------------------------
# 8. Window — list windows
# ---------------------------------------------------------------------------

def desktop_get_windows(filter: str | None = None) -> str:
    """List all open windows with title, position, and size.

    Args:
        filter: Optional substring to filter windows by title (case-insensitive).
    """
    try:
        windows = gw.getAllWindows()
        results = []
        for w in windows:
            title = w.title.strip()
            if not title:
                continue
            if filter and filter.lower() not in title.lower():
                continue
            results.append(
                f"  [{title}] "
                f"pos=({w.left},{w.top}) "
                f"size=({w.width}x{w.height}) "
                f"{'[ACTIVE]' if w.isActive else ''}"
            )
        if not results:
            return f"No windows found" + (f" matching '{filter}'" if filter else "")
        header = f"{len(results)} window(s)" + (f" matching '{filter}'" if filter else "")
        return header + "\n" + "\n".join(results)
    except Exception as e:
        return f"Error listing windows: {e}"


# ---------------------------------------------------------------------------
# 9. Window — focus
# ---------------------------------------------------------------------------

def desktop_focus_window(title: str) -> str:
    """Bring the matching window to the foreground.

    Args:
        title: Substring of the window title to focus (case-insensitive).
    """
    try:
        windows = gw.getWindowsWithTitle(title)
        if not windows:
            # Show available windows as hint
            all_titles = [w.title for w in gw.getAllWindows() if w.title.strip()]
            hint = ", ".join(all_titles[:10])
            more = f" (+{len(all_titles) - 10} more)" if len(all_titles) > 10 else ""
            return f"Error: no window matching '{title}' found.\nAvailable windows: {hint}{more}"
        target = windows[0]
        if len(windows) > 1:
            titles = "', '".join(w.title for w in windows[:5])
            note = f"Note: {len(windows)} windows match '{title}'. Focusing first match.\nMatches: '{titles}'"
        else:
            note = ""
        try:
            target.activate()
        except Exception:
            target.minimize()
            target.restore()
            target.activate()
        result = f"Focused window: {target.title}"
        if note:
            result = note + "\n" + result
        return result
    except Exception as e:
        return f"Error focusing window: {e}"


# ---------------------------------------------------------------------------
# 10. System — screen info
# ---------------------------------------------------------------------------

def desktop_get_screen_info() -> str:
    """Return primary screen resolution and current mouse cursor position."""
    try:
        width, height = pyautogui.size()
        x, y = pyautogui.position()
        return f"Screen: {width}x{height} | Mouse: ({x}, {y})"
    except Exception as e:
        return f"Error getting screen info: {e}"


# ---------------------------------------------------------------------------
# 11. Vision model — locate UI element (doubao / separate vision model)
# ---------------------------------------------------------------------------

def desktop_locate(target: str) -> str:
    """Use the dedicated vision model to find a UI element's screen coordinates.

    Sends a screenshot to the vision model and asks for the element's
    normalized relative coordinates, then converts to absolute pixels.

    Args:
        target: Description of the UI element to find (e.g., '发送按钮', '开始菜单').
    """
    if not VISION_CONFIG:
        return json.dumps({
            "error": "Vision model not configured. Add 'vision' under 'desktop' in config.yaml"
        }, ensure_ascii=False)

    try:
        from openai import OpenAI
    except ImportError:
        return json.dumps({"error": "openai package not installed"}, ensure_ascii=False)

    try:
        img = pyautogui.screenshot()
        screen_w, screen_h = pyautogui.size()

        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        prompt = (
            f"请在截图中找到「{target}」的中心位置。"
            f"\n\n返回目标在图片中的**相对坐标**（归一化坐标），格式："
            f"\nX=0.xxx Y=0.yyy"
            f"\n\n坐标系说明："
            f"\n  X: 0.000 = 图片最左边, 1.000 = 图片最右边"
            f"\n  Y: 0.000 = 图片最上边, 1.000 = 图片最下边"
            f"\n\n例如如果目标在图片正中央，返回：X=0.500 Y=0.500"
            f"\n如果目标在左上角附近，返回：X=0.050 Y=0.050"
            f"\n\n请精确到小数点后3位。只返回一行坐标，不要其他内容。"
        )

        client = OpenAI(
            api_key=VISION_CONFIG["api_key"],
            base_url=VISION_CONFIG.get("base_url"),
        )
        response = client.chat.completions.create(
            model=VISION_CONFIG["model"],
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            max_tokens=VISION_CONFIG.get("max_tokens", 200),
            temperature=VISION_CONFIG.get("temperature", 0.1),
        )
        raw = response.choices[0].message.content.strip()

        x, y = _parse_relative_coords(raw, screen_w, screen_h)

        return json.dumps({
            "x": x, "y": y,
            "target": target,
            "screen": f"{screen_w}x{screen_h}",
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _parse_relative_coords(text: str, screen_w: int, screen_h: int):
    """Parse normalised coordinates and convert to absolute screen pixels.

    Supported formats (relative only):
      X=0.260 Y=0.518
      (0.260, 0.518)
      0.260, 0.518
      26% 52%
    """
    patterns = [
        # X=0.xxx Y=0.yyy
        (r'X\s*[=:：]\s*(0\.\d+)\s*[,，\s]\s*Y\s*[=:：]\s*(0\.\d+)', False),
        # (0.xxx, 0.yyy)
        (r'\(\s*(0\.\d+)\s*[,，]\s*(0\.\d+)\s*\)', False),
        # 0.xxx, 0.yyy
        (r'(0\.\d+)\s*[,，\s]\s*(0\.\d+)', False),
        # 26% 52%
        (r'(\d+\.?\d*)\s*%\s*[,，\s]\s*(\d+\.?\d*)\s*%', True),
    ]

    for pattern, is_pct in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            rx = float(m.group(1))
            ry = float(m.group(2))
            if is_pct:
                rx /= 100
                ry /= 100
            if 0 <= rx <= 1 and 0 <= ry <= 1:
                return int(screen_w * rx), int(screen_h * ry)

    raise ValueError(f"Cannot parse relative coordinates from: {text[:200]}")
