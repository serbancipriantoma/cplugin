import json
import subprocess

from helpers import PLUGIN_ROOT, TempDirCase

from cplugin.init import BLOCK_BEGIN, merge_claude_md, merge_settings


class InitTest(TempDirCase):
    def test_creates_project_layout(self):
        self.init_project()
        p = self.project_dir
        for rel in (".cplugin/config.toml", ".cplugin/.gitignore", ".cplugin/tasks",
                    ".cplugin/sessions", "mindmap", "MIND_MAP.md", "CLAUDE.md",
                    ".claude/settings.json", ".claude/bin/tasks", ".claude/bin/.gitignore"):
            self.assertTrue((p / rel).exists(), rel)
        self.assertIn("# MIND_MAP — Clinic", (p / "MIND_MAP.md").read_text())
        self.assertTrue((p / "CLAUDE.md").read_text().startswith("# Clinic\n"))

    def test_launcher_runs_the_cli(self):
        self.init_project()
        out =subprocess.run([str(self.project_dir / ".claude/bin/tasks"), "version"],
                             capture_output=True, text=True, env=self.env())
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(str(PLUGIN_ROOT), out.stdout)

    def test_second_run_changes_nothing(self):
        self.init_project()
        before = {f: f.read_bytes() for f in self.project_dir.rglob("*") if f.is_file()}
        result = self.run_tasks("init", "--name", "Clinic")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("created:", result.stdout)
        self.assertNotIn("updated:", result.stdout)
        after = {f: f.read_bytes() for f in self.project_dir.rglob("*") if f.is_file()}
        self.assertEqual(before, after)

    def test_keeps_user_files(self):
        (self.project_dir / "CLAUDE.md").write_text("# Mine\n\nKeep this.\n")
        (self.project_dir / "MIND_MAP.md").write_text("# real map\n")
        self.init_project()
        claude_md = (self.project_dir / "CLAUDE.md").read_text()
        self.assertTrue(claude_md.startswith("# Mine\n\nKeep this.\n"))
        self.assertEqual(claude_md.count(BLOCK_BEGIN), 1)
        self.assertEqual((self.project_dir / "MIND_MAP.md").read_text(), "# real map\n")

    def test_refuses_to_nest_inside_a_project(self):
        self.init_project()
        sub = self.project_dir / "src"
        sub.mkdir()
        result = self.run_tasks("init", cwd=sub)
        self.assertEqual(result.returncode, 1)
        self.assertIn("inside the cplugin project", result.stderr)
        self.assertFalse((sub / ".cplugin").exists())

    def test_disables_installed_playbook_only_when_unset(self):
        plugins = self.config_dir / "plugins"
        plugins.mkdir()
        (plugins / "installed_plugins.json").write_text(json.dumps({"plugins": {
            "playbook@playbook-x-marketplace": [], "other@market": []}}))
        settings_path = self.project_dir / ".claude" / "settings.json"
        settings_path.parent.mkdir()
        settings_path.write_text(json.dumps({"model": "opus", "permissions": {"deny": ["TodoWrite"]}}))
        self.init_project()
        settings = json.loads(settings_path.read_text())
        self.assertEqual(settings["model"], "opus")
        self.assertEqual(settings["permissions"]["deny"], ["TodoWrite", "EnterPlanMode"])
        self.assertEqual(settings["enabledPlugins"], {"playbook@playbook-x-marketplace": False})

    def test_invalid_settings_left_untouched(self):
        settings_path = self.project_dir / ".claude" / "settings.json"
        settings_path.parent.mkdir()
        settings_path.write_text("{not json")
        result = self.run_tasks("init")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARNING: .claude/settings.json is not a JSON object", result.stdout)
        self.assertEqual(settings_path.read_text(), "{not json")

    def test_warns_outside_git(self):
        result = self.run_tasks("init")
        self.assertIn("WARNING: not a git repository", result.stdout)


class MergeTest(TempDirCase):
    BLOCK = "<!-- cplugin:begin -->\nnew\n<!-- cplugin:end -->\n"

    def test_replaces_existing_block_in_place(self):
        existing = "top\n\n<!-- cplugin:begin x -->\nold\n<!-- cplugin:end -->\n\nbottom\n"
        merged = merge_claude_md(existing, self.BLOCK, "P")
        self.assertEqual(merged, "top\n\n<!-- cplugin:begin -->\nnew\n<!-- cplugin:end -->\n\nbottom\n")

    def test_appends_when_no_block(self):
        self.assertEqual(merge_claude_md("top\n", self.BLOCK, "P"),
                         "top\n\n<!-- cplugin:begin -->\nnew\n<!-- cplugin:end -->\n")

    def test_settings_respect_explicit_choice(self):
        settings = merge_settings({"enabledPlugins": {"playbook@m": True}}, ["playbook@m"])
        self.assertTrue(settings["enabledPlugins"]["playbook@m"])
