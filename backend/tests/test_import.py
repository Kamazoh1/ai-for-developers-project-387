"""Importing the app module must be free of side effects: the app is built by a factory."""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def test_importing_the_app_module_creates_no_files_and_reads_no_settings(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        # A bad setting would crash an import that reads the environment.
        "CALENDAR_TIMEZONE": "Not/AZone",
    }

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
