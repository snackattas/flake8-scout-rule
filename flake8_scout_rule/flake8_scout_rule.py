import argparse
import fileinput
import os
import random
import string
from dataclasses import dataclass, field
from itertools import groupby
from shutil import move
from typing import List

from flake8 import LOG
from flake8.defaults import NOQA_INLINE_REGEXP
from flake8.formatting.default import Default
from flake8.options.manager import OptionManager
from flake8.violation import Violation


@dataclass
class ViolationsByLine:
    filename: str
    line_number: int
    physical_line: str
    codes: List[str] = field(default_factory=list)

    @property
    def add_noqa_to_line(self) -> str:
        # Remove the newline character if there is one
        physical_line = self.physical_line.rstrip("\n")
        if physical_line.endswith("# noqa"):
            # The line already has a noqa to ignore everything, so don't add another one
            return physical_line
        self.codes.sort()
        matches = NOQA_INLINE_REGEXP.search(self.physical_line)
        if matches:
            existing_codes: str = matches.groupdict()["codes"]
            new_codes: List[str] = [code for code in self.codes if code not in existing_codes]
            if new_codes:
                return f"{physical_line}, {', '.join(new_codes)}"
            else:
                return physical_line
        return f"{physical_line}  # noqa: {', '.join(self.codes)}"


class Flake8ScoutRuleFormatter(Default):
    """A formatter that collects all violations in the format phase and corrects them
    in the stop phase."""

    violations: List[Violation] = []

    def __init__(self, options: argparse.Namespace) -> None:
        # Even though to use this flake8 reporter you need to pass in --format=scout,
        # override the default format to "default" so the users can still see the normal
        # collected violations, before agreeing to add the # noqa annotations to them.
        options.format = "default"
        super().__init__(options)

    @classmethod
    def add_options(cls, parser: OptionManager) -> None:
        """Add a flake8 --no-prompt option to the OptionsManager."""
        cls.option_manager = parser
        help = (
            "Automatically update files with violations without prompting the user to "
            "review the violations."
        )
        parser.add_option(
            "--no-prompt",
            action="store_true",
            default=False,
            help=help,
            parse_from_config=True,
        )

    @staticmethod
    def _random_letters(num_letters: int) -> str:
        return "".join(random.choices(string.ascii_letters, k=num_letters))

    @staticmethod
    def update_lines_in_file(violations: List[ViolationsByLine]) -> None:
        backup_extension = f".bak_{Flake8ScoutRuleFormatter._random_letters(5)}"
        filename = violations[0].filename
        backup_file = f"{filename}{backup_extension}"
        try:
            with fileinput.input(files=filename, inplace=True, backup=backup_extension) as file:
                for line in file:
                    found = False
                    file_lineno = file.filelineno()
                    for violation in violations:
                        if violation.line_number == file_lineno:
                            found = True
                            print(violation.add_noqa_to_line)
                            break
                    if not found:
                        print(line, end="")
        except Exception:
            print(f"Error updating file {filename}")
            move(backup_file, filename)
            raise
        finally:
            os.remove(f"{filename}{backup_extension}")

    @staticmethod
    def prompt_for_corrections() -> bool:
        while True:
            response = input("Do you want to correct these violations inline now? (y/n): ")
            formatted_response = response.strip().lower()[0:1]
            if formatted_response in ["y", "n"]:
                return formatted_response == "y"
            else:
                print("Invalid input. Please enter 'y' or 'n'.")

    @staticmethod
    def group_violations_by_file(violations: List[Violation]) -> List[List[Violation]]:
        groups = groupby(violations, key=lambda v: v.filename)
        violations_by_file = [list(group) for key, group in groups]
        return violations_by_file

    @staticmethod
    def group_file_violations_by_line(violations: List[Violation]) -> List[ViolationsByLine]:
        violations_by_line: List[ViolationsByLine] = []
        for violation in violations:
            found = False
            for vbl in violations_by_line:
                if vbl.line_number == violation.line_number:
                    vbl.codes.append(violation.code)
                    found = True
                    break
            if not found:
                vbl = ViolationsByLine(
                    filename=violation.filename,
                    line_number=violation.line_number,
                    physical_line=violation.physical_line,
                    codes=[violation.code],
                )
                violations_by_line.append(vbl)
        return violations_by_line

    def noqa_annotation_adder(self):
        no_prompt_prefix = "Automatically a" if self.options.no_prompt else "A"
        print(
            f"{no_prompt_prefix}dding '# noqa: <errors>' annotations to the files "
            "with violations now:"
        )
        violations_by_file = self.group_violations_by_file(self.violations)
        for file_violations in violations_by_file:
            violations_by_line = self.group_file_violations_by_line(file_violations)
            LOG.debug(
                f"Adding '# noqa: <errors>' annotations to file: '{violations_by_line[0].filename}'"
            )
            self.update_lines_in_file(violations_by_line)
            print(".", end="")

    def format(self, error: Violation) -> str:
        self.violations.append(error)
        return super().format(error)

    def stop(self):
        if not self.violations:
            print("No violations found, so nothing to add '# noqa: <errors>' to. Exiting.")
            return

        print(f"\nFound {len(self.violations)} violations.")
        if not self.options.no_prompt:
            response = self.prompt_for_corrections()
            if not response:
                print("Not correcting violations, exiting.")
                return

        self.noqa_annotation_adder()
        print("\nDone")
