# Implementation notes

The current contracts and limits are documented in README.md and IMPROVEMENTS.md.

- Blank and whitespace-only cells are null; literal NA and NULL are text.
- UTF-8 BOMs are stripped. Invalid UTF-8 raises an error rather than replacing bytes.
- Duplicate or blank headers and mismatched row widths are errors. Trailing
  fields are never silently discarded.
- Quoted newlines and escaped quotes are supported; bare quotes are rejected.
- Records are consumed once. Exact counts retain unique values, rows and keys;
  this is not constant-memory processing.
- Finite numeric means accumulate exact rational representations of binary
  floats. Range checks use the CSV decimal representation against rule bounds.
- Reports are read-only and contain no raw value samples or source paths.
