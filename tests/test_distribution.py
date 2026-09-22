"""Installed package and console command contract."""

import shutil
import subprocess

import pytest


def test_keshigomu_console_entrypoint_needs_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    executable = shutil.which("keshigomu")
    assert executable is not None
    result = subprocess.run(
        [executable, "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "keshigomu" in result.stdout
    assert "--min-confidence" in result.stdout
    assert result.stderr == ""
