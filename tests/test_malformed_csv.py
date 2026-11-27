import os
from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "dq_scan.py"


def run_scan(path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def test_extra_fields_are_reported_without_a_traceback(tmp_path):
    source = tmp_path / "extra.csv"
    source.write_text("a,b\n1,2,3\n", encoding="utf-8")
    result = run_scan(source)
    assert result.returncode == 1
    assert "row 2" in result.stderr.lower()
    assert "extra field" in result.stderr.lower()
    assert "Traceback" not in result.stderr
    assert "numeric:" not in result.stdout


def test_extra_fields_in_a_later_row_are_reported(tmp_path):
    source = tmp_path / "later.csv"
    source.write_text("a,b\n1,2\n3,4,5\n", encoding="utf-8")
    result = run_scan(source)
    assert result.returncode == 1
    assert "row 3" in result.stderr.lower()
    assert "extra field" in result.stderr.lower()
    assert "Traceback" not in result.stderr


def test_short_rows_remain_missing_values(tmp_path):
    source = tmp_path / "short.csv"
    source.write_text("a,b\n1\n2,3\n", encoding="utf-8")
    result = run_scan(source)
    assert result.returncode == 0
    assert "nulls=1" in result.stdout


def test_quoted_delimiters_are_not_extra_fields(tmp_path):
    source = tmp_path / "quoted.csv"
    source.write_text('a,b\n"one,two",3\n', encoding="utf-8")
    result = run_scan(source)
    assert result.returncode == 0
    assert "one,two" in result.stdout
