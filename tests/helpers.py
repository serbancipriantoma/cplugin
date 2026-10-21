"""Shared fixtures: temp projects and running the real entry points as subprocesses."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

SESSION = "sess-1"


class TempDirCase(unittest.TestCase):
    """Each test gets a fresh temp dir and an isolated CLAUDE_CONFIG_DIR. The
    owning Claude process is pinned to "none" so results do not depend on
    whether the tests themselves run under Claude Code."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.config_dir = self.tmp / "claude-config"
        self.config_dir.mkdir()
        self.project_dir = self.tmp / "proj"
        self.project_dir.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def env(self, **extra: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CPLUGIN_"))}
        env["CLAUDE_CONFIG_DIR"] = str(self.config_dir)
        env["CPLUGIN_AGENT_PID"] = "none"
        env.update(extra)
        return env

    def run_hook(self, event: str, payload: dict, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", str(PLUGIN_ROOT / "hooks" / "run.py"), event],
            input=json.dumps(payload), capture_output=True, text=True,
            env=self.env(**env), cwd=self.tmp, timeout=30,
        )

    def hook_json(self, event: str, payload: dict, **env: str) -> dict | None:
        result = self.run_hook(event, payload, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("hook failed", result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def run_tasks(self, *args: str, cwd: Path | None = None, stdin: str | None = None,
                  session: str | None = SESSION) -> subprocess.CompletedProcess:
        extra = {"CPLUGIN_SESSION_ID": session} if session else {}
        return subprocess.run(
            [sys.executable, "-I", str(PLUGIN_ROOT / "bin" / "tasks.py"), *args],
            capture_output=True, text=True, env=self.env(**extra), input=stdin,
            cwd=cwd or self.project_dir, timeout=30,
        )

    def tasks_ok(self, *args: str, **kwargs) -> str:
        result = self.run_tasks(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def init_project(self) -> None:
        result = self.run_tasks("init", "--name", "Portfolio", session=None)
        self.assertEqual(result.returncode, 0, result.stderr)

    def start_session(self, session_id: str = SESSION, source: str = "startup", **env: str) -> str:
        out = self.hook_json("session-start", {"session_id": session_id, "source": source,
                                               "cwd": str(self.project_dir)}, **env)
        return out["hookSpecificOutput"]["additionalContext"]

    def payload(self, tool: str, tool_input: dict, **extra) -> dict:
        return {"session_id": SESSION, "cwd": str(self.project_dir), "tool_name": tool,
                "tool_input": tool_input, **extra}

    def task_md(self, num: int = 1) -> Path:
        return next((self.project_dir / ".cplugin" / "tasks").glob(f"{num:03d}-*/task.md"))


class ProjectCase(TempDirCase):
    """An initialized project with a registered session."""

    def setUp(self) -> None:
        super().setUp()
        self.init_project()
        self.start_session()

    def new_task(self, name: str = "knight-damage", request: str = "Knights hit archers.") -> int:
        out = self.tasks_ok("new", "feature", name, "--request", "-", stdin=request)
        return int(out.split("Created task ")[1].split(":")[0])

    def activate(self, num: int = 1) -> None:
        self.tasks_ok("work", str(num))

    def check_gate(self, text_prefix: str, outcome: str = "done") -> None:
        """Check the first open gate starting with `text_prefix`, as an edit would."""
        path = self.task_md()
        lines = path.read_text().splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.lstrip().startswith(f"- [ ] {text_prefix}"):
                lines[i] = line.replace("- [ ]", "- [x]", 1).rstrip("\n") + f" {outcome}\n"
                path.write_text("".join(lines))
                return
        raise AssertionError(f"no open gate starting with {text_prefix!r}")
