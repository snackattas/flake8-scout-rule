"""Flake8 formatter that collects all violations and marks them with noqa annotations.

It also adds the violations to the flake8 configuration file's per_file_violations_tracked key,
which is then used to track the violations in the next run of flake8, and by the pre-commit hook
to ensure that the violations are not reintroduced.
"""

import argparse
import configparser
import fileinput
import os
import random
import re
import string
from collections import Counter
from itertools import groupby
from shutil import move
from typing import List, Optional, Type

from flake8 import LOG
from flake8.defaults import NOQA_INLINE_REGEXP
from flake8.exceptions import FailedToLoadPlugin
from flake8.formatting.default import Default
from flake8.options.config import _find_config_file  # type: ignore
from flake8.options.manager import OptionManager
from flake8.violation import Violation
from typing_extensions import Self

from flake8_scout_rule.constants import (
    CODE_WITH_VIOLATION_COUNT_REGEX,
    DEFAULT_FLAKE8_FILE,
    TRACKED_VIOLATIONS_LINE_REGEX,
)
from flake8_scout_rule.data_classes import (
    ExistingViolationsByCount,
    Flake8ScoutRuleConfigurations,
    PerFileViolationsTracked,
    ViolationsByCount,
    ViolationsByFile,
    ViolationsByLine,
)


class Flake8ScoutRuleFormatter(Default):
    """Flake8 formatter that collects all violations and marks them with noqa annotations.

    It also adds the violations to the flake8 configuration file's per_file_violations_tracked key,
    which is then used to track the violations in the next run of flake8, and by the pre-commit hook
    to ensure that the violations are not reintroduced.
    """

    option_manager: Optional[OptionManager] = None
    violations: List[Violation] = []
    per_file_violations_tracked: List[PerFileViolationsTracked] = []

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
        super().__init__(options)
        if self.options.no_update_flake8_config:
            return

        # Validate the flake8 configuration file's per_file_violations_tracked key is formatted
        # correctly, if it exists
        configurations = self.load_raw_per_file_violations_tracked()
        if configurations:
            self.per_file_violations_tracked = self.format_per_file_violations_tracked(
                configurations
            )

    @staticmethod
    def load_raw_per_file_violations_tracked(  # noqa: CCR001
        add_defaults: bool = False,
    ) -> Optional[Flake8ScoutRuleConfigurations]:
        """Load the raw per_file_violations_tracked string from the flake8 configuration file.

        If add_defaults is passed in, if the flake8 configuration file doesn't exist, or the
        per_file_violations_tracked key doesn't exist, create it for the user.
        """
        config_file = _find_config_file(os.getcwd())
        if not config_file:
            if add_defaults:
                config_file = os.path.join(os.getcwd(), ".flake8")
                print(
                    "WARNING - No flake8 config file found, creating a default one at "
                    f"'{config_file}'."
                )
                with open(config_file, "w", encoding="UTF-8") as f:
                    f.write(DEFAULT_FLAKE8_FILE)
                return Flake8ScoutRuleFormatter.load_raw_per_file_violations_tracked(add_defaults)
            LOG.debug(
                "No flake8 config file found during the initialization of the "
                "flake8_scout_rule plugin, continuing plugin execution."
            )
            return None

        config = configparser.ConfigParser()
        config.read(config_file)
        if "flake8_scout_rule" not in config.sections():
            if add_defaults:
                print(
                    "WARNING - Didn't find a [flake8_scout_rule] section in the flake8 "
                    "configuration file, adding it now."
                )
                config.add_section("flake8_scout_rule")
                config["flake8_scout_rule"]["per_file_violations_tracked"] = ""
                with open(config_file, "w", encoding="UTF-8") as f:
                    config.write(f)
                return Flake8ScoutRuleFormatter.load_raw_per_file_violations_tracked(add_defaults)
            LOG.debug(
                "No [flake8_scout_rule] section found in the flake8 configuration file "
                "during the initialization of the flake8_scout_rule plugin, continuing "
                "plugin execution"
            )
            return None

        flake8_scout_rule_section = config["flake8_scout_rule"]
        raw_per_file_violations_tracked = flake8_scout_rule_section.get(
            "per_file_violations_tracked"
        )
        if raw_per_file_violations_tracked is None:
            if add_defaults:
                flake8_scout_rule_section["per_file_violations_tracked"] = ""
                with open(config_file, "w", encoding="UTF-8") as f:
                    config.write(f)
                return Flake8ScoutRuleFormatter.load_raw_per_file_violations_tracked(add_defaults)
            LOG.debug(
                "No per_file_violations_tracked key found in the [flake8_scout_rule] "
                "section of the flake8 configuration file during the initialization of "
                "the flake8_scout_rule plugin, continuing plugin execution"
            )
            return None
        return Flake8ScoutRuleConfigurations(
            config_file=config_file,
            configparser=config,
            raw_per_file_violations_tracked=raw_per_file_violations_tracked,
        )

    @staticmethod
    def format_per_file_violations_tracked(  # noqa: CCR001, C901
        configurations: Flake8ScoutRuleConfigurations,
    ) -> List[PerFileViolationsTracked]:
        """
        Check if [flake8_scout_rule] section of the flake8 config file is formatted correctly.

        If it's not formatted correctly, raise an error here.
        """
        raw_per_file_violations_tracked = configurations.raw_per_file_violations_tracked
        # If the per_file_violations_tracked key is empty, just return an empty list
        if not raw_per_file_violations_tracked:
            return []

        current_file_violations_tracked = []
        lines_not_parsed = []
        for line in raw_per_file_violations_tracked.split("\n"):
            # If the line is empty, just skip it
            if not line:
                continue

            match = TRACKED_VIOLATIONS_LINE_REGEX.match(line)
            if not match:
                lines_not_parsed.append(line)
                continue

            filename = match.group("filename").strip()
            # TODO: Don't do anything now, maybe in the future, remove it from the
            # per_file_violations_tracked. For now, just check if the file exists and log a
            # warning if it doens't exist
            full_filename = os.path.join(os.getcwd(), filename)
            if not os.path.exists(full_filename):
                LOG.warning(
                    f"File '{full_filename}' from the flake8 config file "
                    "per_file_violations_tracked key does not exist, so it will have no"
                    "functional impact."
                )

            codes_with_counts = [m.strip() for m in match.group("codes").split(",")]
            issue_with_single_code = False
            violations_by_count = []
            for code_with_count in codes_with_counts:
                match = CODE_WITH_VIOLATION_COUNT_REGEX.match(code_with_count)
                if not match:
                    lines_not_parsed.append(line)
                    issue_with_single_code = True
                    break
                code = match.group("code")
                count = int(match.group("count"))
                violations_by_count.append(
                    ViolationsByCount(filename=filename, code=code, count=count)
                )
            if not issue_with_single_code:
                current_file_violations_tracked.append(
                    PerFileViolationsTracked(
                        filename=filename, violations_by_count=violations_by_count
                    )
                )
        if lines_not_parsed:
            lines_not_parsed_joined = "\n\t".join(lines_not_parsed)
            exception = Exception(
                "Failed to parse the following lines from the per_file_violations_tracked key in "
                "the [flake8_scout_rule] section of the flake8 configuration file "
                f"'{configurations.config_file}': \n{lines_not_parsed_joined}"
            )
            raise FailedToLoadPlugin("flake8-scout-rule", exception)
        current_file_violations_tracked.sort(key=lambda v: v.filename)
        return current_file_violations_tracked

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

    @staticmethod
    def _get_file_content(filename: str) -> str:
        """Return the content of the specified file."""
        filepath = os.path.join(os.getcwd(), filename)

        with open(filepath, "r", encoding="UTF-8") as f:
            file_content = f.read()
        return file_content

    @staticmethod
    def _existing_violations_by_count_per_file(
        filename: str, file_content: str
    ) -> List[ExistingViolationsByCount]:
        """Return the existing violations by count for the specified file."""
        matches = re.findall(NOQA_INLINE_REGEXP, file_content)
        error_codes = [c.strip() for match in matches for c in re.split(r",\s*", match[0])]
        counter = Counter(error_codes)
        evbc = []
        for code, count in counter.items():
            evbc.append(ExistingViolationsByCount(filename=filename, code=code, count=count))
        return evbc

    def format(self: Self, error: Violation) -> str | None:  # noqa: A003
        """Instance of format from the Default formatter interface."""
        self.violations.append(error)
        return super().format(error)

    def stop(self: Self) -> None:  # noqa: C901, CCR001, PLR912, PLR914
        """Instance of stop from the Default formatter interface."""
        if not self.violations:
            print("No violations found, so nothing to add '# noqa: <errors>' to. Exiting.")
            return

        print(f"\nFound {len(self.violations)} violations.")
        if not self.options.no_review_prompt:
            response = self.prompt_for_corrections()
            if not response:
                print("Not correcting violations, exiting.")
                return

        violations_by_file = self._noqa_annotation_adder()

        if self.options.no_update_flake8_config:
            print("Not updating the flake8 configuration file, exiting.")
            return

        # Now add the defaults if they don't exist yet
        configurations = self.load_raw_per_file_violations_tracked(add_defaults=True)
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
                            lambda e: e.code == current_code,
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
                            lambda nvbc: nvbc.code == code,
                            new_violations_by_count,
                        )
                    )
                    if not found:
                        # TODO: maybe reconcile this with the existing codes in the file
                        reconciled_violations.append(per_file_violations)
            reconciled_violations.sort(key=lambda vbc: vbc.code)
            filtered_vbf.append(
                ViolationsByFile(filename=vbf.filename, violations_by_count=reconciled_violations)
            )
        # Now add in any per_file_violations_tracked that weren't found in this run
        for pfvt in self.per_file_violations_tracked:
            filename = pfvt.filename
            found = list(
                filter(lambda fvbf: fvbf.filename == filename, filtered_vbf)  # type: ignore
            )
            if not found:
                vbc: List[ViolationsByCount] = pfvt.violations_by_count
                filtered_vbf.append(ViolationsByFile(filename=filename, violations_by_count=vbc))

        filtered_vbf.sort(key=lambda vbf: vbf.filename)
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
        backup_extension = f".bak_{Flake8ScoutRuleFormatter._random_letters(5)}"
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
            elif formatted_response == "?":
                print(
                    "\nEnter 'y' to correct the violations inline (by adding '# noqa: <errors>') "
                    " to the actual affected lines.\nThen the formatter will update the flake8 "
                    "configuration file (specifically the per_file_violations_tracked key in the "
                    "[flake8_scout_rule] section) with each file and the violations caught by "
                    "this run of flake8.\nEnter 'n' to exit without making any changes."
                )
            else:
                print("\nInvalid input. Please enter 'y' or 'n' or '?'.")

    @staticmethod
    def _group_violations_by_file_and_line(
        violations: List[Violation], per_file_violations_tracked: List[PerFileViolationsTracked]
    ) -> List[ViolationsByFile]:
        """
        Group violations by file.

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
        violations_by_file.sort(key=lambda vbf: vbf.filename)
        for vbf in violations_by_file:
            vbf.violations_by_line = Flake8ScoutRuleFormatter._group_file_violations_by_line(vbf)
            vbf.violations_by_count = Flake8ScoutRuleFormatter._group_file_violations_by_count(vbf)
            file_content = Flake8ScoutRuleFormatter._get_file_content(vbf.filename)
            vbf.existing_violations_by_count = (
                Flake8ScoutRuleFormatter._existing_violations_by_count_per_file(
                    vbf.filename, file_content
                )
            )

            filename = vbf.filename
            found_per_file_violations_tracked = list(
                filter(
                    lambda p: p.filename == filename,
                    per_file_violations_tracked,
                )
            )
            if found_per_file_violations_tracked:
                vbf.per_file_violations_already_tracked = found_per_file_violations_tracked[0]
        return violations_by_file

    @staticmethod
    def _group_file_violations_by_line(  # noqa: CCR001
        violations_by_file: ViolationsByFile,
    ) -> List[ViolationsByLine]:
        """
        Group violations by line within a file.

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
                    physical_line=violation.physical_line,  # type: ignore
                    codes=[violation.code],
                )
                violations_by_line.append(vbl)
        violations_by_line.sort(key=lambda vbl: vbl.line_number)
        return violations_by_line

    @staticmethod
    def _group_file_violations_by_count(  # noqa: CCR001
        violations_by_file: ViolationsByFile,
    ) -> List[ViolationsByCount]:
        """
        Group violations by count within a file.

        This method processes a list of violations from the whole flake8 run, and groups them by
        count within each file. It ensures that multiple violations of the same type are
        combined
        """
        violations_by_count: List[ViolationsByCount] = []
        for violation in violations_by_file.violations:
            found = False
            for vbc in violations_by_count:
                if vbc.code == violation.code:
                    vbc.count += 1
                    found = True
                    break
            if not found:
                vbc = ViolationsByCount(filename=violation.filename, code=violation.code, count=1)
                violations_by_count.append(vbc)
        violations_by_count.sort(key=lambda vbc: vbc.code)
        return violations_by_count

    def _noqa_annotation_adder(self: Self) -> List[ViolationsByFile]:
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
        violations_by_file_and_line = self._group_violations_by_file_and_line(
            self.violations, self.per_file_violations_tracked
        )
        for file_violations in violations_by_file_and_line:
            LOG.debug(
                f"Adding '# noqa: <errors>' annotations to file: '{file_violations.filename}'"
            )
            self._update_lines_in_file(file_violations.violations_by_line)
            print(".", end="")
        print("\n")
        return violations_by_file_and_line

    @staticmethod
    def _random_letters(num_letters: int) -> str:
        """Generate a random string of the specified length consisting of ASCII letters."""
        return "".join(random.choices(string.ascii_letters, k=num_letters))
