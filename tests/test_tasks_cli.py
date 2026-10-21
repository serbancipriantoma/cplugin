import json

from helpers import SESSION, ProjectCase

from cplugin import gates


class NewTest(ProjectCase):
    def test_numbers_and_fills_the_template(self):
        (self.project_dir / "mindmap" / "combat.md").write_text("# Combat\n")
        mind_map = self.project_dir / "MIND_MAP.md"
        mind_map.write_text("# MIND_MAP\n\n## [6] Combat → mindmap/combat.md\n- damage\n")
        out = self.tasks_ok("new", "feature", "knight-damage", "--module", "combat",
                            "--request", "-", stdin="A knight hits an archer for 6-9.\n")
        self.assertIn("Created task 001: .cplugin/tasks/001-feature-knight-damage/task.md", out)
        text = self.task_md().read_text()
        self.assertIn("# 001 — feature — knight-damage", text)
        self.assertIn("## Request\nA knight hits an archer for 6-9.\n", text)
        self.assertIn("- MIND_MAP [6] Combat → `mindmap/combat.md`", text)
        self.assertIn("## Status\npending", text)
        self.assertIn("Red: the tests fail", text)  # tests-first step shape
        self.assertNotIn("{{", text)
        second = self.tasks_ok("new", "bugfix", "fix-it", "--request", "x")
        self.assertIn("Created task 002", second)

    def test_template_has_no_work_plan_gates_until_written(self):
        self.new_task()
        sections = {g.section.split(" ›")[0] for g in gates.parse(self.task_md().read_text())}
        self.assertNotIn("3. Work Plan", sections)

    def test_warns_about_missing_module_and_request(self):
        out = self.tasks_ok("new", "feature", "x", "--module", "nowhere")
        self.assertIn("WARNING: mindmap/nowhere.md does not exist", out)
        self.assertIn("WARNING: no request given", out)

    def test_rejects_bad_names(self):
        for args in (("feature", "Bad Name"), ("chore", "x"), ("feature", "x", "--module", "../etc")):
            result = self.run_tasks("new", *args)
            self.assertNotEqual(result.returncode, 0, args)

    def test_parallel_shape_when_tests_first_is_off(self):
        config = self.project_dir / ".cplugin" / "config.toml"
        config.write_text(config.read_text().replace("tests_first = true", "tests_first = false"))
        self.new_task()
        self.assertIn("in parallel", self.task_md().read_text())
        self.assertNotIn("Red: the tests fail", self.task_md().read_text())


class LifecycleTest(ProjectCase):
    def state(self) -> dict:
        path = self.project_dir / ".cplugin" / "sessions" / SESSION / "state.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def test_work_activates_and_reports_next_gate(self):
        self.new_task()
        out = self.tasks_ok("work", "1")
        self.assertIn("Active task: 001 feature knight-damage", out)
        self.assertIn("Next gate (.cplugin/tasks/001-feature-knight-damage/task.md:", out)
        self.assertEqual(self.state()["task"], 1)
        self.assertIn("## Status\nactive", self.task_md().read_text())
        self.assertIn("Active task: 001", self.tasks_ok("status"))

    def test_switching_pauses_the_previous_task(self):
        self.new_task("one")
        self.new_task("two")
        self.activate(1)
        out = self.tasks_ok("work", "2")
        self.assertIn("Paused task 001", out)
        self.assertIn("## Status\npaused", self.task_md(1).read_text())

    def test_done_refuses_open_gates_then_closes(self):
        self.new_task()
        self.activate()
        result = self.run_tasks("done")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unchecked gate(s)", result.stderr)

        path = self.task_md()
        path.write_text(path.read_text().replace("## 4. Implementation Review",
                                                 "### Step 1: x\n- [ ] Green: ok\n\n## 4. Implementation Review"))
        path.write_text(path.read_text().replace("- [ ]", "- [x]"))
        out = self.tasks_ok("done")
        self.assertIn("Task 001 is done", out)
        self.assertIn("## Status\ndone", path.read_text())
        self.assertIsNone(self.state()["task"])
        self.assertEqual(self.run_tasks("work", "1").returncode, 1)

    def test_done_refuses_an_empty_work_plan(self):
        self.new_task()
        self.activate()
        path = self.task_md()
        path.write_text(path.read_text().replace("- [ ]", "- [x]"))
        result = self.run_tasks("done")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no gates in its Work Plan", result.stderr)

    def test_stop_and_pause(self):
        self.new_task()
        self.activate()
        self.assertIn("Ask the user: which faction?", self.tasks_ok("pause", "which", "faction?"))
        self.assertEqual(self.state()["pause"], "which faction?")
        self.assertIn("Deactivated task 001", self.tasks_ok("stop"))
        self.assertIsNone(self.state()["task"])
        self.assertIn("No active task", self.tasks_ok("status"))

    def test_list(self):
        self.new_task("one")
        self.activate(1)
        out = self.tasks_ok("list")
        self.assertRegex(out, r"001  active\s+0/\d+ +feature +one")

    def test_session_is_required_for_work(self):
        self.new_task()
        result = self.run_tasks("work", "1", session=None)
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot tell which Claude Code session", result.stderr)

    def test_context_includes_the_active_task(self):
        self.new_task()
        self.activate()
        self.assertIn("Active task: 001 feature knight-damage", self.tasks_ok("context"))
