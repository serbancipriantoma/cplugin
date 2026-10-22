import json
import os
import shutil
import subprocess
import sys
import unittest

from helpers import PLUGIN_ROOT, SESSION, ProjectCase

from foreman import containment, gates, judges
from foreman.project import Project

REVIEW = """## Verdict
ACCEPT WITH CHANGES — the plan holds, one gap.

## Findings
1. [medium] src/greet.js:3 — empty names are not covered — add a test for ""
- [ ] this line must never become a gate
"""

# One script plays every judge CLI. It logs its argv and stdin, then acts on FAKE_MODE_<NAME>.
FAKE = r'''#!{python}
import json, os, sys, time
name = os.path.basename(sys.argv[0])
stdin = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
prompt = sys.argv[sys.argv.index("--print") + 1] if "--print" in sys.argv else stdin
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(json.dumps({{"name": name, "argv": sys.argv[1:], "prompt": prompt,
                          "judge_env": os.environ.get("FOREMAN_JUDGE")}}) + "\n")
mode = os.environ.get("FAKE_MODE_" + name.upper(), "ok")
review = {review!r}
if mode == "fail":
    sys.stderr.write("boom\n"); sys.exit(3)
if mode == "slow":
    time.sleep(30)
if mode == "tamper":
    try:
        with open("src/planted.js", "w") as fh:
            fh.write("// planted\n")
        review += "\nwrote src/planted.js"
    except OSError as exc:
        review += "\nwrite blocked: " + type(exc).__name__
if "-o" in sys.argv:
    with open(sys.argv[sys.argv.index("-o") + 1], "w") as fh:
        fh.write(review)
    print("progress noise on stdout")
else:
    print(review)
'''


class JudgeCase(ProjectCase):
    def setUp(self):
        super().setUp()
        self.fakebin = self.tmp / "fakebin"
        self.fakebin.mkdir()
        self.log = self.tmp / "fake.log"
        for tool in ("git", "sandbox-exec"):
            if shutil.which(tool):
                (self.fakebin / tool).symlink_to(shutil.which(tool))
        (self.project_dir / "src").mkdir()
        (self.project_dir / "src" / "greet.js").write_text("export const greet = (n) => `Hello, ${n}!`\n")
        (self.project_dir / "mindmap" / "greeting.md").write_text("# Greeting — details\nUNIQUE-DETAIL-MARKER\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")
        self.new_task("greet")
        path = self.task_md()
        path.write_text(path.read_text().replace("## Context\n", "## Context\n- `mindmap/greeting.md`\n"))
        self.activate()

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.project_dir), "-c", "user.name=t",
                        "-c", "user.email=t@example.invalid", *args], check=True)

    def fake(self, *names: str) -> None:
        for name in names:
            script = self.fakebin / name
            script.write_text(FAKE.format(python=sys.executable, review=REVIEW))
            script.chmod(0o755)

    def review(self, *args: str, stage: str = "plan-review", **modes: str) -> subprocess.CompletedProcess:
        env = {"PATH": str(self.fakebin), "FAKE_LOG": str(self.log)}
        env.update({f"FAKE_MODE_{name.upper()}": mode for name, mode in modes.items()})
        return self.run_tasks(stage, "1", *args, extra_env=env, timeout=120)

    def calls(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def reports(self) -> list[str]:
        return sorted(p.name for p in (self.task_md().parent / "judges").glob("*.md"))


class PanelTest(JudgeCase):
    def test_panel_reviews_record_findings_as_quotes(self):
        self.fake("codex", "agy")
        before = gates.parse(self.task_md().read_text())
        result = self.review()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("codex: ACCEPT WITH CHANGES", result.stdout)
        self.assertIn("agy: ACCEPT WITH CHANGES", result.stdout)
        self.assertIn("Triage every finding", result.stdout)
        self.assertEqual(len(self.reports()), 2)
        text = self.task_md().read_text()
        section = text.split("## 2. Plan Review")[1].split("\n## 3.")[0]
        self.assertIn("> **Judges, plan-review,", section)
        self.assertIn("> - codex: ACCEPT WITH CHANGES · `judges/plan-review-codex-", section)
        self.assertIn("> 1. [medium] src/greet.js:3", section)
        # Quoted findings are never gates (the block only shifts the line numbers below it).
        self.assertEqual([(g.checked, g.text) for g in gates.parse(text)],
                         [(g.checked, g.text) for g in before])

    def test_commands_and_what_the_judges_read(self):
        self.fake("codex", "agy")
        self.review()
        self.review()  # the second prompt must not carry the first run's findings
        calls = {c["name"]: c for c in self.calls()[-2:]}
        codex = calls["codex"]["argv"]
        self.assertEqual(codex[:2], ["exec", "--ephemeral"])
        self.assertIn("-o", codex)
        self.assertEqual(codex[codex.index("-C") + 1], str(self.project_dir))
        self.assertEqual(codex[-1], "-")
        agy = calls["agy"]["argv"]
        self.assertIn("--dangerously-skip-permissions", agy)
        prompt = calls["codex"]["prompt"]
        self.assertIn("# 001 — feature — greet", prompt)
        self.assertIn("UNIQUE-DETAIL-MARKER", prompt)
        self.assertIn("=== PROJECT MEMORY (MIND_MAP.md) ===", prompt)
        self.assertNotIn("Judges, plan-review", prompt)
        self.assertNotIn("DIFF SINCE", prompt)
        self.assertEqual(calls["agy"]["prompt"], prompt)
        self.assertEqual({c["judge_env"] for c in calls.values()}, {"1"})

    @unittest.skipUnless(containment.detect().ok, "needs sandbox-exec or bubblewrap")
    def test_sandbox_blocks_agy_writes_and_codex_runs_read_only(self):
        self.fake("codex", "agy")
        result = self.review(agy="tamper")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse((self.project_dir / "src" / "planted.js").exists())
        report = next((self.task_md().parent / "judges").glob("plan-review-agy-*.md")).read_text()
        self.assertIn("write blocked:", report)
        self.assertIn("project read-only", report)
        codex = next(c for c in self.calls() if c["name"] == "codex")["argv"]
        self.assertEqual(codex[codex.index("-s") + 1], "read-only")

    def test_tamper_voids_the_reviews(self):
        self.fake("codex")
        result = self.review("--seat", "codex", codex="tamper")
        self.assertEqual(result.returncode, 1)
        self.assertIn("TAMPER", result.stdout)
        self.assertIn("src/planted.js", result.stdout)
        text = self.task_md().read_text()
        self.assertIn("> TAMPER: the project changed while the judges ran (src/planted.js)", text)
        self.assertNotIn("> 1. [medium]", text)
        report = (self.task_md().parent / "judges" / self.reports()[0]).read_text()
        self.assertIn("**TAMPER", report)


class FailureTest(JudgeCase):
    def test_one_failing_judge_does_not_sink_the_panel(self):
        self.fake("codex", "agy")
        result = self.review(agy="fail")
        self.assertEqual(result.returncode, 0)
        self.assertIn("agy: ERROR", result.stdout)
        self.assertIn("exit 3: boom", result.stdout)

    def test_all_failing_judges_exit_2(self):
        self.fake("codex", "agy")
        result = self.review(codex="fail", agy="fail")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Every judge failed", result.stdout)

    def test_a_slow_judge_is_stopped(self):
        self.fake("codex")
        result = self.review("--seat", "codex", "--timeout-min", "0.03", codex="slow")
        self.assertEqual(result.returncode, 2)
        self.assertIn("timed out", result.stdout)

    def test_fallback_to_claude_when_no_cli_is_installed(self):
        self.fake("claude")
        result = self.review()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("claude (sonnet): ACCEPT WITH CHANGES", result.stdout)
        self.assertIn("read-only Claude fallback", result.stdout)
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob")

    def test_no_judge_at_all(self):
        config = self.project_dir / ".foreman" / "config.toml"
        config.write_text(config.read_text().replace('fallback = "claude"', 'fallback = "none"'))
        result = self.review()
        self.assertEqual(result.returncode, 1)
        self.assertIn("no judge is available", result.stderr)

    def test_seat_override_with_model(self):
        self.fake("codex", "agy")
        self.review("--seat", "agy:gemini-3.8-flash-low")
        self.assertEqual([c["name"] for c in self.calls()], ["agy"])
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "gemini-3.8-flash-low")
        self.assertTrue(any("plan-review-agy-gemini-3.8-flash-low-" in r for r in self.reports()))


class ImplReviewTest(JudgeCase):
    def test_diff_since_the_task_started(self):
        meta = json.loads((self.task_md().parent / "meta.json").read_text())
        self.assertEqual(len(meta["base"]), 40)
        (self.project_dir / "src" / "greet.js").write_text("export const greet = (n) => `Hi, ${n}!`\n")
        (self.project_dir / "src" / "farewell.js").write_text("export const bye = 1 // NEW-FILE-MARKER\n")
        self.git("add", "src/greet.js")
        self.git("commit", "-qm", "work")  # committed work still counts
        self.fake("codex")
        result = self.review("--seat", "codex", stage="impl-review")
        self.assertEqual(result.returncode, 0, result.stdout)
        prompt = self.calls()[0]["prompt"]
        self.assertIn("=== DIFF SINCE THE TASK STARTED ===", prompt)
        self.assertIn("+export const greet = (n) => `Hi, ${n}!`", prompt)
        self.assertIn("NEW-FILE-MARKER", prompt)
        self.assertNotIn(".foreman/tasks", prompt.split("=== DIFF")[1])
        self.assertIn("> **Judges, impl-review,", self.task_md().read_text().split("## 4.")[1])


class BoardAndHooksTest(JudgeCase):
    def test_judges_show_on_the_board(self):
        from foreman import board
        self.fake("codex", "agy")
        self.review()
        rows = {r.name: r for r in board.collect(Project(self.project_dir), SESSION).rows}
        self.assertEqual(rows["codex"].status, "done")
        self.assertEqual(rows["agy"].detail, "agy")
        self.assertNotIn("judge", rows)

    def test_hooks_stand_down_inside_a_judge(self):
        out = subprocess.run([sys.executable, "-I", str(PLUGIN_ROOT / "hooks" / "run.py"), "pre-tool-use"],
                             input=json.dumps(self.payload("Write", {"file_path": str(self.project_dir / "src/x.js")})),
                             capture_output=True, text=True, env={**self.env(), "FOREMAN_JUDGE": "1"})
        self.assertEqual((out.returncode, out.stdout), (0, ""))


class PromptUnitTest(unittest.TestCase):
    def test_review_sections_are_removed(self):
        text = "# t\n## 1. Design\nkeep\n## 2. Plan Review\n> old findings\n## 3. Work Plan\nkeep too\n## 4. Implementation Review\nx\n## 5. Final Review\nend\n"
        cleaned = judges.task_for_judges(text)
        self.assertNotIn("old findings", cleaned)
        self.assertNotIn("Implementation Review", cleaned)
        self.assertIn("keep too", cleaned)
        self.assertIn("## 5. Final Review", cleaned)

    def test_verdicts(self):
        self.assertEqual(judges.Review(judges.Seat("codex"), output="## Verdict\n**REJECT** — no").verdict, "REJECT")
        self.assertEqual(judges.Review(judges.Seat("codex"), output="nothing").verdict, "UNPARSED")
        self.assertEqual(judges.Review(judges.Seat("codex"), error="x").verdict, "ERROR")
