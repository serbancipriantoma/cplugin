import io
import json
import os
import subprocess
import sys
import time
from contextlib import redirect_stdout

from helpers import PLUGIN_ROOT, SESSION, ProjectCase

from cplugin import agents, board, session
from cplugin.project import Project

NOW = 1_800_000_000.0


class RenderTest(ProjectCase):
    def test_every_line_has_the_same_width(self):
        b = board.Board("TASK 001 · x ─ gate 1/9", "1. Design — " + "long " * 40, [
            board.Row("MAIN", True, "waiting", "for worker"),
            board.Row("worker", True, "Edit", "src/" + "deep/" * 30 + "file.ts", "1:02:03"),
            board.Row("general-purpose", True, "Bash", "npm test", "0:05"),
        ])
        for width in (30, 50, 80, 140):
            lines = board.render(b, width).splitlines()
            expected = max(board.MIN_WIDTH, min(width, board.MAX_WIDTH))
            self.assertEqual({len(line) for line in lines}, {expected}, width)
        text = board.render(b, 80)
        self.assertIn("…", text)
        self.assertIn("1:02:03 │", text)
        self.assertIn("│ genera… │", text)

    def test_color_wraps_only_the_dots(self):
        b = board.Board("T", "S", [board.Row("MAIN", True, "Edit"), board.Row("worker", False, "—")])
        colored = board.render(b, 60, color=True)
        self.assertIn("\x1b[32m●\x1b[0m", colored)
        self.assertIn("\x1b[2m○\x1b[0m", colored)


class CollectTest(ProjectCase):
    def setUp(self):
        super().setUp()
        self.project = Project(self.project_dir)
        self.dir = session.session_dir(self.project, SESSION)

    def record(self, key: str, **fields) -> None:
        path = self.dir / agents.AGENTS_DIR / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"key": key, **fields}))

    def rows(self) -> dict[str, list[board.Row]]:
        found: dict[str, list[board.Row]] = {}
        for row in board.collect(self.project, SESSION, now=NOW).rows:
            found.setdefault(row.name, []).append(row)
        return found

    def test_no_task(self):
        b = board.collect(self.project, SESSION, now=NOW)
        self.assertEqual(b.title, "NO ACTIVE TASK")
        self.assertEqual([r.name for r in b.rows], ["MAIN", "worker", "tester", "judge"])

    def test_task_title_and_current_gate(self):
        self.new_task("project-filter")
        self.activate()
        b = board.collect(self.project, SESSION, now=NOW)
        self.assertRegex(b.title, r"^TASK 001 · project-filter ─ gate 1/\d+$")
        self.assertTrue(b.subtitle.startswith("1. Design — Read the affected sections"))

    def test_pause_and_freehand_show(self):
        self.new_task()
        self.activate()
        self.tasks_ok("pause", "which", "colour?")
        state = session.read_state(self.dir)
        session.write_state(self.dir, {**state, "freehand": True})
        b = board.collect(self.project, SESSION, now=NOW)
        self.assertTrue(b.title.endswith("· FREEHAND"))
        self.assertEqual(b.subtitle, "waiting for the user: which colour?")

    def test_main_waits_for_running_sub_agents(self):
        self.record("main", role="main", last_action={"tool": "Agent", "target": "x", "at": NOW - 50})
        self.record("w1", role="worker", status="running", started_at=NOW - 42,
                    last_action={"tool": "Edit", "target": f"{self.project_dir}/src/filter.ts", "at": NOW - 2})
        self.record("w2", role="worker", status="running", started_at=NOW - 10)
        rows = self.rows()
        self.assertEqual(rows["MAIN"][0], board.Row("MAIN", True, "waiting", "for worker"))
        self.assertEqual(rows["worker"][0], board.Row("worker", True, "Edit", "src/filter.ts", "0:42"))
        self.assertEqual(rows["worker"][1], board.Row("worker", True, "starting", "", "0:10"))

    def test_finished_and_stale_sub_agents(self):
        self.record("t1", role="tester", status="done", started_at=NOW - 900, ended_at=NOW - 180,
                    last_action={"tool": "Bash", "target": "npm test", "at": NOW - 200})
        self.record("w1", role="worker", status="running", started_at=NOW - 3 * 3600)  # never stopped
        rows = self.rows()
        self.assertEqual(rows["tester"][0], board.Row("tester", False, "done", "npm test", "3m"))
        self.assertEqual(rows["worker"][0], board.Row("worker", False, "—"))  # stale, not running

    def test_main_busy_then_idle(self):
        self.record("main", role="main", last_action={"tool": "Read", "target": "a.md", "at": NOW - 5})
        self.assertEqual(self.rows()["MAIN"][0], board.Row("MAIN", True, "Read", "a.md", "5s"))
        self.record("main", role="main", last_action={"tool": "Read", "target": "a.md", "at": NOW - 600})
        self.assertEqual(self.rows()["MAIN"][0], board.Row("MAIN", False, "idle", "a.md", "10m"))

    def test_other_sub_agents_get_their_own_row(self):
        self.record("e1", role="other", agent_type="Explore", status="running", started_at=NOW - 7)
        self.assertEqual(self.rows()["Explore"][0], board.Row("Explore", True, "starting", "", "0:07"))
        self.assertEqual(self.rows()["MAIN"][0].detail, "for Explore")


class SessionChoiceTest(ProjectCase):
    def test_prefers_live_then_active_task_then_recent(self):
        project = Project(self.project_dir)
        sessions = self.project_dir / ".cplugin" / "sessions"
        for name, meta, state in (("old-live", {"pid": os.getpid(), "last_seen_at": 1}, {}),
                                  ("new-dead", {"pid": None, "last_seen_at": time.time()}, {"task": 1})):
            (sessions / name).mkdir()
            (sessions / name / "meta.json").write_text(json.dumps(meta))
            (sessions / name / "state.json").write_text(json.dumps(state))
        self.assertEqual(board.default_session(project), "old-live")
        self.assertEqual(board.resolve_session(project, "new"), "new-dead")
        self.assertIsNone(board.resolve_session(project, "nope"))


class CommandTest(ProjectCase):
    def board_cmd(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", str(PLUGIN_ROOT / "bin" / "board.py"), *args],
                              capture_output=True, text=True, cwd=self.project_dir, env=self.env())

    def test_prints_once_without_color_when_piped(self):
        out = self.board_cmd()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("┌ NO ACTIVE TASK", out.stdout)
        self.assertIn(f"session {SESSION[:8]}", out.stdout)
        self.assertNotIn("\x1b[", out.stdout)

    def test_launcher_is_installed(self):
        launcher = self.project_dir / ".claude" / "bin" / "board"
        out = subprocess.run([str(launcher), "--session", SESSION], capture_output=True, text=True,
                             cwd=self.project_dir, env=self.env())
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("│ MAIN", out.stdout)

    def test_outside_a_project(self):
        out = subprocess.run([sys.executable, "-I", str(PLUGIN_ROOT / "bin" / "board.py")],
                             capture_output=True, text=True, cwd=self.tmp, env=self.env())
        self.assertEqual(out.returncode, 1)

    def test_watch_redraws_and_restores_the_cursor(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            board.watch(Project(self.project_dir), None, 0.01, color=False, frames=2)
        text = buffer.getvalue()
        self.assertEqual(text.count("\x1b[H\x1b[2J"), 2)
        self.assertTrue(text.startswith("\x1b[?25l"))
        self.assertIn("\x1b[?25h", text)
        self.assertIn("Ctrl+C to quit", text)
