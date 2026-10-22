import json
import os
import subprocess
import time

from helpers import SESSION, ProjectCase

WORKER = {"agent_id": "w1", "agent_type": "foreman:worker"}
TESTER = {"agent_id": "t1", "agent_type": "foreman:tester"}
OTHER = {"agent_id": "g1", "agent_type": "general-purpose"}


def decision(out: dict | None) -> str | None:
    return (out or {}).get("hookSpecificOutput", {}).get("permissionDecision")


def message(out: dict | None) -> str:
    spec = (out or {}).get("hookSpecificOutput", {})
    return spec.get("permissionDecisionReason") or spec.get("additionalContext") or ""


class ActiveTaskCase(ProjectCase):
    def setUp(self):
        super().setUp()
        self.new_task()
        self.activate()

    def pre(self, tool: str, tool_input: dict, **who) -> dict | None:
        return self.hook_json("pre-tool-use", self.payload(tool, tool_input, **who))

    def post(self, tool: str, tool_input: dict, **who) -> dict | None:
        return self.hook_json("post-tool-use", self.payload(tool, tool_input, **who))

    def write(self, rel: str, **who) -> dict | None:
        return self.pre("Write", {"file_path": str(self.project_dir / rel), "content": "x"}, **who)


class WriteRulesTest(ActiveTaskCase):
    def test_main_delegates_code_and_tests(self):
        out = self.write("src/game.ts")
        self.assertEqual(decision(out), "deny")
        self.assertIn("subagent_type 'foreman:worker'", message(out))
        self.assertIn("foreman:tester", message(self.write("tests/game.test.ts")))

    def test_each_role_writes_what_it_owns(self):
        self.assertIsNone(self.write("src/game.ts", **WORKER))
        self.assertIsNone(self.write("tests/game.test.ts", **TESTER))
        self.assertIsNone(self.write("MIND_MAP.md"))
        self.assertIsNone(self.write("README.md", **WORKER))
        self.assertEqual(decision(self.write("tests/game.test.ts", **WORKER)), "deny")
        self.assertEqual(decision(self.write("src/game.ts", **TESTER)), "deny")
        self.assertEqual(decision(self.write("src/game.ts", **OTHER)), "deny")
        self.assertEqual(decision(self.write("mindmap/projects.md", **WORKER)), "deny")

    def test_sub_agents_keep_out_of_task_and_plugin_files(self):
        task_md = str(self.task_md())
        out = self.pre("Edit", {"file_path": task_md, "old_string": "- [ ]", "new_string": "- [x]"}, **WORKER)
        self.assertEqual(decision(out), "deny")
        self.assertIn("Only the main agent edits task.md", message(out))
        self.assertEqual(decision(self.write(".foreman/config.toml", **TESTER)), "deny")
        self.assertIsNone(self.write(".foreman/config.toml"))

    def test_older_config_without_roles_gets_the_defaults(self):
        config = self.project_dir / ".foreman" / "config.toml"
        config.write_text("[tests]\ncommand = \"npm test\"\n")
        self.assertIsNone(self.write("src/game.ts", **WORKER))
        self.assertEqual(decision(self.write("tests/game.test.ts", **WORKER)), "deny")


class CliAndAgentRulesTest(ActiveTaskCase):
    def test_sub_agents_cannot_drive_the_task(self):
        for command in (".claude/bin/tasks done", "cd x && .claude/bin/tasks work 2", "tasks pause why"):
            self.assertEqual(decision(self.pre("Bash", {"command": command}, **WORKER)), "deny", command)
        self.assertIsNone(self.pre("Bash", {"command": ".claude/bin/tasks status"}, **WORKER))
        self.assertIsNone(self.pre("Bash", {"command": "npm test"}, **TESTER))

    def test_foreman_agents_need_the_configured_model(self):
        out = self.pre("Agent", {"subagent_type": "foreman:worker", "prompt": "x"})
        self.assertEqual(decision(out), "deny")
        self.assertIn("model=\"opus\"", message(out))
        self.assertIsNone(self.pre("Agent", {"subagent_type": "foreman:worker", "model": "opus", "prompt": "x"}))
        self.assertIsNone(self.pre("Agent", {"subagent_type": "foreman:tester", "model": "sonnet", "prompt": "x"}))
        self.assertIsNone(self.pre("Agent", {"subagent_type": "general-purpose", "prompt": "x"}))

    def test_foreman_agents_refuse_worktree_isolation(self):
        out = self.pre("Agent", {"subagent_type": "foreman:tester", "model": "sonnet", "isolation": "worktree"})
        self.assertEqual(decision(out), "deny")

    def test_foreman_agents_need_an_active_task(self):
        self.tasks_ok("stop")
        out = self.pre("Agent", {"subagent_type": "foreman:worker", "model": "opus"})
        self.assertIn("no task is active", message(out))


class BashCheckTest(ActiveTaskCase):
    def setUp(self):
        super().setUp()
        (self.project_dir / "src").mkdir()
        (self.project_dir / "src" / "game.ts").write_text("export {}\n")
        (self.project_dir / ".gitignore").write_text("dist/\n")
        git = ["git", "-C", str(self.project_dir), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "init"], check=True)

    def bash(self, use_id: str, effect, **who) -> str:
        self.pre("Bash", {"command": "some command"}, tool_use_id=use_id, **who)
        effect()
        return message(self.post("Bash", {"command": "some command"}, tool_use_id=use_id, **who))

    def touch(self, rel: str, text: str = "changed\n"):
        def effect():
            path = self.project_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return effect

    def test_tester_changing_code_through_bash_is_caught_and_recorded(self):
        note = self.bash("b1", self.touch("src/game.ts"), **TESTER)
        self.assertIn("Role violation: as the tester you changed src/game.ts", note)
        violations = self.task_md().read_text().split("## Violations")[1]
        self.assertIn("tester changed `src/game.ts` through Bash (owner: worker)", violations)

    def test_owner_changes_ignored_files_and_deletions(self):
        self.assertEqual(self.bash("b2", self.touch("src/game.ts"), **WORKER), "")
        self.assertEqual(self.bash("b3", self.touch("dist/app.js"), **TESTER), "")
        note = self.bash("b4", lambda: (self.project_dir / "src" / "game.ts").unlink(), **TESTER)
        self.assertIn("src/game.ts", note)

    def test_main_agent_gets_the_gate_echo_and_the_violation(self):
        note = self.bash("b5", self.touch("src/new.ts"))
        self.assertIn("[foreman] Task 001", note)
        self.assertIn("as the main agent you changed src/new.ts", note)

    def test_parallel_tool_writes_are_not_blamed_on_bash(self):
        def worker_edits_meanwhile():
            self.touch("src/game.ts", "by the worker\n")()
            self.post("Write", {"file_path": str(self.project_dir / "src/game.ts")}, **WORKER)
        self.assertEqual(self.bash("b6", worker_edits_meanwhile, **TESTER), "")

    def test_project_inside_a_larger_repository(self):
        from foreman import bashcheck
        outer = self.tmp / "outer"
        inner = outer / "games" / "proj"
        inner.mkdir(parents=True)
        subprocess.run(["git", "-C", str(outer), "init", "-q"], check=True)
        (inner / "a.ts").write_text("x")
        (outer / "elsewhere.ts").write_text("x")
        self.assertEqual(set(bashcheck.take(inner)), {"a.ts"})


class SubagentHooksTest(ActiveTaskCase):
    def agent_file(self, key: str) -> dict:
        return json.loads((self.project_dir / ".foreman/sessions" / SESSION / "agents" / f"{key}.json").read_text())

    def start(self, **who) -> str:
        out = self.hook_json("subagent-start", {"session_id": SESSION, "cwd": str(self.project_dir), **who})
        return message(out)

    def test_briefs_the_roles(self):
        brief = self.start(**WORKER)
        self.assertIn("You are the worker for task 001 feature knight-damage", brief)
        self.assertIn("You may write: code files under **", brief)
        self.assertIn("tests (tests/**", brief)
        self.assertIn("You are the tester", self.start(**TESTER))
        self.assertIn("only foreman:worker writes code", self.start(**OTHER))
        self.assertEqual(self.agent_file("w1")["status"], "running")

    def test_stop_marks_done(self):
        self.start(**WORKER)
        self.hook_json("subagent-stop", {"session_id": SESSION, "cwd": str(self.project_dir), **WORKER})
        self.assertEqual(self.agent_file("w1")["status"], "done")

    def test_sub_agent_calls_do_not_count_as_main_turn(self):
        self.post("Write", {"file_path": str(self.project_dir / "src/a.ts")}, **WORKER)
        counters_path = self.project_dir / ".foreman/sessions" / SESSION / "counters.json"
        counters = json.loads(counters_path.read_text()) if counters_path.exists() else {}
        self.assertEqual(counters.get("turn_writes", 0), 0)
        self.assertEqual(self.agent_file("w1")["last_action"]["tool"], "Write")

    def test_main_may_wait_for_running_sub_agents(self):
        self.post("Write", {"file_path": str(self.project_dir / "notes.md")})  # a busy turn
        self.start(**WORKER)
        stop = {"session_id": SESSION, "cwd": str(self.project_dir)}
        self.assertIsNone(self.hook_json("stop", stop))
        self.hook_json("subagent-stop", {**stop, **WORKER})
        self.post("Write", {"file_path": str(self.project_dir / "notes.md")})
        self.assertEqual(self.hook_json("stop", stop)["decision"], "block")
        running = [{"id": "x", "type": "subagent", "status": "running"}]
        self.post("Write", {"file_path": str(self.project_dir / "notes.md")})
        self.assertIsNone(self.hook_json("stop", {**stop, "background_tasks": running}))


class ConfigCliTest(ProjectCase):
    def test_show(self):
        out = self.tasks_ok("config", "show")
        self.assertIn("worker: model opus · paths **", out)
        self.assertIn("tester: model sonnet · paths tests/**", out)

    def test_check_warns_and_errors(self):
        out = self.tasks_ok("config", "check")
        self.assertIn("WARNING: tests.command is empty", out)
        config = self.project_dir / ".foreman" / "config.toml"
        config.write_text(config.read_text().replace("tests_first = true", "tests_first = \"yes\""))
        result = self.run_tasks("config", "check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: workflow.tests_first must be true or false", result.stdout)


class ViolationsSectionTest(ProjectCase):
    def test_appends_inside_the_section_or_creates_it(self):
        from foreman.project import Project
        from foreman.task import find_task, record_violation
        self.new_task()
        task = find_task(Project(self.project_dir), 1)
        record_violation(task, "first")
        record_violation(task, "second")
        self.assertTrue(task.text().rstrip().endswith("- first\n- second"))
        task.path.write_text("# 001\n\n## Parked\nnothing\n")
        record_violation(task, "third")
        self.assertTrue(task.text().endswith("## Parked\nnothing\n\n## Violations\n- third\n"))


class WorkerLimitTest(ActiveTaskCase):
    def spawn(self, role: str = "worker", model: str = "opus") -> dict | None:
        return self.pre("Agent", {"subagent_type": f"foreman:{role}", "model": model, "prompt": "x"})

    def set_limit(self, limit: int) -> None:
        config = self.project_dir / ".foreman" / "config.toml"
        config.write_text(config.read_text().replace("max_parallel = 1", f"max_parallel = {limit}", 1))

    def start(self, agent_id: str, role: str = "worker") -> None:
        self.hook_json("subagent-start", {"session_id": SESSION, "cwd": str(self.project_dir),
                                          "agent_id": agent_id, "agent_type": f"foreman:{role}"})

    def stop(self, agent_id: str, role: str = "worker") -> None:
        self.hook_json("subagent-stop", {"session_id": SESSION, "cwd": str(self.project_dir),
                                         "agent_id": agent_id, "agent_type": f"foreman:{role}"})

    def test_one_worker_at_a_time_by_default(self):
        self.assertIsNone(self.spawn())
        self.start("w1")
        out = self.spawn()
        self.assertEqual(decision(out), "deny")
        self.assertIn("max_parallel is 1", message(out))
        self.assertIsNone(self.spawn("tester", "sonnet"))  # the limit is for workers
        self.stop("w1")
        self.assertIsNone(self.spawn())

    def test_two_starts_in_one_message_count_before_either_agent_runs(self):
        self.assertIsNone(self.spawn())
        self.assertEqual(decision(self.spawn()), "deny")

    def test_a_higher_limit(self):
        self.set_limit(2)
        self.assertIsNone(self.spawn())
        self.assertIsNone(self.spawn())
        self.assertEqual(decision(self.spawn()), "deny")
        self.start("w1")
        self.start("w2")
        self.assertEqual(decision(self.spawn()), "deny")
        self.stop("w2")
        self.assertIsNone(self.spawn())

    def test_a_start_that_never_arrived_expires(self):
        self.assertIsNone(self.spawn())
        pending = self.project_dir / ".foreman/sessions" / SESSION / "agents" / "pending"
        old = time.time() - 600
        for path in pending.iterdir():
            os.utime(path, (old, old))
        self.assertIsNone(self.spawn())

    def test_config_check_rejects_a_bad_limit(self):
        self.set_limit(0)
        result = self.run_tasks("config", "check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("roles.worker.max_parallel must be a whole number", result.stdout)
