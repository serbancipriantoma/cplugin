"""Judges: reviews of a task's plan or code by other models that never see the
conversation.

Each seat in config.toml ([[judges.seat]]) is an external CLI run headless in
the project: `codex` inside its own read-only sandbox, `agy` (and the `claude`
fallback, limited to Read/Grep/Glob) under sandbox-exec with the project
read-only. Whatever the containment, a tamper check compares the working tree
and task.md before and after: if anything changed, the reviews are not used
and the run fails. Reports go to the task's judges/ folder; a summary, quoted
so it can never pass for gates, goes into the task's review section.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import agents, bashcheck, gitutil
from .fsutil import write_atomic
from .project import MINDMAP_DIR, Project
from .task import Task, append_to_section, read_meta

EXECUTABLES = {"codex": "codex", "agy": "agy", "claude": "claude"}
ALIASES = {"antigravity": "agy"}
FALLBACK_MODEL = "sonnet"
JUDGE_ENV = "CPLUGIN_JUDGE"   # set for judge processes; cplugin's own hooks stand down

MAX_DETAIL_CHARS = 20_000
MAX_DIFF_CHARS = 60_000
MAX_FINDINGS_CHARS = 4_000

STAGES = {
    "plan": {"command": "plan-review", "heading": "## 2.", "what": "the plan of a task",
             "focus": """What to look for in the plan (the Design answers and the Work Plan):
- Does every Work Plan step trace back to the Request and the Design's criteria? Flag steps
  that serve nothing above them (scope creep), and requirements or criteria no step covers (gaps).
- Are the criteria verifiable, and the interfaces concrete enough for tests to be written
  before the code?
- Are the assumptions about the existing code true? Check them in the repository.
- Missing edge cases, risky steps without a check, a simpler approach that would do."""},
    "impl": {"command": "impl-review", "heading": "## 4.", "what": "the implementation of a task",
             "focus": """What to look for in the implementation (the diff below, against the task):
- Does the code do what the Request and the criteria say? Trace each criterion to the code
  and to a test.
- Code shaped to pass the tests rather than to meet the criteria (hard-coded values,
  special cases for the tests).
- Bugs, unhandled edge cases, missing or weak tests, departures from the project's
  conventions, debug leftovers."""},
}

_VERDICT_RE = re.compile(r"^#+\s*Verdict\s*\n+\s*\**(ACCEPT WITH CHANGES|ACCEPT|REJECT)\b",
                         re.MULTILINE | re.IGNORECASE)
_FINDINGS_RE = re.compile(r"^#+\s*Findings\s*\n(.*?)(?=^#+\s|\Z)", re.MULTILINE | re.DOTALL)
_REVIEW_SECTIONS_RE = re.compile(r"^## [24]\. .*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)


class JudgeError(Exception):
    pass


@dataclass(frozen=True)
class Seat:
    provider: str
    model: str = ""

    @property
    def label(self) -> str:
        model = re.sub(r"[^A-Za-z0-9.]+", "-", self.model).strip("-")
        return f"{self.provider}-{model}" if model else self.provider

    @property
    def title(self) -> str:
        return f"{self.provider} ({self.model})" if self.model else self.provider


@dataclass
class Review:
    seat: Seat
    output: str = ""
    error: str = ""
    seconds: float = 0.0
    containment: str = ""
    report: Path | None = None

    @property
    def verdict(self) -> str:
        if self.error:
            return "ERROR"
        match = _VERDICT_RE.search(self.output)
        return match.group(1).upper() if match else "UNPARSED"

    @property
    def findings(self) -> str:
        match = _FINDINGS_RE.search(self.output)
        text = (match.group(1) if match else self.output).strip()
        return text if len(text) <= MAX_FINDINGS_CHARS else text[:MAX_FINDINGS_CHARS] + "\n[… cut, see the report]"


@dataclass
class Outcome:
    reviews: list[Review]
    notes: list[str] = field(default_factory=list)
    tampered: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.tampered:
            return 1
        return 0 if any(not r.error for r in self.reviews) else 2


# ── choosing the seats ──────────────────────────────────────────────────────

def parse_seat(raw: str) -> Seat:
    provider, _, model = raw.partition(":")
    provider = ALIASES.get(provider, provider)
    if provider not in EXECUTABLES:
        raise JudgeError(f"unknown judge provider {provider!r}; use codex, agy or claude")
    return Seat(provider, model)


def choose_seats(cfg: dict, overrides: list[str] | None = None) -> tuple[list[Seat], list[str]]:
    judges_cfg = cfg.get("judges", {})
    notes: list[str] = []
    if overrides:
        configured = [parse_seat(raw) for raw in overrides]
    else:
        configured = []
        for seat in judges_cfg.get("seat", []):
            if not isinstance(seat, dict):
                continue
            provider = ALIASES.get(str(seat.get("provider", "")), str(seat.get("provider", "")))
            if provider not in EXECUTABLES:
                notes.append(f"skipped judge provider {provider!r}: not supported")
                continue
            configured.append(Seat(provider, str(seat.get("model") or "")))
    available = []
    for seat in configured:
        if shutil.which(EXECUTABLES[seat.provider]):
            available.append(seat)
        else:
            notes.append(f"skipped {seat.title}: `{EXECUTABLES[seat.provider]}` is not on PATH")
    if judges_cfg.get("mode") == "single":
        available = available[:1]
    if available:
        return available, notes
    if judges_cfg.get("fallback") == "claude" and shutil.which("claude") and not overrides:
        notes.append("no configured judge is available; using the read-only Claude fallback")
        return [Seat("claude", FALLBACK_MODEL)], notes
    raise JudgeError("no judge is available: " + "; ".join(notes or ["no seats configured"]))


# ── what the judges read ────────────────────────────────────────────────────

def _read(path: Path, limit: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(missing)"
    return text if len(text) <= limit else text[:limit] + "\n[… cut]"


def task_for_judges(text: str) -> str:
    """The task without its review sections: earlier findings and their triage
    would anchor the judges."""
    return _REVIEW_SECTIONS_RE.sub("", text)


def task_diff(project: Project, task: Task) -> str:
    root = project.root
    exclude = ":(exclude).cplugin"
    base = read_meta(task).get("base") or gitutil.head(root)
    parts = []
    if base:
        diff = gitutil.git(root, "diff", base, "--", ".", exclude, timeout=30)
        parts.append((diff or b"").decode("utf-8", "replace"))
        new_files = gitutil.git(root, "ls-files", "--others", "--exclude-standard", "--", ".", exclude)
    else:  # no commit yet: everything is new
        new_files = gitutil.git(root, "ls-files", "--cached", "--others", "--exclude-standard", "--", ".", exclude)
    for rel in (new_files or b"").decode("utf-8", "replace").splitlines():
        parts.append(f"--- new file: {rel}\n{_read(root / rel, 8_000)}")
    text = "\n".join(p for p in parts if p.strip()) or "(no changes found)"
    return text if len(text) <= MAX_DIFF_CHARS else text[:MAX_DIFF_CHARS] + "\n[… diff cut]"


def build_prompt(project: Project, task: Task, stage: str, plugin_root: Path) -> str:
    spec = STAGES[stage]
    text = task.text()
    details = ""
    for rel in sorted(set(re.findall(rf"{MINDMAP_DIR}/[A-Za-z0-9_./-]+\.md", text))):
        if ".." not in rel:
            details += f"\n=== DETAILS ({rel}) ===\n{_read(project.root / rel, MAX_DETAIL_CHARS)}\n"
    diff = f"\n=== DIFF SINCE THE TASK STARTED ===\n{task_diff(project, task)}\n" if stage == "impl" else ""
    prompt = (plugin_root / "templates" / "judge-prompt.md").read_text(encoding="utf-8")
    for key, value in (("what", spec["what"]), ("root", str(project.root)), ("focus", spec["focus"]),
                       ("task_path", str(task.path.relative_to(project.root))),
                       ("task", task_for_judges(text).strip()),
                       ("mind_map", _read(project.mind_map, MAX_DETAIL_CHARS).strip()),
                       ("details", details), ("diff", diff)):
        prompt = prompt.replace("{{" + key + "}}", value)
    return prompt


# ── containment ─────────────────────────────────────────────────────────────

def seatbelt_status() -> str:
    """"ok" when sandbox-exec can apply a deny rule here, "nested" when an outer
    sandbox forbids it (macOS refuses nested profiles that add rules), else "none"."""
    if not shutil.which("sandbox-exec"):
        return "none"
    probe = '(version 1)(allow default)(deny file-write* (subpath "/cplugin-nesting-probe"))'
    try:
        rc = subprocess.run(["sandbox-exec", "-p", probe, "/usr/bin/true"], capture_output=True, timeout=10).returncode
    except (OSError, subprocess.SubprocessError):
        return "none"
    return "ok" if rc == 0 else "nested"


def read_only_profile(project: Project) -> str:
    paths = {str(project.root), str(project.root.resolve())}
    git_dir = gitutil.git_dir(project.root)
    if git_dir:
        paths |= {str(git_dir), str(git_dir.resolve())}
    rules = "".join(f'(deny file-write* (subpath "{p}"))' for p in sorted(paths))
    return f"(version 1)(allow default){rules}"


def command(seat: Seat, project: Project, prompt: str, out_file: Path, timeout_s: int,
            seatbelt: str) -> tuple[list[str], str | None, str]:
    """argv, stdin and a description of the containment for one judge."""
    root = str(project.root)
    if seat.provider == "codex":
        argv = ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "--color", "never",
                "-C", root, "-o", str(out_file)]
        argv += ["-m", seat.model] if seat.model else []
        if seatbelt == "nested":
            # codex's own sandbox cannot nest either; the outer one still applies.
            return argv + ["--dangerously-bypass-approvals-and-sandbox", "-"], prompt, \
                "outer sandbox only (nested), plus the tamper check"
        return argv + ["-s", "read-only", "-"], prompt, "codex read-only sandbox, plus the tamper check"
    if seat.provider == "agy":
        inner = ["agy", "--dangerously-skip-permissions", "--add-dir", root]
        inner += ["--model", seat.model] if seat.model else []
        # agy stops on its own a little before we would kill it.
        inner += ["--print", prompt, "--print-timeout", f"{max(timeout_s - 15, 30)}s"]
        stdin = None
    else:
        inner = ["claude", "-p", "--tools", "Read,Grep,Glob", "--no-session-persistence",
                 "--model", seat.model or FALLBACK_MODEL]
        stdin = prompt
    if seatbelt == "ok":
        return ["sandbox-exec", "-p", read_only_profile(project), *inner], stdin, \
            "sandbox-exec, project read-only, plus the tamper check"
    return inner, stdin, f"no OS sandbox ({seatbelt}); only the tamper check"


# ── running ─────────────────────────────────────────────────────────────────

def _run_one(seat: Seat, project: Project, prompt: str, timeout_s: int, seatbelt: str) -> Review:
    review = Review(seat)
    with tempfile.TemporaryDirectory(prefix="cplugin-judge-") as tmp:
        out_file = Path(tmp) / "last-message.md"
        argv, stdin, review.containment = command(seat, project, prompt, out_file, timeout_s, seatbelt)
        env = {**os.environ, JUDGE_ENV: "1"}
        started = time.monotonic()
        try:
            proc = subprocess.Popen(argv, cwd=project.root, env=env, text=True, start_new_session=True,
                                    stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            review.error = f"could not start {argv[0]}: {exc}"
            return review
        try:
            stdout, stderr = proc.communicate(stdin, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill(proc)
            review.error = f"timed out after {timeout_s // 60} min"
            stdout, stderr = "", ""
        review.seconds = time.monotonic() - started
        if not review.error:
            output = out_file.read_text(encoding="utf-8").strip() if out_file.is_file() else ""
            review.output = output or (stdout or "").strip()
            if proc.returncode != 0:
                review.error = f"exit {proc.returncode}: " + (stderr or stdout or "").strip()[-600:]
            elif not review.output:
                review.error = "no output"
    return review


def _kill(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


def _fingerprint(project: Project, task: Task) -> dict:
    return {"tree": bashcheck.take(project.root) or {},
            "task": hashlib.sha256(task.path.read_bytes()).hexdigest(),
            "head": gitutil.head(project.root)}


def review(project: Project, task: Task, stage: str, cfg: dict, plugin_root: Path,
           session_dir: Path | None = None, seat_overrides: list[str] | None = None,
           timeout_min: float | None = None) -> Outcome:
    seats, notes = choose_seats(cfg, seat_overrides)
    timeout_s = int(60 * (timeout_min or float(cfg.get("judges", {}).get("timeout_min") or 8)))
    prompt = build_prompt(project, task, stage, plugin_root)
    seatbelt = seatbelt_status()
    if seatbelt != "ok":
        notes.append(f"sandbox-exec is unavailable here ({seatbelt}); the judges run without OS "
                     "write protection, and only the tamper check guards the project")

    for seat in seats:
        if session_dir is not None:
            agents.record_start(session_dir, _agent_key(seat), seat.provider, "judge")
            agents.record_action(session_dir, _agent_key(seat), "judge",
                                 STAGES[stage]["command"], seat.model or seat.provider)
    before = _fingerprint(project, task)
    with ThreadPoolExecutor(max_workers=len(seats)) as pool:
        reviews = list(pool.map(lambda s: _run_one(s, project, prompt, timeout_s, seatbelt), seats))
    after = _fingerprint(project, task)
    if session_dir is not None:
        for seat in seats:
            agents.record_stop(session_dir, _agent_key(seat))

    outcome = Outcome(reviews, notes)
    if before != after:
        outcome.tampered = bashcheck.changed(before["tree"], after["tree"])
        if before["task"] != after["task"]:
            outcome.tampered.append(str(task.path.relative_to(project.root)))
        if before["head"] != after["head"]:
            outcome.tampered.append("HEAD (a commit was made or moved)")
        outcome.tampered = outcome.tampered or ["the working tree"]
    _save(project, task, stage, outcome)
    return outcome


def _agent_key(seat: Seat) -> str:
    return "judge-" + re.sub(r"[^A-Za-z0-9_-]+", "-", seat.label)


# ── recording ───────────────────────────────────────────────────────────────

def _save(project: Project, task: Task, stage: str, outcome: Outcome) -> None:
    command_name = STAGES[stage]["command"]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    directory = task.dir / "judges"
    directory.mkdir(exist_ok=True)
    for r in outcome.reviews:
        r.report = directory / f"{command_name}-{r.seat.label}-{stamp}.md"
        banner = ""
        if outcome.tampered:
            banner = (f"**TAMPER: the project changed while the judges ran "
                      f"({', '.join(outcome.tampered)}). This review was not used.**\n\n")
        write_atomic(r.report, f"# {command_name}: {r.seat.title}\n\n{banner}"
                               f"- Verdict: {r.verdict}\n- Containment: {r.containment}\n"
                               f"- Took: {r.seconds:.0f}s\n"
                               + (f"- Error: {r.error}\n" if r.error else "")
                               + f"\n{r.output}\n")
    append_to_section(task, STAGES[stage]["heading"], _summary_block(project, task, stage, outcome))


def _quote(text: str) -> str:
    return "\n".join(f"> {line}".rstrip() for line in text.splitlines())


def _summary_block(project: Project, task: Task, stage: str, outcome: Outcome) -> str:
    when = time.strftime("%Y-%m-%d %H:%M")
    lines = [f"**Judges, {STAGES[stage]['command']}, {when}**"]
    if outcome.tampered:
        lines += ["", f"TAMPER: the project changed while the judges ran ({', '.join(outcome.tampered)}). "
                      "These reviews were not used; inspect the change with `git diff` before going on."]
    for r in outcome.reviews:
        report = r.report.relative_to(task.dir) if r.report else ""
        lines.append(f"- {r.seat.title}: {r.verdict}" + (f" ({r.error[:120]})" if r.error else "")
                     + f" · `{report}`")
    lines += [f"- note: {n}" for n in outcome.notes]
    if not outcome.tampered:
        for r in outcome.reviews:
            if not r.error:
                lines += ["", f"**{r.seat.title}**", r.findings]
    # The blank line keeps Markdown from folding the quote into the gate list above it.
    return "\n" + _quote("\n".join(lines)) + "\n"


def console_summary(project: Project, task: Task, stage: str, outcome: Outcome) -> str:
    lines = []
    for r in outcome.reviews:
        lines.append(f"{r.seat.title}: {r.verdict} in {r.seconds:.0f}s" + (f" — {r.error}" if r.error else ""))
    lines += [f"note: {n}" for n in outcome.notes]
    if outcome.tampered:
        lines.append(f"TAMPER: the project changed while the judges ran: {', '.join(outcome.tampered)}. "
                     "The reviews were not used. Inspect the change with `git diff`, then run the review again.")
    elif outcome.exit_code == 0:
        rel = task.path.relative_to(project.root)
        lines.append(f"The findings are in {rel}, section {STAGES[stage]['heading']} (quoted), and the "
                     f"full reports in {task.dir.relative_to(project.root)}/judges/. Triage every finding "
                     "on the triage gate: accepted / parked / rejected, with the reason.")
    else:
        lines.append("Every judge failed; nothing was reviewed. Fix the cause above or ask the user.")
    return "\n".join(lines)
