from __future__ import annotations
import re
from datetime import datetime, timedelta
from typing import List, Union, Tuple, Optional, Callable, cast

# TODO: need to get dynamic height working, it's not doing that on the labels.


class LogMessage:
    def __init__(self, timestamp: datetime, level: str, message: str):
        self.timestamp = timestamp
        self.level = level
        self.message = message

    def __repr__(self):
        return f"Event({self.timestamp.time()}, {self.level}, {self.message})"


class PartialLogSection:
    "for use during parsing"

    def __init__(
        self,
        name: str,
        start_time: Optional[datetime],
        start_line: Optional[int] = None,
    ):
        self.name = name
        self.start_time = start_time
        self.end_time: Optional[datetime] = None
        self.start_line = start_line
        self.end_line: Optional[int] = None
        self.children: List[Union["PartialLogSection", LogMessage]] = []

    def close(self, end_time: datetime, end_line: int):
        self.end_time = end_time
        self.end_line = end_line


class LogSection:
    def __init__(
        self,
        name: str,
        start_time: datetime,
        end_time: datetime,
        children: List[Union["LogSection", LogMessage]],
        start_line: int,
        end_line: int,
    ):
        self.name = name
        self.start_time = start_time
        self.end_time = end_time
        self.children = children
        self.start_line = start_line
        self.end_line = end_line

    def duration_microseconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds() * 1e6

    def duration_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    def __repr__(self, indent=0):
        ind = "  " * indent
        dur = (
            f" ({self.duration_microseconds():.0f}µs)"
            if self.duration_microseconds()
            else ""
        )
        s = f"{ind}Section({self.name}, {self.start_time.time()} -> {self.end_time.time() if self.end_time else '...'}{dur}):\n"
        for child in self.children:
            s += (
                child.__repr__(indent + 1)
                if isinstance(child, LogSection)
                else f"{ind}  {child}\n"
            )
        return s


def convert_partial_log_section_to_regular_log_section_rec(
    root: PartialLogSection,
) -> LogSection:
    assert root.start_time is not None
    assert root.end_time is not None
    assert root.start_line is not None
    assert root.end_line is not None

    final_children = []
    for child in root.children:
        if isinstance(child, PartialLogSection):
            final_children.append(
                convert_partial_log_section_to_regular_log_section_rec(child)
            )
        else:
            final_children.append(child)

    return LogSection(
        root.name,
        root.start_time,
        root.end_time,
        final_children,
        root.start_line,
        root.end_line,
    )


def parse_logs(
    filename: str, message_transform: Optional[Callable[[str], str]] = None
) -> LogSection:
    # [timestamp] [log_level] message
    timestamp_re = re.compile(r"\[(.*?)\] \[(.*?)\]\s+(.*)")
    start_of_log_section_re = re.compile(r"^===\s*start\s+(.+?)\s*===\s*\{")
    end_re = re.compile(r"^===\s+end\s+(.+?)\s*===\s*\}")

    root = PartialLogSection("root", None)
    stack: List[PartialLogSection] = [root]

    first_timestamp = None
    last_timestamp = None

    last_used_line_number: Optional[int] = None
    with open(filename, "r") as f:
        for line_num, line in enumerate(f, 1):
            last_used_line_number = line_num
            match = timestamp_re.match(line.strip())
            if not match:
                continue

            ts_str, log_level, msg = match.groups()
            timestamp = datetime.strptime(ts_str, "%H:%M:%S.%f")

            if first_timestamp is None:
                first_timestamp = timestamp
                root.start_time = timestamp
            last_timestamp = timestamp

            # remove the prefixed "| " bars
            msg_clean = re.sub(r"^(?:\|\s*)+", "", msg)

            # apply optional transform
            if message_transform:
                msg_clean = message_transform(msg_clean)

            current_log_section: PartialLogSection = stack[-1]

            # check section start
            start_match = start_of_log_section_re.match(msg_clean)
            line_is_start_of_log_section = start_match != None

            if line_is_start_of_log_section:
                section_name = start_match.group(1)
                section = PartialLogSection(
                    section_name, timestamp, start_line=line_num
                )
                current_log_section.children.append(section)
                stack.append(section)
                continue

            # check section end
            end_match = end_re.match(msg_clean)
            line_is_end_of_log_section = end_match != None
            if line_is_end_of_log_section:
                section_name = end_match.group(1)
                closed_section_is_for_current_log_section = (
                    current_log_section.name == section_name
                )
                if line_is_end_of_log_section:
                    section_name = end_match.group(1)
                    if stack and current_log_section.name == section_name:
                        current_log_section.close(timestamp, end_line=line_num)
                        stack.pop()
                    else:
                        print(f"Warning: unmatched end marker for {section_name}")
                    continue

            # if it's not a start or end log section event then it's a regular message event
            event = LogMessage(timestamp, log_level, msg_clean)
            current_log_section.children.append(event)

    if last_timestamp and last_used_line_number:
        root.start_line = 1
        root.end_line = last_used_line_number
        root.close(last_timestamp, end_line=last_used_line_number)

    return convert_partial_log_section_to_regular_log_section_rec(root)
