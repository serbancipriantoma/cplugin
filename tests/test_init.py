import json
import subprocess
import tomllib

from helpers import PLUGIN_ROOT, TempDirCase

from foreman.init import BLOCK_BEGIN, STATUS_LINE, merge_claude_md, merge_settings


class InitTest(TempDirCase):
    def test_creates_project_layout(self):
        self.init_project()
        p = self.project_dir
        for rel in (".foreman/config.toml", ".foreman/.gitignore", ".foreman/tasks",
                    ".foreman/sessions", "mindmap", "MIND_MAP.md", "CLAUDE.md",
                    ".claude/settings.json", ".claude/settings.local.json", ".claude/bin/tasks",
                    ".claude/bin/board", ".claude/bin/sandbox", ".claude/bin/statusline",
                    ".claude/bin/.gitignore", "locker/.gitignore"):
            self.assertTrue((p / rel).exists(), rel)
        self.assertIn("# MIND_MAP — Portfolio", (p / "MIND_MAP.md").read_text())
        self.assertTrue((p / "CLAUDE.md").read_text().startswith("# Portfolio\n"))

    def test_launcher_runs_the_cli(self):
        self.init_project()
        out =subprocess.run([str(self.project_dir / ".claude/bin/tasks"), "version"],
                             capture_output=True, text=True, env=self.env())
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(str(PLUGIN_ROOT), out.stdout)

    def test_start_works_in_the_session_that_ran_init(self):
        # /foreman:init ends with `tasks start`. That session began before the setup,
        # so it carries no FOREMAN_SESSION_ID and no session of it is registered.
        self.init_project()
        result = self.run_tasks("start", session=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"worker  opus     {PLUGIN_ROOT}/agents/worker.md", result.stdout)
        self.assertIn(f"tester  sonnet   {PLUGIN_ROOT}/agents/tester.md", result.stdout)
        self.assertIn("Judges (panel, up to 8 min each)", result.stdout)
        self.assertIn("no open tasks", result.stdout)
        (self.project_dir / "locker" / "hero.png").write_bytes(b"\x89PNG")
        self.assertIn("Locker\n  locker/ (not in git), 1 file(s)", self.run_tasks("start", session=None).stdout)

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
        self.assertIn("inside the foreman project", result.stderr)
        self.assertFalse((sub / ".foreman").exists())

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

    def test_points_local_settings_at_the_status_line(self):
        result = self.run_tasks("init", session=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("created: .claude/settings.local.json (statusLine: foreman's status line)\n", result.stdout)
        local = json.loads((self.project_dir / ".claude" / "settings.local.json").read_text())
        self.assertEqual(local["statusLine"], STATUS_LINE)
        # Claude Code runs the command through a shell, with CLAUDE_PROJECT_DIR set.
        shown = subprocess.run(["sh", "-c", local["statusLine"]["command"]], input="{}", capture_output=True,
                               text=True, env=self.env(NO_COLOR="1", CLAUDE_PROJECT_DIR=str(self.project_dir)))
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(shown.stdout, "unknown · 0/200k · 0 (↑0 ↓0) · $0.00\n")

    def test_says_when_it_replaces_the_users_status_line(self):
        (self.config_dir / "settings.json").write_text(json.dumps({"statusLine": {"type": "command",
                                                                                  "command": "mine"}}))
        result = self.run_tasks("init", session=None)
        self.assertIn("in this project it replaces the one in ~/.claude/settings.json", result.stdout)

    def test_keeps_a_status_line_the_project_sets(self):
        mine = {"type": "command", "command": "my-line"}
        for name in ("settings.json", "settings.local.json"):
            project = self.tmp / name.replace(".", "-")
            (project / ".claude").mkdir(parents=True)
            (project / ".claude" / name).write_text(json.dumps({"statusLine": mine}))
            result = self.run_tasks("init", cwd=project, session=None)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("unchanged: statusLine (the project sets its own", result.stdout)
            self.assertEqual(json.loads((project / ".claude" / name).read_text())["statusLine"], mine)
        self.assertFalse((self.tmp / "settings-json" / ".claude" / "settings.local.json").exists())

    def test_keeps_local_settings_out_of_git(self):
        # Without the developer's own excludes, which may already ignore the file.
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "XDG_CONFIG_HOME": str(self.tmp / "xdg")}
        subprocess.run(["git", "init", "-q", str(self.project_dir)], check=True, env=self.env(**env))
        result = self.run_tasks("init", session=None, extra_env=env)
        self.assertIn("created: .claude/.gitignore (keeps settings.local.json out of git)", result.stdout)
        ignored = subprocess.run(["git", "-C", str(self.project_dir), "check-ignore", "-q",
                                  ".claude/settings.local.json"], env=self.env(**env))
        self.assertEqual(ignored.returncode, 0)
        again = self.run_tasks("init", session=None, extra_env=env)
        self.assertNotIn(".claude/.gitignore", again.stdout)

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.project_dir), *args], capture_output=True, text=True,
                              env=self.env(GIT_CONFIG_GLOBAL="/dev/null", XDG_CONFIG_HOME=str(self.tmp / "xdg")))

    def test_locker_is_kept_out_of_git(self):
        self.git("init", "-q")
        result = self.run_tasks("init", session=None)
        self.assertIn("created: locker/ (the locker: not in git", result.stdout)
        (self.project_dir / "locker" / "hero.png").write_bytes(b"\x89PNG")
        self.assertEqual(self.git("check-ignore", "-q", "locker/hero.png").returncode, 0)
        self.assertNotIn("locker", self.git("status", "--porcelain", "--untracked-files=all").stdout)
        self.assertIn("`locker/` holds what passes between you and the user",
                      (self.project_dir / "CLAUDE.md").read_text())
        self.assertIn("unchanged: locker/", self.run_tasks("init", session=None).stdout)

    def test_locker_takes_the_configured_name(self):
        self.init_project()
        config_path = self.project_dir / ".foreman" / "config.toml"
        config_path.write_text(config_path.read_text().replace('dir = "locker"', 'dir = "crate"'))
        result = self.run_tasks("init", session=None)
        self.assertIn("created: crate/ (the locker", result.stdout)
        self.assertIn("`crate/` holds what passes", (self.project_dir / "CLAUDE.md").read_text())

    def test_leaves_a_folder_the_project_owns(self):
        self.git("init", "-q")
        tracked = self.project_dir / "locker" / "notes.txt"
        tracked.parent.mkdir()
        tracked.write_text("ours")
        self.git("add", "locker/notes.txt")
        result = self.run_tasks("init", session=None)
        self.assertIn("WARNING: locker is the project's own", result.stdout)
        self.assertFalse((self.project_dir / "locker" / ".gitignore").exists())
        mine = self.tmp / "other"
        (mine / "locker").mkdir(parents=True)
        (mine / "locker" / ".gitignore").write_text("*.tmp\n")
        result = self.run_tasks("init", cwd=mine, session=None)
        self.assertIn("WARNING: locker is the project's own", result.stdout)
        self.assertEqual((mine / "locker" / ".gitignore").read_text(), "*.tmp\n")

    def test_bad_locker_name_is_reported(self):
        self.init_project()
        config_path = self.project_dir / ".foreman" / "config.toml"
        config_path.write_text(config_path.read_text().replace('dir = "locker"', 'dir = "../outside"'))
        self.assertIn("WARNING: locker.dir in .foreman/config.toml is not a usable folder name",
                      self.run_tasks("init", session=None).stdout)
        self.assertFalse((self.tmp / "outside").exists())


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
        return (self.project_dir / ".foreman" / "config.toml").read_text()

    def test_upgrades_untouched_old_defaults_and_nothing_else(self):
        (self.project_dir / ".foreman").mkdir()
        (self.project_dir / ".foreman" / "config.toml").write_text(OLD_CONFIG)
        result = self.run_tasks("init")
        self.assertIn("updated: .foreman/config.toml (old defaults upgraded: roles.worker.paths, "
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
        self.assertNotIn("updated: .foreman/config.toml", self.run_tasks("init").stdout)

    def test_customized_paths_are_left_alone(self):
        (self.project_dir / ".foreman").mkdir()
        custom = OLD_CONFIG.replace('["src/**", "app/**"]', '["game/**"]')
        (self.project_dir / ".foreman" / "config.toml").write_text(custom)
        self.run_tasks("init")
        self.assertIn('paths = ["game/**"]', self.config())


class MergeTest(TempDirCase):
    BLOCK = "<!-- foreman:begin -->\nnew\n<!-- foreman:end -->\n"

    def test_replaces_existing_block_in_place(self):
        existing = "top\n\n<!-- foreman:begin x -->\nold\n<!-- foreman:end -->\n\nbottom\n"
        merged = merge_claude_md(existing, self.BLOCK, "P")
        self.assertEqual(merged, "top\n\n<!-- foreman:begin -->\nnew\n<!-- foreman:end -->\n\nbottom\n")

    def test_appends_when_no_block(self):
        self.assertEqual(merge_claude_md("top\n", self.BLOCK, "P"),
                         "top\n\n<!-- foreman:begin -->\nnew\n<!-- foreman:end -->\n")

    def test_settings_respect_explicit_choice(self):
        settings = merge_settings({"enabledPlugins": {"playbook@m": True}}, ["playbook@m"])
        self.assertTrue(settings["enabledPlugins"]["playbook@m"])
