"""
Tests unitarios para aicli.services.jira — fetch_comments y filter_new_comments.
Ejecutar: py -m unittest tests/test_jira_comments.py -v

Usa unittest.mock.patch sobre httpx.get — sin red real.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("JIRA_URL", "https://example.atlassian.net")
os.environ.setdefault("JIRA_EMAIL", "test@example.com")
os.environ.setdefault("JIRA_TOKEN", "token123")

from aicli.services import jira


def _adf_comment(text: str) -> dict:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


class FetchCommentsTestCase(unittest.TestCase):

    @patch("httpx.get")
    def test_successful_fetch_returns_ordered_comments(self, mock_get):
        # Jira orderBy=-created -> el mock simula respuesta más nuevo primero
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "comments": [
                {"id": "3", "author": {"displayName": "QA3"}, "created": "2026-01-03T10:00:00.000+0000", "body": _adf_comment("tercero")},
                {"id": "2", "author": {"displayName": "QA2"}, "created": "2026-01-02T10:00:00.000+0000", "body": _adf_comment("segundo")},
                {"id": "1", "author": {"displayName": "QA1"}, "created": "2026-01-01T10:00:00.000+0000", "body": _adf_comment("primero")},
            ]
        }
        mock_get.return_value = mock_resp

        result = jira.fetch_comments("PROJ-9")

        self.assertEqual(len(result), 3)
        # debe devolver en orden cronológico (más viejo primero)
        self.assertEqual([c["id"] for c in result], ["1", "2", "3"])
        self.assertEqual(result[0]["body"], "primero")
        self.assertEqual(result[2]["body"], "tercero")
        for c in result:
            self.assertIn("author", c)
            self.assertIn("created", c)

    @patch("httpx.get")
    def test_non_200_returns_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp

        result = jira.fetch_comments("PROJ-9")
        self.assertEqual(result, [])

    @patch("httpx.get", side_effect=Exception("network down"))
    def test_exception_returns_empty(self, mock_get):
        result = jira.fetch_comments("PROJ-9")
        self.assertEqual(result, [])


class FilterNewCommentsTestCase(unittest.TestCase):

    def setUp(self):
        self.comments = [
            {"id": "500", "author": "a", "body": "x", "created": "t1"},
            {"id": "501", "author": "a", "body": "y", "created": "t2"},
            {"id": "502", "author": "a", "body": "z", "created": "t3"},
        ]

    def test_watermark_present_filters_tail(self):
        result = jira.filter_new_comments(self.comments, "500")
        self.assertEqual([c["id"] for c in result], ["501", "502"])

    def test_watermark_absent_returns_all(self):
        result = jira.filter_new_comments(self.comments, None)
        self.assertEqual(len(result), 3)

    def test_watermark_empty_list_returns_empty(self):
        result = jira.filter_new_comments([], "500")
        self.assertEqual(result, [])

    def test_watermark_not_found_returns_all(self):
        result = jira.filter_new_comments(self.comments, "999")
        self.assertEqual(len(result), 3)


if __name__ == "__main__":
    unittest.main()
