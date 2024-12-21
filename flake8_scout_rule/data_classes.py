from configparser import ConfigParser
from dataclasses import dataclass, field
from typing import List, Optional

from flake8.defaults import NOQA_INLINE_REGEXP
from flake8.violation import Violation

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

@dataclass
# TODO: remove this class, just use a Collections.counter on the ViolationsByFile class
class ViolationsByCount:
    filename: str
    code: str
    count: int

    @property
    def code_with_violation_count(self) -> str:
        """
        Returns the code with the count of violations.

        This method processes the code and appends the count of violations to it.

        :return: The code with the count of violations.
        :rtype: str
        """
        return f"{self.code}{{{self.count}}}"

ExistingViolationsByCount = ViolationsByCount


@dataclass
class PerFileViolationsTracked:
    filename: str
    violations_by_count: List[ViolationsByCount]


@dataclass
class ViolationsByFile:
    filename: str
    violations: List[Violation] = field(default_factory=list)
    violations_by_line: List[ViolationsByLine] = field(default_factory=list)
    violations_by_count: List[ViolationsByCount] = field(default_factory=list)
    existing_violations_by_count: List[ViolationsByCount] = field(default_factory=list)
    per_file_violations_already_tracked: Optional[PerFileViolationsTracked] = None

    @property
    def violations_by_count_string(self) -> str:
        """
        Returns the list of codes and their counts as a single string.

        :return: The list of codes for the violations by line.
        :rtype: List[str]
        """
        vbcs = ", ".join([vbc.code_with_violation_count for vbc in self.violations_by_count])
        return f"{self.filename}: {vbcs}"

@dataclass
class Flake8ScoutRuleConfigurations:
    config_file: Optional[str] = None
    configparser: Optional[ConfigParser] = None
    raw_per_file_violations_tracked: Optional[str] = None

