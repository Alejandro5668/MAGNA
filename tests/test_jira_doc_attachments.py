"""
Tests unitarios para aicli.services.jira.download_doc_attachments — descarga
de adjuntos PDF/CSV/DOCX sin ningún análisis/parseo de MAGNA.
Ejecutar: py -m unittest tests/test_jira_doc_attachments.py -v

Usa unittest.mock.patch sobre httpx.get — sin red real, sin tocar disco real
(Path.write_bytes mockeado).
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


def _attachment(filename: str, mime_type: str, content_url: str = "https://example.atlassian.net/att/1") -> dict:
    return {"id": "1", "filename": filename, "mimeType": mime_type, "content": content_url}


class DownloadDocAttachmentsTestCase(unittest.TestCase):

    @patch.object(Path, "write_bytes")
    @patch("httpx.get")
    def test_downloads_pdf_csv_and_docx(self, mock_get, mock_write):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"fake-bytes"
        mock_get.return_value = mock_resp

        attachments = [
            _attachment("informe.pdf", "application/pdf"),
            _attachment("datos.csv", "text/csv"),
            _attachment("doc.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            _attachment("legacy.doc", "application/msword"),
        ]

        paths = jira.download_doc_attachments(attachments)

        self.assertEqual(len(paths), 4)
        self.assertEqual(mock_write.call_count, 4)
        self.assertTrue(all(p.endswith((".pdf", ".csv", ".docx", ".doc")) for p in paths))

    @patch("httpx.get")
    def test_ignores_non_doc_mime_types(self, mock_get):
        attachments = [
            _attachment("foto.png", "image/png"),
            _attachment("planilla.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            _attachment("video.mp4", "video/mp4"),
        ]

        paths = jira.download_doc_attachments(attachments)

        self.assertEqual(paths, [])
        mock_get.assert_not_called()

    @patch("httpx.get")
    def test_non_200_response_is_skipped(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        paths = jira.download_doc_attachments([_attachment("missing.pdf", "application/pdf")])

        self.assertEqual(paths, [])

    @patch("httpx.get", side_effect=Exception("network down"))
    def test_exception_is_swallowed_and_skipped(self, mock_get):
        paths = jira.download_doc_attachments([_attachment("informe.pdf", "application/pdf")])
        self.assertEqual(paths, [])


if __name__ == "__main__":
    unittest.main()
