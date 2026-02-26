---
name: quote-verbatim-qa
description: Validate whether markdown-table quote columns are verbatim from source PDFs. Use for QA of LLM-generated screening/appraisal tables (for example output.md with File Name and Supporting Quote columns), and generate a per-row CSV report with matched snippets and match modes.
---

# Quote Verbatim QA

## Workflow

1. Identify the markdown table file (usually `output.md`) and the directory containing PDFs.
2. Run the verifier.
3. Review pass/fail summary and inspect `quote_verification_report.csv`.
4. For failures, compare `quote_texts` and `matched_texts`, then decide whether the row is a true mismatch or extraction artifact.

## Run

Preferred (installed CLI):

```bash
quote-verify --md /path/to/output.md --base-dir /path/to/dir --report-csv /path/to/dir/quote_verification_report.csv
```

Fallback (no install):

```bash
PYTHONPATH=/path/to/quote-verbatim-qa/src python3 /path/to/quote-verbatim-qa/scripts/verify_quotes.py --md /path/to/output.md --base-dir /path/to/dir --report-csv /path/to/dir/quote_verification_report.csv
```

## Output Fields

- `status`: `PASS` or `FAIL`
- `quote_texts`: quote text extracted from table
- `matched_texts`: matched snippet(s) from extracted PDF text
- `match_modes`: strategy used (`contiguous`, `ellipsis_*`, `alnum_compact`, etc.)
- `note`: filename reconciliation or row-repair notes
- `failed_quotes`: quote text not matched

## Notes

- `pdftotext` must be available in `PATH`.
- The verifier handles common PDF text artifacts (ligatures, unicode token noise, spacing/hyphenation, plus-sign variants, minor filename mismatches).
- Malformed markdown rows with raw `|` inside quote cells are repaired by merging overflow cells into the quote column.
