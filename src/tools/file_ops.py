"""File operation tools: read, write, patch."""

import os
import base64
import itertools
import collections
import difflib
from pathlib import Path

# Track directories we've read from, for did-you-mean suggestions
_read_dirs: set[str] = set()

# Image extensions that should be read as binary for multimodal models
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def _is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _IMAGE_EXTS


def file_read(
    path: str,
    start: int = 1,
    keyword: str | None = None,
    count: int = 200,
    show_linenos: bool = True,
) -> str:
    """Read file content with line numbers and optional keyword search.

    For image files (.png/.jpg/.gif/.bmp/.webp), returns base64 data
    for multimodal model viewing.

    Args:
        path: Path to the file to read.
        start: First line number to read from (1-based, default: 1).
        keyword: If provided, returns content around the first match.
        count: Maximum number of lines to return (default: 200).
        show_linenos: Whether to include line number prefixes (default: True).

    Returns:
        File content with line numbers, or base64 image data for image files.
    """
    try:
        if _is_image(path):
            return _read_image(path)

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            stream = ((i, l.rstrip("\r\n")) for i, l in enumerate(f, 1))
            stream = itertools.dropwhile(lambda x: x[0] < start, stream)

            if keyword:
                before = collections.deque(maxlen=count // 3)
                for i, l in stream:
                    if keyword.lower() in l.lower():
                        res = list(before) + [(i, l)] + list(
                            itertools.islice(stream, count - len(before) - 1)
                        )
                        break
                    before.append((i, l))
                else:
                    return f"Keyword '{keyword}' not found after line {start}."
            else:
                res = list(itertools.islice(stream, count))

            realcnt = len(res)
            remaining = sum(1 for _ in itertools.islice(stream, 5000))
            total_lines = (res[0][0] - 1 if res else start - 1) + realcnt + remaining

            partial = total_lines > realcnt
            header = f"[FILE] {total_lines}+ lines" if partial else f"[FILE] {total_lines} lines"
            if partial:
                header += f" | PARTIAL showing {realcnt}; read more if needed"
            header += "\n"

            MAX_LINE = min(max(100, 256000 // max(realcnt, 1)), 8000)
            result = "\n".join(
                f"{i}|{l if len(l) <= MAX_LINE else l[:MAX_LINE] + ' ... [TRUNCATED]'}"
                for i, l in res
            )

            _read_dirs.add(os.path.dirname(os.path.abspath(path)))
            return header + result

    except FileNotFoundError:
        # Try did-you-mean suggestions
        msg = f"Error: File not found: {path}"
        try:
            tgt = os.path.basename(path)
            scan = os.path.dirname(os.path.dirname(os.path.abspath(path)))
            cands = list(_scan_files(scan, depth=2))
            scored = sorted(
                [
                    (difflib.SequenceMatcher(None, tgt.lower(), c[0].lower()).ratio(), c)
                    for c in cands[:1000]
                ],
                key=lambda x: -x[0],
            )[:5]
            top = [(s, c) for s, c in scored if s > 0.3]
            if top:
                msg += "\n\nDid you mean:\n" + "\n".join(
                    f"  {c[1]}  ({s:.0%})" for s, c in top
                )
        except Exception:
            pass
        return msg
    except Exception as e:
        return f"Error reading file: {e}"


def _read_image(path: str) -> str:
    """Read an image file and return base64 data for multimodal models."""
    import json
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
    }
    ext = os.path.splitext(path)[1].lower()
    mime = mime_map.get(ext, "image/png")
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return json.dumps({
            "text": f"Image file: {path} ({len(b64)} bytes base64)",
            "image": {"base64": b64, "mime": mime, "path": path},
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error reading image: {e}"


def _scan_files(base: str, depth: int = 2):
    """Recursively scan for files."""
    try:
        for e in os.scandir(base):
            if e.is_file():
                yield (e.name, e.path)
            elif depth > 0 and e.is_dir(follow_symlinks=False):
                yield from _scan_files(e.path, depth - 1)
    except (PermissionError, OSError):
        pass


def file_write(path: str, content: str, mode: str = "overwrite") -> str:
    """Write content to a file with support for overwrite, append, and prepend.

    Args:
        path: Destination file path (parent directories created automatically).
        content: Content to write.
        mode: Write mode — 'overwrite' (default), 'append', or 'prepend'.
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        if mode == "prepend":
            old = open(path, "r", encoding="utf-8").read() if os.path.exists(path) else ""
            open(path, "w", encoding="utf-8").write(content + old)
        else:
            with open(path, "a" if mode == "append" else "w", encoding="utf-8") as f:
                f.write(content)
        return f"File written: {path} ({len(content)} bytes, mode={mode})"
    except Exception as e:
        return f"Error writing file: {e}"


def file_patch(path: str, old_content: str, new_content: str) -> str:
    """Replace old_content with new_content at exactly one location in a file.

    Use file_read first to verify the exact content to replace. The old_content
    must match exactly one occurrence in the file.

    Args:
        path: Path to the file to patch.
        old_content: Exact text to find and replace (must match exactly once).
        new_content: Text to replace old_content with.
    """
    try:
        if not os.path.exists(path):
            return "Error: file does not exist"
        with open(path, "r", encoding="utf-8") as f:
            full_text = f.read()
        if not old_content:
            return "Error: old_content is empty"
        count = full_text.count(old_content)
        if count == 0:
            return "Error: old_content not found in file. Use file_read to verify current content."
        if count > 1:
            return f"Error: found {count} matches — old_content must be unique. Provide more surrounding context."
        updated = full_text.replace(old_content, new_content)
        with open(path, "w", encoding="utf-8") as f:
            f.write(updated)
        return f"File patched: {path} (1 replacement)"
    except Exception as e:
        return f"Error patching file: {e}"
