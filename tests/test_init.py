import json
import subprocess
import tomllib

from helpers import PLUGIN_ROOT, TempDirCase

from cplugin.init import BLOCK_BEGIN, merge_claude_md, merge_settings


class InitTest(TempDirCase):
    def test_creates_project_layout(self):
        self.init_project()
        p = self.project_dir
        for rel in (".cplugin/config.toml", ".cplugin/.gitignore", ".cplugin/tasks",
                    ".cplugin/sessions", "mindmap", "MIND_MAP.md", "CLAUDE.md",
                    ".claude/settings.json", ".claude/bin/tasks", ".claude/bin/board", ".claude/bin/sandbox",
                    ".claude/bin/.gitignore"):
            self.assertTrue((p / rel).exists(), rel)
        self.assertIn("# MIND_MAP — Portfolio", (p / "MIND_MAP.md").read_text())
        self.assertTrue((p / "CLAUDE.md").read_text().startswith("# Portfolio\n"))

    def test_launcher_runs_the_cli(self):
        self.init_project()
        out =subprocess.run([str(self.project_dir / ".claude/bin/tasks"), "version"],
                             capture_output=True, text=True, env=self.env())
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(str(PLUGIN_ROOT), out.stdout)

    def test_second_run_changes_nothing(self):
        self.init_project()
        before = {f: f.read_bytes() for f in self.project_dir.rglob("*") if f.is_file()}
        result = self.run_tasks("init", "--name", "Portfolio")
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


OLD_CONFIG = """[workflow]
tests_first = true

[roles.worker]
# Claude sub-agent that writes production code.
model = "opus"                      # opus | sonnet | haiku | fable | full model ID
paths = ["src/**", "app/**"]        # where it may write code
max_parallel = 1

[roles.tester]
model = "sonnet"
paths = ["tests/**", "**/test_*.py", "**/*_test.*", "**/*.test.*", "**/*.spec.*"]

[roles.main]
paths = ["MIND_MAP.md", "mindmap/**"]

[tests]
command = "pytest -q"
"""


class ConfigUpgradeTest(TempDirCase):
    def config(self) -> str:
        return (self.project_dir / ".cplugin" / "config.toml").read_text()

    def test_upgrades_untouched_old_defaults_and_nothing_else(self):
        (self.project_dir / ".cplugin").mkdir()
        (self.project_dir / ".cplugin" / "config.toml").write_text(OLD_CONFIG)
        result = self.run_tasks("init")
        self.assertIn("updated: .cplugin/config.toml (old defaults upgraded: roles.worker.paths, "
                      "roles.tester.paths)", result.stdout)
        text = self.config()
        self.assertIn('paths = ["**"]', text)
        self.assertIn('"**/__tests__/**"', text)
        self.assertIn('paths = ["MIND_MAP.md", "mindmap/**"]', text)
        self.assertIn('command = "pytest -q"', text)
        self.assertIn("# Claude sub-agent that writes production code.", text)
        cfg = tomllib.loads(text)
        self.assertEqual(cfg["roles"]["worker"]["paths"], ["**"])
        self.assertEqual(cfg["roles"]["worker"]["max_parallel"], 1)
        self.assertNotIn("updated: .cplugin/config.toml", self.run_tasks("init").stdout)

    def test_customized_paths_are_left_alone(self):
        (self.project_dir / ".cplugin").mkdir()
        custom = OLD_CONFIG.replace('["src/**", "app/**"]', '["game/**"]')
        (self.project_dir / ".cplugin" / "config.toml").write_text(custom)
        self.run_tasks("init")
        self.assertIn('paths = ["game/**"]', self.config())


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
