import json

from helpers import SESSION, ProjectCase


def context_of(out: dict | None) -> str:
    return (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")


class PostToolUseTest(ProjectCase):
    def post(self, tool: str = "Read", tool_input: dict | None = None, **extra) -> str:
        return context_of(self.hook_json("post-tool-use", self.payload(tool, tool_input or {"file_path": "x"}, **extra)))

    def counters(self) -> dict:
        return json.loads((self.project_dir / ".foreman/sessions" / SESSION / "counters.json").read_text())

    def test_silent_without_a_task_but_counts(self):
        self.assertEqual(self.post(), "")
        self.post("Write", {"file_path": str(self.project_dir / "a.md")})
        self.assertEqual(self.counters()["turn_tools"], 2)
        self.assertEqual(self.counters()["turn_writes"], 1)

    def test_echoes_the_next_gate_with_location(self):
        self.new_task()
        self.activate()
        text = self.post()
        self.assertRegex(text, r"^\[foreman\] Task 001 · gate 1/\d+ · \.foreman/tasks/001-feature-knight-damage/task\.md:\d+ "
                               r"\[1\. Design\] Read the affected sections")

    def test_questions_start_after_a_few_calls_on_one_gate(self):
        self.new_task()
        self.activate()
        self.assertEqual(len(self.post().splitlines()), 1)
        self.assertEqual(len(self.post().splitlines()), 1)
        third = self.post("Edit", {"file_path": str(self.project_dir / "src/a.ts")})
        self.assertEqual(len(third.splitlines()), 2)
        self.assertIn(third.splitlines()[1], ("Is this the simplest change that works?",
                                              "How will I verify this?",
                                              "Does this serve the request, or an idea of my own?"))

    def test_moving_to_the_next_gate_resets_the_count(self):
        self.new_task()
        self.activate()
        for _ in range(3):
            self.post()
        self.check_gate("Read the affected sections", "combat.md")
        self.assertIn("The request in my own words", self.post())
        self.assertEqual(self.counters()["gate_calls"], 1)

    def test_test_commands_get_test_questions(self):
        self.new_task()
        self.activate()
        for _ in range(2):
            self.post()
        text = self.post("Bash", {"command": "npm test -- --run"})
        self.assertIn(text.splitlines()[1], ("Did I read the output, or skim it?",
                                             "Did it pass (or fail) for the right reason?",
                                             "Am I testing what the criteria say, or what is easy to test?"))

    def test_sub_agents_are_left_alone_for_now(self):
        self.new_task()
        self.activate()
        self.assertEqual(self.post(agent_type="foreman:worker"), "")


class StopTest(ProjectCase):
    def stop(self, **extra) -> dict | None:
        return self.hook_json("stop", {"session_id": SESSION, "cwd": str(self.project_dir), **extra})

    def busy_turn(self) -> None:
        self.hook_json("post-tool-use", self.payload("Write", {"file_path": str(self.project_dir / "a.md")}))

    def test_blocks_with_open_gates_after_real_work(self):
        self.new_task()
        self.activate()
        self.busy_turn()
        out = self.stop()
        self.assertEqual(out["decision"], "block")
        self.assertIn("Task 001 has", out["reason"])
        self.assertIn("tasks pause", out["reason"])

    def test_allows_a_conversational_turn(self):
        self.new_task()
        self.activate()
        self.hook_json("post-tool-use", self.payload("Read", {"file_path": "x"}))
        self.assertIsNone(self.stop())

    def test_never_blocks_twice_in_a_row(self):
        self.new_task()
        self.activate()
        self.busy_turn()
        self.assertIsNone(self.stop(stop_hook_active=True))

    def test_pause_lets_the_turn_end_once(self):
        self.new_task()
        self.activate()
        self.tasks_ok("pause", "which faction first?")
        self.busy_turn()
        self.assertIsNone(self.stop())
        self.busy_turn()
        self.assertEqual(self.stop()["decision"], "block")

    def test_counters_reset_when_the_turn_ends(self):
        self.busy_turn()
        self.assertIsNone(self.stop())
        counters = json.loads((self.project_dir / ".foreman/sessions" / SESSION / "counters.json").read_text())
        self.assertEqual((counters["turn_tools"], counters["turn_writes"]), (0, 0))

    def test_no_task_means_no_block(self):
        self.busy_turn()
        self.assertIsNone(self.stop())


class SessionEndTest(ProjectCase):
    def test_marks_the_end_and_keeps_the_task(self):
        self.new_task()
        self.activate()
        self.hook_json("session-end", {"session_id": SESSION, "cwd": str(self.project_dir),
                                       "reason": "prompt_input_exit"})
        directory = self.project_dir / ".foreman/sessions" / SESSION
        self.assertEqual(json.loads((directory / "meta.json").read_text())["end_reason"], "prompt_input_exit")
        self.assertEqual(json.loads((directory / "state.json").read_text())["task"], 1)
        context = self.start_session(source="resume")
        self.assertIn("Active task: 001 feature knight-damage", context)
