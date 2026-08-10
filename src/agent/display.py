"""ANSI formatting helpers for console output — shared between CLI and IM bridge."""

import json

DIM = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


def fmt_tool_input(name: str, args: dict) -> str:
    parts = [f"\n{BOLD}🔧 {name}{RESET}"]
    parts.append(f"{DIM}   📥 input:{RESET}")
    args_str = json.dumps(args, indent=3, ensure_ascii=False)
    for line in args_str.split("\n"):
        parts.append(f"   {line}")
    return "\n".join(parts)


def fmt_tool_output(output: str) -> str:
    if len(output) > 800:
        output = output[:800] + "\n... (truncated)"
    parts = [f"{DIM}   📤 output:{RESET}"]
    for line in output.split("\n")[:25]:
        parts.append(f"   {DIM}{line}{RESET}")
    return "\n".join(parts)


def fmt_thinking(text: str) -> str:
    return f"{DIM}{text}{RESET}"


def print_thinking(text: str) -> None:
    print(f"{DIM}{text}{RESET}", end="", flush=True)
