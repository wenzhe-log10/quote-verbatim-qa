import unittest

from quote_verifier.cli import normalize_text, reconcile_row_cells


class QuoteVerifierCoreTests(unittest.TestCase):
    def test_normalize_plus_and_tokens(self) -> None:
        raw = "1 þ , 2 þ /uniFB01 /C21 de /uniFB01 ned"
        norm = normalize_text(raw)
        self.assertIn("1+", norm)
        self.assertIn("2+", norm)
        self.assertNotIn("/c21", norm)
        self.assertIn("defined", norm)

    def test_cd34_marker_normalization(self) -> None:
        self.assertEqual(normalize_text("CD34 1 cells"), "cd34+ cells")
        self.assertEqual(normalize_text("CD341 cells"), "cd34+ cells")

    def test_reconcile_row_with_extra_pipes(self) -> None:
        header_len = 5
        quote_idx = 3
        row = ["file.pdf", "Include", "", '"TABLE 1', "Test", 'Type"', "reason"]
        fixed, note = reconcile_row_cells(row, header_len, quote_idx)
        self.assertIsNotNone(fixed)
        self.assertEqual(len(fixed), header_len)
        self.assertIn("merged", note)


if __name__ == "__main__":
    unittest.main()
