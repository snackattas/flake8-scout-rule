import configparser
import os
from operator import attrgetter
from typing import List, Optional

from flake8 import LOG
from flake8.exceptions import FailedToLoadPlugin
from flake8.options.config import _find_config_file  # type: ignore
from typing_extensions import Self

from flake8_scout_rule.constants import (
    CODE_WITH_VIOLATION_COUNT_REGEX,
    DEFAULT_FLAKE8_FILE,
    TRACKED_VIOLATIONS_LINE_REGEX,
)
from flake8_scout_rule.data_classes import (
    Flake8ScoutRuleConfigurations,
    PerFileViolationsTracked,
    ViolationsByCount,
)


class PerFileViolationsTrackedManager:
    """Data class for parsed per_file_violations_tracked key in the flake8 configuration file."""

    def __init__(self):
        self.per_file_violations_tracked: List[PerFileViolationsTracked] = []
        # Validate the flake8 configuration file's per_file_violations_tracked key is formatted
        # correctly, if it exists
        configurations = self.load_raw_per_file_violations_tracked()
        if configurations:
            self.per_file_violations_tracked = self.format_per_file_violations_tracked(
                configurations
            )

    def load_raw_per_file_violations_tracked(  # noqa: CCR001, PLR911
        self: Self,
        add_defaults: bool = False,
    ) -> Optional[Flake8ScoutRuleConfigurations]:
        """Load the raw per_file_violations_tracked string from the flake8 configuration file.

        If add_defaults is passed in, if the flake8 configuration file doesn't exist, or the
        per_file_violations_tracked key doesn't exist, create it for the user.
        """
        config_file = _find_config_file(os.getcwd())
        if not config_file:
            if add_defaults:
                config_file = os.path.join(os.path.realpath(os.getcwd()), ".flake8")
                print(
                    "WARNING - No flake8 config file found, creating a default one at "
                    f"'{config_file}'."
                )
                with open(config_file, "w", encoding="UTF-8") as f:
                    f.write(DEFAULT_FLAKE8_FILE)
                return self.load_raw_per_file_violations_tracked(add_defaults)
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
                return self.load_raw_per_file_violations_tracked(add_defaults)
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
                return self.load_raw_per_file_violations_tracked(add_defaults)
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

    def format_per_file_violations_tracked(  # noqa: CCR001, C901, PLR914
        self: Self,
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
        current_file_violations_tracked.sort(key=attrgetter("filename"))
        return current_file_violations_tracked
