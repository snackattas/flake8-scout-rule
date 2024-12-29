import re
from collections import Counter
from itertools import groupby
from operator import attrgetter
from typing import List, Optional

from flake8.defaults import NOQA_INLINE_REGEXP
from flake8.violation import Violation
from typing_extensions import Self

from flake8_scout_rule.data_classes import (
    ExistingViolationsByCount,
    ReconciledViolationsByFile,
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
    def group_file_violations_by_line(
        violations_by_file: ViolationsByFile,
    ) -> List[ViolationsByLine]:  # noqa: CCR001
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

    def reconcile_violations_for_updating_per_file_violations_tracked(  # noqa: C901
        self: Self,
    ) -> List[ReconciledViolationsByFile]:
        """
        Reconcile the violations with the existing per_file_violations_tracked key in the flake8 configuration file.

        This method processes the violations grouped by file and reconciles them with the
        per_file_violations_tracked key in the flake8 configuration file. It ensures that the
        violations are correctly tracked and updated in the configuration file.
        """
        reconciled_vbfs: List[ReconciledViolationsByFile] = []

        for vbf in self.violations_by_file:
            existing_violations_by_count = vbf.existing_violations_by_count
            per_file_violations_already_tracked = vbf.per_file_violations_already_tracked

            # If there are no existing violations, just add the ones found here, don't need to
            # worry about the per_file_violations_tracked
            if not existing_violations_by_count and not per_file_violations_already_tracked:
                reconciled_vbfs.append(vbf)
                continue

            newly_added_vbcs = vbf.violations_by_count
            reconciled_vbcs: List[ViolationsByCount] = []
            if existing_violations_by_count:
                for nv in newly_added_vbcs:
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
                        reconciled_vbcs.append(
                            ViolationsByCount(filename=nv.filename, code=nv.code, count=new_count)
                        )
                    else:
                        reconciled_vbcs.append(nv)
            else:
                reconciled_vbcs = newly_added_vbcs

            # We only care about per_file_violations_tracked if there are tracked violations of
            # OTHER codes in the file (not overlapping with any found this run),
            # or other files that have been tracked that don't have violations in this run
            # Because otherwise, we just read the file ourselves to manage counting the violations
            if per_file_violations_already_tracked:
                per_file_violations_count = per_file_violations_already_tracked.violations_by_count
                for per_file_violations in per_file_violations_count:
                    code = per_file_violations.code
                    found = list(
                        filter(
                            lambda nvbc: nvbc.code == code,  # noqa: PLW640
                            reconciled_vbcs,
                        )
                    )
                    if not found:
                        # TODO: maybe reconcile this with the existing codes in the file
                        reconciled_vbcs.append(per_file_violations)
            reconciled_vbcs.sort(key=attrgetter("code"))
            reconciled_vbfs.append(
                ReconciledViolationsByFile(
                    filename=vbf.filename, violations_by_count=reconciled_vbcs
                )
            )
        # Now add in any per_file_violations_tracked that weren't found in this run
        for pfvt in self.per_file_violations_tracked_manager.per_file_violations_tracked:
            filename = pfvt.filename
            found = list(
                filter(lambda fvbf: fvbf.filename == filename, reconciled_vbfs)  # type: ignore  # noqa: PLW640
            )
            if not found:
                vbc: List[ViolationsByCount] = pfvt.violations_by_count
                reconciled_vbfs.append(
                    ReconciledViolationsByFile(filename=filename, violations_by_count=vbc)
                )

        reconciled_vbfs.sort(key=attrgetter("filename"))
        return reconciled_vbfs
