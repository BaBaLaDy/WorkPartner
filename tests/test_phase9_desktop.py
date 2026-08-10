"""Phase 9 integration tests — desktop control tools.

Desktop tools make real GUI calls — all pyautogui operations are mocked."""
import sys
import os
import json
import base64
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pyautogui
from PIL import Image
from src.tools.defaults import create_default_registry
from src.tools.desktop import _parse_region, SCREENSHOT_DIR, SCREENSHOT_PATH


def _json_result(result):
    """Parse a JSON tool result, return dict or None."""
    try:
        return json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None


def test_registry():
    """All 11 desktop tools registered in default registry."""
    reg = create_default_registry()
    desktop_names = sorted(n for n in reg.list_names() if n.startswith("desktop_"))
    assert len(desktop_names) == 11, f"Expected 11, got {len(desktop_names)}: {desktop_names}"
    print(f"  [OK] {len(desktop_names)} desktop tools: {desktop_names}")

    # Verify each has a docstring (required for tool schema)
    for name in desktop_names:
        fn = reg.get(name)
        assert fn is not None, f"Tool {name} not found in registry"
        assert fn.__doc__, f"Tool {name} missing docstring"
    print(f"  [OK] All 11 tools have docstrings")

    # Verify OpenAI schema export
    schemas = reg.as_openai_tools()
    desktop_schemas = [s for s in schemas if s["function"]["name"].startswith("desktop_")]
    assert len(desktop_schemas) == 11
    print(f"  [OK] All 11 tools export as OpenAI schemas")


def test_region_parsing():
    """Region string parsing."""
    assert _parse_region(None) is None
    assert _parse_region("") is None
    assert _parse_region("0,0,800,600") == (0, 0, 800, 600)
    assert _parse_region(" 50 , 60 , 700 , 500 ") == (50, 60, 700, 500)
    print(f"  [OK] Region parsing: None / '0,0,800,600' / ' 50 , 60 , 700 , 500 '")

    try:
        _parse_region("0,0,800")
        assert False, "Should have raised"
    except ValueError:
        pass
    print(f"  [OK] Region parsing: invalid -> ValueError")


def test_screenshot_mocked():
    """Screenshot tool with mocked pyautogui — returns JSON with base64 image."""
    from src.tools.desktop import desktop_screenshot

    # Create a tiny real image so base64 encoding works
    tiny_img = Image.new("RGB", (10, 10), color="red")

    with patch("src.tools.desktop.pyautogui.screenshot") as mock_ss:
        mock_ss.return_value = tiny_img

        result = desktop_screenshot()
        data = _json_result(result)
        assert data is not None, f"Expected JSON, got: {result[:100]}"
        assert "text" in data
        assert "Screenshot" in data["text"]
        assert "Grid" in data["text"]  # Grid info present
        assert "image" in data
        assert "base64" in data["image"]
        assert data["image"]["mime"] == "image/png"
        # Verify base64 decodes back to valid PNG
        decoded = base64.b64decode(data["image"]["base64"])
        assert decoded[:4] == b'\x89PNG'
        print(f"  [OK] Screenshot JSON: text + image/base64 (+ valid PNG with grid overlay)")

    with patch("src.tools.desktop.pyautogui.screenshot") as mock_ss:
        mock_ss.return_value = tiny_img
        result = desktop_screenshot(region="0,0,400,300")
        mock_ss.assert_called_once_with(region=(0, 0, 400, 300))
        data = _json_result(result)
        assert "region 0,0,400,300" in data["text"]
        print(f"  [OK] Screenshot region: includes region info")

    with patch("src.tools.desktop.pyautogui.screenshot", side_effect=OSError("fail")):
        result = desktop_screenshot()
        data = _json_result(result)
        assert "Error" in data["text"]
        print(f"  [OK] Screenshot error: JSON with error text")


def test_file_read_image():
    """file_read on image files returns JSON with base64."""
    from src.tools.file_ops import file_read

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a tiny PNG
        img = Image.new("RGB", (5, 5), color="blue")
        img_path = os.path.join(tmpdir, "test.png")
        img.save(img_path, "PNG")

        result = file_read(img_path)
        data = _json_result(result)
        assert data is not None, f"Expected JSON for image, got: {result[:100]}"
        assert "Image file" in data["text"]
        assert data["image"]["mime"] == "image/png"
        decoded = base64.b64decode(data["image"]["base64"])
        assert decoded[:4] == b'\x89PNG'
        print(f"  [OK] file_read PNG: JSON with valid base64")

    with tempfile.TemporaryDirectory() as tmpdir:
        img = Image.new("RGB", (5, 5), color="green")
        jpg_path = os.path.join(tmpdir, "test.jpg")
        img.save(jpg_path, "JPEG")
        result = file_read(jpg_path)
        data = _json_result(result)
        assert data["image"]["mime"] == "image/jpeg"
        print(f"  [OK] file_read JPEG: correct mime type")

    # Non-image file still returns plain text
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = os.path.join(tmpdir, "hello.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("Hello World")
        result = file_read(txt_path)
        assert "Hello World" in result
        assert _json_result(result) is None  # Not JSON
        print(f"  [OK] file_read text: plain text unchanged")


def test_tool_node_multimodal():
    """tool_node creates multimodal ToolMessage when result contains image."""
    from src.agent.nodes.tools import _build_message_content

    # Plain text result → string
    result = _build_message_content("plain text result")
    assert isinstance(result, str)
    assert result == "plain text result"
    print(f"  [OK] _build_message_content plain text: str")

    # JSON without image → string
    result = _build_message_content('{"text": "hello"}')
    assert isinstance(result, str)
    print(f"  [OK] _build_message_content JSON no image: str")

    # JSON with image → multimodal list
    result = _build_message_content(
        '{"text": "Screenshot taken", '
        '"image": {"base64": "iVBORw0KGgo=", "mime": "image/png", "path": "/tmp/s.png"}}'
    )
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert len(result) == 2
    assert result[0]["type"] == "text"
    assert result[0]["text"] == "Screenshot taken"
    assert result[1]["type"] == "image_url"
    assert result[1]["image_url"]["url"] == "data:image/png;base64,iVBORw0KGgo="
    print(f"  [OK] _build_message_content with image: multimodal list[text, image_url]")

    # JSON with image but no text → only image block
    result = _build_message_content(
        '{"image": {"base64": "AAAA", "mime": "image/jpeg"}}'
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["type"] == "image_url"
    print(f"  [OK] _build_message_content image only: single image_url block")

    # Invalid JSON → string
    result = _build_message_content("{not valid json")
    assert isinstance(result, str)
    print(f"  [OK] _build_message_content invalid JSON: str fallback")


def test_click_mocked():
    """Click tool with mocked pyautogui."""
    from src.tools.desktop import desktop_click

    with patch("src.tools.desktop.pyautogui.click") as mc:
        result = desktop_click(100, 200)
        mc.assert_called_once_with(100, 200, clicks=1, button="left")
        assert "left click" in result
        print(f"  [OK] Click left: {result}")

    with patch("src.tools.desktop.pyautogui.click") as mc:
        result = desktop_click(300, 400, button="right", clicks=2)
        mc.assert_called_once_with(300, 400, clicks=2, button="right")
        print(f"  [OK] Click double-right: {result}")

    # Validation
    assert desktop_click(10, 10, button="invalid").startswith("Error")
    assert desktop_click(10, 10, clicks=3).startswith("Error")
    print(f"  [OK] Click validation: invalid params -> Error")

    with patch("src.tools.desktop.pyautogui.click", side_effect=pyautogui.FailSafeException("fail")):
        result = desktop_click(10, 10)
        assert "FAILSAFE" in result
        print(f"  [OK] Click FAILSAFE: {result}")


def test_move_mocked():
    """Move tool."""
    from src.tools.desktop import desktop_move
    with patch("src.tools.desktop.pyautogui.moveTo") as mm:
        result = desktop_move(500, 300)
        mm.assert_called_once_with(500, 300)
        print(f"  [OK] Move: {result}")


def test_drag_mocked():
    """Drag tool."""
    from src.tools.desktop import desktop_drag
    with patch("src.tools.desktop.pyautogui.dragTo") as md, \
         patch("src.tools.desktop.pyautogui.moveTo") as mm:
        result = desktop_drag(100, 200, 400, 500, duration=0.3)
        mm.assert_called_once_with(100, 200)
        md.assert_called_once_with(400, 500, duration=0.3)
        print(f"  [OK] Drag: {result}")


def test_scroll_mocked():
    """Scroll tool."""
    from src.tools.desktop import desktop_scroll
    with patch("src.tools.desktop.pyautogui.scroll") as ms, \
         patch("src.tools.desktop.pyautogui.moveTo") as mm:
        result = desktop_scroll(5, x=200, y=300)
        mm.assert_called_once_with(200, 300)
        ms.assert_called_once_with(5)
        print(f"  [OK] Scroll at position: {result}")

    with patch("src.tools.desktop.pyautogui.scroll") as ms:
        result = desktop_scroll(-3)
        ms.assert_called_once_with(-3)
        print(f"  [OK] Scroll down: {result}")


def test_type_mocked():
    """Type tool — ASCII vs Chinese paths."""
    from src.tools.desktop import desktop_type

    with patch("src.tools.desktop.pyautogui.write") as mw:
        result = desktop_type("Hello World")
        mw.assert_called_once_with("Hello World", interval=0.02)
        print(f"  [OK] Type ASCII: {result}")

    with patch("src.tools.desktop.pyautogui.hotkey") as mh, \
         patch("src.tools.desktop.pyperclip.copy") as mc:
        result = desktop_type("你好世界")
        mc.assert_called_once_with("你好世界")
        mh.assert_called_once_with("ctrl", "v")
        print(f"  [OK] Type Chinese (clipboard): {result}")

    assert desktop_type("").startswith("Error")
    print(f"  [OK] Type empty: Error")


def test_press_mocked():
    """Press key / combo tool."""
    from src.tools.desktop import desktop_press

    with patch("src.tools.desktop.pyautogui.press") as mp:
        result = desktop_press("enter")
        mp.assert_called_once_with("enter")
        print(f"  [OK] Press single: {result}")

    with patch("src.tools.desktop.pyautogui.hotkey") as mh:
        result = desktop_press("ctrl+shift+t")
        mh.assert_called_once_with("ctrl", "shift", "t")
        print(f"  [OK] Press combo: {result}")

    with patch("src.tools.desktop.pyautogui.hotkey", side_effect=ValueError("bad")):
        result = desktop_press("bad_key++")
        assert "Error" in result
        print(f"  [OK] Press error: {result}")


def _fake_window(title, left=0, top=0, width=800, height=600, active=False):
    w = MagicMock()
    w.title = title
    w.left = left
    w.top = top
    w.width = width
    w.height = height
    w.isActive = active
    return w


def test_get_windows_mocked():
    """Window listing tool."""
    from src.tools.desktop import desktop_get_windows

    with patch("src.tools.desktop.gw.getAllWindows") as mg:
        mg.return_value = [
            _fake_window("Chrome", active=True),
            _fake_window("Notepad"),
            _fake_window(""),
        ]
        result = desktop_get_windows()
        assert "Chrome" in result
        assert "Notepad" in result
        assert "ACTIVE" in result
        # empty title excluded
        line_count = result.count("\n")
        assert line_count == 2, f"Expected 2 windows, got {line_count}"
        print(f"  [OK] List windows: 2 visible windows")

    with patch("src.tools.desktop.gw.getAllWindows") as mg:
        mg.return_value = [
            _fake_window("Google Chrome"),
            _fake_window("Visual Studio Code"),
        ]
        result = desktop_get_windows(filter="chrome")
        assert "Google Chrome" in result
        assert "Visual Studio Code" not in result
        print(f"  [OK] Filter windows 'chrome': 1 match")

    with patch("src.tools.desktop.gw.getAllWindows") as mg:
        mg.return_value = [_fake_window("Notepad")]
        result = desktop_get_windows(filter="ZZZ")
        assert "No windows" in result
        print(f"  [OK] Filter windows 'ZZZ': no matches")


def test_focus_window_mocked():
    """Window focus tool."""
    from src.tools.desktop import desktop_focus_window

    with patch("src.tools.desktop.gw.getWindowsWithTitle") as mgt, \
         patch("src.tools.desktop.gw.getAllWindows") as mga:
        w = _fake_window("Notepad - Untitled")
        w.activate = MagicMock()
        mgt.return_value = [w]
        mga.return_value = [w]

        result = desktop_focus_window("Notepad")
        assert "Focused window" in result
        w.activate.assert_called_once()
        print(f"  [OK] Focus window: {result}")

    with patch("src.tools.desktop.gw.getWindowsWithTitle") as mgt, \
         patch("src.tools.desktop.gw.getAllWindows") as mga:
        mgt.return_value = []
        mga.return_value = [_fake_window("Chrome"), _fake_window("Explorer")]
        result = desktop_focus_window("NonExistent")
        assert result.startswith("Error")
        assert "Chrome" in result
        print(f"  [OK] Focus not found: shows available windows")


def test_screen_info_mocked():
    """Screen info tool."""
    from src.tools.desktop import desktop_get_screen_info
    with patch("src.tools.desktop.pyautogui.size") as ms, \
         patch("src.tools.desktop.pyautogui.position") as mp:
        ms.return_value = (1920, 1080)
        mp.return_value = (500, 300)
        result = desktop_get_screen_info()
        assert "1920x1080" in result
        assert "(500, 300)" in result
        print(f"  [OK] Screen info: {result}")


def test_graph_compiles_with_desktop():
    """Verify agent graph compiles with desktop tools registered."""
    from src.agent.graph import build_agent_graph

    reg = create_default_registry()
    graph = build_agent_graph(registry=reg)
    compiled = graph.compile()
    nodes = list(graph.nodes.keys())
    assert "chat" in nodes
    assert "tools" in nodes
    print(f"  [OK] Graph compiles with {len(reg.list_names())} tools, nodes: {nodes}")


if __name__ == "__main__":
    print("Phase 9 Desktop Control Tests\n")
    test_registry()
    test_region_parsing()
    test_screenshot_mocked()
    test_file_read_image()
    test_tool_node_multimodal()
    test_click_mocked()
    test_move_mocked()
    test_drag_mocked()
    test_scroll_mocked()
    test_type_mocked()
    test_press_mocked()
    test_get_windows_mocked()
    test_focus_window_mocked()
    test_screen_info_mocked()
    test_graph_compiles_with_desktop()
    print("\nAll Phase 9 tests passed.")
