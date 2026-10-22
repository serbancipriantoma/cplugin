"""Entry point of the status line; .claude/bin/statusline in a project execs this.

Claude Code runs it with the session's JSON on stdin and shows what it prints
under the prompt. It always exits 0, printing what it could read.
"""

import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

if sys.version_info < (3, 11):
    print(f"foreman needs Python 3.11+, found {sys.version.split()[0]}")
    sys.exit(0)

sys.path.insert(0, str(PLUGIN_ROOT))

from foreman import statusline  # noqa: E402

print(statusline.render(sys.stdin.read(), color="NO_COLOR" not in os.environ))
