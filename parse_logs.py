from __future__ import annotations
import re
from datetime import datetime, timedelta
from typing import List, Union, Tuple, Optional, Callable, Union, cast
from .data_structure_utils.tree import *

# TODO: need to get dynamic height working, it's not doing that on the labels.


class LogMessage:
    # TODO: remove level.
    def __init__(self, timestamp: datetime, level: str, message: str):
        self.timestamp = timestamp
        self.level = level
        self.message = message

    def __repr__(self):
        return f"Message({self.timestamp.time()}, {self.level}, {self.message})"


class PartialLogSection:
    # this starts a log section
    def __init__(
        self,
        name: str,
        start_time: Optional[datetime] = None,
        start_line: Optional[int] = None,
    ):
        self.name = name
        self.start_time = start_time
        self.start_line = start_line
        self.end_time: Optional[datetime] = None
        self.end_line: Optional[int] = None

        # and this closes it.

    def close(self, end_time, end_line):
        self.end_time = end_time
        self.end_line = end_line

    def duration_microseconds(self):
        if not (self.start_time and self.end_time):
            return 0
        return (self.end_time - self.start_time).total_seconds() * 1e6

    def __repr__(self):
        dur = f" ({self.duration_microseconds():.0f}µs)" if self.end_time else " (open)"
        return f"Section({self.name}{dur})"


class LogSection:
    # unlike a partial log section it contains all the data.
    def __init__(
        self,
        name: str,
        start_time: datetime,
        end_time: datetime,
        start_line: int,
        end_line: int,
    ):
        self.name = name
        self.start_time = start_time
        self.end_time = end_time
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
        return s


PartialLogEntry = Union[PartialLogSection, LogMessage]
LogEntry = Union[LogSection, LogMessage]


def convert_partial_tree_to_regular_tree(
    root: TreeNode[PartialLogEntry],
) -> TreeNode[LogEntry]:

    partial = root.data

    assert isinstance(partial, PartialLogSection)

    assert partial.start_time is not None
    assert partial.end_time is not None
    assert partial.start_line is not None
    assert partial.end_line is not None

    # convert the node data itself
    new_data = LogSection(
        partial.name,
        partial.start_time,
        partial.end_time,
        partial.start_line,
        partial.end_line,
    )

    new_node = TreeNode[LogEntry](new_data)

    # convert children recursively
    for child in root.children:
        if isinstance(child.data, PartialLogSection):
            new_child = convert_partial_tree_to_regular_tree(child)
            new_node.add_child(new_child)
        else:
            # for logmessage or anything else, just wrap directly
            new_node.add_child(TreeNode(child.data))

    return new_node


def parse_logs(filename: str, message_transform=None) -> TreeNode[LogEntry]:
    timestamp_re = re.compile(r"\[(.*?)\] \[(.*?)\]\s+(.*)")
    start_of_log_section_re = re.compile(r"^===\s*start\s+(.+?)\s*===\s*\{")
    end_re = re.compile(r"^===\s+end\s+(.+?)\s*===\s*\}")

    # root section
    root_data: PartialLogEntry = PartialLogSection("root")
    root: TreeNode[PartialLogEntry] = TreeNode(root_data)
    assert isinstance(root.data, PartialLogSection)
    stack_of_sections: List[TreeNode[PartialLogEntry]] = [root]

    first_timestamp = None
    last_timestamp = None

    with open(filename, "r") as f:

        last_used_line_number: Optional[int] = None
        for line_num, line in enumerate(f, start=1):
            last_used_line_number = line_num
            match = timestamp_re.match(line.strip())
            if not match:
                continue

            ts_str, level, msg = match.groups()
            timestamp = datetime.strptime(ts_str, "%H:%M:%S.%f")

            if first_timestamp is None:
                first_timestamp = timestamp
                root.data.start_time = timestamp

            last_timestamp = timestamp

            # Clean message
            msg_clean = re.sub(r"^(?:\|\s*)+", "", msg)
            if message_transform:
                msg_clean = message_transform(msg_clean)

            current_section: TreeNode[PartialLogEntry] = stack_of_sections[-1]
            assert isinstance(current_section.data, PartialLogSection)

            # --- Start of section ---
            start_match = start_of_log_section_re.match(msg_clean)
            if start_match:
                section_name = start_match.group(1)
                sec_data: PartialLogEntry = PartialLogSection(
                    section_name,
                    start_time=timestamp,
                    start_line=line_num,
                )
                new_node: TreeNode[PartialLogEntry] = TreeNode(sec_data)
                current_section.add_child(new_node)
                stack_of_sections.append(new_node)
                continue

            # --- End of section ---
            end_match = end_re.match(msg_clean)
            if end_match:
                section_name = end_match.group(1)

                if stack_of_sections and current_section.data.name == section_name:
                    current_section.data.close(timestamp, line_num)
                    stack_of_sections.pop()
                else:
                    print(f"Warning: unmatched end of section: {section_name}")
                continue

            # --- Regular message ---
            msg_data = LogMessage(timestamp, level, msg_clean)
            current_section.add_child(TreeNode(msg_data))

    # Close root
    if last_timestamp and last_used_line_number:
        root.data.start_line = 1
        root.data.end_line = last_used_line_number
        root.data.close(last_timestamp, last_used_line_number)

    return convert_partial_tree_to_regular_tree(root)
