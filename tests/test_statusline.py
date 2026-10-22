import json
import re
import subprocess
import sys

from helpers import PLUGIN_ROOT, SESSION, ProjectCase, TempDirCase

from foreman import agents, roles, session, statusline
from foreman.project import Project


def usage_line(message_id: str, input_tokens: int = 0, cache_write: int = 0, cache_read: int = 0,
               output: int = 0) -> str:
    return json.dumps({"type": "assistant", "message": {"id": message_id, "usage": {
        "input_tokens": input_tokens, "cache_creation_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read, "output_tokens": output}}})


FULL = {"model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5 (1M context)"},
        "effort": {"level": "xhigh"},
        "context_window": {"total_input_tokens": 412_345, "context_window_size": 1_000_000,
                           "used_percentage": 41},
        "rate_limits": {"five_hour": {"used_percentage": 23.5}},
        "cost": {"total_cost_usd": 12.3456}}


class StatusLineRun:
    def run_line(self, payload: object) -> str:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        result = subprocess.run([sys.executable, "-I", str(PLUGIN_ROOT / "bin" / "statusline.py")],
                                input=text, capture_output=True, text=True,
                                env=self.env(NO_COLOR="1"), cwd=self.tmp, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout.rstrip("\n")


class SessionLineTest(StatusLineRun, TempDirCase):
    def test_every_figure(self):
        self.assertEqual(self.run_line(FULL),
                         "Opus 5.5 [xhigh] · 412k/1M · 5h 23.5% · 0 (↑0 ↓0) · $12.35")

    def test_figures_not_sent_yet_are_left_out(self):
        # What Claude Code sends before the first response.
        start = {"model": {"display_name": "Opus 5.5"}, "effort": {"level": "high"},
                 "context_window": {"total_input_tokens": 0, "context_window_size": 1_000_000,
                                    "used_percentage": None},
                 "cost": {"total_cost_usd": 0}}
        self.assertEqual(self.run_line(start), "Opus 5.5 [high] · 0/1M · 0 (↑0 ↓0) · $0.00")

    def test_unreadable_input_still_prints_a_line(self):
        for payload in ("", "{not json", "[]"):
            self.assertEqual(self.run_line(payload), "unknown · 0/200k · 0 (↑0 ↓0) · $0.00", payload)

    def test_weighted_tokens_count_each_message_once_and_the_sub_agents(self):
        main = self.tmp / "transcripts" / "s1.jsonl"
        sub = self.tmp / "transcripts" / "s1" / "subagents" / "agent-a1.jsonl"
        sub.parent.mkdir(parents=True)
        # Message "a" is written twice, the first line with a partial output count.
        main.write_text("\n".join([
            json.dumps({"type": "user", "message": {"content": "hi"}}),
            usage_line("a", input_tokens=2, cache_write=1000, cache_read=10_000, output=3),
            usage_line("a", input_tokens=2, cache_write=1000, cache_read=10_000, output=296),
            "{broken",
            usage_line("b", input_tokens=10, output=20),
        ]) + "\n")
        sub.write_text(usage_line("c", input_tokens=100, output=1) + "\n"
                       + usage_line("c", input_tokens=100, output=40) + "\n")
        # input: 2 + 1.25 × 1000 + 0.1 × 10000 + 10 + 100; output: 5 × (296 + 20 + 40)
        self.assertEqual(statusline.weighted_usage(main), statusline.Weighted(2362, 1780))
        line = self.run_line({**FULL, "transcript_path": str(main)})
        self.assertIn(" · 4k (↑2k ↓2k) · ", line)

    def test_missing_transcript_counts_nothing(self):
        line = self.run_line({**FULL, "transcript_path": str(self.tmp / "gone.jsonl")})
        self.assertIn(" · 0 (↑0 ↓0) · ", line)

    def test_colors_follow_the_thresholds(self):
        line = statusline.render(json.dumps(FULL), color=True)
        self.assertIn(f"{statusline.CYAN}23.5%", line)                # a decimal is still under 50
        self.assertIn(f"{statusline.GREEN}412k", line)
        self.assertIn(f"{statusline.BRIGHT_MAGENTA}xhigh", line)
        hot = {**FULL, "rate_limits": {"five_hour": {"used_percentage": 81}},
               "context_window": {**FULL["context_window"], "used_percentage": 85}}
        line = statusline.render(json.dumps(hot), color=True)
        self.assertIn(f"{statusline.BRIGHT_MAGENTA}81%", line)
        self.assertIn(f"{statusline.RED}412k", line)
        self.assertNotIn("\x1b", statusline.render(json.dumps(FULL), color=False))

    def test_formats(self):
        self.assertEqual([statusline.format_tokens(n) for n in (999, 1500, 45_200, 2_500_000)],
                         ["999", "2k", "45k", "2.50M"])
        self.assertEqual([statusline.format_window(n) for n in (200_000, 1_000_000, 1_500_000)],
                         ["200k", "1M", "1.5M"])
        self.assertEqual([statusline.format_percent(p) for p in (7, 23.5, 33.333)], ["7%", "23.5%", "33.3%"])

    def test_outside_a_foreman_project_there_is_one_line(self):
        line = self.run_line({**FULL, "workspace": {"project_dir": str(self.project_dir)}})
        self.assertEqual(len(line.splitlines()), 1)


class ForemanLineTest(StatusLineRun, ProjectCase):
    def payload(self) -> dict:
        return {**FULL, "session_id": SESSION, "cwd": str(self.project_dir),
                "workspace": {"project_dir": str(self.project_dir)}}

    def foreman_line(self) -> str:
        lines = self.run_line(self.payload()).splitlines()
        self.assertEqual(len(lines), 2, lines)
        return lines[1]

    def test_no_active_task(self):
        self.assertEqual(self.foreman_line(), "foreman · no active task")

    def test_active_task_gate_and_working_sub_agent(self):
        self.activate(self.new_task())
        directory = session.session_dir(Project(self.project_dir), SESSION)
        agents.record_start(directory, "agent-w1", "foreman:worker", roles.WORKER)
        agents.record_action(directory, "agent-w1", roles.WORKER, "Edit", str(self.project_dir / "src/combat.ts"))
        line = self.foreman_line()
        self.assertRegex(line, r"^foreman · task 001 knight-damage · gate 1/\d+ · worker ● Edit src/combat\.ts$")

    def test_pause_and_freehand(self):
        self.activate(self.new_task())
        self.tasks_ok("pause", "which damage formula?")
        self.assertIn(" · waiting for you: which damage formula?", self.foreman_line())
        self.tasks_ok("freehand")
        line = self.foreman_line()
        self.assertTrue(line.startswith("foreman · freehand: rules off"), line)
        self.assertNotIn("no active task", line)

    def test_finds_the_project_from_a_subfolder(self):
        sub = self.project_dir / "src"
        sub.mkdir()
        payload = {**self.payload(), "workspace": {"project_dir": str(sub)}}
        self.assertTrue(re.search(r"\nforeman · ", self.run_line(payload)))
