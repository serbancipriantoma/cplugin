import os
from unittest import mock

from helpers import PLUGIN_ROOT, ProjectCase

from foreman import config, environment
from foreman.containment import Containment
from foreman.project import Project


OK = Containment("sandbox-exec", "ok")
NESTED = Containment("sandbox-exec", "nested", "already inside another sandbox")


class EnvironmentCase(ProjectCase):
    def setUp(self):
        super().setUp()
        self.only_codex = self.tmp / "only-codex"
        self.only_codex.mkdir()
        stub = self.only_codex / "codex"
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
        self.project = Project(self.project_dir)

    def cfg(self) -> dict:
        return config.load(self.project)


class BannerTest(EnvironmentCase):
    def test_marks_missing_judges(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.only_codex)}):
            text = environment.banner(self.project, self.cfg(), None, OK)
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("foreman "))
        self.assertIn("no active task", lines[0])
        self.assertIn("MIND_MAP.md is still the empty template", lines[0])
        self.assertEqual(lines[1], "agents: worker opus · tester sonnet")
        self.assertEqual(lines[2], 'judges: codex ✓, agy ✗ not installed  (say "start" for details)')

    def test_no_judge_installed_names_the_fallback(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "nowhere")}):
            text = environment.banner(self.project, self.cfg(), None, OK)
        self.assertIn("codex ✗ not installed, agy ✗ not installed → claude -p (sonnet), read-only", text)
        self.assertIn("`claude` is not on PATH", text)

    def test_warns_when_judges_cannot_be_sandboxed(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.only_codex)}):
            only_codex = environment.banner(self.project, self.cfg(), None, NESTED)
        self.assertNotIn("warning", only_codex)  # codex brings its own sandbox
        agy = self.only_codex / "agy"
        agy.write_text("#!/bin/sh\nexit 0\n")
        agy.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(self.only_codex)}):
            text = environment.banner(self.project, self.cfg(), None, NESTED)
        self.assertIn("warning: judges run without an OS sandbox here (sandbox-exec: already inside another sandbox)", text)


class ReportTest(EnvironmentCase):
    def test_full_report(self):
        self.new_task("one")
        self.new_task("two")
        self.activate(2)
        with mock.patch.dict(os.environ, {"PATH": str(self.only_codex)}):
            text = environment.report(self.project, self.cfg(), PLUGIN_ROOT, "sess-1", OK)
        self.assertIn(f"worker  opus     {PLUGIN_ROOT}/agents/worker.md", text)
        self.assertIn(f"codex   ✓ {self.only_codex}/codex · the CLI's default model", text)
        self.assertIn("agy     ✗ not installed: this seat is skipped", text)
        self.assertIn("active: 002 feature two", text)
        self.assertIn("pending 001 feature one", text)
        self.assertIn("tests.command is not set", text)


class HookAndCliTest(EnvironmentCase):
    def test_session_start_shows_the_banner_to_the_user_and_the_agent(self):
        out = self.hook_json("session-start", {"session_id": "sess-2", "source": "startup",
                                               "cwd": str(self.project_dir)}, PATH=str(self.only_codex))
        self.assertIn("judges: codex ✓, agy ✗ not installed", out["systemMessage"])
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("This session, as shown to the user:\nforeman ", context)

    def test_tasks_start_and_config_show(self):
        env = {"PATH": f"{self.only_codex}{os.pathsep}/usr/bin{os.pathsep}/bin"}
        out = self.run_tasks("start", extra_env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Judges (panel, up to 8 min each)", out.stdout)
        self.assertIn("agy     ✗ not installed", out.stdout)
        shown = self.run_tasks("config", "show", extra_env=env).stdout
        self.assertIn("judges: panel · codex ✓, agy ✗ not installed", shown)
