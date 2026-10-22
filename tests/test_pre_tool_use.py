from helpers import ProjectCase, TempDirCase


def decision(out: dict | None) -> str | None:
    return (out or {}).get("hookSpecificOutput", {}).get("permissionDecision")


def reason(out: dict | None) -> str:
    spec = (out or {}).get("hookSpecificOutput", {})
    return spec.get("permissionDecisionReason") or spec.get("additionalContext") or ""


class OutsideProjectTest(TempDirCase):
    def test_does_nothing_outside_a_project(self):
        out = self.hook_json("pre-tool-use", self.payload("Write", {"file_path": str(self.project_dir / "a.py")}))
        self.assertIsNone(out)


class NoTaskTest(ProjectCase):
    def write(self, rel: str, **extra) -> dict | None:
        return self.hook_json("pre-tool-use", self.payload(
            "Write", {"file_path": str(self.project_dir / rel), "content": "x"}, **extra))

    def test_blocks_code_without_a_task(self):
        for rel in ("src/game.ts", "src/ui/hud.tsx", "styles/main.css", "shaders/water.glsl", "bin/run"):
            out = self.write(rel)
            self.assertEqual(decision(out), "deny", rel)
            self.assertIn("No active task", reason(out))

    def test_relative_paths_are_resolved_against_cwd(self):
        out = self.hook_json("pre-tool-use", self.payload("Edit", {"file_path": "src/game.ts",
                                                                    "old_string": "a", "new_string": "b"}))
        self.assertEqual(decision(out), "deny")

    def test_allows_docs_data_and_plugin_files(self):
        for rel in ("README.md", "assets/levels.json", "mindmap/combat.md", "MIND_MAP.md",
                    ".claude/settings.json", ".foreman/config.toml", "scripts/notes.md"):
            self.assertIsNone(self.write(rel), rel)

    def test_extensionless_script_with_shebang_is_code(self):
        script = self.project_dir / "deploy"
        script.write_text("#!/bin/sh\necho hi\n")
        self.assertEqual(decision(self.write("deploy")), "deny")
        (self.project_dir / "NOTES").write_text("plain")
        self.assertIsNone(self.write("NOTES"))

    def test_extra_code_extensions_from_config(self):
        config = self.project_dir / ".foreman" / "config.toml"
        config.write_text(config.read_text().replace("extra_code_extensions = []", 'extra_code_extensions = ["tscn"]'))
        self.assertEqual(decision(self.write("scenes/main.tscn")), "deny")

    def test_broken_config_still_enforces(self):
        (self.project_dir / ".foreman" / "config.toml").write_text("[[[broken")
        self.assertEqual(decision(self.write("src/game.ts")), "deny")

    def test_outside_the_project_is_not_policed(self):
        self.assertIsNone(self.hook_json("pre-tool-use", self.payload("Write", {"file_path": "/tmp/x.py"})))

    def test_active_task_lets_the_worker_write_code(self):
        self.new_task()
        self.activate()
        self.assertIsNone(self.write("src/game.ts", agent_id="w1", agent_type="foreman:worker"))

    def test_unknown_session_fails_closed(self):
        out = self.write("src/game.ts", session_id="never-registered")
        self.assertEqual(decision(out), "deny")


class TaskFileTest(ProjectCase):
    def test_blocks_creating_task_md_by_hand(self):
        path = self.project_dir / ".foreman" / "tasks" / "009-feature-x" / "task.md"
        out = self.hook_json("pre-tool-use", self.payload("Write", {"file_path": str(path), "content": "# x"}))
        self.assertEqual(decision(out), "deny")
        self.assertIn("tasks new", reason(out))

    def test_blocks_writing_session_state(self):
        path = self.project_dir / ".foreman" / "sessions" / "sess-1" / "state.json"
        out = self.hook_json("pre-tool-use", self.payload("Write", {"file_path": str(path), "content": "{}"}))
        self.assertEqual(decision(out), "deny")

    def test_blocks_shell_shortcuts(self):
        for command in ("mkdir -p .foreman/tasks/005-feature-x",
                        "echo '- [x] a' >> .foreman/tasks/001-feature-x/task.md",
                        "cat x | tee .foreman/tasks/001-feature-x/task.md",
                        "sed -i '' 's/- \\[ \\]/- [x]/g' .foreman/tasks/001-feature-x/task.md",
                        'echo \'{"task": 3}\' > .foreman/sessions/sess-1/state.json'):
            out = self.hook_json("pre-tool-use", self.payload("Bash", {"command": command}))
            self.assertEqual(decision(out), "deny", command)

    def test_allows_reading_task_files_in_the_shell(self):
        for command in ("cat .foreman/tasks/001-feature-x/task.md", "ls .foreman/tasks",
                        ".claude/bin/tasks new feature x --request -", "git add .foreman/tasks"):
            self.assertIsNone(self.hook_json("pre-tool-use", self.payload("Bash", {"command": command})), command)


class GateCountTest(ProjectCase):
    def setUp(self):
        super().setUp()
        self.new_task()
        self.activate()
        self.path = self.task_md()

    def edit(self, old: str, new: str, **extra) -> dict | None:
        return self.hook_json("pre-tool-use", self.payload(
            "Edit", {"file_path": str(self.path), "old_string": old, "new_string": new, **extra}))

    def test_one_gate_with_outcome_passes_silently(self):
        old = "- [ ] The request in my own words:"
        self.assertIsNone(self.edit(old, old.replace("[ ]", "[x]") + " knights damage archers"))

    def test_bare_check_is_pointed_out(self):
        old = "- [ ] The request in my own words:"
        out = self.edit(old, old.replace("[ ]", "[x]"))
        self.assertIsNone(decision(out))
        self.assertIn("Checked without an outcome", reason(out))

    def test_two_gates_warn(self):
        old = "- [ ] In scope:\n- [ ] Out of scope:"
        out = self.edit(old, "- [x] In scope: damage\n- [x] Out of scope: magic")
        self.assertIsNone(decision(out))
        self.assertIn("2 gates in one edit", reason(out))

    def test_three_gates_block(self):
        old = "- [ ] Done means (verifiable criteria):\n- [ ] In scope:\n- [ ] Out of scope:"
        out = self.edit(old, old.replace("[ ]", "[x]"))
        self.assertEqual(decision(out), "deny")
        self.assertIn("3 gates", reason(out))

    def test_replace_all_counts_every_occurrence(self):
        out = self.edit("- [ ]", "- [x]", replace_all=True)
        self.assertEqual(decision(out), "deny")

    def test_write_compares_with_the_file(self):
        text = self.path.read_text()
        out = self.hook_json("pre-tool-use", self.payload(
            "Write", {"file_path": str(self.path), "content": text.replace("- [ ]", "- [x]")}))
        self.assertEqual(decision(out), "deny")

    def test_inactive_task_is_not_policed(self):
        self.tasks_ok("stop")
        old = "- [ ] Done means (verifiable criteria):\n- [ ] In scope:\n- [ ] Out of scope:"
        self.assertIsNone(self.edit(old, old.replace("[ ]", "[x]")))
