import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from helpers import PLUGIN_ROOT, SESSION, ProjectCase

from foreman import board, containment, environment, sandbox
from foreman.project import Project


def decision(out: dict | None) -> str | None:
    return (out or {}).get("hookSpecificOutput", {}).get("permissionDecision")


class FreehandCase(ProjectCase):
    def setUp(self):
        super().setUp()
        git = ["git", "-C", str(self.project_dir), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        self.git = lambda *args: subprocess.run([*git, *args], check=True, capture_output=True)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")

    def state(self) -> dict:
        return json.loads((self.project_dir / ".foreman/sessions" / SESSION / "state.json").read_text())


class FreehandCliTest(FreehandCase):
    def test_on_pauses_the_task_and_off_logs_the_changes(self):
        self.new_task()
        self.activate()
        out = self.tasks_ok("freehand")
        self.assertIn("Freehand on", out)
        self.assertIn("Task 001 is paused meanwhile", out)
        self.assertIsNone(self.state()["task"])
        self.assertIn("## Status\npaused", self.task_md().read_text())
        self.assertIn("Freehand is on", self.tasks_ok("status"))
        self.assertIn("already on", self.tasks_ok("freehand"))

        (self.project_dir / "src").mkdir()
        (self.project_dir / "src" / "a.js").write_text("1\n")
        (self.project_dir / "b.js").write_text("2\n")
        self.git("add", "b.js")
        self.git("commit", "-qm", "quick fix")
        out = self.tasks_ok("freehand", "off")
        self.assertIn("1 commit(s), 2 file(s) changed: b.js, src/a.js", out)
        self.assertIn("`.claude/bin/tasks work 1` resumes it", out)
        log = (self.project_dir / ".foreman" / "freehand.md").read_text()
        self.assertIn("- commits: 1\n  - ", log)
        self.assertIn("quick fix", log)
        self.assertIn("- files changed: `b.js`, `src/a.js`", log)
        self.assertIsNone(self.state()["freehand"])

    def test_work_ends_freehand(self):
        self.new_task()
        self.tasks_ok("freehand")
        out = self.tasks_ok("work", "1")
        self.assertIn("Freehand off.", out)
        self.assertIn("Active task: 001", out)
        self.assertIsNone(self.state()["freehand"])


class FreehandHooksTest(FreehandCase):
    def write(self, rel: str, **who) -> dict | None:
        return self.hook_json("pre-tool-use", self.payload("Write", {"file_path": str(self.project_dir / rel)}, **who))

    def test_rules_are_suspended(self):
        self.tasks_ok("freehand")
        self.assertIsNone(self.write("src/game.ts"))
        self.assertIsNone(self.write("tests/game.test.ts"))
        self.hook_json("post-tool-use", self.payload("Write", {"file_path": str(self.project_dir / "src/game.ts")}))
        self.assertIsNone(self.hook_json("stop", {"session_id": SESSION, "cwd": str(self.project_dir)}))

    def test_only_the_user_turns_it_on(self):
        for command in (".claude/bin/tasks freehand", "tasks freehand on",
                        f"python3 -I {PLUGIN_ROOT}/bin/tasks.py freehand"):
            out = self.hook_json("pre-tool-use", self.payload("Bash", {"command": command}))
            self.assertEqual(decision(out), "deny", command)
        self.assertIsNone(self.hook_json("pre-tool-use", self.payload("Bash", {"command": ".claude/bin/tasks freehand off"})))

    def test_banner_context_and_board_show_it(self):
        self.tasks_ok("freehand")
        out = self.hook_json("session-start", {"session_id": SESSION, "source": "resume", "cwd": str(self.project_dir)})
        self.assertIn("freehand since", out["systemMessage"])
        self.assertIn("Freehand is on since", out["hookSpecificOutput"]["additionalContext"])
        b = board.collect(Project(self.project_dir), SESSION)
        self.assertEqual(b.title, "FREEHAND · the user drives, rules suspended")


class SandboxTest(ProjectCase):
    def test_profile(self):
        home = Path("/Users/someone")
        text = containment.seatbelt_profile(self.project_dir, home)
        self.assertTrue(text.startswith("(version 1)\n(allow default)\n(deny file-write*"))
        self.assertIn(f'(require-not (subpath "{self.project_dir}"))', text)
        self.assertIn('(require-not (subpath "/Users/someone/.claude"))', text)
        self.assertIn('(require-not (regex #"^/Users/someone/\\.claude\\.json"))', text)
        self.assertNotIn('"/Users/someone"))', text)  # the home folder itself stays read-only
        self.assertTrue(text.rstrip().endswith(f'(deny file-write* (subpath "{self.project_dir}/.git"))'))

    def test_plugin_dir_only_for_a_checkout(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.config_dir)}):
            self.assertFalse(sandbox.plugin_installed(PLUGIN_ROOT))
            installed = self.config_dir / "plugins" / "cache" / "m" / "foreman" / "0.1.0"
            installed.mkdir(parents=True)
            self.assertTrue(sandbox.plugin_installed(installed))

    def test_refuses_inside_itself(self):
        with mock.patch.dict(os.environ, {environment.SANDBOX_ENV: "1"}):
            with self.assertRaises(sandbox.SandboxError):
                sandbox.check()

    def test_launcher_dry_run_and_refusals(self):
        launcher = self.project_dir / ".claude" / "bin" / "sandbox"
        self.assertTrue(launcher.is_file())
        claude_stub = self.tmp / "stub-bin" / "claude"
        claude_stub.parent.mkdir()
        claude_stub.write_text("#!/bin/sh\nexit 0\n")
        claude_stub.chmod(0o755)
        python_dir = os.path.dirname(sys.executable)  # the launcher needs Python 3.11+, not the system 3.9
        env = self.env(PATH=os.pathsep.join([str(claude_stub.parent), python_dir, "/usr/bin", "/bin"]))
        out = subprocess.run([str(launcher), "--dry-run", "--continue"], capture_output=True, text=True,
                             cwd=self.project_dir, env=env)
        if containment.detect().ok:
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn(f"{claude_stub} --dangerously-skip-permissions --plugin-dir {PLUGIN_ROOT} --continue",
                          out.stdout)
        else:
            self.assertEqual(out.returncode, 1)
        nested = subprocess.run([str(launcher), "--dry-run"], capture_output=True, text=True,
                                cwd=self.project_dir, env={**env, environment.SANDBOX_ENV: "1"})
        self.assertEqual(nested.returncode, 1)
        self.assertIn("Refusing to run Claude Code without permission prompts unconfined", nested.stderr)
