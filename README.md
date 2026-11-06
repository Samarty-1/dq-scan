# dq-scan

Read-only CSV quality checks for analysts and data pipelines. Python 3.11+;
no third-party dependencies, services or network access required.

## Quick start

From a checkout:

```sh
python dq_scan.py examples/sample.csv
python dq_scan.py examples/sample.csv --config examples/rules.json --format json --fail-on error
python -m unittest -v
```

The second command deliberately exits **1**: the sample contains a negative
amount, which violates the example rule. Its JSON report is still complete.
See [the example report](examples/sample-report.json).

## What it checks

- Missing values and distinct nonnull values per column.
- Duplicate records and repeated nonnull values within each column.
- Duplicate or null primary keys, including composite keys.
- Numeric values outside configured inclusive ranges.
- Non-numeric values in columns configured with numeric ranges.
- NaN and infinity, which cannot be valid finite numeric measurements.
- Invalid CSV structure, duplicate/blank headers and invalid UTF-8.

Numbers have finite-value count, minimum, maximum and mean summaries. Mixed
columns summarize only their finite numeric cells, with the subset count
explicitly included. There is no automatic outlier or bias detector.

## Pipeline usage

```sh
python dq_scan.py orders.csv --key customer_id --key order_id --format json --fail-on warning
python dq_scan.py export.csv --delimiter ";" --null-threshold 0.05
python dq_scan.py --table export.csv --format json
```

Use one positional path or --table. Repeat --key for each column in a composite
key. --format json prints only JSON to stdout; input/configuration errors go to
stderr without a partial report.

| Exit | Meaning |
| --- | --- |
| 0 | Valid input; no findings meet the selected failure policy |
| 1 | Completed audit with findings meeting --fail-on |
| 2 | Invalid input, unreadable file, malformed CSV or invalid configuration |

--fail-on none is the default for compatibility and never fails on findings.
warning fails on warnings or errors; error fails only on errors.
Argument errors also exit 2. Interrupts and operating-system termination have
their normal process behavior.

Null-threshold violations and duplicate records are warnings. Key violations,
nonfinite numbers and numeric range/type violations are errors.

## Reusable rules

```json
{
  "null_threshold": 0.1,
  "key_columns": ["order_id"],
  "ranges": {
    "amount": {"min": 0, "max": 1000}
  }
}
```

Pass a JSON file with --config rules.json. Unknown settings and nonexistent
column names are rejected. --null-threshold and --key override their config
values. Ranges require min, max, or both; bounds must be finite numbers and
min must not exceed max. Comparisons include the boundary.

A null fraction must be **greater than** the threshold to produce a finding;
equality passes. The default threshold is 0.2. Range checks skip nulls, so
configure the null threshold as well if missing values are unacceptable.

## Python API

```python
from dq_scan import audit_csv

report = audit_csv(
    "orders.csv",
    null_threshold=0.05,
    key_columns=["customer_id", "order_id"],
    ranges={"amount": {"min": 0}},
)
print(report["row_count"])
for finding in report["findings"]:
    print(finding["severity"], finding["code"], finding["count"])
```

audit_csv returns a plain dictionary. Input/schema/options errors raise
ValueError; filesystem and decoding errors propagate. It does not print.
The older scan(path, delim=",") function prints text and returns 0 for a valid
scan or 1 for an input error.

## Report contract (schema_version 1)

Top-level fields are schema_version, row_count, column_count, duplicate_rows,
columns, key, rules and findings.

Each column contains name, type (empty/number/text/mixed), null_count,
null_fraction, distinct_count, duplicate_values, nonfinite_count,
invalid_numeric_count, out_of_range_count and numeric. numeric is null if
there are no finite numeric cells; otherwise it contains count, min, max, mean.
invalid_numeric_count applies only to columns with a range rule.

key is null when no key is configured; otherwise it contains columns,
null_count and duplicate_count. Counts refer to records, not individual cells.
Duplicate counts count occurrences beyond the first; null key records do not
also contribute to duplicate-key counts.

Each finding contains code, severity, count and column (null for record/key
findings). Codes are null_threshold, duplicate_row, duplicate_key, null_key,
nonfinite_number, invalid_numeric and out_of_range. No raw cell samples or
source paths are included. Field order is deterministic but consumers should
read JSON keys, not rely on text layout or ordering.

## Parsing and scale

UTF-8 with or without a BOM is supported, including quoted delimiters, escaped
quotes and multiline quoted cells. Empty physical lines are skipped.
A header-only file is a valid zero-row dataset; a completely empty file is an
error. Every data record must have exactly the header's number of fields.

Empty and whitespace-only cells are null. Literal NA and NULL remain text.
Nonempty values and headers are not trimmed or normalized. String identities
such as 001 and 1 remain distinct. Numeric summaries use binary floating-point;
the mean accumulates those floats exactly before final rounding. Range checks
compare the original CSV decimal against the configured bounds, preserving
large integer boundaries. JSON fractional bounds retain ordinary Python float
precision. Values outside finite float range are reported as nonfinite.

The file is read once, but **memory grows with unique values, rows and keys**.
Exact duplicate detection is not constant-memory and high-cardinality datasets
may exceed available memory. Python's standard CSV field-size limit applies.
The source is never rewritten or automatically repaired.

## Development and provenance

```sh
python -m unittest -v
```

The suite tests real files, API behavior and CLI subprocesses. CI runs on
Windows and Linux with Python 3.11 and 3.13. See
[the improvement rationale](IMPROVEMENTS.md) for design decisions, compatibility
changes and the independent review findings addressed.

Based on [the original dq-scan project](https://github.com/liesbethbelmokhtar203-source/dq-scan).
The original [MIT license](LICENSE) is retained.
