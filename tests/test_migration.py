import json

from helpers import TempDirCase

OLD_BLOCK = "<!-- cplugin:begin — managed by /cplugin:init -->\n## cplugin workflow\nold\n<!-- cplugin:end -->"


class LegacyLayoutTest(TempDirCase):
    """Projects set up while the plugin was still called cplugin."""

    def setUp(self):
        super().setUp()
        legacy = self.project_dir / ".cplugin"
        (legacy / "tasks" / "001-feature-x").mkdir(parents=True)
        (legacy / "tasks" / "001-feature-x" / "task.md").write_text("# 001 — feature — x\n\n## Status\nactive\n")
        (legacy / "sessions" / "s-old").mkdir(parents=True)
        (legacy / "sessions" / "s-old" / "state.json").write_text(json.dumps({"task": 1}))
        (legacy / "config.toml").write_text("[tests]\ncommand = \"npm test\"\n")
        (self.project_dir / "CLAUDE.md").write_text(f"# Game\n\nMine.\n\n{OLD_BLOCK}\n\nAfter.\n")
        (self.project_dir / "MIND_MAP.md").write_text("<!-- cplugin:stub — old -->\n# MIND_MAP\n")

    def test_session_start_says_how_to_migrate(self):
        out = self.hook_json("session-start", {"session_id": "s1", "cwd": str(self.project_dir)})
        self.assertIn("Run /foreman:init to move it to .foreman/", out["systemMessage"])
        self.assertFalse((self.project_dir / ".foreman").exists())

    def test_init_moves_the_state_and_replaces_the_block(self):
        result = self.run_tasks("init", session=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("updated: .cplugin/ moved to .foreman/", result.stdout)
        self.assertFalse((self.project_dir / ".cplugin").exists())
        state = self.project_dir / ".foreman"
        self.assertTrue((state / "tasks" / "001-feature-x" / "task.md").is_file())
        self.assertEqual(json.loads((state / "sessions" / "s-old" / "state.json").read_text())["task"], 1)
        self.assertIn('command = "npm test"', (state / "config.toml").read_text())
        claude_md = (self.project_dir / "CLAUDE.md").read_text()
        self.assertNotIn("cplugin", claude_md)
        self.assertIn("<!-- foreman:begin", claude_md)
        self.assertTrue(claude_md.startswith("# Game\n\nMine.\n\n"))
        self.assertTrue(claude_md.endswith("<!-- foreman:end -->\n\nAfter.\n"))
        self.assertIn("still the empty template", self.run_tasks("context").stdout)
        self.assertNotIn("moved", self.run_tasks("init", session=None).stdout)

    def test_a_project_with_both_folders_is_left_alone(self):
        (self.project_dir / ".foreman").mkdir()
        self.run_tasks("init", session=None)
        self.assertTrue((self.project_dir / ".cplugin").is_dir())
