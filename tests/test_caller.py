import unittest
from unittest.mock import patch

from aicli.services import caller
from pathlib import Path


class LaunchClaudeApiKeyStripTestCase(unittest.TestCase):
    """launch_claude() nunca debe dejar que ANTHROPIC_API_KEY del entorno
    llegue al subproceso `claude` interactivo — si está seteada, el CLI la
    prioriza sobre la sesión de suscripción ya logueada y factura contra la
    API en vez de la suscripción."""

    def test_launch_claude_strips_anthropic_api_key_from_subprocess_env(self):
        with patch.object(caller, "_find_claude_windows", return_value=None), \
             patch.object(caller.platform, "system", return_value="Linux"), \
             patch.object(caller.os, "environ", {
                 "ANTHROPIC_API_KEY": "sk-ant-fake", "PATH": "/usr/bin",
                 "USERPROFILE": str(caller.Path.home()), "HOME": str(caller.Path.home()),
             }), \
             patch("aicli.services.indexer._write_md_atomic"), \
             patch("aicli.services.tickets.save_session_ctx_path"), \
             patch.object(caller.subprocess, "run") as mock_run:
            caller.launch_claude(context="contexto", task="hacer algo")

        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertNotIn("ANTHROPIC_API_KEY", kwargs["env"])
        self.assertIn("PATH", kwargs["env"])


class LaunchClaudeJiraAttachmentsTestCase(unittest.TestCase):
    """Las imágenes de Jira ya no se pre-analizan con la API: launch_claude
    debe escribir la ruta local para que Claude Code las lea con su propia
    tool Read. PDF/CSV/DOCX se pasan igual, sin ningún análisis de MAGNA."""

    def test_jira_images_and_docs_render_local_paths_without_analysis(self):
        captured = {}

        def _fake_write(path, content):
            captured["path"] = path
            captured["content"] = content

        with patch.object(caller, "_find_claude_windows", return_value=None), \
             patch.object(caller.platform, "system", return_value="Linux"), \
             patch("aicli.services.indexer._write_md_atomic", side_effect=_fake_write), \
             patch("aicli.services.tickets.save_session_ctx_path"), \
             patch.object(caller.subprocess, "run"):
            caller.launch_claude(
                context="contexto",
                task="hacer algo",
                ticket_id="PROJ-1",
                jira_data={"id": "PROJ-1", "summary": "resumen", "attachments": []},
                jira_images=[("captura.png", r"C:\evidencias\captura.png")],
                jira_docs=[("informe.pdf", r"C:\evidencias\informe.pdf")],
            )

        content = captured["content"]
        self.assertIn("## Imágenes adjuntas (sin analizar", content)
        self.assertIn(r"- captura.png → C:\evidencias\captura.png", content)
        self.assertIn("## Documentos adjuntos (PDF/CSV/DOCX, sin analizar", content)
        self.assertIn(r"- informe.pdf → C:\evidencias\informe.pdf", content)
        # No debe quedar rastro de la sección vieja de análisis por IA.
        self.assertNotIn("Evidencia adjunta (analizada)", content)

    def test_non_other_excludes_doc_mime_types(self):
        captured = {}

        def _fake_write(path, content):
            captured["content"] = content

        with patch.object(caller, "_find_claude_windows", return_value=None), \
             patch.object(caller.platform, "system", return_value="Linux"), \
             patch("aicli.services.indexer._write_md_atomic", side_effect=_fake_write), \
             patch("aicli.services.tickets.save_session_ctx_path"), \
             patch.object(caller.subprocess, "run"):
            caller.launch_claude(
                context="contexto",
                task="hacer algo",
                ticket_id="PROJ-1",
                jira_data={
                    "id": "PROJ-1",
                    "summary": "resumen",
                    "attachments": [
                        {"filename": "informe.pdf", "mimeType": "application/pdf"},
                        {"filename": "datos.csv", "mimeType": "text/csv"},
                        {"filename": "doc.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
                        {"filename": "raro.zip", "mimeType": "application/zip"},
                    ],
                },
            )

        content = captured["content"]
        self.assertNotIn("informe.pdf (application/pdf)", content)
        self.assertNotIn("datos.csv (text/csv)", content)
        self.assertIn("## Otros adjuntos", content)
        self.assertIn("raro.zip (application/zip)", content)


if __name__ == "__main__":
    unittest.main()
