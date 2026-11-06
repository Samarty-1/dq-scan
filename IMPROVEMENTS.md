# From CSV statistics to repeatable quality checks

## Why this project

The upstream project has a useful aim: read-only quality checks without
dependencies. Its code only printed column statistics. Documented thresholds
were unimplemented, the recommended unittest command discovered zero tests,
duplicate CSV headers could silently overwrite data, and invalid UTF-8 was
silently replaced. These gaps undermine the purpose of a quality checker.

The improvements serve analysts validating exports and engineers deciding
whether a dataset should proceed through a pipeline.

## Design decisions

- Validate CSV structure before emitting results. No partial report should
  survive malformed input.
- Separate the audit API from text and JSON rendering so callers do not need
  to parse console output.
- Use explicit numeric ranges supplied by domain owners, rather than claiming
  to detect anomalies from a dataset's own minimum and maximum.
- Compare ranges using original decimal values, avoiding false failures at
  large integer boundaries. Numeric summaries use binary floats, accumulated
  exactly as rational values before the final mean is rounded.
- Represent composite keys as tuples, preserving field boundaries. Count null
  keys separately from duplicate nonnull keys.
- Preserve strings for identity: identifiers 001 and 1 remain distinct even
  though their numeric interpretation is equal.
- Keep source files untouched. Do not silently clean, impute or deduplicate.
- Read the CSV once, keeping aggregate state. Exact counts retain unique rows,
  values and keys, so memory is proportional to unique data, not constant.
- Preserve zero runtime and test dependencies. The documented unittest command
  now discovers real integration and API tests.

## Verification

The upstream sample passed but default unittest discovery ran zero tests.
New regressions exposed invalid CLI behavior and the missing audit API.
An independent review then found three additional correctness issues:
bare quotes accepted by Python's strict CSV reader, mean underflow/cancellation,
and false range violations at large integer boundaries. Regression tests were
run failing before all three were fixed.

Tests exercise real temporary files and actual CLI subprocesses. Coverage
includes counts, composite keys, inclusive ranges, threshold boundaries, BOM,
UTF-8 failures, malformed records/quoting, quoted newlines, empty/header-only
input, nonfinite values, extreme finite means, config overrides, JSON output,
source preservation and the original sample.

Run `python -m unittest -v`. CI covers Windows and Linux on Python 3.11 and 3.13.
See GitHub Actions for results on the published commit.

### Measured memory tradeoff

A local Python 3.13 tracemalloc comparison used a CSV with header `id,label`
and 50,000 identical `1,repeated` records. The upstream scan peaked at
14.372 MiB of traced Python allocations in 0.725 seconds; the improved audit
peaked at 0.044 MiB in 0.983 seconds. The new report correctly counted 50,000
rows and 49,999 duplicates. This was a single synthetic run, not a general
benchmark: it demonstrates the benefit for repeated data and the extra CPU
cost of validation and accurate aggregation. Tracemalloc is not process RSS,
and high-cardinality input will retain substantially more data.

## Compatibility and limits

The old positional command and scan(path, delim) wrapper remain. Text layout
changes; callers needing stable fields should use schema_version 1 JSON.
Whitespace-only cells are now null; distinct counts exclude nulls; duplicate
values count repeats after the first nonnull occurrence. Raw value samples are
omitted from reports.

Only UTF-8 CSV is supported. No Postgres connector, automatic repair, learned
outlier detector, fuzzy matching or universal data-quality score is claimed.
Range rules do not imply nonnull constraints; use the null threshold as well.
Cardinality and duplicate comparisons are exact string comparisons without
case, whitespace or numeric normalization. Numeric summaries round to binary
float precision; range comparisons preserve the CSV decimal value.
High-cardinality inputs can exhaust memory. CSV field limits follow Python's
csv module defaults. A rule violation is evidence of that rule failing, not
proof of general dataset fitness.
