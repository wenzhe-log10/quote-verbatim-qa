#!/usr/bin/env python3
"""Verify quote-column snippets in a markdown table against source PDFs.

Usage:
  python3 verify_quotes.py --md output.md
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}

QUOTE_CANDIDATES = {"supporting quote", "quotation", "quote"}
FILE_CANDIDATES = {"file name", "filename", "file"}


@dataclass
class RowCheck:
    row_num: int
    file_name: str
    status: str
    quote_count: int
    quote_texts: list[str]
    matched_texts: list[str]
    match_modes: list[str]
    failed_quotes: list[str]
    note: str = ""


def split_markdown_row(line: str) -> list[str]:
    """Split a markdown table row on unescaped pipes."""
    line = line.strip()
    if not (line.startswith("|") and line.endswith("|")):
        return []

    cells: list[str] = []
    current: list[str] = []
    escaped = False

    # Skip outer pipes.
    content = line[1:-1]
    for ch in content:
        if escaped:
            current.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    cells.append("".join(current).strip())
    return cells


def is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", c.strip()) for c in cells)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Remove most control chars that appear in some pdftotext outputs.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    # Remove font-encoding tokens like '/C21' that are not semantic text.
    text = re.sub(r"/[cC][0-9A-Fa-f]{2,4}", " ", text)
    # Decode PDF glyph tokens like '/uniFB02' into actual Unicode characters.
    def _decode_uni_token(m: re.Match[str]) -> str:
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return m.group(0)

    # Allow optional surrounding spaces so fragments like "de /uniFB01 ned" become "defined".
    text = re.sub(r"\s*/?uni([0-9A-Fa-f]{4})\s*", _decode_uni_token, text)
    text = unicodedata.normalize("NFKC", text)
    # Normalize dash variants (en/em/minus/etc.) to ASCII hyphen.
    text = re.sub(r"[‐‑‒–—―−]", "-", text)
    # Map common Greek letter variants used in marker contexts.
    text = text.replace("κ", "k").replace("Κ", "k")
    text = text.replace("λ", "l").replace("Λ", "l")
    text = text.replace("β", "b").replace("Β", "b")
    # Thorn is frequently used in extracted PDFs for plus-like glyphs (e.g., "1þ").
    text = text.replace("þ", "+").replace("Þ", "+")
    for src, dst in LIGATURE_MAP.items():
        text = text.replace(src, dst)
    text = text.replace("\u00ad", "")  # soft hyphen
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("’", "'").replace("‘", "'")
    # Undo line-break hyphenation.
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = re.sub(r"\s+", " ", text)
    # Normalize spacing around punctuation.
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,.;:!?])([^\s])", r"\1 \2", text)
    # Normalize plus spacing.
    text = re.sub(r"\s*\+\s*", "+", text)
    # Normalize marker-plus notation variants from extraction (e.g., CD341, CD34 1 -> CD34+).
    text = re.sub(r"\b(cd\d{1,3}|tdt)\s*1\b", r"\1+", text, flags=re.IGNORECASE)
    # Drop citation digits glued to long words (e.g., "tissues1" -> "tissues").
    text = re.sub(r"\b([a-z]{5,})\d{1,2}\b", r"\1", text)
    # Fix split words introduced by ligature decoding (e.g., "fl ow" -> "flow").
    text = re.sub(r"\b(ffi|ffl|ff|fi|fl)\s+([a-z]{2,})\b", r"\1\2", text, flags=re.IGNORECASE)
    # Make spacing around hyphens robust to OCR/tokenization quirks.
    text = re.sub(r"\s*-\s*", "-", text)
    return text.strip().lower()


def compact_alnum(text: str) -> str:
    """Aggressive normalization for OCR/extraction artifacts."""
    t = normalize_text(text)
    # Drop standalone citation numbers (e.g., '.14', '[12]') while keeping tokens like CD19.
    t = re.sub(r"\b\d+\b", " ", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def compact_alnum_with_map(text: str) -> tuple[str, list[int]]:
    """Return compacted text and char-index map back to input text."""
    t = re.sub(r"\b\d+\b", " ", text)
    out: list[str] = []
    idx_map: list[int] = []
    for i, ch in enumerate(t):
        if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            out.append(ch)
            idx_map.append(i)
    return "".join(out), idx_map


def compact_find_span(needle: str, haystack: str) -> tuple[int, int] | None:
    """Find compacted needle in compacted haystack and map back to haystack indexes."""
    compact_needle = compact_alnum(needle)
    compact_hay, idx_map = compact_alnum_with_map(haystack)
    k = compact_hay.find(compact_needle)
    if k < 0 or not compact_needle:
        return None
    start = idx_map[k]
    end = idx_map[k + len(compact_needle) - 1] + 1
    return start, end


def extract_quoted_spans(cell: str) -> list[str]:
    # Support ascii and curly quotes.
    spans: list[str] = []
    for pat in (r'"([^"]+)"', r"“([^”]+)”"):
        spans.extend(m.group(1).strip() for m in re.finditer(pat, cell))
    return [s for s in spans if s]


def fragments_in_order(fragments: list[str], text: str) -> bool:
    pos = 0
    for frag in fragments:
        idx = text.find(frag, pos)
        if idx < 0:
            return False
        pos = idx + len(frag)
    return True


def sentence_fragments(text: str, min_len: int = 25) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) >= min_len]


def chunked_compact_match(span_norm: str, pdf_norm: str) -> str | None:
    """Conservative fallback: match a high fraction of ordered word chunks."""
    words = span_norm.split()
    if len(words) < 20:
        return None

    chunks = [" ".join(words[i : i + 6]) for i in range(0, len(words), 6)]
    pos = 0
    matched_chunks: list[str] = []
    needed = max(3, int(0.75 * len(chunks)))

    for chunk in chunks:
        sub = pdf_norm[pos:]
        span = compact_find_span(chunk, sub)
        if span is None:
            continue
        s, e = span
        matched_chunks.append(sub[s:e])
        pos += e

    if len(matched_chunks) >= needed:
        return " || ".join(matched_chunks)
    return None


def _match_span_core(span_norm: str, pdf_norm: str) -> tuple[str, str] | None:
    idx = pdf_norm.find(span_norm)
    if idx >= 0:
        return "contiguous", pdf_norm[idx : idx + len(span_norm)]

    if re.search(r"(?:\.\s*){3,}", span_norm):
        ellipsis_frags = [f.strip(" .") for f in re.split(r"(?:\.\s*){3,}", span_norm) if f.strip(" .")]
        if ellipsis_frags and fragments_in_order(ellipsis_frags, pdf_norm):
            matched: list[str] = []
            pos = 0
            for frag in ellipsis_frags:
                j = pdf_norm.find(frag, pos)
                matched.append(pdf_norm[j : j + len(frag)])
                pos = j + len(frag)
            return "ellipsis_fragments_in_order", " ... ".join(matched)
        # OCR-tolerant fallback for ellipsis fragments.
        if ellipsis_frags:
            matched = []
            pos = 0
            ok = True
            for frag in ellipsis_frags:
                sub = pdf_norm[pos:]
                span = compact_find_span(frag, sub)
                if span is None:
                    ok = False
                    break
                s, e = span
                matched.append(sub[s:e])
                pos += e
            if ok:
                return "ellipsis_fragments_compact_in_order", " ... ".join(matched)

    sent_frags = sentence_fragments(span_norm)
    if len(sent_frags) >= 2 and all(f in pdf_norm for f in sent_frags):
        matched = []
        for frag in sent_frags:
            j = pdf_norm.find(frag)
            matched.append(pdf_norm[j : j + len(frag)])
        return "sentence_fragments_anywhere", " || ".join(matched)

    # Fallback for OCR/tokenization artifacts like split words or citation markers.
    span = compact_find_span(span_norm, pdf_norm)
    if span is not None:
        start, end = span
        return "alnum_compact", pdf_norm[start:end]

    chunked = chunked_compact_match(span_norm, pdf_norm)
    if chunked is not None:
        return "chunked_compact_in_order", chunked

    return None


def match_span(span_norm: str, pdf_norm: str) -> tuple[str, str] | None:
    """Return (match mode, matched text) or None if not matched."""
    found = _match_span_core(span_norm, pdf_norm)
    if found is not None:
        return found

    # Quotes may include editorial bracket insertions (e.g., "[MRD]") not present in PDF text.
    if "[" in span_norm and "]" in span_norm:
        alt = re.sub(r"\[[^\]]+\]", " ", span_norm)
        alt = re.sub(r"\s+", " ", alt).strip()
        if alt and alt != span_norm:
            alt_found = _match_span_core(alt, pdf_norm)
            if alt_found is not None:
                mode, matched = alt_found
                return f"{mode}_drop_brackets", matched

    return None


def find_table(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    for i in range(len(lines) - 1):
        header = split_markdown_row(lines[i])
        sep = split_markdown_row(lines[i + 1])
        if not header or not sep:
            continue
        if len(header) != len(sep) or not is_separator_row(sep):
            continue

        rows: list[list[str]] = []
        j = i + 2
        while j < len(lines):
            cells = split_markdown_row(lines[j])
            if not cells:
                break
            rows.append(cells)
            j += 1
        if rows:
            return header, rows
    raise ValueError("No markdown table with data rows found.")


def get_col_idx(header: list[str], candidates: set[str]) -> int:
    lowered = [h.strip().lower() for h in header]
    for i, name in enumerate(lowered):
        if name in candidates:
            return i
    raise ValueError(f"Could not find table column from candidates: {sorted(candidates)}")


def normalize_filename(name: str, drop_pdf_ext: bool = False) -> str:
    n = unicodedata.normalize("NFKC", name).strip().lower()
    n = re.sub(r"\s+", " ", n)
    if drop_pdf_ext and n.endswith(".pdf"):
        n = n[:-4].rstrip()
    return n


def resolve_pdf_path(base_dir: Path, raw_file_name: str) -> tuple[Path | None, str]:
    """Resolve raw table file name to an existing PDF path."""
    raw_file_name = raw_file_name.strip()
    direct = base_dir / raw_file_name
    if direct.exists():
        return direct, ""

    # Common case: table omits ".pdf".
    if not raw_file_name.lower().endswith(".pdf"):
        with_ext = base_dir / f"{raw_file_name}.pdf"
        if with_ext.exists():
            return with_ext, f"resolved file name to {with_ext.name}"

    pdf_files = [p for p in base_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
    by_full: dict[str, list[Path]] = {}
    by_stem: dict[str, list[Path]] = {}
    for p in pdf_files:
        by_full.setdefault(normalize_filename(p.name, drop_pdf_ext=False), []).append(p)
        by_stem.setdefault(normalize_filename(p.name, drop_pdf_ext=True), []).append(p)

    q_full = normalize_filename(raw_file_name, drop_pdf_ext=False)
    q_stem = normalize_filename(raw_file_name, drop_pdf_ext=True)

    candidates: list[Path] = []
    candidates.extend(by_full.get(q_full, []))
    candidates.extend(by_stem.get(q_stem, []))
    # If table includes extension but spacing differs, also try stem-normalized from full query.
    candidates.extend(by_stem.get(normalize_filename(q_full, drop_pdf_ext=True), []))

    # De-duplicate preserving order.
    uniq: list[Path] = []
    seen: set[str] = set()
    for c in candidates:
        k = str(c)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)

    if len(uniq) == 1:
        return uniq[0], f"resolved file name to {uniq[0].name}"
    if len(uniq) > 1:
        return None, "ambiguous PDF file name"
    return None, "missing PDF file"


def extract_pdf_text(pdf_path: Path, mode: str = "plain") -> str:
    cmd = ["pdftotext", str(pdf_path), "-"]
    if mode == "raw":
        cmd = ["pdftotext", "-raw", str(pdf_path), "-"]
    elif mode != "plain":
        raise ValueError(f"unsupported mode: {mode}")
    proc = subprocess.run(
        # Plain mode keeps better reading order for multi-column papers.
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "").strip() or "pdftotext failed")
    return proc.stdout


def reconcile_row_cells(row: list[str], header_len: int, quote_idx: int) -> tuple[list[str] | None, str]:
    """Reconcile malformed markdown rows with extra '|' inside a cell."""
    if len(row) == header_len:
        return row, ""

    if len(row) < header_len:
        # Conservative pad: keeps deterministic column indexing.
        return row + [""] * (header_len - len(row)), "row had fewer cells; padded"

    # Too many cells: usually due to raw '|' inside Supporting Quote.
    overflow = len(row) - header_len
    if 0 <= quote_idx < len(row):
        end = quote_idx + overflow + 1
        if end <= len(row):
            merged = row[:quote_idx] + [" | ".join(row[quote_idx:end])] + row[end:]
            if len(merged) == header_len:
                return merged, "row had extra cells; merged into quote column"

    # Fallback: merge overflow into last column.
    merged_last = row[: header_len - 1] + [" | ".join(row[header_len - 1 :])]
    if len(merged_last) == header_len:
        return merged_last, "row had extra cells; merged into last column"

    return None, "row cell count mismatch"


def verify_rows(base_dir: Path, rows: Iterable[list[str]], header_len: int, file_idx: int, quote_idx: int) -> list[RowCheck]:
    results: list[RowCheck] = []
    pdf_norm_cache: dict[str, list[tuple[str, str]]] = {}

    for n, row in enumerate(rows, start=1):
        row, row_note = reconcile_row_cells(row, header_len, quote_idx)
        if row is None:
            results.append(RowCheck(n, "", "FAIL", 0, [], [], [], [], note=row_note))
            continue

        file_name = row[file_idx].strip()
        quote_cell = row[quote_idx].strip()

        if not file_name:
            note = "empty file name" if not row_note else f"{row_note}; empty file name"
            results.append(RowCheck(n, file_name, "FAIL", 0, [], [], [], [], note=note))
            continue
        pdf_path, resolve_note = resolve_pdf_path(base_dir, file_name)
        if pdf_path is None:
            note = resolve_note if not row_note else f"{row_note}; {resolve_note}"
            results.append(RowCheck(n, file_name, "FAIL", 0, [], [], [], [], note=note))
            continue

        spans = extract_quoted_spans(quote_cell)
        if not spans:
            spans = [quote_cell] if quote_cell else []
        if not spans:
            results.append(RowCheck(n, file_name, "FAIL", 0, [], [], [], [], note="no quote text found"))
            continue

        cache_key = str(pdf_path)
        if cache_key not in pdf_norm_cache:
            variants: list[tuple[str, str]] = []
            for mode in ("plain", "raw"):
                raw_text = extract_pdf_text(pdf_path, mode=mode)
                variants.append((mode, normalize_text(raw_text)))
            pdf_norm_cache[cache_key] = variants

        failures: list[str] = []
        modes: list[str] = []
        matched_texts: list[str] = []
        for span in spans:
            span_norm = normalize_text(span)
            matched = False
            for src_mode, pdf_norm in pdf_norm_cache[cache_key]:
                match = match_span(span_norm, pdf_norm)
                if match is None:
                    continue
                match_mode, matched_text = match
                modes.append(f"{match_mode}@{src_mode}")
                matched_texts.append(matched_text)
                matched = True
                break
            if not matched:
                failures.append(span)

        status = "PASS" if not failures else "FAIL"
        results.append(
            RowCheck(
                row_num=n,
                file_name=file_name,
                status=status,
                quote_count=len(spans),
                quote_texts=spans,
                matched_texts=matched_texts,
                match_modes=modes,
                failed_quotes=failures,
                note="; ".join(x for x in (row_note, resolve_note) if x),
            )
        )
    return results


def write_csv_report(path: Path, checks: Iterable[RowCheck]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "row_num",
                "file_name",
                "status",
                "quote_count",
                "failed_count",
                "quote_texts",
                "matched_texts",
                "match_modes",
                "note",
                "failed_quotes",
            ]
        )
        for c in checks:
            writer.writerow(
                [
                    c.row_num,
                    c.file_name,
                    c.status,
                    c.quote_count,
                    len(c.failed_quotes),
                    " || ".join(c.quote_texts),
                    " || ".join(c.matched_texts),
                    " | ".join(c.match_modes),
                    c.note,
                    " || ".join(c.failed_quotes),
                ]
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify markdown-table quotes against local PDF files.")
    parser.add_argument("--md", default="output.md", help="Markdown file containing the table.")
    parser.add_argument("--base-dir", default=".", help="Directory containing PDF files.")
    parser.add_argument(
        "--report-csv",
        default="quote_verification_report.csv",
        help="CSV report output path.",
    )
    args = parser.parse_args()

    md_path = Path(args.md)
    base_dir = Path(args.base_dir)
    report_path = Path(args.report_csv)

    if not md_path.exists():
        print(f"ERROR: markdown file not found: {md_path}", file=sys.stderr)
        return 2

    lines = md_path.read_text(encoding="utf-8").splitlines()
    try:
        header, rows = find_table(lines)
        file_idx = get_col_idx(header, FILE_CANDIDATES)
        quote_idx = get_col_idx(header, QUOTE_CANDIDATES)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    checks = verify_rows(base_dir, rows, len(header), file_idx, quote_idx)
    write_csv_report(report_path, checks)

    total = len(checks)
    passed = sum(1 for c in checks if c.status == "PASS")
    failed = total - passed

    print(f"Checked rows: {total}")
    print(f"PASS: {passed}")
    print(f"FAIL: {failed}")
    print(f"CSV report: {report_path}")
    if failed:
        print("\nFailed rows:")
        for c in checks:
            if c.status == "FAIL":
                print(f"- row {c.row_num}: {c.file_name} (failed_quotes={len(c.failed_quotes)}) {c.note}".rstrip())
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
