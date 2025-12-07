import re
import sys
import configparser
from datetime import datetime
import matplotlib.pyplot as plt
from tqdm import tqdm
import numpy as np

TS_PATTERN = re.compile(r"\[(\d\d:\d\d:\d\d\.\d+)\]")


def parse_timestamp_fast(ts: str) -> float:
    """Parse HH:MM:SS.mmm into seconds as float, fast."""
    h, m, s = ts.split(":")
    s, ms = s.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + float("0." + ms)


def preprocess_log_file(log_file, section_regexes):
    """
    log_file: path to file
    section_regexes: list of (section_name, regex_pattern, const_value)
    Returns: dict {section_name: (times, values)}
    """
    compiled = [
        (name, re.compile(r) if r else None, cv) for name, r, cv in section_regexes
    ]

    results = {name: ([], []) for name, _, _ in compiled}
    first_ts = None

    with open(log_file) as f:
        for line in f:
            ts_match = TS_PATTERN.search(line)
            if not ts_match:
                continue

            timestamp = parse_timestamp_fast(ts_match.group(1))
            if first_ts is None:
                first_ts = timestamp
            rel_time = timestamp - first_ts

            for name, regex, const_value in compiled:
                val_match = regex.search(line) if regex else None
                if val_match:
                    if regex and regex.groups == 0:
                        val = const_value
                    else:
                        val = float(val_match.group(1))
                    results[name][0].append(rel_time)
                    results[name][1].append(val)
                elif const_value is not None and not results[name][1]:
                    # first point is constant if nothing matched yet
                    results[name][0].append(rel_time)
                    results[name][1].append(const_value)

    return results


def main():
    if len(sys.argv) != 2:
        print("Usage: logplot.py <config.ini>")
        sys.exit(1)

    config_file = sys.argv[1]

    cfg = configparser.ConfigParser()
    cfg.read(config_file)

    plt.figure()
    colormap = plt.get_cmap("tab20")
    label_to_color = {label: colormap(i % 20) for i, label in enumerate(cfg.sections())}

    # First pass: build a mapping log_file -> sections using it
    log_file_to_sections = {}
    max_time = 0.0

    for section in cfg.sections():
        freq = cfg.get(section, "frequency_hz", fallback=None)
        if freq is not None:
            continue  # frequency-based sections handled later

        log_file = cfg.get(section, "log_file", fallback=None)
        if not log_file:
            raise ValueError(f"[{section}] missing 'log_file=' or 'frequency_hz='")

        regex_str = cfg.get(section, "regex", fallback=None)
        const_value = cfg.get(section, "const_value", fallback=None)
        if const_value is not None:
            const_value = float(const_value)

        if log_file not in log_file_to_sections:
            log_file_to_sections[log_file] = []

        log_file_to_sections[log_file].append((section, regex_str, const_value))

    # Process all log files once
    log_results = {}
    for log_file, sections in tqdm(
        log_file_to_sections.items(), desc="Processing log files"
    ):
        results = preprocess_log_file(log_file, sections)
        log_results.update(results)
        # Update max_time
        for t, _ in results.values():
            if t:
                max_time = max(max_time, t[-1])

    if max_time == 0:
        max_time = 1.0

    # Plot sections
    for section in cfg.sections():
        freq = cfg.get(section, "frequency_hz", fallback=None)
        if freq is not None:
            # Frequency section
            freq = float(freq)
            const_value = cfg.getfloat(section, "const_value")
            period = 1.0 / freq
            n_points = int(max_time / period) + 1
            times = np.linspace(0, max_time, n_points)
            values = np.full(n_points, const_value)
            plt.plot(
                times,
                values,
                label=f"{section} ({freq} Hz)",
                color=label_to_color[section],
            )
            continue

        # Log-based section
        times, values = log_results.get(section, ([], []))
        if not times:
            print(f"[{section}] Warning: no data points found.")
            continue

        color = cfg.get(section, "color", fallback=None)
        plot_color = color if color else label_to_color[section]

        # Use plot without markers for speed
        plt.plot(
            times, values, marker="o", label=section, color=plot_color, linewidth=1
        )

    plt.xlabel("Time (seconds since start)")
    plt.ylabel("Value")
    plt.title("Log Plot")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
