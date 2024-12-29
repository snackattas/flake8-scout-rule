import re
from collections import Counter
from itertools import groupby
from operator import attrgetter
from typing import List

from flake8.defaults import NOQA_INLINE_REGEXP
from flake8.violation import Violation
from typing_extensions import Self

from flake8_scout_rule.data_classes import (
    ExistingViolationsByCount,
    ViolationsByCount,
    ViolationsByFile,
    ViolationsByLine,
)
from flake8_scout_rule.per_file_violations_tracked_manager import (
    PerFileViolationsTrackedManager,
)
from flake8_scout_rule.utils import normalize_filename


class ViolationsManager:
    def __init__(self: Self, per_file_violations_tracked_manager: PerFileViolationsTrackedManager):
        self.violations: List[Violation] = []
        self.violations_by_file: List[ViolationsByFile] = []
        self.per_file_violations_tracked_manager = per_file_violations_tracked_manager

    def add_violation(self: Self, violation: Violation):
        self.violations.append(violation)

    @staticmethod
    def group_file_violations_by_line(  # noqa: CCR001
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
        violations_by_line.sort(key=attrgetter("line_number"))
        return violations_by_line

    @staticmethod
    def group_file_violations_by_count(  # noqa: CCR001
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
        violations_by_count.sort(key=attrgetter("code"))
        return violations_by_count

    @staticmethod
    def _get_file_content(filename: str) -> str:
        """Return the content of the specified file."""
        with open(filename, "r", encoding="UTF-8") as f:
            file_content = f.read()
        return file_content

    @staticmethod
    def existing_violations_by_count_per_file(
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

    def group_violations(self: Self) -> None:
        # Normalize the filenames in the violations now to match the per_file_violations_tracked
        self.violations = [
            v._replace(filename=normalize_filename(v.filename)) for v in self.violations
        ]
        grp_by_filename = groupby(self.violations, key=attrgetter("filename"))
        violations_by_file = [
            ViolationsByFile(filename=key, violations=list(grp)) for key, grp in grp_by_filename
        ]
        violations_by_file.sort(key=attrgetter("filename"))
        per_file_violations_tracked = (
            self.per_file_violations_tracked_manager.per_file_violations_tracked
        )
        for vbf in violations_by_file:
            vbf.violations_by_line = self.group_file_violations_by_line(vbf)
            vbf.violations_by_count = self.group_file_violations_by_count(vbf)
            file_content = self._get_file_content(vbf.filename)
            vbf.existing_violations_by_count = self.existing_violations_by_count_per_file(
                vbf.filename, file_content
            )

            filename = vbf.filename
            found_per_file_violations_tracked = list(
                filter(
                    lambda p: p.filename == filename,  # noqa: PLW640
                    per_file_violations_tracked,
                )
            )
        if found_per_file_violations_tracked:
            vbf.per_file_violations_already_tracked = found_per_file_violations_tracked[0]
        self.violations_by_file = violations_by_file
