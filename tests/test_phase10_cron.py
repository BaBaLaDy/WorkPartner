"""Phase 10 — Cron scheduler tests.

Tests for: ScheduledTask model, ScheduledTaskManager, TaskScheduler,
cron tools, and integration with TodoManager.
"""

import asyncio
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from pytest import fixture

# -- Add project root to path --
PROJECT_ROOT = Path(__file__).parent.parent


@fixture(autouse=True)
def _chdir_project_root():
    """Run tests from the project root (restores the original cwd after each
    test so this file does not pollute the rest of the suite)."""
    prev = Path.cwd()
    os.chdir(PROJECT_ROOT)
    yield
    os.chdir(prev)


class TestScheduledTaskModel(unittest.TestCase):
    """1.1 — ScheduledTask dataclass serialization."""

    def test_to_dict_and_from_dict(self):
        from src.tasks.scheduler import ScheduledTask

        st = ScheduledTask(
            id="abc12345",
            name="每日早报",
            schedule_type="recurring",
            cron_expression="0 9 * * *",
            task_title="发送今日待办",
            task_description="列出pending任务",
            task_priority="high",
            enabled=True,
            created_at="2026-05-04T10:00:00",
        )

        d = st.to_dict()
        self.assertEqual(d["id"], "abc12345")
        self.assertEqual(d["schedule_type"], "recurring")

        restored = ScheduledTask.from_dict(d)
        self.assertEqual(restored.id, st.id)
        self.assertEqual(restored.cron_expression, "0 9 * * *")
        self.assertEqual(restored.task_priority, "high")

    def test_next_trigger_text(self):
        from src.tasks.scheduler import ScheduledTask

        once = ScheduledTask(
            id="x1", name="t", schedule_type="once",
            trigger_at="2026-06-01T15:00:00",
        )
        self.assertIn("2026-06-01", once.next_trigger_text)

        rec = ScheduledTask(
            id="x2", name="t", schedule_type="recurring",
            cron_expression="0 9 * * 1",
        )
        self.assertIn("0 9 * * 1", rec.next_trigger_text)

        paused = ScheduledTask(
            id="x3", name="t", schedule_type="recurring",
            cron_expression="0 9 * * *", enabled=False,
        )
        self.assertEqual("已暂停", paused.next_trigger_text)


class TestScheduledTaskManager(unittest.TestCase):
    """1.2 — ScheduledTaskManager CRUD + JSON persistence."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "scheduled_tasks.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_mgr(self):
        from src.tasks.scheduler import ScheduledTaskManager
        return ScheduledTaskManager(str(self.path))

    def test_add_and_list(self):
        mgr = self._make_mgr()
        st = mgr.add(name="测试", schedule_type="once", trigger_at="2026-06-01T12:00:00",
                      task_title="做某事", task_priority="high")
        self.assertEqual(st.name, "测试")
        self.assertEqual(st.schedule_type, "once")
        self.assertEqual(len(st.id), 8)

        all_s = mgr.list()
        self.assertEqual(len(all_s), 1)
        self.assertEqual(all_s[0].id, st.id)

    def test_add_and_list_recurring(self):
        mgr = self._make_mgr()
        mgr.add(name="每日", schedule_type="recurring", cron_expression="0 9 * * *",
                task_title="日报")
        mgr.add(name="每周", schedule_type="recurring", cron_expression="0 9 * * 1",
                task_title="周报")
        self.assertEqual(mgr.count, 2)

    def test_list_enabled_only(self):
        mgr = self._make_mgr()
        mgr.add(name="a", schedule_type="once", trigger_at="2026-06-01T12:00:00")
        s2 = mgr.add(name="b", schedule_type="recurring", cron_expression="0 * * * *")
        mgr.set_enabled(s2.id, False)

        all_s = mgr.list()
        enabled = mgr.list(enabled_only=True)
        self.assertEqual(len(all_s), 2)
        self.assertEqual(len(enabled), 1)

    def test_delete(self):
        mgr = self._make_mgr()
        st = mgr.add(name="t", schedule_type="once", trigger_at="2026-06-01T12:00:00")
        self.assertEqual(mgr.count, 1)
        self.assertTrue(mgr.delete(st.id))
        self.assertEqual(mgr.count, 0)
        self.assertFalse(mgr.delete("nonexistent"))

    def test_set_enabled_and_record_trigger(self):
        mgr = self._make_mgr()
        st = mgr.add(name="t", schedule_type="recurring", cron_expression="0 9 * * *")
        self.assertTrue(st.enabled)

        mgr.set_enabled(st.id, False)
        self.assertFalse(mgr.get(st.id).enabled)

        mgr.set_enabled(st.id, True)
        self.assertTrue(mgr.get(st.id).enabled)

        mgr.record_trigger(st.id)
        after = mgr.get(st.id)
        self.assertIsNotNone(after.last_triggered)
        self.assertEqual(after.execution_count, 1)

    def test_persistence_roundtrip(self):
        mgr1 = self._make_mgr()
        mgr1.add(name="t1", schedule_type="once", trigger_at="2026-06-01T12:00:00",
                  task_title="task1")
        mgr1.add(name="t2", schedule_type="recurring", cron_expression="0 9 * * *",
                  task_title="task2")

        from src.tasks.scheduler import ScheduledTaskManager
        mgr2 = ScheduledTaskManager(str(self.path))
        self.assertEqual(mgr2.count, 2)
        names = {s.name for s in mgr2.list()}
        self.assertEqual(names, {"t1", "t2"})

    def test_backward_compat_empty_file(self):
        self.path.write_text("{}", encoding="utf-8")
        mgr = self._make_mgr()
        self.assertEqual(mgr.count, 0)

    def test_backward_compat_corrupt_file(self):
        self.path.write_text("not json", encoding="utf-8")
        mgr = self._make_mgr()
        self.assertEqual(mgr.count, 0)


class TestTodoManagerScheduleFields(unittest.TestCase):
    """1.3-1.5 — TodoItem extended fields + backward compat."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "tasks.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_add_with_schedule_fields(self):
        from src.tasks.todo import TodoManager
        todo = TodoManager(str(self.path))
        task = todo.add(
            title="定时生成的待办",
            description="由cron触发",
            priority="high",
            parent_schedule_id="abc12345",
            schedule_type="recurring",
            cron_expression="0 9 * * *",
        )
        self.assertEqual(task["parent_schedule_id"], "abc12345")
        self.assertEqual(task["schedule_type"], "recurring")
        self.assertEqual(task["cron_expression"], "0 9 * * *")

    def test_add_without_schedule_fields(self):
        from src.tasks.todo import TodoManager
        todo = TodoManager(str(self.path))
        task = todo.add(title="普通待办", description="手动创建")
        self.assertIsNone(task["parent_schedule_id"])
        self.assertIsNone(task["schedule_type"])
        self.assertIsNone(task["cron_expression"])

    def test_backward_compat_old_tasks_json(self):
        """Load tasks.json without new fields — should work with null values."""
        old_data = {
            "tasks": [
                {
                    "id": "old001",
                    "title": "旧任务",
                    "description": "",
                    "status": "done",
                    "priority": "medium",
                    "created_at": "2026-01-01T00:00:00",
                    "completed_at": "2026-01-01T01:00:00",
                    "created_in_session": None,
                    "completed_in_session": None
                }
            ]
        }
        self.path.write_text(json.dumps(old_data, ensure_ascii=False), encoding="utf-8")

        from src.tasks.todo import TodoManager
        todo = TodoManager(str(self.path))
        tasks = todo.list()
        self.assertEqual(len(tasks), 1)
        # Old tasks load fine — new fields just aren't present
        self.assertEqual(tasks[0]["title"], "旧任务")


class TestTaskScheduler(unittest.TestCase):
    """2.x — TaskScheduler APScheduler integration."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sched_path = Path(self.tmpdir.name) / "scheduled_tasks.json"
        self.tasks_path = Path(self.tmpdir.name) / "tasks.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_components(self):
        from src.tasks.scheduler import ScheduledTaskManager, TaskScheduler
        from src.tasks.todo import TodoManager

        store = ScheduledTaskManager(str(self.sched_path))
        todo = TodoManager(str(self.tasks_path))
        scheduler = TaskScheduler(store, todo=todo, timezone_str="Asia/Shanghai")
        return store, todo, scheduler

    def test_init_and_startup(self):
        store, todo, scheduler = self._make_components()
        self.assertIsNotNone(scheduler.scheduler)
        self.assertEqual(scheduler._store.count, 0)

        scheduler.start()
        scheduler.shutdown(wait=False)

    def test_one_shot_triggers_todo(self):
        store, todo, scheduler = self._make_components()

        trigger_time = datetime.now(tz=timezone.utc) + timedelta(seconds=1)
        st = store.add(
            name="test-once",
            schedule_type="once",
            trigger_at=trigger_time.isoformat(),
            task_title="once-task",
            task_description="test-desc",
            task_priority="high",
        )
        scheduler.start()
        scheduler._register_job(st)

        time.sleep(2.5)

        scheduler.shutdown(wait=False)

        tasks = todo.list()
        self.assertGreaterEqual(len(tasks), 1)

        triggered = [t for t in tasks if t.get("parent_schedule_id") == st.id]
        self.assertEqual(len(triggered), 1)
        self.assertEqual(triggered[0]["title"], "once-task")
        self.assertEqual(triggered[0]["schedule_type"], "once")

        updated = store.get(st.id)
        self.assertFalse(updated.enabled)

    def test_pause_resume(self):
        store, todo, scheduler = self._make_components()
        st = store.add(
            name="pause-test",
            schedule_type="recurring",
            cron_expression="0 9 * * *",
            task_title="daily",
        )
        scheduler.start()
        scheduler._register_job(st)

        scheduler.pause_schedule(st.id)
        self.assertFalse(store.get(st.id).enabled)
        self.assertNotIn(st.id, scheduler._job_ids)

        scheduler.resume_schedule(st.id)
        self.assertTrue(store.get(st.id).enabled)
        self.assertIn(st.id, scheduler._job_ids)

        scheduler.shutdown(wait=False)

    def test_delete_schedule(self):
        store, todo, scheduler = self._make_components()
        far_future = (datetime.now(tz=timezone.utc) + timedelta(days=365)).isoformat()
        st = store.add(
            name="delete-me",
            schedule_type="once",
            trigger_at=far_future,
            task_title="test",
        )
        scheduler.start()
        scheduler._register_job(st)

        self.assertEqual(store.count, 1)
        scheduler.delete_schedule(st.id)
        self.assertEqual(store.count, 0)
        self.assertNotIn(st.id, scheduler._job_ids)

        scheduler.shutdown(wait=False)


class TestCronTools(unittest.TestCase):
    """3.x — cron_* tool functions."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmpdir.name)
        # cron_* tools read a module-level ScheduleService — inject a fresh
        # one backed by the per-test temp cwd before each test.
        from src.services.schedule_service import ScheduleService
        from src.tools import cron_tools
        cron_tools.setup_schedule_service(ScheduleService())
        self._cron_tools = cron_tools

    def tearDown(self):
        self._cron_tools.setup_schedule_service(None)
        os.chdir(self.orig_cwd)
        self.tmpdir.cleanup()

    def test_cron_add_once(self):
        from src.tools.cron_tools import cron_add, cron_list

        result = cron_add(
            name="提醒开会",
            schedule_type="once",
            task_title="参加会议",
            task_description="项目周会",
            task_priority="high",
            trigger_at="2026-06-01T14:00:00",
        )
        self.assertIn("Schedule created", result)

        schedules = cron_list()
        self.assertIn("提醒开会", schedules)
        self.assertIn("参加会议", schedules)

    def test_cron_add_recurring(self):
        from src.tools.cron_tools import cron_add, cron_list

        result = cron_add(
            name="每日早报",
            schedule_type="recurring",
            task_title="发送摘要",
            cron_expression="0 9 * * *",
            task_priority="medium",
        )
        self.assertIn("Schedule created", result)

        schedules = cron_list()
        self.assertIn("每日早报", schedules)
        self.assertIn("cron: 0 9 * * *", schedules)

    def test_cron_add_validation(self):
        from src.tools.cron_tools import cron_add

        # Missing name
        r = cron_add(name=" ", schedule_type="once", trigger_at="2026-06-01T12:00:00")
        self.assertIn("Error", r)

        # Wrong type
        r = cron_add(name="x", schedule_type="invalid", trigger_at="2026-06-01T12:00:00")
        self.assertIn("Error", r)

        # Missing trigger_at for once
        r = cron_add(name="x", schedule_type="once")
        self.assertIn("Error", r)

        # Missing cron_expression for recurring
        r = cron_add(name="x", schedule_type="recurring")
        self.assertIn("Error", r)

    def test_cron_pause_resume(self):
        from src.tools.cron_tools import cron_add, cron_pause, cron_resume, cron_list

        cron_add(name="测试", schedule_type="recurring", cron_expression="0 * * * *",
                 task_title="test")

        result = cron_pause("nonexistent")
        self.assertIn("Error", result)

        # Find the ID from the list
        sched_list = cron_list()
        import re
        match = re.search(r'\[([a-f0-9]{8})\]', sched_list)
        if match:
            sid = match.group(1)
            r = cron_pause(sid)
            self.assertIn("paused", r)
            r2 = cron_pause(sid)
            self.assertIn("already paused", r2)
            r3 = cron_resume(sid)
            self.assertIn("resumed", r3)
            r4 = cron_resume(sid)
            self.assertIn("already enabled", r4)

    def test_cron_delete(self):
        from src.tools.cron_tools import cron_add, cron_delete, cron_list

        cron_add(name="待删", schedule_type="once", trigger_at="2026-06-01T12:00:00",
                 task_title="test")

        sched_list = cron_list()
        import re
        match = re.search(r'\[([a-f0-9]{8})\]', sched_list)
        if match:
            sid = match.group(1)
            r = cron_delete(sid)
            self.assertIn("deleted", r)
            r2 = cron_delete(sid)
            self.assertIn("Error", r2)

    def test_cron_update(self):
        from src.tools.cron_tools import cron_add, cron_update, cron_list

        cron_add(name="原名", schedule_type="recurring", cron_expression="0 9 * * *",
                 task_title="原标题")

        sched_list = cron_list()
        import re
        match = re.search(r'\[([a-f0-9]{8})\]', sched_list)
        if match:
            sid = match.group(1)
            r = cron_update(sid, name="新名", task_title="新标题")
            self.assertIn("updated", r)

            updated_list = cron_list()
            self.assertIn("新名", updated_list)
            self.assertIn("新标题", updated_list)

    def test_cron_list_empty(self):
        from src.tools.cron_tools import cron_list
        result = cron_list()
        self.assertIn("No scheduled tasks", result)


class TestIntegrationScheduleToTodo(unittest.TestCase):
    """6.4 — Schedule trigger → todo created → picked up by managed loop."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmpdir.name)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        self.tmpdir.cleanup()

    def test_schedule_todo_integration(self):
        """Cron trigger creates a todo with parent_schedule_id, visible in todo_list."""
        from src.tasks.scheduler import ScheduledTaskManager, TaskScheduler
        from src.tasks.todo import TodoManager

        store = ScheduledTaskManager("scheduled_tasks.json")
        todo = TodoManager("tasks.json")

        st = store.add(
            name="integration-test",
            schedule_type="once",
            trigger_at=(datetime.now(tz=timezone.utc) + timedelta(seconds=1)).isoformat(),
            task_title="integration-todo",
            task_description="from-cron",
            task_priority="high",
        )

        scheduler = TaskScheduler(store, todo=todo, timezone_str="Asia/Shanghai")
        scheduler.start()
        scheduler._on_trigger(st.id)
        scheduler.shutdown(wait=False)

        tasks = todo.list()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "integration-todo")
        self.assertEqual(tasks[0]["description"], "from-cron")
        self.assertEqual(tasks[0]["priority"], "high")
        self.assertEqual(tasks[0]["parent_schedule_id"], st.id)
        self.assertEqual(tasks[0]["schedule_type"], "once")

        updated = store.get(st.id)
        self.assertFalse(updated.enabled)


if __name__ == "__main__":
    unittest.main()
