"""Test Phase 4: TodoManager + Streamlit app imports."""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tasks.todo import TodoManager


def test_add_and_list():
    """Add tasks and verify they appear in the list."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        mgr = TodoManager(tmp)
        assert mgr.pending_count == 0
        assert mgr.done_count == 0

        mgr.add("Task 1", "First task", "high")
        mgr.add("Task 2", "Second task", "low")
        mgr.add("Task 3", "", "medium")

        assert mgr.pending_count == 3
        assert len(mgr.list()) == 3
        print(f"  [PASS] add+list: {mgr.pending_count} pending tasks")
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_update_and_status_flow():
    """Test task status transitions."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        mgr = TodoManager(tmp)
        t = mgr.add("Test task", "A test", "medium")
        tid = t["id"]

        # pending → in_progress
        mgr.mark_in_progress(tid)
        assert mgr.get(tid)["status"] == "in_progress"

        # in_progress → done
        mgr.mark_done(tid)
        assert mgr.get(tid)["status"] == "done"
        assert mgr.get(tid)["completed_at"] is not None
        assert mgr.done_count == 1
        assert mgr.pending_count == 0
        print(f"  [PASS] status flow: pending→in_progress→done")
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_delete():
    """Test task deletion."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        mgr = TodoManager(tmp)
        t = mgr.add("Delete me")
        assert len(mgr.list()) == 1

        mgr.delete(t["id"])
        assert len(mgr.list()) == 0
        assert mgr.get(t["id"]) is None
        print(f"  [PASS] delete: task removed")
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_priority_ordering():
    """Test get_next_pending respects priority ordering."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        mgr = TodoManager(tmp)
        mgr.add("Low task", "", "low")
        mgr.add("High task", "", "high")
        mgr.add("Medium task", "", "medium")

        next_task = mgr.get_next_pending()
        assert next_task is not None
        assert next_task["priority"] == "high"
        assert next_task["title"] == "High task"
        print(f"  [PASS] priority ordering: high picked first")
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_persistence():
    """Test tasks survive re-creation of TodoManager (disk persistence)."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        mgr1 = TodoManager(tmp)
        mgr1.add("Persistent task", "Should survive reload")
        assert mgr1.pending_count == 1

        # Re-create with same file
        mgr2 = TodoManager(tmp)
        assert mgr2.pending_count == 1
        assert mgr2.list()[0]["title"] == "Persistent task"
        print(f"  [PASS] persistence: task survives reload")
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_streamlit_app_import():
    """Sanity check: streamlit_app module can be imported."""
    # Streamlit's set_page_config must be first — we can only import-check the
    # non-streamlit dependencies the app uses.
    from src.frontend.streamlit_app import build_system_prompt, init_session, BASE_SYSTEM_PROMPT
    assert "WorkPartner" in BASE_SYSTEM_PROMPT
    print(f"  [PASS] streamlit_app helpers importable")


def test_todolist_cancelled_filtering():
    """Test cancelled tasks don't appear in pending list."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        mgr = TodoManager(tmp)
        t = mgr.add("Cancel me")
        mgr.mark_cancelled(t["id"])
        assert mgr.pending_count == 0
        assert mgr.get_next_pending() is None
        print(f"  [PASS] cancelled tasks excluded from pending")
    finally:
        Path(tmp).unlink(missing_ok=True)


if __name__ == "__main__":
    print("Phase 4 Integration Tests\n")
    test_add_and_list()
    test_update_and_status_flow()
    test_delete()
    test_priority_ordering()
    test_persistence()
    test_todolist_cancelled_filtering()
    test_streamlit_app_import()
    print("\nAll Phase 4 tests passed.")
