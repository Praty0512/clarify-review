"""The CLI must not crash when stdout is a legacy (cp1252) pipe, as on Windows."""

import io
import sys

from clarifyreview import cli


def test_main_survives_cp1252_stdout(monkeypatch, capsys):
    raw = io.BytesIO()
    fake = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", fake)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))

    rc = cli.main(["replay", "--db", "data/study_v2.db", "--list"])
    fake.flush()

    assert rc == 0
    assert sys.stdout.encoding.lower().replace("_", "-") == "utf-8"
    assert raw.getvalue()


def test_subprocess_replay_with_cp1252_env():
    import os
    import subprocess

    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    env.pop("PYTHONUTF8", None)
    r = subprocess.run([sys.executable, "-m", "clarifyreview.cli", "replay",
                        "--db", "data/study_v2.db"],
                       capture_output=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert b"Traceback" not in r.stderr
