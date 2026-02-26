# Integration Notes

Use the same CLI entrypoint in any agent framework that supports shell/tool execution.

## Codex

```bash
quote-verify --md /path/to/output.md --base-dir /path/to/dir --report-csv /path/to/dir/quote_verification_report.csv
```

## Claude Code

Run from terminal tool:

```bash
quote-verify --md /path/to/output.md --base-dir /path/to/dir --report-csv /path/to/dir/quote_verification_report.csv
```

## Amp / Custom Agent

Call the same command as a shell step in your workflow:

```bash
quote-verify --md "$OUTPUT_MD" --base-dir "$DOC_DIR" --report-csv "$DOC_DIR/quote_verification_report.csv"
```

## No Installation Mode

If you do not install as a package:

```bash
PYTHONPATH=/path/to/quote-verbatim-qa/src python3 /path/to/quote-verbatim-qa/scripts/verify_quotes.py --md /path/to/output.md --base-dir /path/to/dir --report-csv /path/to/dir/quote_verification_report.csv
```
