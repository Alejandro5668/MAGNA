import unittest
from unittest.mock import patch

from aicli.services import caller


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


if __name__ == "__main__":
    unittest.main()
