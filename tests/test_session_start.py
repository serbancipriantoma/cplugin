import json
import subprocess
import sys

from helpers import PLUGIN_ROOT, TempDirCase

from cplugin.mindmap import CONTEXT_LIMIT, MIND_MAP_BUDGET


class SessionStartTest(TempDirCase):
    def payload(self, **extra) -> dict:
        return {"session_id": "sess-1", "source": "startup", "cwd": str(self.project_dir),
                "hook_event_name": "SessionStart", **extra}

    def context(self, result) -> str:
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        return out["hookSpecificOutput"]["additionalContext"]

    def test_silent_outside_a_project(self):
        result = self.run_hook("session-start", self.payload())
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertFalse((self.project_dir / ".cplugin").exists())

    def test_stub_map_asks_for_mindmap(self):
        self.init_project()
        text = self.context(self.run_hook("session-start", self.payload()))
        self.assertIn("still the empty template", text)
        self.assertIn("/cplugin:mindmap", text)

    def test_loads_real_map_from_a_subdirectory(self):
        self.init_project()
        (self.project_dir / "MIND_MAP.md").write_text("# MIND_MAP\n\n## [2] Projects → mindmap/projects.md\n")
        sub = self.project_dir / "src" / "deep"
        sub.mkdir(parents=True)
        text = self.context(self.run_hook("session-start", self.payload(cwd=str(sub))))
        self.assertIn("## [2] Projects → mindmap/projects.md", text)

    def test_oversized_map_is_clipped_under_the_cap(self):
        self.init_project()
        big_map = "# MIND_MAP\n" + ("- " + "x" * 97 + "\n") * 200  # 20,011 chars
        (self.project_dir / "MIND_MAP.md").write_text(big_map)
        text = self.context(self.run_hook("session-start", self.payload()))
        self.assertLess(len(text), CONTEXT_LIMIT)
        self.assertIn(f"MIND_MAP.md is {len(big_map.strip()):,} characters", text)
        self.assertIn("How to use the memory", text)  # the reminder survives the clip
        self.assertIn(f"budget: {MIND_MAP_BUDGET:,}", text)

    def test_records_session_and_exports_id(self):
        self.init_project()
        env_file = self.tmp / "env"
        self.context(self.run_hook("session-start", self.payload(), CLAUDE_ENV_FILE=str(env_file)))
        self.assertEqual(env_file.read_text(), "export CPLUGIN_SESSION_ID=sess-1\n")
        meta = json.loads((self.project_dir / ".cplugin/sessions/sess-1/meta.json").read_text())
        self.assertEqual(meta["last_source"], "startup")

    def test_bad_session_id_is_not_used_as_a_path(self):
        self.init_project()
        text = self.context(self.run_hook("session-start", self.payload(session_id="../../evil")))
        self.assertIn("no usable session_id", text)
        self.assertEqual(list((self.project_dir / ".cplugin/sessions").iterdir()), [])

    def test_restores_deleted_launcher(self):
        self.init_project()
        launcher = self.project_dir / ".claude/bin/tasks"
        launcher.unlink()
        self.context(self.run_hook("session-start", self.payload()))
        self.assertTrue(launcher.is_file())

    def test_internal_error_never_fails_the_hook(self):
        result = self.run_hook("no-such-event", self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertIn("hook failed", result.stderr)

    def test_garbage_stdin_never_fails_the_hook(self):
        result =subprocess.run([sys.executable, "-I", str(PLUGIN_ROOT / "hooks/run.py"), "session-start"],
                                input="{not json", capture_output=True, text=True, env=self.env())
        self.assertEqual(result.returncode, 0)
        self.assertIn("hook failed", result.stderr)
