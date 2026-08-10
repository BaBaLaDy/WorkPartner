"""WorkPartner — CLI entry point.

Thin rendering layer. All agent logic lives in WorkPartnerEngine.

Usage:
    python -m src.main                  # auto-create new session
    python -m src.main --session <name> # open specific session
    python -m src.main --new-session    # create a new named session
    python -m src.main --list-sessions  # list all sessions
    python -m src.main --with-bridge    # CLI + IM bridge (Telegram, Feishu, etc.)
    python -m src.main --daemon         # background daemon mode (no UI, no API)
"""

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.session import build_system_prompt
from src.agent.session_manager import SessionManager
from src.memory import MemoryManager
from src.agent.display import fmt_thinking, fmt_tool_input, fmt_tool_output, print_thinking
from src.providers.factory import load_config
from src.tools.shutdown import is_shutdown_requested
from src.core.engine import WorkPartnerEngine

# ANSI reset
RESET = "\033[0m"


def _print_history(messages: list[dict], limit: int = 10):
    """Print recent conversation history on startup / session switch."""
    if not messages:
        return
    recent = messages[-limit:]
    print(f"\n  ── Recent conversation ({len(messages)} messages total, "
          f"showing last {len(recent)}) ──")
    for msg in recent:
        role = "\U0001F9D1" if msg["role"] == "user" else "\U0001F916"
        content = msg["content"].replace("\n", " ")
        if len(content) > 120:
            content = content[:117] + "..."
        print(f"  {role} {content}")


def _cmd_list_sessions():
    """List all sessions and exit."""
    config = load_config()
    history_dir = config.get("history", {}).get("directory", "./history")
    sm = SessionManager(history_dir)

    sessions = sm.list_sessions()
    if not sessions:
        print("No sessions found.")
        return

    print(f"{'Session':<24} {'Created':<22} {'Last Active':<22}")
    print("-" * 68)
    for s in sessions:
        marker = "★" if s["active"] else " "
        tid = s["thread_id"]
        if len(tid) > 22:
            tid = tid[:19] + "..."
        created = s["created_at"][:19] if s["created_at"] else "-"
        last = s["last_active"][:19] if s["last_active"] else "-"
        print(f"{marker} {tid:<22} {created:<22} {last:<22}")


def _cmd_delete_session(thread_id: str):
    config = load_config()
    history_dir = config.get("history", {}).get("directory", "./history")
    sm = SessionManager(history_dir)

    info = sm.get_session(thread_id)
    if info is None:
        print(f"Session '{thread_id}' not found.")
        return

    if sm.delete_session(thread_id):
        print(f"Deleted session: {info['name']} ({thread_id})")
    else:
        print(f"Cannot delete the last remaining session.")


def _print_session_info(sm: SessionManager):
    """Print session info header."""
    info = sm.get_session(sm.active_id)
    if info:
        name = info["name"]
        tid = info["thread_id"]
        created = info["created_at"][:19] if info["created_at"] else "-"
        last = info["last_active"][:19] if info["last_active"] else "-"
        print(f"  Session: {name} ({tid})")
        other = [s for s in sm.list_sessions() if not s["active"]]
        if other:
            names = ", ".join(s["name"] for s in other)
            print(f"  Others:  {names}")
    print(f"  Commands: /sessions, /switch <name>, /new <name>, "
          f"/delete <name>, /clear-reset, /exit")


async def run_cli(session_name: str | None = None, new_session: str | None = None, *, with_bridge: bool = False):
    config = load_config()
    provider_cfg = config["providers"]["openai"]
    agent_cfg = config.get("agent", {})

    # -- Create the unified Engine (shares graph/registry/memory/skills) --
    engine = WorkPartnerEngine()

    # -- Session manager (same one the Engine uses) --
    sm = engine.session_manager

    if new_session is not None:
        sm.create_session(new_session)
    elif session_name is not None:
        found = None
        for s in sm.list_sessions():
            if s["name"] == session_name or s["thread_id"] == session_name:
                found = s["thread_id"]
                break
        if found:
            sm.switch_session(found)
        else:
            print(f"Session '{session_name}' not found. Creating it.")
            sm.create_session(session_name)
    else:
        sm.auto_create()

    # -- Memory --
    engine.memory.check_and_compile_longterm()

    # -- Create interactive session (shares engine's graph/registry) --
    session = engine.create_interactive_session(owner="cli")
    await engine.start_mcp()

    # -- IM bridge --
    if with_bridge:
        for name, cfg in engine._adapters_config.items():
            if cfg.get("enabled", False):
                await engine.connect_channel(name)
        if engine.bridge._adapters:
            print(f"  IM Bridge: started with {len(engine.bridge._adapters)} adapter(s)")
        else:
            print("  IM Bridge: no adapters connected (check config + tokens)")

    # -- scheduler (Engine already created it) --
    scheduler = engine.scheduler
    scheduler.start()

    # -- load and display previous conversation --
    history = session.load_history()
    _first_turn = len(history) == 0

    print("=" * 55)
    print(f"  WorkPartner Agent")
    print(f"  Model: {provider_cfg['model']}")
    print(f"  Tools: {len(engine.registry.list_names())} total")
    print(f"  Max turns: {agent_cfg.get('max_turns', 70)} | "
          f"Compress: >{agent_cfg.get('compression_threshold', 30)} msgs, "
          f"keep {agent_cfg.get('compression_keep_recent', 5)}")
    _print_session_info(sm)
    print("=" * 55)
    _print_history(history)

    pending = session.todo.list("pending")
    if pending:
        print(f"\n  Pending tasks ({len(pending)}):")
        for t in pending:
            desc = f" -- {t['description'][:60]}" if t.get("description") else ""
            print(f"    [{t['id']}] {t['title']}{desc}")
        print(f"\n  Tip: say 'complete my tasks' and I'll work through them.\n")

    _interrupted = False

    try:
        while True:
            try:
                user_input = (await asyncio.to_thread(input, "\n> ")).strip()
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except EOFError:
                print("\nGoodbye!")
                break
            except asyncio.CancelledError:
                print("\nGoodbye!")
                break

            if not user_input:
                continue

            # -- Meta commands --
            lower = user_input.lower()

            if lower in ("/exit", "/quit"):
                print("Goodbye!")
                break

            if lower == "/sessions":
                sessions = session.sessions.list_sessions()
                for s in sessions:
                    marker = "★" if s["active"] else " "
                    print(f"  {marker} {s['name']:<20} ({s['thread_id']})")
                continue

            if lower.startswith("/switch "):
                target = user_input[8:].strip()
                found = next(
                    (s["thread_id"] for s in session.sessions.list_sessions()
                     if s["name"] == target or s["thread_id"] == target), None)
                if found:
                    session.sessions.switch_session(found)
                    session.sync_thread()
                    history = session.load_history()
                    print(f"Switched to session: {target}")
                    _print_history(history)
                else:
                    print(f"Session '{target}' not found. Use /sessions to list.")
                continue

            if lower.startswith("/new "):
                name = user_input[5:].strip()
                tid = session.sessions.create_session(name)
                session.sessions.switch_session(tid)
                session.sync_thread()
                print(f"Created session: {name} ({tid})")
                continue

            if lower.startswith("/delete "):
                target = user_input[8:].strip()
                found = next(
                    (s["thread_id"] for s in session.sessions.list_sessions()
                     if s["name"] == target or s["thread_id"] == target), None)
                if found:
                    ok = session.sessions.delete_session(found)
                    if ok:
                        session.sync_thread()
                        print(f"Deleted session: {target}")
                    else:
                        print("Cannot delete the last remaining session.")
                else:
                    print(f"Session '{target}' not found.")
                continue

            if lower == "/clear-reset":
                session.reset_agent()
                print("[Session cleared — conversation reset, history preserved]")
                continue

            if lower == "/clear":
                session.reset_agent()
                print("[Session cleared]")
                continue

            # -- Normal chat turn --
            _interrupted = False
            system_prompt = build_system_prompt(
                session.injector, user_input,
                memory_manager=session._memory_manager,
            )
            print()

            try:
                # stream events用来把流式返回进行包装，更细粒度地控制输出，同时在需要时显示thinking状态
                async for event in session.stream_events(user_input, system_prompt):
                    kind = event.get("event", "")

                    if kind == "turn_start":
                        turn = event["data"]["turn"]
                        print(f"\n{'─' * 25} Turn {turn} {'─' * 25}")

                    elif kind == "thinking_delta":
                        print_thinking(event["data"])

                    elif kind == "text_delta":
                        print(event["data"], end="", flush=True)

                    elif kind == "tool_input":
                        info = event["data"]
                        print(fmt_tool_input(info["name"], info["input"]))

                    elif kind == "tool_output":
                        print(fmt_tool_output(event["data"]["output"]))

                    elif kind in ("on_chat_model_stream", "on_tool_start", "on_tool_end"):
                        pass

                    elif kind == "on_chain_start" and event.get("name") == "compress":
                        print("\n[Compressing context...] ", end="", flush=True)

                    elif kind == "on_chain_end" and event.get("name") == "compress":
                        summary = event.get("data", {}).get("output", {}).get("compression_summary", "")
                        print(f"done ({len(summary)} chars)", flush=True)

                if _first_turn:
                    session.maybe_auto_title(user_input)
                    _first_turn = False

                if is_shutdown_requested():
                    print("Agent requested shutdown. Exiting...")
                    break

            except KeyboardInterrupt:
                print(f"\n{RESET}[Interrupted]", flush=True)
                _interrupted = True
                continue

            except asyncio.CancelledError:
                print(f"\n{RESET}[Interrupted]", flush=True)
                _interrupted = True
                continue

            except Exception as e:
                print(f"\n[Error] {e}")

            print()

    finally:
        scheduler.shutdown(wait=False)
        await engine.stop_mcp()
        if with_bridge and engine.bridge._adapters:
            print("IM Bridge: stopping...")
            await engine.bridge.stop()
            print("IM Bridge: stopped")


def _run_daemon():
    """Run the engine in daemon mode — no UI, no API, polls todos."""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    engine = WorkPartnerEngine()
    print("WorkPartner Daemon starting — polling todos every 5s")
    print("Press Ctrl+C to stop.")
    engine.run_serve(with_api=False)


def main():
    parser = argparse.ArgumentParser(description="WorkPartner CLI Agent")
    parser.add_argument("--session", "-s", type=str, default=None,
                        help="Resume or create a session by name")
    parser.add_argument("--new-session", "-n", type=str, default=None,
                        metavar="NAME",
                        help="Create a new session with the given name")
    parser.add_argument("--list-sessions", "-l", action="store_true",
                        help="List all sessions and exit")
    parser.add_argument("--delete-session", "-d", type=str, default=None,
                        metavar="NAME",
                        help="Delete a session and exit")
    parser.add_argument("--with-bridge", "-b", action="store_true",
                        help="Start IM bridge alongside CLI (Telegram, Feishu, etc.)")
    parser.add_argument("--daemon", action="store_true",
                        help="Run in background daemon mode (no UI, no API, polls todos)")
    args = parser.parse_args()

    if args.list_sessions:
        _cmd_list_sessions()
    elif args.delete_session:
        _cmd_delete_session(args.delete_session)
    elif args.daemon:
        _run_daemon()
    else:
        try:
            asyncio.run(run_cli(
                session_name=args.session,
                new_session=args.new_session,
                with_bridge=args.with_bridge,
            ))
        except KeyboardInterrupt:
            pass  # Clean exit on Ctrl+C


if __name__ == "__main__":
    main()
