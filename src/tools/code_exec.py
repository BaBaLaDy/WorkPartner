"""Code execution tool — runs Python / shell code with timeout and output capture."""

import os
import sys
import subprocess
import tempfile
import threading
import time
from pathlib import Path


def code_run(code: str, type: str = "python", timeout: int = 60, cwd: str = ".") -> str:
    """Execute a code snippet in a subprocess with timeout and output capture.

    Use 'python' type for multi-line Python scripts, 'powershell' or 'bash'
    for shell commands. Maximum timeout is 120 seconds.

    Args:
        code: The code snippet to execute.
        type: Execution type — 'python' (default), 'powershell', or 'bash'.
        timeout: Maximum execution time in seconds (capped at 120).
        cwd: Working directory for the subprocess (default: current directory).

    Returns:
        String with exit code, stdout, and status indicator.
    """
    timeout = min(timeout, 120)
    code_cwd = os.path.abspath(cwd or ".")
    os.makedirs(code_cwd, exist_ok=True)

    if type in ("python", "py"):
        return _run_python(code, timeout, code_cwd)
    elif type in ("powershell", "pwsh", "ps1", "bash", "sh", "shell"):
        return _run_shell(code, type, timeout, code_cwd)
    else:
        return f"Error: unsupported type '{type}'. Use 'python' or 'powershell'."


def _run_python(code: str, timeout: int, cwd: str) -> str:
    tmp_path = None
    try:
        tmp_file = tempfile.NamedTemporaryFile(
            suffix=".ai.py", delete=False, mode="w", encoding="utf-8", dir=cwd
        )
        tmp_file.write(code)
        tmp_path = tmp_file.name
        tmp_file.close()

        return _run_process(
            [sys.executable, "-u", tmp_path],
            timeout=timeout,
            cwd=cwd,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _run_shell(code: str, shell_type: str, timeout: int, cwd: str) -> str:
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", code]
    else:
        cmd = ["bash", "-c", code]
    return _run_process(cmd, timeout=timeout, cwd=cwd)


def _run_process(cmd: list[str], timeout: int, cwd: str) -> str:
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE

    full_stdout: list[str] = []

    def stream_reader(proc):
        try:
            for line_bytes in iter(proc.stdout.readline, b""):
                try:
                    line = line_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    line = line_bytes.decode("gbk", errors="ignore")
                full_stdout.append(line)
        except Exception:
            pass

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            cwd=cwd,
            startupinfo=startupinfo,
        )
        start_t = time.time()
        t = threading.Thread(target=stream_reader, args=(process,), daemon=True)
        t.start()

        while t.is_alive():
            if time.time() - start_t > timeout:
                process.kill()
                full_stdout.append(f"\n[Timeout] Process killed after {timeout}s")
                break
            time.sleep(0.5)

        t.join(timeout=2)
        exit_code = process.poll()

        stdout_str = "".join(full_stdout)
        # Truncate very long output
        if len(stdout_str) > 8000:
            stdout_str = stdout_str[:4000] + "\n...[omitted]...\n" + stdout_str[-3000:]

        status = "success" if exit_code == 0 else "error"
        icon = "OK" if exit_code == 0 else "FAIL"
        return f"[{icon}] Exit: {exit_code}\n[stdout]\n{stdout_str}"

    except FileNotFoundError:
        return f"Error: executable not found: {cmd[0]}"
    except Exception as e:
        return f"Error running process: {e}"
