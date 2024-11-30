import os
import subprocess
import tempfile
from argparse import Namespace
from io import StringIO
from shutil import copy
from typing import Generator
from unittest.mock import patch

import pytest
from flake8.violation import Violation

from flake8_scout_rule import Flake8ScoutRuleFormatter
from flake8_scout_rule.flake8_scout_rule import ViolationsByLine


@pytest.fixture
def python_dir_with_violations() -> Generator[str, None, None]:
    cwd = os.getcwd()
    files = [os.path.join(cwd, "tests", "flake8_violation_files", f) for f in ["file1", "file2"]]
    with tempfile.TemporaryDirectory() as tmp_dir:
        for f in files:
            copy(f, os.path.join(tmp_dir, os.path.basename(f) + ".py"))
        yield tmp_dir


def test_black_box(python_dir_with_violations: str) -> None:
    command = f"flake8 --format=scout --no-prompt {python_dir_with_violations}"
    result = subprocess.run(
        command,
        cwd=python_dir_with_violations,
        capture_output=True,
        text=True,
        shell=True,
    )
    assert result.returncode == 1  # There should be violations, so it should return 1
    assert result.stderr == ""
    assert "Found 18 violations" in result.stdout
    assert "Automatically adding '# noqa: <errors>' annotations" in result.stdout

    result2 = subprocess.run(
        command,
        cwd=python_dir_with_violations,
        capture_output=True,
        text=True,
        shell=True,
    )
    assert result2.returncode == 0  # There should be no violations, now they should be noqa'd


def test_black_box_with_ignore(python_dir_with_violations: str) -> None:
    command = f"flake8 --format=scout --no-prompt --ignore E302,F401 {python_dir_with_violations}"
    result = subprocess.run(
        command,
        cwd=python_dir_with_violations,
        capture_output=True,
        text=True,
        shell=True,
    )
    assert result.returncode == 1  # There should be violations, so it should return 1
    assert result.stderr == ""
    assert "Found 14 violations" in result.stdout
    assert "Automatically adding '# noqa: <errors>' annotations" in result.stdout


def test_black_box_with_select(python_dir_with_violations: str) -> None:
    command = f"flake8 --format=scout --no-prompt --select F841,E225 {python_dir_with_violations}"
    result = subprocess.run(
        command,
        cwd=python_dir_with_violations,
        capture_output=True,
        text=True,
        shell=True,
    )
    assert result.returncode == 1  # There should be violations, so it should return 1
    assert result.stderr == ""
    assert "Found 12 violations" in result.stdout
    assert "Automatically adding '# noqa: <errors>' annotations" in result.stdout


def test_violation_by_line_add_noqa_to_line_ends_with_noqa():
    vbl = ViolationsByLine(
        filename="main.py", line_number=42, physical_line="x =  1  # noqa\n", codes=["E222"]
    )
    assert vbl.add_noqa_to_line == "x =  1  # noqa"


def test_violation_by_line_add_noqa_to_line_codes_match():
    vbl = ViolationsByLine(
        filename="main.py",
        line_number=42,
        physical_line="x =  1  # noqa: E222, E225\n",
        codes=["E222", "E226"],
    )
    assert vbl.add_noqa_to_line == "x =  1  # noqa: E222, E225, E226"


def test_violation_by_line_add_noqa_to_line_codes_dont_add_existing_code():
    vbl = ViolationsByLine(
        filename="main.py",
        line_number=42,
        physical_line="x =  1  # noqa: E222, E225\n",
        codes=["E222", "E226"],
    )
    assert vbl.add_noqa_to_line == "x =  1  # noqa: E222, E225, E226"


def test_violation_by_line_add_noqa_to_line_codes_dont_add_all_code():
    vbl = ViolationsByLine(
        filename="main.py", line_number=42, physical_line="x = 1\n", codes=["E226", "E222"]
    )
    assert vbl.add_noqa_to_line == "x = 1  # noqa: E222, E226"


@patch("builtins.input", return_value="y")
def test_flake8_scout_rule_formatter(mock_input, python_dir_with_violations):
    options = Namespace(output_file=None, color=False, tee=False, no_prompt=False)
    formatter = Flake8ScoutRuleFormatter(options)
    formatter.start()
    # Too lazy to add ALL the violations, just add a few

    file1 = python_dir_with_violations + "/file1.py"
    file2 = python_dir_with_violations + "/file2.py"
    violations = [
        Violation(
            code="F841",
            filename=file1,
            line_number=4,
            column_number=5,
            text="local variable 'nospacebetweenequals' is assigned to but never used",
            physical_line="    nospacebetweenequalsagain=1\n",
        ),
        Violation(
            code="E225",
            filename=file1,
            line_number=4,
            column_number=25,
            text="missing whitespace around operator",
            physical_line="    nospacebetweenequalsagain=1\n",
        ),
        Violation(
            code="F841",
            filename=file2,
            line_number=4,
            column_number=5,
            text="local variable 'nospacebetweenequals' is assigned to but never used",
            physical_line="    nospacebetweenequalsagain=1\n",
        ),
        Violation(
            code="E225",
            filename=file2,
            line_number=4,
            column_number=25,
            text="missing whitespace around operator",
            physical_line="    nospacebetweenequalsagain=1\n",
        ),
    ]
    for v in violations:
        formatter.format(v)

    with patch("sys.stdout", new=StringIO()) as captured_stdout:
        formatter.stop()

    assert "Found 4 violations" in captured_stdout.getvalue()
    noqa_addition = "  # noqa: E225, F841"
    with open(file1) as f:
        content = f.read()
        assert content.count(noqa_addition) == 1

    with open(file2) as f:
        content = f.read()
        assert content.count(noqa_addition) == 1
    assert mock_input.called is True
