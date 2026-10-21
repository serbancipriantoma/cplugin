import json
import os
import subprocess
import sys
import time
from unittest import mock

from helpers import TempDirCase

from cplugin import session
from cplugin.project import Project


def dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def alive_meta() -> dict:
    me = os.getpid()
    return {"pid": me, "pid_start": session.process_start_time(me)}


class SessionTest(TempDirCase):
    def setUp(self):
        super().setUp()
        self.project = Project(self.project_dir)
        self.project.sessions_dir.mkdir(parents=True)

    def make_session(self, name: str, meta: dict | None, age_days: float = 0,
                     state: dict | None = None) -> None:
        directory = self.project.sessions_dir / name
        directory.mkdir()
        if meta is not None:
            (directory / session.META_FILE).write_text(json.dumps(meta))
        if state is not None:
            (directory / session.STATE_FILE).write_text(json.dumps(state))
        if age_days:
            past = time.time() - age_days * 86400
            for path in (*directory.iterdir(), directory):
                os.utime(path, (past, past))

    def remaining(self) -> set[str]:
        return {p.name for p in self.project.sessions_dir.iterdir()}

    def test_safe_session_id(self):
        self.assertEqual(session.safe_session_id("abc-123_X"), "abc-123_X")
        for bad in ("../x", "", "a/b", None, 7, "x" * 129):
            self.assertIsNone(session.safe_session_id(bad))

    def test_gc_keeps_live_sessions_however_old(self):
        self.make_session("live", alive_meta(), age_days=30)
        self.assertEqual(session.gc_dead_sessions(self.project, keep=None), [])

    def test_gc_keeps_recently_ended_sessions_for_continue(self):
        self.make_session("ended-yesterday", {"pid": dead_pid()}, age_days=1)
        self.assertEqual(session.gc_dead_sessions(self.project, keep=None), [])

    def test_gc_reclaims_dead_and_idle(self):
        self.make_session("dead-old", {"pid": dead_pid()}, age_days=8)
        self.make_session("own", {"pid": dead_pid()}, age_days=8)
        self.assertEqual(session.gc_dead_sessions(self.project, keep="own"), ["dead-old"])
        self.assertEqual(self.remaining(), {"own"})

    def test_gc_treats_recycled_pid_as_dead(self):
        self.make_session("recycled", {"pid": os.getpid(), "pid_start": "Thu Jan  1 00:00:00 1970"},
                          age_days=8)
        self.assertEqual(session.gc_dead_sessions(self.project, keep=None), ["recycled"])

    def test_gc_recent_activity_inside_counts(self):
        self.make_session("busy", {"pid": dead_pid()}, age_days=8)
        (self.project.sessions_dir / "busy" / session.COUNTERS_FILE).write_text("{}")
        self.assertEqual(session.gc_dead_sessions(self.project, keep=None), [])

    def test_gc_orphans_only_when_old(self):
        self.make_session("fresh-orphan", None)
        self.make_session("old-orphan", {"pid": None}, age_days=8)
        self.assertEqual(session.gc_dead_sessions(self.project, keep=None), ["old-orphan"])

    def test_gc_never_follows_symlinks(self):
        target = self.tmp / "precious"
        target.mkdir()
        (target / "file").write_text("keep")
        past = time.time() - 30 * 86400
        os.utime(target / "file", (past, past))
        os.utime(target, (past, past))
        (self.project.sessions_dir / "link").symlink_to(target)
        session.gc_dead_sessions(self.project, keep=None)
        self.assertTrue((target / "file").exists())

    def test_register_keeps_start_time_across_sources(self):
        session.register(self.project, "s1", "startup", None)
        first = session.read_meta(self.project.sessions_dir / "s1")
        session.mark_ended(self.project, "s1", "prompt_input_exit")
        session.register(self.project, "s1", "resume", None)
        second = session.read_meta(self.project.sessions_dir / "s1")
        self.assertEqual(first["started_at"], second["started_at"])
        self.assertEqual(second["last_source"], "resume")
        self.assertNotIn("ended_at", second)

    def test_inherit_moves_task_within_the_same_process(self):
        me = os.getpid()
        self.make_session("before-clear", {**alive_meta(), "last_seen_at": 1}, state={"task": 7})
        session.register(self.project, "after-clear", "clear", me)
        self.assertEqual(session.inherit_from_same_process(self.project, "after-clear", me), 7)
        self.assertEqual(session.read_state(self.project.sessions_dir / "after-clear")["task"], 7)
        old = session.read_state(self.project.sessions_dir / "before-clear")
        self.assertIsNone(old["task"])
        self.assertEqual(old["handed_to"], "after-clear")

    def test_inherit_ignores_other_processes(self):
        self.make_session("other", {"pid": dead_pid()}, state={"task": 7})
        session.register(self.project, "mine", "startup", os.getpid())
        self.assertIsNone(session.inherit_from_same_process(self.project, "mine", os.getpid()))

    def test_resolve_cli_session_prefers_env_then_process(self):
        self.make_session("by-env", None)
        self.make_session("by-pid", {**alive_meta(), "last_seen_at": 5})
        with mock.patch.dict(os.environ, {"CPLUGIN_SESSION_ID": "by-env", "CPLUGIN_AGENT_PID": str(os.getpid())}):
            self.assertEqual(session.resolve_cli_session(self.project), "by-env")
        with mock.patch.dict(os.environ, {"CPLUGIN_SESSION_ID": "missing", "CPLUGIN_AGENT_PID": str(os.getpid())}):
            self.assertEqual(session.resolve_cli_session(self.project), "by-pid")
        with mock.patch.dict(os.environ, {"CPLUGIN_SESSION_ID": "", "CPLUGIN_AGENT_PID": "none"}):
            self.assertIsNone(session.resolve_cli_session(self.project))

    def test_find_agent_pid_walks_up_to_claude(self):
        fake_claude = self.tmp / "claude"
        fake_claude.symlink_to("/bin/sh")
        parent = subprocess.Popen([str(fake_claude), "-c", "sleep 5; true"])
        try:
            child_pid = None
            for _ in range(50):
                out = subprocess.run(["pgrep", "-P", str(parent.pid)], capture_output=True, text=True)
                if out.stdout.strip():
                    child_pid = int(out.stdout.split()[0])
                    break
                time.sleep(0.05)
            self.assertIsNotNone(child_pid, "sleep child never appeared")
            self.assertEqual(session.find_agent_pid(start_pid=child_pid), parent.pid)
        finally:
            parent.kill()
            parent.wait()

    def test_find_agent_pid_stops_at_init(self):
        self.assertIsNone(session.find_agent_pid(start_pid=1))
