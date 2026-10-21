"""Entry point of the `tasks` CLI; .claude/bin/tasks in a project execs this."""

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

if sys.version_info < (3, 11):
    sys.exit(f"cplugin needs Python 3.11+, found {sys.version.split()[0]}")

sys.path.insert(0, str(PLUGIN_ROOT))

from cplugin.cli import main  # noqa: E402

sys.exit(main(sys.argv[1:], PLUGIN_ROOT))
