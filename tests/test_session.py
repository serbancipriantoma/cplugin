import json
import os
import subprocess
import sys
import time

from helpers import TempDirCase

from cplugin import session
from cplugin.project import Project


def dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


class SessionTest(TempDirCase):
    def setUp(self):
        super().setUp()
        self.project = Project(self.project_dir)
        self.project.sessions_dir.mkdir(parents=True)

    def make_session(self, name: str, meta: dict | None, age_days: float = 0) -> None:
        directory = self.project.sessions_dir / name
        directory.mkdir()
        if meta is not None:
            (directory / session.META_FILE).write_text(json.dumps(meta))
        if age_days:
            past = time.time() - age_days * 86400
            os.utime(directory, (past, past))

    def remaining(self) -> set[str]:
        return {p.name for p in self.project.sessions_dir.iterdir()}

    def test_safe_session_id(self):
        self.assertEqual(session.safe_session_id("abc-123_X"), "abc-123_X")
        for bad in ("../x", "", "a/b", None, 7, "x" * 129):
            self.assertIsNone(session.safe_session_id(bad))

    def test_gc_reclaims_dead_owner_keeps_live_and_own(self):
        me = os.getpid()
        self.make_session("live", {"pid": me, "pid_start": session.process_start_time(me)}, age_days=30)
        self.make_session("dead", {"pid": dead_pid()})
        self.make_session("own", {"pid": dead_pid()})
        removed = session.gc_dead_sessions(self.project, keep="own")
        self.assertEqual(removed, ["dead"])
        self.assertEqual(self.remaining(), {"live", "own"})

    def test_gc_treats_recycled_pid_as_dead(self):
        self.make_session("recycled", {"pid": os.getpid(), "pid_start": "Thu Jan  1 00:00:00 1970"})
        self.assertEqual(session.gc_dead_sessions(self.project, keep=None), ["recycled"])

    def test_gc_orphans_only_when_old(self):
        self.make_session("fresh-orphan", None)
        self.make_session("old-orphan", {"pid": None}, age_days=8)
        self.assertEqual(session.gc_dead_sessions(self.project, keep=None), ["old-orphan"])

    def test_gc_never_follows_symlinks(self):
        target = self.tmp / "precious"
        target.mkdir()
        (target / "file").write_text("keep")
        (self.project.sessions_dir / "link").symlink_to(target)
        session.gc_dead_sessions(self.project, keep=None)
        self.assertTrue((target / "file").exists())

    def test_register_keeps_start_time_across_sources(self):
        session.register(self.project, "s1", "startup", None)
        first = session.read_meta(self.project.sessions_dir / "s1")
        session.register(self.project, "s1", "compact", None)
        second = session.read_meta(self.project.sessions_dir / "s1")
        self.assertEqual(first["started_at"], second["started_at"])
        self.assertEqual(second["last_source"], "compact")

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
