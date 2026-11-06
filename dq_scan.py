#!/usr/bin/env python3
"""Read-only CSV quality audits with text and versioned JSON reports."""
import argparse
import csv
import json
import math
import sys
from decimal import Decimal, DecimalException
from fractions import Fraction


def _finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name + " must be a finite number")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(name + " must be a finite number") from None
    if not math.isfinite(number):
        raise ValueError(name + " must be a finite number")
    return number


def _validate_options(null_threshold, key_columns, ranges):
    threshold = _finite_number(null_threshold, "null_threshold")
    if not 0 <= threshold <= 1:
        raise ValueError("null_threshold must be between 0 and 1")
    if not isinstance(key_columns, (list, tuple)) or any(
            not isinstance(c, str) or not c for c in key_columns):
        raise ValueError("key_columns must be a list of column names")
    if len(set(key_columns)) != len(key_columns):
        raise ValueError("key_columns contains duplicate names")
    if not isinstance(ranges, dict):
        raise ValueError("ranges must be an object")
    for name, bounds in ranges.items():
        if not isinstance(name, str) or not isinstance(bounds, dict) or not bounds:
            raise ValueError("each range must name a column and contain min or max")
        if set(bounds) - {"min", "max"}:
            raise ValueError("range supports only min and max: " + name)
        for bound, value in bounds.items():
            _finite_number(value, name + "." + bound)
        if bounds.get("min", -math.inf) > bounds.get("max", math.inf):
            raise ValueError("range min exceeds max: " + name)
    return threshold


class _Column:
    def __init__(self, name, bounds):
        self.name = name
        self.bounds = bounds
        self.values = set()
        self.nulls = self.nonfinite = self.invalid = self.outside = 0
        self.count = 0
        self.minimum = self.maximum = None
        self.total = Fraction(0)

    def add(self, value):
        if not value.strip():
            self.nulls += 1
            return
        self.values.add(value)
        try:
            number = float(value)
        except ValueError:
            self.invalid += 1
            return
        if not math.isfinite(number):
            self.nonfinite += 1
            return
        self.count += 1
        self.minimum = number if self.minimum is None else min(self.minimum, number)
        self.maximum = number if self.maximum is None else max(self.maximum, number)
        # Sum binary floats exactly, rounding only the final mean. This avoids
        # overflow, cancellation and subnormal underflow in incremental means.
        self.total += Fraction.from_float(number)
        if self.bounds:
            try:
                exact = Decimal(value)
            except DecimalException as exc:
                raise ValueError("Numeric value exceeds supported decimal range in column "
                                 + self.name) from exc
            lower = Decimal(str(self.bounds.get("min", "-Infinity")))
            upper = Decimal(str(self.bounds.get("max", "Infinity")))
            if not lower <= exact <= upper:
                self.outside += 1

    def report(self, rows):
        present = rows - self.nulls
        kind = ("empty" if not present else "number" if not self.invalid
                else "mixed" if self.count or self.nonfinite else "text")
        return {
            "name": self.name, "type": kind,
            "null_count": self.nulls,
            "null_fraction": self.nulls / rows if rows else 0.0,
            "distinct_count": len(self.values),
            "duplicate_values": present - len(self.values),
            "nonfinite_count": self.nonfinite,
            "invalid_numeric_count": self.invalid if self.bounds else 0,
            "out_of_range_count": self.outside,
            "numeric": ({"count": self.count, "min": self.minimum,
                         "max": self.maximum, "mean": float(self.total / self.count)}
                        if self.count else None),
        }


def _validated_lines(stream, delimiter):
    """Reject bare quotes, which csv.reader(strict=True) otherwise accepts."""
    state = "start"
    for line_number, line in enumerate(stream, 1):
        for char in line:
            if state == "quoted":
                if char == '"':
                    state = "after_quote"
            elif state == "after_quote":
                if char == '"':
                    state = "quoted"
                elif char == delimiter or char in '\r\n':
                    state = "start"
                else:
                    raise ValueError("CSV line {0}: unexpected character after closing quote"
                                     .format(line_number))
            elif char == delimiter or char in '\r\n':
                state = "start"
            elif char == '"':
                if state != "start":
                    raise ValueError("CSV line {0}: quote inside an unquoted field"
                                     .format(line_number))
                state = "quoted"
            else:
                state = "unquoted"
        yield line


def audit_csv(path, delimiter=",", null_threshold=0.2, key_columns=(), ranges=None):
    """Scan once and return a JSON-compatible report without modifying input.

    Exact distinct/duplicate counts retain unique values, rows and keys in
    memory. Numeric summaries describe finite parseable cells, including in
    mixed columns. Blank/whitespace-only cells are null; NA/NULL remain text.
    """
    ranges = {} if ranges is None else ranges
    threshold = _validate_options(null_threshold, key_columns, ranges)
    if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in '\r\n\0"':
        raise ValueError("delimiter must be one character other than quote, newline or NUL")
    row_count = duplicates = key_nulls = key_duplicates = 0
    seen_rows, seen_keys = set(), set()
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(_validated_lines(stream, delimiter), delimiter=delimiter, strict=True)
        try:
            header = next(reader, None)
            if not header or any(not name.strip() for name in header):
                raise ValueError("CSV must have a nonempty header for every column")
            if len(set(header)) != len(header):
                raise ValueError("CSV contains duplicate column headers")
            unknown = (set(key_columns) | set(ranges)) - set(header)
            if unknown:
                raise ValueError("Unknown columns: " + ", ".join(sorted(unknown)))
            columns = [_Column(name, ranges.get(name)) for name in header]
            key_indices = [header.index(name) for name in key_columns]
            for row in reader:
                if not row:  # Match historical DictReader treatment of blank lines.
                    continue
                if len(row) != len(header):
                    raise ValueError("CSV line {0}: expected {1} fields, found {2}"
                                     .format(reader.line_num, len(header), len(row)))
                row_count += 1
                record = tuple(row)
                duplicates += record in seen_rows
                seen_rows.add(record)
                if key_indices:
                    key = tuple(row[i] for i in key_indices)
                    if any(not value.strip() for value in key):
                        key_nulls += 1
                    else:
                        key_duplicates += key in seen_keys
                        seen_keys.add(key)
                for column, value in zip(columns, row):
                    column.add(value)
        except csv.Error as exc:
            raise ValueError("CSV line {0}: {1}".format(reader.line_num, exc)) from exc

    reports = [column.report(row_count) for column in columns]
    findings = []

    def finding(code, severity, count, column=None):
        findings.append({"code": code, "severity": severity, "count": count, "column": column})

    for column in reports:
        name = column["name"]
        if column["null_fraction"] > threshold:
            finding("null_threshold", "warning", column["null_count"], name)
        for metric, code in [("nonfinite_count", "nonfinite_number"),
                             ("invalid_numeric_count", "invalid_numeric"),
                             ("out_of_range_count", "out_of_range")]:
            if column[metric]:
                finding(code, "error", column[metric], name)
    if duplicates:
        finding("duplicate_row", "warning", duplicates)
    if key_nulls:
        finding("null_key", "error", key_nulls)
    if key_duplicates:
        finding("duplicate_key", "error", key_duplicates)
    return {
        "schema_version": 1, "row_count": row_count, "column_count": len(header),
        "duplicate_rows": duplicates, "columns": reports,
        "key": ({"columns": list(key_columns), "null_count": key_nulls,
                 "duplicate_count": key_duplicates} if key_columns else None),
        "rules": {"null_threshold": threshold, "ranges": ranges},
        "findings": findings,
    }


def print_report(report):
    print("{0} rows, {1} columns".format(report["row_count"], report["column_count"]))
    for column in report["columns"]:
        print("{name}: nulls={null_count} dupes={duplicate_values} unique={distinct_count}"
              .format(**column))
        if column["numeric"]:
            print("  finite numeric cells: count={count} min={min} max={max} mean={mean}"
                  .format(**column["numeric"]))
    print("Duplicate rows: " + str(report["duplicate_rows"]))
    for finding in report["findings"]:
        print("{severity}: {code}, column={column}, count={count}".format(**finding))


def scan(path, delim=","):
    """Compatibility wrapper: print a report, return 0 or 1 for invalid input."""
    try:
        print_report(audit_csv(path, delimiter=delim))
        return 0
    except (OSError, ValueError, UnicodeError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="UTF-8 CSV input")
    parser.add_argument("--table", help="CSV path (alias for positional input)")
    parser.add_argument("--delimiter", default=",")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--null-threshold", type=float, default=None)
    parser.add_argument("--key", action="append", default=None, help="Repeat for composite keys")
    parser.add_argument("--config", help="JSON rules: null_threshold, key_columns, ranges")
    parser.add_argument("--fail-on", choices=["none", "warning", "error"], default="none")
    args = parser.parse_args(argv)
    if bool(args.path) == bool(args.table):
        parser.error("provide exactly one input path, positional or --table")
    try:
        config = {}
        if args.config:
            with open(args.config, encoding="utf-8-sig") as stream:
                config = json.load(stream)
            if not isinstance(config, dict) or set(config) - {"null_threshold", "key_columns", "ranges"}:
                raise ValueError("config supports only null_threshold, key_columns and ranges")
        if args.null_threshold is not None:
            config["null_threshold"] = args.null_threshold
        if args.key is not None:
            config["key_columns"] = args.key
        report = audit_csv(args.path or args.table, delimiter=args.delimiter, **config)
        if args.format == "json":
            print(json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2))
        else:
            print_report(report)
    except (OSError, ValueError, UnicodeError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 2
    severities = {"warning", "error"} if args.fail_on == "warning" else {args.fail_on}
    return int(any(item["severity"] in severities for item in report["findings"]))


if __name__ == "__main__":
    sys.exit(main())
