"""
Tests unitarios para aicli.services.jira — campo "parent" en fetch_my_issues.
Ejecutar: .venv\\Scripts\\python.exe -m pytest tests/test_jira_parent_field.py -v

Usa unittest.mock.patch sobre httpx.post — sin red real.
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


def _issue(key, parent=None, status="En curso", priority="Media", status_key="indeterminate"):
    fields = {
        "summary": f"resumen {key}",
        "status": {"name": status, "statusCategory": {"key": status_key}},
        "priority": {"name": priority},
    }
    if parent is not None:
        fields["parent"] = parent
    return {"key": key, "fields": fields}


class FetchMyIssuesParentFieldTestCase(unittest.TestCase):

    @patch("httpx.post")
    def test_requests_parent_field(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issues": []}
        mock_post.return_value = mock_resp

        jira.fetch_my_issues()

        kwargs = mock_post.call_args.kwargs
        self.assertIn("parent", kwargs["json"]["fields"])

    @patch("httpx.post")
    def test_parent_present_is_parsed(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "issues": [
                _issue("SOL-2", parent={"key": "SOL-1", "fields": {"summary": "Historia madre"}}),
            ]
        }
        mock_post.return_value = mock_resp

        result = jira.fetch_my_issues()

        item = result["en_curso"][0]
        self.assertEqual(item["parent"], {"key": "SOL-1", "summary": "Historia madre"})

    @patch("httpx.post")
    def test_parent_absent_is_none(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issues": [_issue("SOL-3")]}
        mock_post.return_value = mock_resp

        result = jira.fetch_my_issues()

        item = result["en_curso"][0]
        self.assertIsNone(item["parent"])

    @patch("httpx.post")
    def test_parent_malformed_does_not_raise(self, mock_post):
        # Parent presente pero sin "fields" (Jira a veces solo manda el key) —
        # no debe lanzar y debe caer a summary vacío, igual que fetch_issue.
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "issues": [_issue("SOL-4", parent={"key": "SOL-1"})],
        }
        mock_post.return_value = mock_resp

        result = jira.fetch_my_issues()

        item = result["en_curso"][0]
        self.assertEqual(item["parent"], {"key": "SOL-1", "summary": ""})

    @patch("httpx.post")
    def test_parent_empty_dict_is_none(self, mock_post):
        # dict vacío es falsy — mismo comportamiento que fetch_issue.
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issues": [_issue("SOL-5", parent={})]}
        mock_post.return_value = mock_resp

        result = jira.fetch_my_issues()

        item = result["en_curso"][0]
        self.assertIsNone(item["parent"])


if __name__ == "__main__":
    unittest.main()
