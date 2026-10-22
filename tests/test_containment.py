import os
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest import mock

from helpers import TempDirCase

from foreman import containment
from foreman.containment import Containment


def done(rc: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], rc, "", stderr)


class DetectTest(unittest.TestCase):
    """detect() on Linux, with the system answers faked so it runs anywhere."""

    def setUp(self):
        containment.detect.cache_clear()
        self.addCleanup(containment.detect.cache_clear)
        patcher = mock.patch.object(containment.sys, "platform", "linux")
        patcher.start()
        self.addCleanup(patcher.stop)

    def detect(self, which: dict, runs: list) -> Containment:
        with mock.patch.object(containment.shutil, "which", lambda name: which.get(name)), \
             mock.patch.object(containment, "_run", side_effect=runs) as run:
            found = containment.detect()
        self.calls = [c.args[0] for c in run.call_args_list]
        return found

    def test_bwrap_missing(self):
        found = self.detect({}, [])
        self.assertEqual((found.tool, found.state), (None, "none"))
        self.assertIn("apt install bubblewrap", found.hint)

    def test_bwrap_works(self):
        found = self.detect({"bwrap": "/usr/bin/bwrap", "true": "/usr/bin/true"}, [done(0)])
        self.assertEqual((found.tool, found.state, found.proc), ("bwrap", "ok", True))
        self.assertEqual(self.calls[0], ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "/usr/bin/true"])

    def test_without_a_fresh_proc(self):
        found = self.detect({"bwrap": "/usr/bin/bwrap", "true": "/usr/bin/true"},
                            [done(1, "bwrap: Can't mount proc"), done(0)])
        self.assertEqual((found.state, found.proc), ("ok", False))

    def test_namespaces_blocked(self):
        found = self.detect({"bwrap": "/usr/bin/bwrap", "true": "/usr/bin/true"},
                            [done(1), done(1, "bwrap: setting up uid map: Permission denied")])
        self.assertEqual(found.state, "nested")
        self.assertIn("setting up uid map: Permission denied", found.hint)
        self.assertIn("docs/linux.md", found.hint)


class BwrapArgvTest(TempDirCase):
    def setUp(self):
        super().setUp()
        self.home = self.tmp / "home"
        for sub in (".claude", ".config"):
            (self.home / sub).mkdir(parents=True)
        (self.home / ".claude.json").write_text("{}")
        (self.project_dir / ".git").mkdir()

    def argv(self, **kwargs) -> list[str]:
        with mock.patch.dict(os.environ, {"TMPDIR": "", "XDG_RUNTIME_DIR": ""}):
            return containment.bwrap_argv(self.project_dir, ["claude", "-p"], home=self.home, **kwargs)

    def binds(self, argv: list[str]) -> list[tuple[str, str]]:
        return [(argv[i], argv[i + 1]) for i in range(len(argv) - 1) if argv[i] in ("--bind", "--ro-bind")]

    def test_session_shape(self):
        argv = self.argv(interactive=True)
        self.assertEqual(argv[:7], ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc"])
        binds = self.binds(argv)
        root, git = str(self.project_dir), str(self.project_dir / ".git")
        self.assertIn(("--bind", str(self.home / ".claude")), binds)
        self.assertIn(("--bind", str(self.home / ".claude.json")), binds)
        self.assertNotIn(("--bind", str(self.home / ".codex")), binds)   # missing paths are skipped
        self.assertNotIn(("--bind", str(self.home)), binds)               # the home folder stays read-only
        self.assertLess(binds.index(("--bind", root)), binds.index(("--ro-bind", git)))  # .git wins over the project
        self.assertEqual(argv[-3:], ["--", "claude", "-p"])
        self.assertIn("--die-with-parent", argv)
        self.assertNotIn("--new-session", argv)   # it would cut the terminal off

    def test_judge_shape(self):
        argv = self.argv(writable=False, proc=False)
        self.assertNotIn("--proc", argv)
        self.assertIn("--new-session", argv)
        binds = self.binds(argv)
        self.assertEqual(binds[-2], ("--ro-bind", str(self.project_dir)))  # after every writable bind

    def test_seatbelt_judge_profile_denies_the_project_last(self):
        text = containment.seatbelt_profile(self.project_dir, self.home, writable=False)
        lines = text.splitlines()
        self.assertEqual(lines[-2], f'(deny file-write* (subpath "{self.project_dir}"))')
        self.assertEqual(lines[-1], f'(deny file-write* (subpath "{self.project_dir}/.git"))')
        self.assertNotIn(f'(require-not (subpath "{self.project_dir}"))', text)


@unittest.skipUnless(containment.detect().ok, "needs a working sandbox-exec or bubblewrap")
class RealContainmentTest(TempDirCase):
    """Real writes, on whichever system runs the tests (macOS or Linux)."""

    def setUp(self):
        super().setUp()
        subprocess.run(["git", "-C", str(self.project_dir), "init", "-q"], check=True)

    def run_in(self, argv: list[str]) -> str:
        return subprocess.run(argv, capture_output=True, text=True).stdout

    def test_session_writes_the_project_only(self):
        probe = Path.home() / f"foreman-containment-test-{uuid.uuid4().hex}"
        script = (f"touch {self.project_dir}/inside.txt; echo inside=$?; "
                  f"touch {probe}; echo home=$?; "
                  f"touch {self.project_dir}/.git/probe; echo git=$?")
        try:
            out = self.run_in(containment.wrap_session(self.project_dir, ["/bin/sh", "-c", script]))
            self.assertIn("inside=0", out)
            self.assertIn("home=1", out)
            self.assertIn("git=1", out)
            self.assertFalse(probe.exists())
        finally:
            probe.unlink(missing_ok=True)

    def test_judges_cannot_write_the_project_even_inside_a_temp_folder(self):
        script = f"touch {self.project_dir}/planted.txt; echo project=$?; touch {self.tmp}/scratch.txt; echo temp=$?"
        out = self.run_in(containment.wrap_read_only(self.project_dir, ["/bin/sh", "-c", script]))
        self.assertIn("project=1", out)
        self.assertIn("temp=0", out)
        self.assertFalse((self.project_dir / "planted.txt").exists())
