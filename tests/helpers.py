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


class TempDirCase(unittest.TestCase):
    """Each test gets a fresh temp dir and an isolated CLAUDE_CONFIG_DIR."""

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
        env.update(extra)
        return env

    def run_hook(self, event: str, payload: dict, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", str(PLUGIN_ROOT / "hooks" / "run.py"), event],
            input=json.dumps(payload), capture_output=True, text=True,
            env=self.env(**env), cwd=self.tmp, timeout=30,
        )

    def run_tasks(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", str(PLUGIN_ROOT / "bin" / "tasks.py"), *args],
            capture_output=True, text=True, env=self.env(),
            cwd=cwd or self.project_dir, timeout=30,
        )

    def init_project(self) -> None:
        result = self.run_tasks("init", "--name", "Clinic")
        self.assertEqual(result.returncode, 0, result.stderr)
