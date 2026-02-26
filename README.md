# quote-verbatim-qa

Portable quote QA tool for validating that table quote fields are verbatim from source PDFs.

## What It Checks

- Parses markdown tables (`output.md`-style).
- Maps each row to its PDF (`File Name` column).
- Verifies quote column text against PDF text extraction.
- Handles common PDF extraction artifacts:
  - ligatures and `/uniXXXX` tokens
  - control/font tokens (`/C21`, etc.)
  - `þ`/`+` confusion (`1þ`, `2þ`, `3þ`)
  - spacing/hyphenation breaks
  - minor filename mismatches (missing `.pdf`, extra spaces)
  - malformed markdown rows with raw `|` inside quote cells

## Requirements

- Python 3.10+
- `pdftotext` in `PATH`

## Install

```bash
cd quote-verbatim-qa
pip install -e .
```

## Run

```bash
quote-verify --md /path/to/output.md --base-dir /path/to/folder --report-csv /path/to/folder/quote_verification_report.csv
```

or:

```bash
PYTHONPATH=src python3 scripts/verify_quotes.py --md /path/to/output.md --base-dir /path/to/folder --report-csv /path/to/folder/quote_verification_report.csv
```

## Output

CSV columns include:

- `status` (`PASS`/`FAIL`)
- `quote_texts` (from table)
- `matched_texts` (matched snippet(s) from PDF extraction)
- `match_modes` (matching strategy used)
- `note` (filename reconciliation or row-repair notes)

## Agent Integration

- Codex: call `quote-verify ...` directly.
- Claude Code / Amp / custom agents: execute the same CLI command from shell tool integration.

## Tests

```bash
cd quote-verbatim-qa
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```
