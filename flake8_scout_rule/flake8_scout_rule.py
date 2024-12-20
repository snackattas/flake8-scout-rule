import argparse
import fileinput
import os
import random
import string
import sys
from dataclasses import dataclass, field
from itertools import groupby
from shutil import move
from typing import List

from flake8 import LOG
from flake8.defaults import NOQA_INLINE_REGEXP
from flake8.formatting.default import Default
from flake8.options.manager import OptionManager
from flake8.options.parse_args import parse_args
from flake8.violation import Violation
from flake8.options.config import load_config,_find_config_file

@dataclass
class ViolationsByFile:
    filename: str
    violations: List[Violation] = field(default_factory=list)

@dataclass
class ViolationsByLine:
    filename: str
    line_number: int
    physical_line: str
    codes: List[str] = field(default_factory=list)

    @property
    def add_noqa_to_line(self) -> str:
        """
        Returns the valid '# noqa: <errors>' annotation to existing line.

        This method processes the physical line of code and appends the appropriate
        '# noqa: <errors>' annotation based on the violations codes. If the line
        already has a '# noqa' annotation, it updates it with the new codes.

        :return: The line of code with the '# noqa: <errors>' annotation.
        :rtype: str
        """
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

    def format(self, error: Violation) -> str:
        """Instance of format from the Default formatter interface."""
        self.violations.append(error)
        return super().format(error)

    def stop(self):
        """Instance of stop from the Default formatter interface."""
        if not self.violations:
            print("No violations found, so nothing to add '# noqa: <errors>' to. Exiting.")
            return

        print(f"\nFound {len(self.violations)} violations.")
        if not self.options.no_prompt:
            response = self.prompt_for_corrections()
            if not response:
                print("Not correcting violations, exiting.")
                return

        violations_by_file_by_line = self._noqa_annotation_adder()

        # print(f"violations_by_file_by_line: {violations_by_file_by_line}")
        # config = _find_config_file(os.getcwd())
        # result = None
        # if config:
        #     configparser, string = load_config(config, extra=[])
        # plugins, namespace = parse_args(sys.argv[1:])
        # print(f"loaded config: {result}")

        print("\nDone")

    @staticmethod
    def _update_lines_in_file(violations: List[ViolationsByLine]) -> None:
        """
        Updates lines in the specified file by adding '# noqa: <errors>' annotations.

        This method assumes that the violations are all part of the same file

        It creates a backup of the file before making any changes and
        restores the original file in case of an error during the update process.

        :param violations: A list of violations grouped by line within a file.
        :type violations: List[ViolationsByLine]
        """
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
        """
        Prompts the user to decide whether to correct violations inline.

        This method repeatedly asks the user for input until a valid response ('y' or 'n')
        is provided. It returns True if the user chooses to correct the violations, and False
        otherwise.

        :return: True if the user wants to correct the violations, False otherwise.
        :rtype: bool
        """
        while True:
            response = input("Do you want to correct these violations inline now? (y/n): ")
            formatted_response = response.strip().lower()[0:1]
            if formatted_response in ["y", "n"]:
                return formatted_response == "y"
            else:
                print("Invalid input. Please enter 'y' or 'n'.")

    @staticmethod
    def _group_violations_by_file(violations: List[Violation]) -> List[ViolationsByFile]:
        """
        Groups violations by file.

        This method processes a list of violations and groups them by the filename.
        It ensures that all violations belonging to the same file are grouped together
        in a list.

        :param violations: A list of `Violation` objects to be grouped by file.
        :type violations: List[Violation]
        :return: A list of lists, where each inner list contains `Violation` objects for a single
        file.
        :rtype: List[ViolationsByFile]
        """
        grp_by_filename = groupby(violations, key=lambda v: v.filename)
        violations_by_file = [
            ViolationsByFile(filename=key, violations=list(grp)) for key, grp in grp_by_filename
        ]
        return violations_by_file

    @staticmethod
    def _group_file_violations_by_line(violations_by_file: ViolationsByFile) -> List[ViolationsByLine]:
        """
        Groups violations by line within a file.

        This method processes a list of violations from the whole flake8 run, and groups them by
        line number within each file. It ensures that multiple violations on the same line are
        combined into a single `ViolationsByLine` object.

        :param violations: A list of `Violation` objects to be grouped by line.
        :type violations: List[Violation]
        :return: A list of `ViolationsByLine` objects, each representing a line with one or more
        violations.
        :rtype: List[ViolationsByLine]
        """
        violations_by_line: List[ViolationsByLine] = []
        for violation in violations_by_file.violations:
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

    def _noqa_annotation_adder(self) -> List[List[ViolationsByLine]]:
        """
        Adds '# noqa: <errors>' annotations to lines in files with violations.

        The method groups violations by file and then by line within each file,
        ensuring that multiple violations on the same line are handled correctly.
        It creates a backup of each file before making any changes and restores the
        original file in case of an error during the update process.
        """
        no_prompt_prefix = "Automatically a" if self.options.no_prompt else "A"
        print(
            f"{no_prompt_prefix}dding '# noqa: <errors>' annotations to the files "
            "with violations now:"
        )
        violations_by_file = self._group_violations_by_file(self.violations)
        violations_by_file_by_line = []
        for file_violations in violations_by_file:
            violations_by_line = self._group_file_violations_by_line(file_violations)
            violations_by_file_by_line.append(violations_by_line)
            LOG.debug(
                f"Adding '# noqa: <errors>' annotations to file: '{violations_by_line[0].filename}'"
            )
            self._update_lines_in_file(violations_by_line)
            print(".", end="")
        return violations_by_file_by_line

    @staticmethod
    def _random_letters(num_letters: int) -> str:
        """Generates a random string of the specified length consisting of ASCII letters."""
        return "".join(random.choices(string.ascii_letters, k=num_letters))
