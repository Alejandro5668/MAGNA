"""
Tests unitarios para aicli.tui.modals.filter_boards — filtro por substring
case-insensitive del BoardSwitcherModal.
Ejecutar: .venv\\Scripts\\python.exe -m pytest tests/test_board_switcher_filter.py -v
"""
import unittest

from aicli.tui.modals import filter_boards


_OPTIONS = [("SOL", 5, 1), ("MAG", 2, 0), ("apiservice", 3, 0)]


class FilterBoardsTestCase(unittest.TestCase):

    def test_empty_query_returns_all(self):
        self.assertEqual(filter_boards(_OPTIONS, ""), _OPTIONS)

    def test_substring_match_case_insensitive(self):
        self.assertEqual(filter_boards(_OPTIONS, "sol"), [("SOL", 5, 1)])
        self.assertEqual(filter_boards(_OPTIONS, "API"), [("apiservice", 3, 0)])

    def test_no_match_returns_empty(self):
        self.assertEqual(filter_boards(_OPTIONS, "zzz"), [])

    def test_whitespace_only_query_treated_as_empty(self):
        self.assertEqual(filter_boards(_OPTIONS, "   "), _OPTIONS)

    def test_none_query_treated_as_empty(self):
        self.assertEqual(filter_boards(_OPTIONS, None), _OPTIONS)


if __name__ == "__main__":
    unittest.main()
