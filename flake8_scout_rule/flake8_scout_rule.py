"""Flake8 formatter that collects all violations and marks them with noqa annotations.

It also adds the violations to the flake8 configuration file's per_file_violations_tracked key,
which is then used to track the violations in the next run of flake8, and by the pre-commit hook
to ensure that the violations are not reintroduced.
"""

import argparse
import fileinput
import os
from operator import attrgetter
from shutil import move
from typing import List, Optional, Type

from flake8 import LOG
from flake8.formatting.default import Default
from flake8.options.manager import OptionManager
from flake8.violation import Violation
from typing_extensions import Self

from flake8_scout_rule.data_classes import (
    PerFileViolationsTracked,
    ViolationsByCount,
    ViolationsByFile,
    ViolationsByLine,
)
from flake8_scout_rule.per_file_violations_tracked_manager import (
    PerFileViolationsTrackedManager,
)
from flake8_scout_rule.utils import random_letters
from flake8_scout_rule.violations_manager import ViolationsManager


class Flake8ScoutRuleFormatter(Default):
    """Flake8 formatter that collects all violations and marks them with noqa annotations.

    It also adds the violations to the flake8 configuration file's per_file_violations_tracked key,
    which is then used to track the violations in the next run of flake8, and by the pre-commit hook
    to ensure that the violations are not reintroduced.
    """

    def __init__(self: Self, options: argparse.Namespace) -> None:
        """
        Initialize the Flake8ScoutRuleFormatter.

        Even though the --format=scout option is required to use this flake8 reporter,
        override the default format to "default" so users can still see the normal
        collected violations before agreeing to add the # noqa annotations to them.

        This method also loads the per_file_violations_tracked key from the flake8 configuration,
        and if the entries in the key aren't formatted correctly, it raises an error, preventing
        the plugin and flake8 from running.
        """
        options.format = "default"
        self.option_manager: Optional[OptionManager] = None
        super().__init__(options)
        self.violations: List[Violation] = []
        self.per_file_violations_tracked: List[PerFileViolationsTracked] = []

        if self.options.no_update_flake8_config:
            return

        self.per_file_violations_tracked_manager = PerFileViolationsTrackedManager()
        self.violations_manager = ViolationsManager(self.per_file_violations_tracked_manager)

    @classmethod
    def add_options(cls: Type["Flake8ScoutRuleFormatter"], parser: OptionManager) -> None:
        """Add the --no-review-prompt and --no-update-flake8-file options to OptionsManager."""
        cls.option_manager = parser
        no_review_prompt_help = (
            "(Default: true) Automatically update files with violations without prompting the user "
            "to review the violations."
        )
        parser.add_option(
            "--no-review-prompt",
            action="store_true",
            default=False,
            help=no_review_prompt_help,
            parse_from_config=True,
        )

        no_update_flake8_config_help = (
            "(Default: false) Stop from automatically creating/updating the flake8 configuration "
            "file's [flake8_scout_rule] section with the violations that were found in this run."
        )
        parser.add_option(
            "--no-update-flake8-config",
            action="store_true",
            default=False,
            help=no_update_flake8_config_help,
            parse_from_config=True,
        )

    def format(self: Self, error: Violation) -> str | None:  # noqa: A003
        """Instance of format from the Default formatter interface."""
        self.violations_manager.add_violation(error)
        return super().format(error)

    def stop(self: Self) -> None:  # noqa: C901, CCR001, PLR912, PLR914, PLR915
        """Instance of stop from the Default formatter interface."""
        if not self.violations_manager.violations:
            print("No violations found, so nothing to add '# noqa: <errors>' to. Exiting.")
            return

        print(f"\nFound {len(self.violations_manager.violations)} violations.")
        if not self.options.no_review_prompt:
            response = self.prompt_for_corrections()
            if not response:
                print("Not correcting violations, exiting.")
                return

        self.violations_manager.group_violations()
        self._noqa_annotation_adder()
        violations_by_file = self.violations_manager.violations_by_file
        if self.options.no_update_flake8_config:
            print("Not updating the flake8 configuration file, exiting.")
            return

        # Now add the defaults if they don't exist yet
        configurations = (
            self.per_file_violations_tracked_manager.load_raw_per_file_violations_tracked(
                add_defaults=True
            )
        )
        if (
            configurations is None
            or configurations.configparser is None
            or configurations.config_file is None
        ):
            LOG.warning("Failed to load the flake8 configuration file, exiting.")
            return

        filtered_vbf: List[ViolationsByFile] = []
        for vbf in violations_by_file:
            existing_violations_by_count = vbf.existing_violations_by_count
            per_file_violations_already_tracked = vbf.per_file_violations_already_tracked

            # If there are no existing violations, just add the ones found here, don't need to
            # worry about the per_file_violations_tracked
            if not existing_violations_by_count and not per_file_violations_already_tracked:
                filtered_vbf.append(vbf)
                continue

            new_violations_by_count = vbf.violations_by_count
            reconciled_violations: List[ViolationsByCount] = []
            if existing_violations_by_count:
                for nv in new_violations_by_count:
                    current_code = nv.code
                    evbc_code_found: List[ViolationsByCount] = list(
                        filter(
                            lambda e: e.code == current_code,  # noqa: PLW640
                            existing_violations_by_count,
                        )
                    )
                    evbc_code: Optional[ViolationsByCount] = None
                    if evbc_code_found:
                        evbc_code = evbc_code_found[0]
                    # If we see the noqa codes already in the file, just add the existing count to
                    # the new violations found this round
                    if evbc_code:
                        new_count = nv.count + evbc_code.count
                        reconciled_violations.append(
                            ViolationsByCount(filename=nv.filename, code=nv.code, count=new_count)
                        )
                    else:
                        reconciled_violations.append(nv)
            else:
                reconciled_violations = new_violations_by_count

            if per_file_violations_already_tracked:
                per_file_violations_count = per_file_violations_already_tracked.violations_by_count
                for per_file_violations in per_file_violations_count:
                    code = per_file_violations.code
                    found = list(
                        filter(
                            lambda nvbc: nvbc.code == code,  # noqa: PLW640
                            new_violations_by_count,
                        )
                    )
                    if not found:
                        # TODO: maybe reconcile this with the existing codes in the file
                        reconciled_violations.append(per_file_violations)
            reconciled_violations.sort(key=attrgetter("code"))
            filtered_vbf.append(
                ViolationsByFile(filename=vbf.filename, violations_by_count=reconciled_violations)
            )
        # Now add in any per_file_violations_tracked that weren't found in this run
        for pfvt in self.per_file_violations_tracked:
            filename = pfvt.filename
            found = list(
                filter(lambda fvbf: fvbf.filename == filename, filtered_vbf)  # type: ignore  # noqa: PLW640
            )
            if not found:
                vbc: List[ViolationsByCount] = pfvt.violations_by_count
                filtered_vbf.append(ViolationsByFile(filename=filename, violations_by_count=vbc))

        filtered_vbf.sort(key=attrgetter("filename"))
        tracked_violation_strs: List[str] = [vbf.violations_by_count_string for vbf in filtered_vbf]
        pfvt_formatted: str = "\n" + "\n".join(tracked_violation_strs)
        configurations.configparser["flake8_scout_rule"][
            "per_file_violations_tracked"
        ] = pfvt_formatted
        with open(configurations.config_file, "w", encoding="UTF-8") as f:
            configurations.configparser.write(f)
        print(
            f"Updated the flake8 configuration file '{configurations.config_file}' with the "
            "violations found in this run."
        )
        print("Done")

    @staticmethod
    def _update_lines_in_file(violations: List[ViolationsByLine]) -> None:  # noqa: CCR001
        """
        Updates lines in the specified file by adding '# noqa: <errors>' annotations.

        This method assumes that the violations are all part of the same file

        It creates a backup of the file before making any changes and
        restores the original file in case of an error during the update process.

        :param violations: A list of violations grouped by line within a file.
        :type violations: List[ViolationsByLine]
        """
        backup_extension = f".bak_{random_letters(5)}"
        filename = violations[0].filename
        backup_file = f"{filename}{backup_extension}"
        try:
            with fileinput.input(files=filename, inplace=True, backup=backup_extension) as file:
                for line in file:
                    line_number = file.filelineno()
                    processed_line = Flake8ScoutRuleFormatter._process_line(
                        line, line_number, violations
                    )
                    print(processed_line, end="")
        except Exception:
            print(f"Error updating file {filename}")
            move(backup_file, filename)
            raise
        finally:
            os.remove(f"{filename}{backup_extension}")

    @staticmethod
    def _process_line(line: str, file_lineno: int, violations: List[ViolationsByLine]) -> str:
        """
        Processes a line of code and adds the correct '# noqa: <errors>' annotation if violations.

        This function checks if the given line number has any associated violations. If a violation
        is found, it returns the line with the '# noqa: <errors>' annotation. If no violation is
        found, it returns the original line.

        :param line: The actual text of the line of code to process.
        :type line: str
        :param file_lineno: The line number of the file being processed.
        :type file_lineno: int
        :param violations: A list of violations grouped by line within a file.
        :type violations: List[ViolationsByLine]
        :return: The processed line with the '# noqa: <errors>' annotation if there are violations,
        otherwise the original line.
        :rtype: str
        """
        for violation in violations:
            if violation.line_number == file_lineno:
                return f"{violation.add_noqa_to_line}\n"
        # The line naturally has \n at the end, so just return it
        return line

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
            response = input(
                "\nWould you like to correct these violations inline and update the "
                "flake8 configuration file with the them? (y/n/?): "
            )
            formatted_response = response.strip().lower()[0:1]
            if formatted_response in ["y", "n"]:
                return formatted_response == "y"
            if formatted_response == "?":
                print(
                    "\nEnter 'y' to correct the violations inline (by adding '# noqa: <errors>') "
                    " to the actual affected lines.\nThen the formatter will update the flake8 "
                    "configuration file (specifically the per_file_violations_tracked key in the "
                    "[flake8_scout_rule] section) with each file and the violations caught by "
                    "this run of flake8.\nEnter 'n' to exit without making any changes."
                )
            else:
                print("\nInvalid input. Please enter 'y' or 'n' or '?'.")

    def _noqa_annotation_adder(self: Self) -> None:
        """
        Adds '# noqa: <errors>' annotations to lines in files with violations.

        The method groups violations by file and then by line within each file,
        ensuring that multiple violations on the same line are handled correctly.
        It creates a backup of each file before making any changes and restores the
        original file in case of an error during the update process.
        """
        no_review_prompt_prefix = "Automatically a" if self.options.no_review_prompt else "A"
        print(
            f"{no_review_prompt_prefix}dding '# noqa: <errors>' annotations to the files "
            "with violations now:"
        )
        for file_violations in self.violations_manager.violations_by_file:
            LOG.debug(
                f"Adding '# noqa: <errors>' annotations to file: '{file_violations.filename}'"
            )
            self._update_lines_in_file(file_violations.violations_by_line)
            print(".", end="")
        print("\n")
