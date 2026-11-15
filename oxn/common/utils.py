"""
Purpose: Provides utility functions.
Functionality: Contains helper functions for time conversion, and timestamps.
Connection: Utility functions are used across different modules for common tasks.

"""

import re
from datetime import datetime, timezone

SECONDS_MAP = {
    "us": 1 / 10**6,
    "ms": 1 / 10**3,
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}
"""Map used to convert time strings to seconds"""

time_string_format_regex = r"(\d+)(us|ms|s|m|h|d)"
"""One number and unit of a time string"""


def validate_time_string(time_string) -> bool:
    """Validate that a time string consists of numbers with units only, like 90s or 1m30s"""
    return bool(re.fullmatch(f"(?:{time_string_format_regex})+", time_string))


def time_string_to_seconds(time_string) -> float:
    """Convert a time string with units to a float"""
    matches = re.findall(time_string_format_regex, time_string)
    seconds = 0.0
    for match in matches:
        value_part = match[0]
        unit_part = match[1]
        seconds += float(value_part) * SECONDS_MAP[unit_part]
    return seconds


def to_milliseconds(seconds):
    """Convert seconds to milliseconds"""
    return seconds * 10**3


def to_microseconds(seconds):
    """Convert seconds to microseconds"""
    return seconds * 10**6


def utc_timestamp() -> float:
    """Get the current time in"""
    return datetime.now(timezone.utc).timestamp()


def humanize_utc_timestamp(timestamp):
    """Return a human-readable version of a timestamp"""
    # naive like utcfromtimestamp, which Python 3.12 deprecates
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None)
