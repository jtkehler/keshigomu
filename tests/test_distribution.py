"""Installed package and console command contract."""

import shutil
import subprocess
from importlib.metadata import entry_points

import pytest


def test_keshigomu_console_entrypoint_needs_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    commands = entry_points(group="console_scripts", name="keshigomu")
    assert len(commands) == 1
    command = next(iter(commands))
    assert command.value == "keshigomu.cli:app"
    assert command.dist is not None
    assert command.dist.metadata["Name"] == "keshigomu"

    executable = shutil.which("keshigomu")
    assert executable is not None
    result = subprocess.run(
        [executable, "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "keshigomu" in result.stdout
    assert "--min-confidence" in result.stdout
    assert result.stderr == ""
