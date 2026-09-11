"""
Tests unitarios para aicli.services.qa_orchestrator — kill switch, blackboard
(layout + supersede), _parse_agent_json (tolerancia raw_decode) y _git
(deny-list de comandos peligrosos).

Ejecutar: py -m unittest tests/test_qa_orchestrator.py -v

Los tests de blackboard usan MYCONTEXT_HOME apuntando a un tempdir — nunca
tocan ~/.mycontext real. Los tests de _git usan repos git desechables creados
en tempdirs — nunca tocan el repo real de AICLI ni ningún remoto real.
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init"], path)
    _run_git(["config", "user.email", "qa-spike@example.com"], path)
    _run_git(["config", "user.name", "QA Spike"], path)


def _commit_count(path: Path) -> int:
    r = _run_git(["rev-list", "--count", "HEAD"], path)
    if r.returncode != 0:
        return 0
    return int(r.stdout.strip() or 0)


class ParseAgentJsonTestCase(unittest.TestCase):

    def setUp(self):
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator

    # ── 2.4 ─────────────────────────────────────────────────────────────────

    def test_parse_agent_json_plain(self):
        result = self.qa._parse_agent_json('{"status": "pass"}')
        self.assertEqual(result, {"status": "pass"})

    def test_parse_agent_json_fenced(self):
        text = '```json\n{"status": "pass", "checks": []}\n```'
        result = self.qa._parse_agent_json(text)
        self.assertEqual(result, {"status": "pass", "checks": []})

    def test_parse_agent_json_bare_fence(self):
        text = '```\n{"status": "fail"}\n```'
        result = self.qa._parse_agent_json(text)
        self.assertEqual(result, {"status": "fail"})

    def test_parse_agent_json_trailing_noise_tolerated(self):
        # raw_decode debe ignorar texto extra después del JSON (bug real ya
        # encontrado en task.py::_detect_relevant_modules, commit a775146).
        text = '{"status": "pass"}\n\nEspero que esto ayude a resolver el ticket.'
        result = self.qa._parse_agent_json(text)
        self.assertEqual(result, {"status": "pass"})

    def test_parse_agent_json_unparseable_returns_none(self):
        result = self.qa._parse_agent_json("esto no es JSON en absoluto")
        self.assertIsNone(result)

    def test_parse_agent_json_non_object_returns_none(self):
        # Un array top-level no es un objeto de stage válido.
        result = self.qa._parse_agent_json('["pass", "fail"]')
        self.assertIsNone(result)


class BlackboardTestCase(unittest.TestCase):
    """Fase 2 — layout/atomicidad del blackboard, no la mecánica de lanzamiento
    (Fase 3, cubierta por LaunchTestCase). Se mockea subprocess.Popen porque,
    desde esta unidad, trigger_qa() SIEMPRE intenta lanzar el proceso
    detached — estos tests no necesitan (ni deben) spawnear uno real."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        self.base = Path(self._tmp.name)
        popen_patcher = patch(
            "aicli.services.qa_orchestrator.subprocess.Popen",
            return_value=Mock(pid=1234),
        )
        popen_patcher.start()
        self.addCleanup(popen_patcher.stop)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        os.environ.pop("MAGNA_QA", None)
        self._tmp.cleanup()

    # ── 2.1 ─────────────────────────────────────────────────────────────────

    def test_trigger_qa_kill_switch_returns_none(self):
        os.environ["MAGNA_QA"] = "off"
        result = self.qa.trigger_qa(
            ticket_id="PROJ-900", project_path=self.base, files=["a.py"],
        )
        self.assertIsNone(result)
        # ni siquiera debe crear el directorio del blackboard
        self.assertFalse((self.base / "qa_results").exists())

    # ── 2.2 / 2.3 ────────────────────────────────────────────────────────────

    def test_trigger_qa_writes_initial_status_with_schema(self):
        run_id = self.qa.trigger_qa(
            ticket_id="PROJ-901", project_path=self.base, files=["a.py"], branch="fix/PROJ-901",
        )
        self.assertIsNotNone(run_id)

        status_path = self.base / "qa_results" / "PROJ-901" / "status.json"
        self.assertTrue(status_path.exists())
        data = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], self.qa.STATUS_SCHEMA)
        self.assertEqual(data["run_id"], run_id)
        self.assertEqual(data["ticket_id"], "PROJ-901")
        self.assertEqual(data["branch"], "fix/PROJ-901")
        self.assertEqual(data["state"], "pending")
        self.assertEqual(data["attempt"], 0)
        self.assertEqual(data["events"], [])

    def test_trigger_qa_supersede_discards_prior_partial_artifacts(self):
        run_dir = self.base / "qa_results" / "PROJ-902"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "repro.json").write_text('{"schema": "qa.repro/1"}', encoding="utf-8")
        (run_dir / "verify.json").write_text('{"schema": "qa.verify/1"}', encoding="utf-8")

        first_run_id = self.qa.trigger_qa(
            ticket_id="PROJ-902", project_path=self.base, files=["a.py"],
        )
        self.assertFalse((run_dir / "repro.json").exists())
        self.assertFalse((run_dir / "verify.json").exists())

        second_run_id = self.qa.trigger_qa(
            ticket_id="PROJ-902", project_path=self.base, files=["a.py"],
        )
        self.assertNotEqual(first_run_id, second_run_id)

    # ── 2.5 — threat: subprocess/shell (ticket id con caracteres peligrosos) ──

    def test_safe_dir_name_for_ticket_id_with_shell_metacharacters(self):
        malicious = "PROJ-1 & rm -rf /; echo pwned"
        run_dir = self.qa._run_dir(malicious)

        # El nombre final del directorio nunca debe contener espacios ni
        # metacaracteres de shell — tickets._safe_id ya garantiza esto.
        self.assertNotIn(" ", run_dir.name)
        self.assertNotIn("&", run_dir.name)
        self.assertNotIn(";", run_dir.name)
        self.assertRegex(run_dir.name, r"^[A-Z0-9_-]+$")

        # trigger_qa debe poder operar sobre ese ticket sin crear ningún
        # directorio fuera de qa_results/<dir-seguro>.
        run_id = self.qa.trigger_qa(
            ticket_id=malicious, project_path=self.base, files=["a.py"],
        )
        self.assertIsNotNone(run_id)
        self.assertTrue(run_dir.exists())
        self.assertEqual(run_dir.parent, self.base / "qa_results")


class GitDenylistTestCase(unittest.TestCase):
    """Threat matrix: git repository selection, commit state, push state."""

    def setUp(self):
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        _init_repo(self.repo)
        (self.repo / "tracked.py").write_text("original\n", encoding="utf-8")
        _run_git(["add", "tracked.py"], self.repo)
        _run_git(["commit", "-m", "initial"], self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    # ── 2.9 — deny-list coverage ──────────────────────────────────────────────

    def test_git_denylist_full_set_raises(self):
        for cmd in ("push", "fetch", "pull", "remote", "reset", "checkout",
                    "clean", "rebase", "merge", "cherry-pick"):
            with self.assertRaises(ValueError, msg=f"{cmd} debería estar prohibido"):
                self.qa._git([cmd], self.repo)

    def test_git_allowed_commands_still_work(self):
        result = self.qa._git(["status", "--porcelain"], self.repo)
        self.assertEqual(result.returncode, 0)

    # ── 2.6 — threat: push state ──────────────────────────────────────────────

    def test_git_push_denied_before_any_subprocess_call(self):
        with patch("subprocess.run") as mock_run:
            with self.assertRaises(ValueError):
                self.qa._git(["push", "origin", "main"], self.repo)
            mock_run.assert_not_called()

    def test_git_full_cycle_leaves_origin_unchanged(self):
        origin = Path(self._tmp.name) / "origin.git"
        origin.mkdir(parents=True, exist_ok=True)
        _run_git(["init", "--bare"], origin)
        _run_git(["remote", "add", "origin", str(origin)], self.repo)
        # push legítimo inicial para poblar el remoto de referencia
        _run_git(["push", "origin", "HEAD:refs/heads/main"], self.repo)
        before = _run_git(["ls-remote", str(origin)], self.repo).stdout

        (self.repo / "tracked.py").write_text("modified by correction\n", encoding="utf-8")
        self.qa._git(["add", "--", "tracked.py"], self.repo)
        self.qa._git(["commit", "-m", "fix(qa-auto): correccion automatica 1/2 - motivo"], self.repo)

        with self.assertRaises(ValueError):
            self.qa._git(["push", "origin", "main"], self.repo)

        after = _run_git(["ls-remote", str(origin)], self.repo).stdout
        self.assertEqual(before, after)

    # ── 2.7 — threat: commit state ────────────────────────────────────────────

    def test_git_add_scoped_pathspec_leaves_unrelated_file_unstaged(self):
        (self.repo / "tracked.py").write_text("touched by fix\n", encoding="utf-8")
        (self.repo / "unrelated.py").write_text("developer's own uncommitted work\n", encoding="utf-8")

        self.qa._git(["add", "--", "tracked.py"], self.repo)

        status = _run_git(["status", "--porcelain"], self.repo).stdout
        lines = {line[:2].strip(): line[3:] for line in status.splitlines()}
        self.assertIn("tracked.py", status)
        self.assertTrue(any(l.startswith("M") and "tracked.py" in l for l in status.splitlines()))
        unrelated_lines = [l for l in status.splitlines() if "unrelated.py" in l]
        self.assertEqual(len(unrelated_lines), 1)
        self.assertTrue(unrelated_lines[0].startswith("??"))

    def test_git_commit_empty_diff_creates_zero_commits(self):
        before = _commit_count(self.repo)
        # nada tocado, nada staged: commit debe fallar (returncode != 0) y
        # jamás crear un commit nuevo.
        result = self.qa._git(["commit", "-m", "attempt with nothing staged"], self.repo)
        self.assertNotEqual(result.returncode, 0)
        after = _commit_count(self.repo)
        self.assertEqual(before, after)

    # ── 2.8 — threat: git repository selection ────────────────────────────────

    def test_git_operates_only_in_given_cwd_not_other_repo(self):
        decoy = Path(self._tmp.name) / "decoy"
        _init_repo(decoy)
        (decoy / "f.py").write_text("decoy\n", encoding="utf-8")
        _run_git(["add", "f.py"], decoy)
        _run_git(["commit", "-m", "decoy initial"], decoy)
        decoy_before = _commit_count(decoy)
        repo_before = _commit_count(self.repo)

        (self.repo / "tracked.py").write_text("scoped change\n", encoding="utf-8")
        self.qa._git(["add", "--", "tracked.py"], self.repo)
        self.qa._git(["commit", "-m", "fix(qa-auto): correccion automatica 1/2 - motivo"], self.repo)

        self.assertEqual(_commit_count(self.repo), repo_before + 1)
        self.assertEqual(_commit_count(decoy), decoy_before)


class LaunchTestCase(unittest.TestCase):
    """Fase 3 — argv de re-entrada y lanzador Popen detached."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        self.base = Path(self._tmp.name)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        os.environ.pop("MAGNA_QA", None)
        # El test end-to-end real (sin mocks) deja un proceso hijo detached
        # que puede tardar un instante extra en soltar el handle de
        # run.log en Windows incluso después de reportar state="done" —
        # reintenta la limpieza en vez de asumir que el handle ya se liberó.
        for attempt in range(10):
            try:
                self._tmp.cleanup()
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.5)

    # ── 3.1/3.2 — argv de re-entrada (frozen vs. dev) ────────────────────────

    def test_qa_run_argv_dev_mode_reenters_main_py(self):
        argv = self.qa._qa_run_argv("PROJ-1", Path("/some/project"), "run-abc")
        self.assertEqual(argv[0], sys.executable)
        self.assertTrue(argv[1].endswith("main.py"))
        # Las opciones van antes del positional a propósito — ver docstring
        # de _qa_run_argv (evita la ambigüedad de despacho de Click/Typer).
        self.assertEqual(
            argv[2:],
            ["qa-run", "--project-path", str(Path("/some/project")), "--run-id", "run-abc", "PROJ-1"],
        )

    def test_qa_run_argv_frozen_mode_skips_main_py(self):
        with patch.object(sys, "frozen", True, create=True):
            argv = self.qa._qa_run_argv("PROJ-1", Path("/some/project"), "run-abc")
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1], "qa-run")
        self.assertEqual(
            argv[2:],
            ["--project-path", str(Path("/some/project")), "--run-id", "run-abc", "PROJ-1"],
        )

    # ── 3.3 — Popen detached launcher (mockeado) ─────────────────────────────

    def test_trigger_qa_launches_detached_popen_with_expected_kwargs(self):
        fake_proc = Mock(pid=4242)
        with patch("aicli.services.qa_orchestrator.subprocess.Popen", return_value=fake_proc) as mock_popen:
            run_id = self.qa.trigger_qa(
                ticket_id="PROJ-910", project_path=self.base, files=["a.py"],
            )
        self.assertIsNotNone(run_id)
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        argv = args[0]
        self.assertEqual(argv[0], sys.executable)
        self.assertIn("qa-run", argv)
        self.assertIn("PROJ-910", argv)
        self.assertIn(run_id, argv)
        self.assertEqual(kwargs["cwd"], str(self.base))
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
        self.assertTrue(kwargs["close_fds"])
        if sys.platform == "win32":
            expected_flags = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
            self.assertEqual(kwargs["creationflags"], expected_flags)
        else:
            self.assertTrue(kwargs.get("start_new_session"))

        status_path = self.base / "qa_results" / "PROJ-910" / "status.json"
        data = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(data["pid"], 4242)
        self.assertEqual(data["state"], "pending")

        run_log = self.base / "qa_results" / "PROJ-910" / "run.log"
        self.assertTrue(run_log.exists())

    # ── 3.4 — launch failure nunca propaga la excepción ──────────────────────

    def test_trigger_qa_launch_failure_writes_error_status_never_raises(self):
        with patch("aicli.services.qa_orchestrator.subprocess.Popen", side_effect=OSError("boom")):
            run_id = self.qa.trigger_qa(
                ticket_id="PROJ-911", project_path=self.base, files=["a.py"],
            )
        self.assertIsNone(run_id)
        status_path = self.base / "qa_results" / "PROJ-911" / "status.json"
        data = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(data["state"], "error")
        self.assertEqual(data["reason"], "launch_failed")

    # ── 3.3 real — spike S3, extremo a extremo, sin mocks ────────────────────

    def test_trigger_qa_real_process_survives_and_completes(self):
        run_id = self.qa.trigger_qa(
            ticket_id="PROJ-912", project_path=self.base, files=["a.py"],
        )
        self.assertIsNotNone(run_id)
        status_path = self.base / "qa_results" / "PROJ-912" / "status.json"

        deadline = time.time() + 45
        final_state = None
        while time.time() < deadline:
            try:
                data = json.loads(status_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                data = {}
            if data.get("state") == "done":
                final_state = data
                break
            time.sleep(0.3)

        self.assertIsNotNone(final_state, "el proceso detached nunca llegó a state=done")
        self.assertEqual(final_state["run_id"], run_id)
        self.assertIsInstance(final_state["pid"], int)

        run_log = self.base / "qa_results" / "PROJ-912" / "run.log"
        self.assertTrue(run_log.exists())


class QaRunEntrypointTestCase(unittest.TestCase):
    """Fase 3 — comando oculto `qa-run`: heartbeat mínimo + supersede cooperativo."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        import aicli.commands.qa_cmd as qa_cmd
        importlib.reload(qa_cmd)
        self.qa_cmd = qa_cmd
        self.base = Path(self._tmp.name)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def test_qa_run_exits_immediately_on_run_id_mismatch(self):
        run_dir = self.qa._run_dir("PROJ-920")
        status = self.qa._new_status("OLD-RUN", "PROJ-920", str(self.base), None)
        self.qa._write_json_atomic(run_dir / "status.json", status)
        before = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))

        self.qa_cmd.qa_run(ticket_id="PROJ-920", project_path=str(self.base), run_id="NEW-RUN")

        after = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(before, after)

    def test_qa_run_writes_heartbeats_and_finishes_done(self):
        run_dir = self.qa._run_dir("PROJ-921")
        status = self.qa._new_status("R1", "PROJ-921", str(self.base), None)
        self.qa._write_json_atomic(run_dir / "status.json", status)

        self.qa_cmd.qa_run(ticket_id="PROJ-921", project_path=str(self.base), run_id="R1")

        final = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(final["state"], "done")
        self.assertEqual(final["run_id"], "R1")
        self.assertGreater(final["heartbeat"], status["heartbeat"])


if __name__ == "__main__":
    unittest.main()
