import os
import shutil
import subprocess
import tempfile
from argparse import Namespace
from dataclasses import dataclass
from io import StringIO
from shutil import copy
from typing import Generator, List
from unittest.mock import Mock, patch

import pytest
from flake8.violation import Violation

from flake8_scout_rule import Flake8ScoutRuleFormatter
from flake8_scout_rule.flake8_scout_rule import ViolationsByLine


@dataclass
class TestData:
    files: List[str]
    dir: str


@pytest.fixture
def violations_test_dir() -> Generator[TestData, None, None]:
    cwd = os.getcwd()
    files = [os.path.join(cwd, "tests", "flake8_violation_files", f) for f in ["file1", "file2"]]
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_file_paths = []
        for f in files:
            tmp_file_path = os.path.join(tmp_dir, os.path.basename(f) + ".py")
            copy(f, tmp_file_path)
            tmp_file_paths.append(tmp_file_path)
        os.chdir(tmp_dir)
        test_data = TestData(files=tmp_file_paths, dir=tmp_dir)
        yield test_data
    os.chdir(cwd)


@pytest.fixture(scope="session", autouse=True)
def flake8_file_fixture() -> Generator[None, None, None]:
    flake8_path = os.path.join(os.getcwd(), ".flake8")
    if os.path.isfile(flake8_path):
        temp_flake8_path = os.path.join(os.getcwd(), ".flake8_temp")
        shutil.move(flake8_path, temp_flake8_path)
        yield
        shutil.move(temp_flake8_path, flake8_path)
    else:
        yield


@pytest.fixture
def violations_fixture(violations_test_dir: TestData) -> List[Violation]:
    violations = [
        Violation(
            code="F841",
            filename=violations_test_dir.files[0],
            line_number=4,
            column_number=5,
            text="local variable 'nospacebetweenequals' is assigned to but never used",
            physical_line="    nospacebetweenequalsagain=1\n",
        ),
        Violation(
            code="E225",
            filename=violations_test_dir.files[0],
            line_number=4,
            column_number=25,
            text="missing whitespace around operator",
            physical_line="    nospacebetweenequalsagain=1\n",
        ),
        Violation(
            code="F841",
            filename=violations_test_dir.files[1],
            line_number=4,
            column_number=5,
            text="local variable 'nospacebetweenequals' is assigned to but never used",
            physical_line="    nospacebetweenequalsagain=1\n",
        ),
        Violation(
            code="E225",
            filename=violations_test_dir.files[1],
            line_number=4,
            column_number=25,
            text="missing whitespace around operator",
            physical_line="    nospacebetweenequalsagain=1\n",
        ),
    ]
    return violations


def test_black_box_with_path_passed_to_flake8(violations_test_dir: TestData) -> None:
    flake8_file = os.path.join(violations_test_dir.dir, ".flake8")
    assert os.path.isfile(flake8_file) is False

    command = f"flake8 --format=scout --no-review-prompt {violations_test_dir.dir}"
    result = subprocess.run(
        command,
        cwd=violations_test_dir.dir,
        capture_output=True,
        text=True,
        shell=True,
    )

    assert result.returncode == 1  # There should be violations, so it should return 1
    assert result.stderr == ""
    stdout = result.stdout

    assert "Found 47 violations" in stdout
    assert "Automatically adding '# noqa: <errors>' annotations" in stdout
    # get the full path since sometimes os.getcwd returns a symlink
    flake8_file = os.path.realpath(flake8_file)
    assert f"No flake8 config file found, creating a default one at '{flake8_file}'" in stdout
    assert os.path.isfile(flake8_file) is True
    with open(flake8_file, "r") as f:
        flake8_content = f.read()

    assert "[flake8_scout_rule]\nper_file_violations_tracked = \n\t" in flake8_content
    assert "\n\tfile1.py: A001{1}, ANN201{1}" in flake8_content
    assert "\n\tfile2.py: A001{1}, ANN201{1}" in flake8_content

    result2 = subprocess.run(
        command,
        cwd=violations_test_dir.dir,
        capture_output=True,
        text=True,
        shell=True,
    )
    assert result2.returncode == 0  # There should be no violations, now they should be noqa'd
    with open(flake8_file, "r") as f:
        flake8_content2 = f.read()
    assert flake8_content2 == flake8_content


def test_black_box(violations_test_dir: TestData) -> None:
    flake8_file = os.path.join(violations_test_dir.dir, ".flake8")
    assert os.path.isfile(flake8_file) is False

    command = "flake8 --format=scout --no-review-prompt"
    result = subprocess.run(
        command,
        cwd=violations_test_dir.dir,
        capture_output=True,
        text=True,
        shell=True,
    )

    assert result.returncode == 1  # There should be violations, so it should return 1
    assert result.stderr == ""
    stdout = result.stdout

    assert "Found 47 violations" in stdout
    assert "Automatically adding '# noqa: <errors>' annotations" in stdout
    # get the full path since sometimes os.getcwd returns a symlink
    flake8_file = os.path.realpath(flake8_file)
    assert f"No flake8 config file found, creating a default one at '{flake8_file}'" in stdout
    assert os.path.isfile(flake8_file) is True
    with open(flake8_file, "r") as f:
        flake8_content = f.read()

    assert "[flake8_scout_rule]\nper_file_violations_tracked = \n\t" in flake8_content
    assert "\n\tfile1.py: A001{1}, ANN201{1}" in flake8_content
    assert "\n\tfile2.py: A001{1}, ANN201{1}" in flake8_content

    result2 = subprocess.run(
        command,
        cwd=violations_test_dir.dir,
        capture_output=True,
        text=True,
        shell=True,
    )
    assert result2.returncode == 0  # There should be no violations, now they should be noqa'd
    with open(flake8_file, "r") as f:
        flake8_content2 = f.read()
    assert flake8_content2 == flake8_content


def test_black_box_with_ignore(violations_test_dir: TestData) -> None:
    command = (
        "flake8 --format=scout --no-review-prompt --ignore E302,F401 " f"{violations_test_dir.dir}"
    )
    result = subprocess.run(
        command,
        cwd=violations_test_dir.dir,
        capture_output=True,
        text=True,
        shell=True,
    )
    assert result.returncode == 1  # There should be violations, so it should return 1
    assert result.stderr == ""
    assert "Found 43 violations" in result.stdout
    assert "Automatically adding '# noqa: <errors>' annotations" in result.stdout


def test_black_box_with_select(violations_test_dir: TestData) -> None:
    command = (
        "flake8 --format=scout --no-review-prompt --select F841,E225 " f"{violations_test_dir.dir}"
    )
    result = subprocess.run(
        command,
        cwd=violations_test_dir.dir,
        capture_output=True,
        text=True,
        shell=True,
    )
    assert result.returncode == 1  # There should be violations, so it should return 1
    assert result.stderr == ""
    assert "Found 12 violations" in result.stdout
    assert "Automatically adding '# noqa: <errors>' annotations" in result.stdout


def test_violation_by_line_add_noqa_to_line_ends_with_noqa() -> None:
    vbl = ViolationsByLine(
        filename="main.py", line_number=42, physical_line="x =  1  # noqa\n", codes=["E222"]
    )
    assert vbl.add_noqa_to_line == "x =  1  # noqa"


def test_violation_by_line_add_noqa_to_line_codes_match() -> None:
    vbl = ViolationsByLine(
        filename="main.py",
        line_number=42,
        physical_line="x =  1  # noqa: E222, E225\n",
        codes=["E222", "E226"],
    )
    assert vbl.add_noqa_to_line == "x =  1  # noqa: E222, E225, E226"


def test_violation_by_line_add_noqa_to_line_codes_dont_add_existing_code() -> None:
    vbl = ViolationsByLine(
        filename="main.py",
        line_number=42,
        physical_line="x =  1  # noqa: E222, E225\n",
        codes=["E222", "E226"],
    )
    assert vbl.add_noqa_to_line == "x =  1  # noqa: E222, E225, E226"


def test_violation_by_line_add_noqa_to_line_codes_dont_add_all_code() -> None:
    vbl = ViolationsByLine(
        filename="main.py", line_number=42, physical_line="x = 1\n", codes=["E226", "E222"]
    )
    assert vbl.add_noqa_to_line == "x = 1  # noqa: E222, E226"


@patch("builtins.input", return_value="y")
def test_flake8_scout_rule_formatter(
    mock_input: Mock, violations_test_dir: TestData, violations_fixture: List[Violation]
) -> None:
    options = Namespace(
        output_file=None,
        color=False,
        tee=False,
        no_review_prompt=False,
        no_update_flake8_config=False,
    )
    formatter = Flake8ScoutRuleFormatter(options)
    formatter.start()
    for v in violations_fixture:
        formatter.format(v)

    with patch("sys.stdout", new=StringIO()) as captured_stdout:
        formatter.stop()

    stdout = captured_stdout.getvalue()
    print(f"Captured stdout:\n{stdout}")
    assert "Found 4 violations" in stdout
    noqa_addition = "  # noqa: E225, F841"
    with open(violations_test_dir.files[0], encoding="UTF-8") as f:
        content = f.read()
        assert content.count(noqa_addition) == 1

    with open(violations_test_dir.files[1], encoding="UTF-8") as f:
        content = f.read()
        assert content.count(noqa_addition) == 1
    assert mock_input.called is True


def test_flake8_scout_rule_formatter_no_review_prompt(
    violations_test_dir: TestData, violations_fixture: List[Violation]
) -> None:
    options = Namespace(
        output_file=None,
        color=False,
        tee=False,
        no_review_prompt=True,
        no_update_flake8_config=False,
    )
    formatter = Flake8ScoutRuleFormatter(options)
    formatter.start()
    for v in violations_fixture:
        formatter.format(v)

    with patch("sys.stdout", new=StringIO()) as captured_stdout:
        formatter.stop()

    stdout = captured_stdout.getvalue()
    print(f"Captured stdout:\n{stdout}")
    assert "Found 4 violations" in stdout
    noqa_addition = "  # noqa: E225, F841"
    with open(violations_test_dir.files[0], encoding="UTF-8") as f:
        content = f.read()
        assert content.count(noqa_addition) == 1

    with open(violations_test_dir.files[1], encoding="UTF-8") as f:
        content = f.read()
        assert content.count(noqa_addition) == 1
