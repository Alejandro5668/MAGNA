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
import threading
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
        # Pre-flight de entorno ya confirmado — este spike prueba el
        # lanzamiento detached extremo a extremo, no el gate de env
        # pre-flight (cubierto por EnvPreflightPipelineWiringTestCase);
        # sin esto, el proceso real pausaría en awaiting_input y nunca
        # llegaría a state=done dentro del deadline.
        self.qa.write_env_context(
            self.qa._run_dir("PROJ-912"), db="test_db", url="http://localhost:3000", source="user",
        )
        run_id = self.qa.trigger_qa(
            ticket_id="PROJ-912", project_path=self.base, files=["a.py"],
        )
        self.assertIsNotNone(run_id)
        status_path = self.base / "qa_results" / "PROJ-912" / "status.json"

        # "done" o "awaiting_input" son ambos terminales-para-este-spike: el
        # repro real, sin ticket ni bug report reales, puede legítimamente
        # reportar "blocked" (no tiene nada que reproducir ni acceso a
        # DB/navegador) y pausar por el canal de entorno — lo que este spike
        # prueba es que el proceso detached sobrevive y termina escribiendo
        # ALGÚN estado, no qué verdict de negocio produce el agente real.
        deadline = time.time() + 45
        final_state = None
        while time.time() < deadline:
            try:
                data = json.loads(status_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                data = {}
            if data.get("state") in ("done", "awaiting_input"):
                final_state = data
                break
            time.sleep(0.3)

        self.assertIsNotNone(final_state, "el proceso detached nunca llegó a un estado terminal")
        self.assertEqual(final_state["run_id"], run_id)
        self.assertIsInstance(final_state["pid"], int)

        run_log = self.base / "qa_results" / "PROJ-912" / "run.log"
        self.assertTrue(run_log.exists())


class QaRunEntrypointTestCase(unittest.TestCase):
    """Fase 3 (supersede al arrancar) + Fase 5 (wiring real a qa_runner.run_pipeline)."""

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

    def test_qa_run_delegates_to_run_pipeline_when_run_id_still_current(self):
        # Fase 5: qa_run() ya no maneja stages/heartbeats por sí mismo — le
        # delega toda la orquestación a qa_runner.run_pipeline(). Este test
        # confirma el wiring (args correctos), no la lógica interna del
        # pipeline (cubierta por QaRunnerPipelineTestCase).
        run_dir = self.qa._run_dir("PROJ-921")
        status = self.qa._new_status("R1", "PROJ-921", str(self.base), "fix/PROJ-921")
        self.qa._write_json_atomic(run_dir / "status.json", status)

        with patch.object(self.qa_cmd.qa_runner, "run_pipeline") as mock_pipeline, \
             patch.object(self.qa_cmd.qa_runner, "ticket_history_text", return_value="hist"), \
             patch.object(self.qa_cmd.qa_runner, "latest_touched_files", return_value=["a.py"]):
            self.qa_cmd.qa_run(ticket_id="PROJ-921", project_path=str(self.base), run_id="R1")

        mock_pipeline.assert_called_once()
        _, kwargs = mock_pipeline.call_args
        self.assertEqual(kwargs["ticket_id"], "PROJ-921")
        self.assertEqual(kwargs["run_id"], "R1")
        self.assertEqual(kwargs["run_dir"], run_dir)
        self.assertEqual(kwargs["status_path"], run_dir / "status.json")
        self.assertEqual(kwargs["ticket_history"], "hist")
        self.assertEqual(kwargs["files"], ["a.py"])
        self.assertEqual(kwargs["branch"], "fix/PROJ-921")


class _FakeProc:
    """Doble minimalista de subprocess.Popen para invoke_stage — expone
    `.stdout` (iterable de líneas ya listas), `.wait()` y `.kill()`, sin
    spawnear ningún proceso real."""

    def __init__(self, lines):
        self.stdout = iter(lines)
        self.waited = False
        self.killed = False

    def wait(self):
        self.waited = True

    def kill(self):
        self.killed = True


class _FakeHangingProc:
    """Simula un proceso que imprime una línea y después cuelga (nunca más
    output, nunca termina solo) — usado para probar que invoke_stage lo mata
    y levanta TimeoutExpired en vez de bloquear para siempre."""

    def __init__(self):
        self._kill_event = threading.Event()
        self.killed = False
        self.stdout = self._lines()

    def _lines(self):
        yield "arrancando\n"
        self._kill_event.wait()
        return

    def kill(self):
        self.killed = True
        self._kill_event.set()

    def wait(self):
        pass


class QaPromptsTestCase(unittest.TestCase):
    """Fase 4 — prompts de stage + helper de invocación headless."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        import aicli.services.qa_prompts as qa_prompts
        importlib.reload(qa_prompts)
        self.qp = qa_prompts

    def tearDown(self):
        os.environ.pop("MAGNA_QA_DEFAULT_DB", None)
        os.environ.pop("MAGNA_QA_APP_URL", None)
        self._tmp.cleanup()

    # ── 2.1/2.2 — Requirement: Repro Stage Isolation (updated for env +
    # anti-lookup clause — a rendered-text scan for "diff"/"commit" is
    # defeated by the isolation clause itself, which must NAME them to
    # forbid them; the durable guarantee is structural: no diff/files/commit
    # PARAMETER, never actual diff content in the prompt) ────────────────────

    def test_repro_prompt_signature_has_no_diff_files_commit_parameter(self):
        import inspect
        params = list(inspect.signature(self.qp.build_repro_prompt).parameters)
        self.assertEqual(params, ["run_dir", "ticket_id", "ticket_history", "env"])
        for forbidden in ("diff", "files", "commit", "archivos_tocados", "git_diff"):
            self.assertNotIn(forbidden, params)

    def test_repro_prompt_isolation_clause_present_no_actual_diff_content(self):
        env = {"db": "magna_test", "url": "http://localhost:3000"}
        path = self.qp.build_repro_prompt(self.run_dir, "PROJ-1", "historial de ejemplo", env)
        content = path.read_text(encoding="utf-8")
        self.assertIn("qa.repro/1", content)
        self.assertIn("not_reproduced", content)
        self.assertIn("blocked", content)
        # la clausula de aislamiento NOMBRA los comandos prohibidos —
        # eso es lo que la hace testeable/segura, no un scan de texto.
        self.assertIn("git diff", content)
        self.assertIn("git log", content)
        self.assertIn("git show", content)
        self.assertIn("git blame", content)
        # pero jamás contiene un diff REAL (ningún hunk, ningún fence ```diff)
        self.assertNotIn("```diff", content)
        self.assertNotIn("@@", content)
        self.assertIn("magna_test", content)
        self.assertIn("http://localhost:3000", content)

    def test_repro_prompt_has_no_answer_block_or_default_config_block(self):
        # No gana _answer_block() (podría nombrar el fix) ni
        # _default_config_block() (invita a arqueología del repo) —
        # design.md decision 10.
        answer_path = self.run_dir / "answer.json"
        answer_path.parent.mkdir(parents=True, exist_ok=True)
        answer_path.write_text(json.dumps({"value": "usar staging"}), encoding="utf-8")
        env = {"db": "magna_test", "url": "http://localhost:3000"}

        path = self.qp.build_repro_prompt(self.run_dir, "PROJ-1", "historial", env)

        content = path.read_text(encoding="utf-8").lower()
        self.assertNotIn("ya respondió esto", content)
        self.assertNotIn("configuración por defecto", content)
        # el answer.json NUNCA es consumido por repro — otro stage lo usará
        self.assertTrue(answer_path.exists())

    # ── 4.2 — Requirement: Verify Stage Contract ─────────────────────────────

    def test_verify_prompt_requires_browser_and_read_only_db(self):
        path = self.qp.build_verify_prompt(self.run_dir, "PROJ-1", "historial")
        content = path.read_text(encoding="utf-8").lower()
        self.assertIn("navegador", content)
        self.assertIn("solo lectura", content)
        self.assertIn("qa.verify/1", content)

    # ── 4.3 — Requirement: File Scoping for Corrections ──────────────────────

    def test_corrector_prompt_inlines_checklist_and_scopes_to_touched_files(self):
        path = self.qp.build_corrector_prompt(
            self.run_dir, "PROJ-1", attempt=1, max_attempts=2,
            archivos_tocados=["foo.py", "bar.py"],
            git_diff="- old\n+ new", failure_reason="verify fail: boton roto",
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("checklist de seguridad", content.lower())
        self.assertIn("git push", content)
        self.assertIn("foo.py", content)
        self.assertIn("bar.py", content)
        self.assertIn("intento 1/2", content.lower())
        self.assertNotIn("baz.py", content)

    # ── 4.4 — headless invocation helper ─────────────────────────────────────

    def test_invoke_stage_calls_bare_dash_p_with_no_extra_flags(self):
        prompt_path = self.run_dir / "prompts" / "repro.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text("contenido", encoding="utf-8")

        fake_proc = _FakeProc(['{"status": "reproduced"}'])
        with patch.object(self.qp, "_find_claude_windows", return_value=None), \
             patch.object(self.qp.subprocess, "Popen", return_value=fake_proc) as mock_popen:
            out = self.qp.invoke_stage(
                prompt_path, self.run_dir, run_dir=self.run_dir, stage="repro", timeout=5,
            )

        self.assertEqual(out, '{"status": "reproduced"}')
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        argv = args[0]
        self.assertEqual(argv[0], "claude")
        self.assertEqual(argv[1], "-p")
        self.assertNotIn("--output-format", argv)
        self.assertNotIn("--permission-mode", argv)
        self.assertEqual(kwargs["shell"], False)
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertTrue(fake_proc.waited)

    def test_invoke_stage_strips_anthropic_api_key_from_subprocess_env(self):
        """Si ANTHROPIC_API_KEY está en el entorno (p. ej. .env del proyecto
        para el indexer de MAGNA), claude -p headless la prioriza sobre la
        sesión de suscripción ya logueada y factura contra la API — el
        pipeline de QA nunca debe dejar que eso pase."""
        prompt_path = self.run_dir / "prompts" / "repro.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text("contenido", encoding="utf-8")

        fake_proc = _FakeProc(['{"status": "reproduced"}'])
        with patch.object(self.qp, "_find_claude_windows", return_value=None), \
             patch.object(self.qp.os, "environ", {"ANTHROPIC_API_KEY": "sk-ant-fake", "PATH": "/usr/bin"}), \
             patch.object(self.qp.subprocess, "Popen", return_value=fake_proc) as mock_popen:
            self.qp.invoke_stage(
                prompt_path, self.run_dir, run_dir=self.run_dir, stage="repro", timeout=5,
            )

        _, kwargs = mock_popen.call_args
        self.assertNotIn("ANTHROPIC_API_KEY", kwargs["env"])
        self.assertIn("PATH", kwargs["env"])

    # ── streaming a run_dir/live/<stage>.log — extensión no-SDD ──────────────

    def test_invoke_stage_streams_lines_to_live_log_progressively(self):
        prompt_path = self.run_dir / "prompts" / "verify.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text("contenido", encoding="utf-8")

        lines = ["linea 1\n", "linea 2\n", '{"status": "pass"}\n']
        with patch.object(self.qp, "_find_claude_windows", return_value=None), \
             patch.object(self.qp.subprocess, "Popen", return_value=_FakeProc(lines)):
            out = self.qp.invoke_stage(
                prompt_path, self.run_dir, run_dir=self.run_dir, stage="verify", timeout=5,
            )

        self.assertEqual(out, "".join(lines))
        live_path = self.run_dir / "live" / "verify.log"
        self.assertEqual(live_path.read_text(encoding="utf-8"), "".join(lines))

    def test_invoke_stage_truncates_live_log_on_fresh_call(self):
        prompt_path = self.run_dir / "prompts" / "verify.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text("contenido", encoding="utf-8")

        with patch.object(self.qp, "_find_claude_windows", return_value=None), \
             patch.object(self.qp.subprocess, "Popen", return_value=_FakeProc(["intento viejo y largo\n"])):
            self.qp.invoke_stage(prompt_path, self.run_dir, run_dir=self.run_dir, stage="verify", timeout=5)

        with patch.object(self.qp, "_find_claude_windows", return_value=None), \
             patch.object(self.qp.subprocess, "Popen", return_value=_FakeProc(["nuevo\n"])):
            self.qp.invoke_stage(prompt_path, self.run_dir, run_dir=self.run_dir, stage="verify", timeout=5)

        content = (self.run_dir / "live" / "verify.log").read_text(encoding="utf-8")
        self.assertEqual(content, "nuevo\n")
        self.assertNotIn("viejo", content)

    def test_invoke_stage_timeout_kills_process_and_raises(self):
        prompt_path = self.run_dir / "prompts" / "repro.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text("contenido", encoding="utf-8")

        fake_proc = _FakeHangingProc()
        with patch.object(self.qp, "_find_claude_windows", return_value=None), \
             patch.object(self.qp.subprocess, "Popen", return_value=fake_proc):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.qp.invoke_stage(
                    prompt_path, self.run_dir, run_dir=self.run_dir, stage="repro", timeout=0.05,
                )

        self.assertTrue(fake_proc.killed)

    # ── needs_input escape hatch — extensión no-SDD ──────────────────────────

    def test_verify_prompt_documents_needs_input_and_two_tier_db_rule(self):
        path = self.qp.build_verify_prompt(self.run_dir, "PROJ-1", "historial")
        content = path.read_text(encoding="utf-8").lower()
        self.assertIn("needs_input", content)
        self.assertIn("solo lectura", content)
        self.assertIn("sin excepción", content)
        self.assertIn("libertad total de lectura", content)

    def test_corrector_prompt_documents_needs_input_and_two_tier_db_rule(self):
        path = self.qp.build_corrector_prompt(
            self.run_dir, "PROJ-1", attempt=1, max_attempts=2,
            archivos_tocados=["foo.py"], git_diff="", failure_reason="motivo",
        )
        content = path.read_text(encoding="utf-8").lower()
        self.assertIn("needs_input", content)
        self.assertIn("solo lectura", content)
        self.assertIn("sin excepción", content)
        self.assertIn("libertad total de lectura", content)

    def test_repro_prompt_has_no_needs_input_field(self):
        # repro recibe el DB/URL YA confirmado por env_preflight — nunca
        # necesita preguntar por su cuenta (needs_input es exclusivo de
        # verify/corrector).
        env = {"db": "magna_test", "url": "http://localhost:3000"}
        path = self.qp.build_repro_prompt(self.run_dir, "PROJ-1", "historial", env)
        content = path.read_text(encoding="utf-8")
        self.assertNotIn("needs_input", content)

    def test_verify_prompt_interpolates_configured_default_db_and_url(self):
        os.environ["MAGNA_QA_DEFAULT_DB"] = "postgres://local/test_db"
        os.environ["MAGNA_QA_APP_URL"] = "http://localhost:4000"
        path = self.qp.build_verify_prompt(self.run_dir, "PROJ-1", "historial")
        content = path.read_text(encoding="utf-8")
        self.assertIn("postgres://local/test_db", content)
        self.assertIn("http://localhost:4000", content)

    def test_verify_prompt_shows_unconfigured_placeholder_when_env_unset(self):
        os.environ.pop("MAGNA_QA_DEFAULT_DB", None)
        os.environ.pop("MAGNA_QA_APP_URL", None)
        path = self.qp.build_verify_prompt(self.run_dir, "PROJ-1", "historial")
        content = path.read_text(encoding="utf-8")
        self.assertIn("(no configurada)", content)

    def test_corrector_prompt_interpolates_configured_default_db_and_url(self):
        os.environ["MAGNA_QA_DEFAULT_DB"] = "postgres://local/test_db"
        os.environ["MAGNA_QA_APP_URL"] = "http://localhost:4000"
        path = self.qp.build_corrector_prompt(
            self.run_dir, "PROJ-1", attempt=1, max_attempts=2,
            archivos_tocados=["foo.py"], git_diff="", failure_reason="motivo",
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("postgres://local/test_db", content)
        self.assertIn("http://localhost:4000", content)

    def test_verify_prompt_consumes_and_deletes_answer_file(self):
        answer_path = self.run_dir / "answer.json"
        answer_path.parent.mkdir(parents=True, exist_ok=True)
        answer_path.write_text(json.dumps({"value": "cliente_acme_backup"}), encoding="utf-8")

        path = self.qp.build_verify_prompt(self.run_dir, "PROJ-1", "historial")

        content = path.read_text(encoding="utf-8")
        self.assertIn("cliente_acme_backup", content)
        self.assertIn("ya respondió esto", content.lower())
        self.assertFalse(answer_path.exists())

    def test_corrector_prompt_consumes_and_deletes_answer_file(self):
        answer_path = self.run_dir / "answer.json"
        answer_path.parent.mkdir(parents=True, exist_ok=True)
        answer_path.write_text(json.dumps({"value": "usar staging"}), encoding="utf-8")

        path = self.qp.build_corrector_prompt(
            self.run_dir, "PROJ-1", attempt=1, max_attempts=2,
            archivos_tocados=["foo.py"], git_diff="", failure_reason="motivo",
        )

        content = path.read_text(encoding="utf-8")
        self.assertIn("usar staging", content)
        self.assertIn("ya respondió esto", content.lower())
        self.assertFalse(answer_path.exists())

    def test_verify_prompt_without_answer_file_has_no_answer_mention(self):
        path = self.qp.build_verify_prompt(self.run_dir, "PROJ-1", "historial")
        content = path.read_text(encoding="utf-8").lower()
        self.assertNotIn("ya respondió esto", content)


class QaRunnerStageTestCase(unittest.TestCase):
    """Fase 5.1 — funciones de stage individuales (repro/verify/regression)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.project_path = Path(self._tmp.name) / "project"
        self.project_path.mkdir(parents=True, exist_ok=True)
        os.environ.pop("MAGNA_E2E_REPO", None)
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

    def tearDown(self):
        os.environ.pop("MAGNA_E2E_REPO", None)
        self._tmp.cleanup()

    def test_run_repro_stage_writes_repro_json_from_agent_output(self):
        with patch.object(self.runner.qa_prompts, "invoke_stage", return_value='{"status": "reproduced", "steps": []}'):
            result = self.runner.run_repro_stage(self.run_dir, self.project_path, "PROJ-1", "hist", {"db": "x", "url": "y"})
        self.assertEqual(result["status"], "reproduced")
        data = json.loads((self.run_dir / "repro.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "reproduced")

    def test_run_repro_stage_unparseable_output_is_stage_error(self):
        with patch.object(self.runner.qa_prompts, "invoke_stage", return_value="no es json"):
            result = self.runner.run_repro_stage(self.run_dir, self.project_path, "PROJ-1", "hist", {"db": "x", "url": "y"})
        self.assertEqual(result["status"], "error")
        self.assertTrue((self.run_dir / "raw" / "repro.txt").exists())

    def test_run_verify_stage_writes_verify_json(self):
        with patch.object(self.runner.qa_prompts, "invoke_stage", return_value='{"status": "pass", "checks": []}'):
            result = self.runner.run_verify_stage(self.run_dir, self.project_path, "PROJ-1", "hist")
        self.assertEqual(result["status"], "pass")
        data = json.loads((self.run_dir / "verify.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "pass")

    def test_run_regression_stage_skipped_without_e2e_repo_env(self):
        result = self.runner.run_regression_stage(self.run_dir, self.project_path)
        self.assertEqual(result["status"], "skipped")
        data = json.loads((self.run_dir / "regression.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "skipped")


class QaRunnerCorrectionTestCase(unittest.TestCase):
    """Fase 5.3 — ciclo de corrección: file scoping + branch pre-flight."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.repo = Path(self._tmp.name) / "repo"
        _init_repo(self.repo)
        (self.repo / "tracked.py").write_text("original\n", encoding="utf-8")
        _run_git(["add", "tracked.py"], self.repo)
        _run_git(["commit", "-m", "initial"], self.repo)
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

    def tearDown(self):
        self._tmp.cleanup()

    def test_correction_attempt_aborts_on_branch_mismatch(self):
        _run_git(["checkout", "-b", "some-other-branch"], self.repo)
        result = self.runner.run_correction_attempt(
            run_dir=self.run_dir, project_path=self.repo, ticket_id="PROJ-1",
            attempt=1, archivos_tocados=["tracked.py"],
            failure_reason="motivo", branch="fix/PROJ-1",
        )
        self.assertEqual(result["status"], "aborted")
        self.assertIsNone(result["commit"])
        self.assertEqual(_commit_count(self.repo), 1)

    def test_correction_attempt_commits_only_touched_files(self):
        current_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], self.repo).stdout.strip()
        (self.repo / "tracked.py").write_text("corrected\n", encoding="utf-8")
        (self.repo / "unrelated.py").write_text("developer's own work\n", encoding="utf-8")

        with patch.object(self.runner.qa_prompts, "invoke_stage", return_value='{"status": "applied", "motivo": "boton arreglado"}'):
            result = self.runner.run_correction_attempt(
                run_dir=self.run_dir, project_path=self.repo, ticket_id="PROJ-1",
                attempt=1, archivos_tocados=["tracked.py"],
                failure_reason="boton roto", branch=current_branch,
            )

        self.assertEqual(result["status"], "applied")
        self.assertIn("correccion automatica 1/2", result["commit"])
        self.assertEqual(_commit_count(self.repo), 2)
        status = _run_git(["status", "--porcelain"], self.repo).stdout
        unrelated_lines = [l for l in status.splitlines() if "unrelated.py" in l]
        self.assertEqual(len(unrelated_lines), 1)
        self.assertTrue(unrelated_lines[0].startswith("??"))

    # ── needs_input escape hatch — extensión no-SDD ──────────────────────────

    def test_correction_attempt_needs_input_returns_awaiting_input_without_committing(self):
        current_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], self.repo).stdout.strip()
        before = _commit_count(self.repo)
        question = {"kind": "select", "prompt": "¿Qué base usar?", "options": ["a", "b"]}
        agent_json = json.dumps({"status": "applied", "motivo": "x", "needs_input": question})

        with patch.object(self.runner.qa_prompts, "invoke_stage", return_value=agent_json):
            result = self.runner.run_correction_attempt(
                run_dir=self.run_dir, project_path=self.repo, ticket_id="PROJ-1",
                attempt=1, archivos_tocados=["tracked.py"],
                failure_reason="motivo", branch=current_branch,
            )

        self.assertEqual(result["status"], "awaiting_input")
        self.assertIsNone(result["commit"])
        self.assertEqual(result["needs_input"], question)
        self.assertEqual(_commit_count(self.repo), before)


class QaRunnerPipelineTestCase(unittest.TestCase):
    """Fase 5.1/5.2/5.3 — orquestación completa con stage fns inyectadas."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner
        self.base = Path(self._tmp.name)
        self.run_id = "R1"
        self.run_dir = self.qa._run_dir("PROJ-930")
        status = self.qa._new_status(self.run_id, "PROJ-930", str(self.base), "fix/PROJ-930")
        self.status_path = self.run_dir / "status.json"
        self.qa._write_json_atomic(self.status_path, status)
        # Pre-flight de entorno ya confirmado — esta clase testea la
        # orquestación POST-pre-flight; EnvPreflightPipelineWiringTestCase
        # (más abajo) cubre el gate en sí, sin este seed.
        self.qa.write_env_context(self.run_dir, db="magna_test", url="http://localhost:3000", source="user")

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    # ── 5.4 — RED: not_reproduced never starts correction ────────────────────

    def test_pipeline_not_reproduced_never_starts_correction(self):
        # steps no vacío — distingue de la normalización "sin evidencia de
        # intento" (repro_no_attempt_evidence) que ahora recibe manual_review.
        repro_fn = Mock(return_value={
            "schema": self.qa.REPRO_SCHEMA, "status": "not_reproduced", "steps": ["intenté reproducir"],
        })
        verify_fn = Mock()
        correction_fn = Mock()

        verdict = self.runner.run_pipeline(
            ticket_id="PROJ-930", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=repro_fn, verify_fn=verify_fn,
            regression_fn=Mock(), correction_fn=correction_fn,
        )

        self.assertEqual(verdict["verdict"], "dudoso")
        self.assertFalse(verdict["qa_verified"])
        verify_fn.assert_not_called()
        correction_fn.assert_not_called()

    # ── 5.5 — RED: cap exhausted → manual_review, no 3rd attempt ─────────────

    def test_pipeline_correction_cap_exhausted_reaches_manual_review(self):
        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"})
        verify_fn = Mock(return_value={"schema": self.qa.VERIFY_SCHEMA, "status": "fail", "checks": []})
        regression_fn = Mock(return_value={"schema": self.qa.REGRESSION_SCHEMA, "status": "skipped"})
        correction_fn = Mock(return_value={"status": "applied", "commit": "fix(qa-auto): x"})

        verdict = self.runner.run_pipeline(
            ticket_id="PROJ-930", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=repro_fn, verify_fn=verify_fn,
            regression_fn=regression_fn, correction_fn=correction_fn,
        )

        self.assertEqual(verdict["verdict"], "manual_review")
        self.assertFalse(verdict["qa_verified"])
        self.assertEqual(correction_fn.call_count, self.runner.MAX_CORRECTION_ATTEMPTS)
        self.assertNotIn("blocked", verdict["verdict"])
        self.assertNotIn("reverted", verdict["verdict"])

    # ── sanity: happy path passes without correction ─────────────────────────

    def test_pipeline_verify_pass_regression_skipped_is_passed(self):
        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"})
        verify_fn = Mock(return_value={"schema": self.qa.VERIFY_SCHEMA, "status": "pass", "checks": []})
        regression_fn = Mock(return_value={"schema": self.qa.REGRESSION_SCHEMA, "status": "skipped"})
        correction_fn = Mock()

        verdict = self.runner.run_pipeline(
            ticket_id="PROJ-930", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=repro_fn, verify_fn=verify_fn,
            regression_fn=regression_fn, correction_fn=correction_fn,
        )

        self.assertEqual(verdict["verdict"], "passed")
        self.assertTrue(verdict["qa_verified"])
        correction_fn.assert_not_called()

    # ── supersede: a newer run_id must abort this pipeline mid-flight ────────

    def test_pipeline_aborts_when_superseded_mid_run(self):
        def _supersede_and_reproduce(*args, **kwargs):
            newer = self.qa._new_status("R2", "PROJ-930", str(self.base), "fix/PROJ-930")
            self.qa._write_json_atomic(self.status_path, newer)
            return {"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"}

        verdict = self.runner.run_pipeline(
            ticket_id="PROJ-930", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=_supersede_and_reproduce, verify_fn=Mock(), regression_fn=Mock(),
            correction_fn=Mock(),
        )

        self.assertIsNone(verdict)
        self.assertFalse((self.run_dir / "verdict.json").exists())

    # ── needs_input escape hatch — extensión no-SDD ──────────────────────────

    def test_pipeline_verify_needs_input_writes_awaiting_input_status_not_verdict(self):
        question = {"kind": "text", "prompt": "¿Qué URL usar?", "options": None}
        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"})
        verify_fn = Mock(return_value={
            "schema": self.qa.VERIFY_SCHEMA, "status": "fail", "checks": [], "needs_input": question,
        })
        regression_fn = Mock()
        correction_fn = Mock()

        result = self.runner.run_pipeline(
            ticket_id="PROJ-930", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=repro_fn, verify_fn=verify_fn,
            regression_fn=regression_fn, correction_fn=correction_fn,
        )

        regression_fn.assert_not_called()
        correction_fn.assert_not_called()
        self.assertFalse((self.run_dir / "verdict.json").exists())

        status = json.loads(self.status_path.read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "awaiting_input")
        self.assertEqual(status["question"], question)
        self.assertEqual(result["state"], "awaiting_input")

    def test_pipeline_correction_needs_input_writes_awaiting_input_status(self):
        question = {"kind": "select", "prompt": "¿Qué backup de cliente?", "options": ["acme", "beta"]}
        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"})
        verify_fn = Mock(return_value={"schema": self.qa.VERIFY_SCHEMA, "status": "fail", "checks": []})
        regression_fn = Mock()
        correction_fn = Mock(return_value={"status": "awaiting_input", "commit": None, "needs_input": question})

        result = self.runner.run_pipeline(
            ticket_id="PROJ-930", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=repro_fn, verify_fn=verify_fn,
            regression_fn=regression_fn, correction_fn=correction_fn,
        )

        self.assertFalse((self.run_dir / "verdict.json").exists())
        status = json.loads(self.status_path.read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "awaiting_input")
        self.assertEqual(status["question"], question)
        self.assertEqual(result["state"], "awaiting_input")


class QaStatusSurfaceTestCase(unittest.TestCase):
    """Fase 7 — read_qa_status/read_qa_badge, funciones puras que alimentan el
    badge de TicketPanel._row() y la superficie de estado del TUI. Cobertura
    completa de staleness con reloj congelado queda para la Fase 8 (PR5) —
    esta unidad cubre los estados que Fase 7 consume directamente."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        self.base = Path(self._tmp.name)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def _write_status(self, ticket_id: str, **overrides) -> Path:
        run_dir = self.qa._run_dir(ticket_id)
        status = self.qa._new_status("R1", ticket_id, str(self.base), None)
        status.update(overrides)
        self.qa._write_json_atomic(run_dir / "status.json", status)
        return run_dir

    def test_read_qa_status_returns_none_when_no_run_yet(self):
        self.assertIsNone(self.qa.read_qa_status("PROJ-950"))

    def test_read_qa_badge_none_when_no_run_yet(self):
        self.assertIsNone(self.qa.read_qa_badge("PROJ-950"))

    def test_read_qa_badge_in_progress_for_non_terminal_state(self):
        self._write_status("PROJ-951", state="verify", heartbeat=time.time())
        badge = self.qa.read_qa_badge("PROJ-951")
        self.assertEqual(badge, {"ch": "◔", "col": self.qa._BADGE_ACCENT, "state": "in-progress"})

    def test_read_qa_badge_passed_reads_verdict_json(self):
        run_dir = self._write_status("PROJ-952", state="done")
        self.qa._write_json_atomic(run_dir / "verdict.json", {"verdict": "passed", "qa_verified": True})
        badge = self.qa.read_qa_badge("PROJ-952")
        self.assertEqual(badge, {"ch": "✓", "col": self.qa._BADGE_OK, "state": "passed"})

    def test_read_qa_badge_manual_review(self):
        run_dir = self._write_status("PROJ-953", state="done")
        self.qa._write_json_atomic(run_dir / "verdict.json", {"verdict": "manual_review", "qa_verified": False})
        badge = self.qa.read_qa_badge("PROJ-953")
        self.assertEqual(badge["state"], "manual-review")
        self.assertEqual(badge["ch"], "!")

    def test_read_qa_badge_doubtful(self):
        run_dir = self._write_status("PROJ-954", state="done")
        self.qa._write_json_atomic(run_dir / "verdict.json", {"verdict": "dudoso", "qa_verified": False})
        badge = self.qa.read_qa_badge("PROJ-954")
        self.assertEqual(badge, {"ch": "?", "col": self.qa._BADGE_WARN, "state": "doubtful"})

    def test_read_qa_badge_error_state(self):
        self._write_status("PROJ-955", state="error", reason="launch_failed")
        badge = self.qa.read_qa_badge("PROJ-955")
        self.assertEqual(badge, {"ch": "⚠", "col": self.qa._BADGE_ERROR, "state": "error"})

    def test_read_qa_status_marks_stale_when_heartbeat_old_and_non_terminal(self):
        self._write_status("PROJ-956", state="verify", heartbeat=time.time() - 700)
        status = self.qa.read_qa_status("PROJ-956")
        self.assertTrue(status.get("stale"))

    def test_read_qa_status_not_stale_when_heartbeat_recent(self):
        self._write_status("PROJ-957", state="verify", heartbeat=time.time())
        status = self.qa.read_qa_status("PROJ-957")
        self.assertFalse(status.get("stale", False))

    def test_read_qa_badge_stale_shows_error_badge(self):
        self._write_status("PROJ-958", state="verify", heartbeat=time.time() - 700)
        badge = self.qa.read_qa_badge("PROJ-958")
        self.assertEqual(badge["state"], "error")

    def test_qa_evidence_log_path_matches_run_dir(self):
        run_dir = self.qa._run_dir("PROJ-959")
        self.assertEqual(self.qa.qa_evidence_log_path("PROJ-959"), run_dir / "evidence.log")

    # ── TUI wiring gap fix: awaiting_input debe tener badge propio, nunca
    # caer en "in-progress" (ver brief de esta unidad) ──────────────────────

    def test_read_qa_badge_awaiting_input_is_distinct_from_in_progress(self):
        self._write_status("PROJ-965", state="awaiting_input", heartbeat=time.time())
        badge = self.qa.read_qa_badge("PROJ-965")
        self.assertEqual(badge["state"], "awaiting-input")
        in_progress_badge = {"ch": "◔", "col": self.qa._BADGE_ACCENT, "state": "in-progress"}
        self.assertNotEqual(badge, in_progress_badge)
        # símbolo y color siempre juntos — ninguno de los dos solo
        self.assertIn("ch", badge)
        self.assertIn("col", badge)

    def test_read_qa_status_awaiting_input_never_stale_with_old_heartbeat(self):
        # Esperar al usuario indefinidamente es esperado, no un signo de
        # proceso muerto — el gap que esta unidad corrige.
        self._write_status("PROJ-966", state="awaiting_input", heartbeat=time.time() - 700)
        status = self.qa.read_qa_status("PROJ-966")
        self.assertFalse(status.get("stale", False))

    def test_read_qa_badge_awaiting_input_not_shown_as_error_despite_old_heartbeat(self):
        self._write_status("PROJ-967", state="awaiting_input", heartbeat=time.time() - 700)
        badge = self.qa.read_qa_badge("PROJ-967")
        self.assertEqual(badge["state"], "awaiting-input")


class QaAnswerResumeTestCase(unittest.TestCase):
    """Extensión no-SDD — needs_input: write_qa_answer/resume_qa."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        self.base = Path(self._tmp.name)
        popen_patcher = patch(
            "aicli.services.qa_orchestrator.subprocess.Popen",
            return_value=Mock(pid=4321),
        )
        self.mock_popen = popen_patcher.start()
        self.addCleanup(popen_patcher.stop)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def _write_awaiting_status(self, ticket_id: str, run_id: str = "R1", **overrides) -> Path:
        run_dir = self.qa._run_dir(ticket_id)
        status = self.qa._new_status(run_id, ticket_id, str(self.base), None)
        status["state"] = "awaiting_input"
        status["question"] = {"kind": "text", "prompt": "?", "options": None}
        status.update(overrides)
        self.qa._write_json_atomic(run_dir / "status.json", status)
        return run_dir

    def test_write_qa_answer_writes_value_json(self):
        self.qa.write_qa_answer("PROJ-970", "postgres_local")
        answer_path = self.qa._run_dir("PROJ-970") / "answer.json"
        data = json.loads(answer_path.read_text(encoding="utf-8"))
        self.assertEqual(data, {"value": "postgres_local"})

    def test_resume_qa_noop_when_no_status_at_all(self):
        self.qa.resume_qa("PROJ-971", self.base)
        self.mock_popen.assert_not_called()
        self.assertFalse((self.qa._run_dir("PROJ-971") / "status.json").exists())

    def test_resume_qa_noop_when_not_awaiting_input(self):
        run_dir = self.qa._run_dir("PROJ-972")
        status = self.qa._new_status("R1", "PROJ-972", str(self.base), None)
        status["state"] = "verify"
        self.qa._write_json_atomic(run_dir / "status.json", status)

        self.qa.resume_qa("PROJ-972", self.base)

        self.mock_popen.assert_not_called()
        after = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(after["state"], "verify")

    def test_resume_qa_reuses_same_run_id_and_appends_event(self):
        run_dir = self._write_awaiting_status("PROJ-973", run_id="ORIGINAL-RUN")

        self.qa.resume_qa("PROJ-973", self.base)

        status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["run_id"], "ORIGINAL-RUN")
        self.assertEqual(status["state"], "pending")
        self.assertEqual(len(status["events"]), 1)
        self.assertEqual(status["events"][0]["kind"], "resume")

    def test_resume_qa_appends_to_existing_events_not_replace(self):
        run_dir = self._write_awaiting_status("PROJ-974", events=[
            {"seq": 1, "ts": time.time(), "kind": "correction", "msg": "intento previo"},
        ])

        self.qa.resume_qa("PROJ-974", self.base)

        status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(len(status["events"]), 2)
        self.assertEqual(status["events"][0]["kind"], "correction")
        self.assertEqual(status["events"][1]["kind"], "resume")

    def test_resume_qa_resets_stage_files_but_keeps_answer_json(self):
        run_dir = self._write_awaiting_status("PROJ-975")
        (run_dir / "verify.json").write_text('{"schema": "qa.verify/1"}', encoding="utf-8")
        (run_dir / "verdict.json").write_text('{"schema": "qa.verdict/1"}', encoding="utf-8")
        answer_path = run_dir / "answer.json"
        answer_path.write_text('{"value": "x"}', encoding="utf-8")

        self.qa.resume_qa("PROJ-975", self.base)

        self.assertFalse((run_dir / "verify.json").exists())
        self.assertFalse((run_dir / "verdict.json").exists())
        self.assertTrue(answer_path.exists())

    def test_resume_qa_launches_detached_process_with_reused_run_id(self):
        self._write_awaiting_status("PROJ-976", run_id="ORIGINAL-RUN")

        self.qa.resume_qa("PROJ-976", self.base)

        self.mock_popen.assert_called_once()
        args, _ = self.mock_popen.call_args
        argv = args[0]
        self.assertIn("PROJ-976", argv)
        self.assertIn("ORIGINAL-RUN", argv)


class QaEvidenceLogTestCase(unittest.TestCase):
    """Fase 7 (dependencia de aggregator) — evidence.log legible por humanos,
    consumido por LogScreen. Requirement: Evidence Viewable on Demand."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_evidence_log_produces_human_readable_digest(self):
        repro = {"status": "reproduced", "expected": "boton verde", "actual": "boton rojo"}
        verify = {"status": "pass", "checks": [{"name": "color", "result": "pass", "detail": ""}]}
        regression = {"status": "skipped", "total": 0, "passed": 0, "failed": 0, "failures": []}
        verdict = {
            "verdict": "passed", "qa_verified": True, "reason": "verify_pass_regression_ok",
            "attempts": 0, "commits": [],
        }

        self.runner._write_evidence_log(self.run_dir, repro, verify, regression, verdict)

        content = (self.run_dir / "evidence.log").read_text(encoding="utf-8")
        self.assertIn("passed", content)
        self.assertIn("boton rojo", content)
        self.assertIn("color: pass", content)

    def test_write_evidence_log_lists_correction_commits(self):
        repro = {"status": "reproduced"}
        verify = {"status": "pass", "checks": []}
        regression = {"status": "skipped"}
        verdict = {
            "verdict": "passed", "qa_verified": True, "reason": "verify_pass_regression_ok",
            "attempts": 1, "commits": ["fix(qa-auto): correccion automatica 1/2 - boton"],
        }
        self.runner._write_evidence_log(self.run_dir, repro, verify, regression, verdict)
        content = (self.run_dir / "evidence.log").read_text(encoding="utf-8")
        self.assertIn("fix(qa-auto): correccion automatica 1/2 - boton", content)


class QaPipelineEvidenceIntegrationTestCase(unittest.TestCase):
    """Fase 7 — confirma que run_pipeline (Fase 5) ahora también deja
    evidence.log en cada camino terminal, no solo verdict.json."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner
        self.base = Path(self._tmp.name)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def test_pipeline_writes_evidence_log_on_happy_path(self):
        run_id = "R1"
        run_dir = self.qa._run_dir("PROJ-940")
        status = self.qa._new_status(run_id, "PROJ-940", str(self.base), None)
        status_path = run_dir / "status.json"
        self.qa._write_json_atomic(status_path, status)
        self.qa.write_env_context(run_dir, db="magna_test", url="http://localhost:3000", source="user")

        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"})
        verify_fn = Mock(return_value={"schema": self.qa.VERIFY_SCHEMA, "status": "pass", "checks": []})
        regression_fn = Mock(return_value={"schema": self.qa.REGRESSION_SCHEMA, "status": "skipped"})

        self.runner.run_pipeline(
            ticket_id="PROJ-940", project_path=self.base, run_dir=run_dir,
            run_id=run_id, status_path=status_path,
            repro_fn=repro_fn, verify_fn=verify_fn, regression_fn=regression_fn,
            correction_fn=Mock(),
        )
        self.assertTrue((run_dir / "evidence.log").exists())

    def test_pipeline_writes_evidence_log_on_not_reproduced_early_exit(self):
        run_id = "R2"
        run_dir = self.qa._run_dir("PROJ-941")
        status = self.qa._new_status(run_id, "PROJ-941", str(self.base), None)
        status_path = run_dir / "status.json"
        self.qa._write_json_atomic(status_path, status)
        self.qa.write_env_context(run_dir, db="magna_test", url="http://localhost:3000", source="user")

        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "not_reproduced"})

        self.runner.run_pipeline(
            ticket_id="PROJ-941", project_path=self.base, run_dir=run_dir,
            run_id=run_id, status_path=status_path,
            repro_fn=repro_fn, verify_fn=Mock(), regression_fn=Mock(), correction_fn=Mock(),
        )
        self.assertTrue((run_dir / "evidence.log").exists())


class SyncTriggerTestCase(unittest.TestCase):
    """Fase 6 — el único call site de trigger_qa() en `_sync_impl`, no debe
    bloquear ni propagar excepciones (Requirement: Non-Blocking Trigger)."""

    def test_trigger_qa_guarded_calls_trigger_qa_with_expected_args(self):
        from aicli.commands import sync as sync_mod
        with patch.object(sync_mod, "trigger_qa") as mock_trigger, \
             patch.object(sync_mod, "get_ticket_branch", return_value="fix/PROJ-1"):
            sync_mod._trigger_qa_guarded("PROJ-1", Path("/some/project"), ["a.py"])
        mock_trigger.assert_called_once_with(
            ticket_id="PROJ-1", project_path=Path("/some/project"),
            files=["a.py"], branch="fix/PROJ-1",
        )

    def test_trigger_qa_guarded_never_raises_when_trigger_qa_blows_up(self):
        from aicli.commands import sync as sync_mod
        with patch.object(sync_mod, "trigger_qa", side_effect=RuntimeError("boom")), \
             patch.object(sync_mod, "get_ticket_branch", return_value=None):
            sync_mod._trigger_qa_guarded("PROJ-2", Path("/x"), [])  # no debe lanzar

    def test_sync_impl_calls_guarded_trigger_after_clear_active_ticket(self):
        import inspect
        from aicli.commands import sync as sync_mod
        src = inspect.getsource(sync_mod._sync_impl)
        idx_clear = src.index("clear_active_ticket()")
        idx_trigger = src.index("_trigger_qa_guarded(")
        self.assertGreater(idx_trigger, idx_clear)
        # debe estar dentro del bloque `if save:` — ambas líneas comparten
        # la misma indentación de 12 espacios en el cuerpo de ese bloque.
        self.assertIn("            _trigger_qa_guarded(", src)


class TicketPanelBadgeTestCase(unittest.TestCase):
    """Fase 7.1 — badge symbol+color en _row(); función pura, no requiere
    un App de Textual montado."""

    def setUp(self):
        from aicli.tui.widgets import TicketPanel
        self.panel = TicketPanel()

    def test_row_appends_badge_when_qa_present(self):
        t = {
            "id": "PROJ-1", "summary": "algo", "_rounds": 0, "_active": False,
            "_qa": {"ch": "✓", "col": "#4ADE80", "state": "passed"},
        }
        text = self.panel._row(t)
        self.assertIn("✓", text.plain)

    def test_row_omits_badge_when_qa_absent(self):
        t = {"id": "PROJ-2", "summary": "algo", "_rounds": 0, "_active": False}
        text = self.panel._row(t)
        for ch in ("✓", "✗", "?", "!", "⚠", "◔"):
            self.assertNotIn(ch, text.plain)

    def test_row_badge_symbol_present_never_colour_alone(self):
        t = {
            "id": "PROJ-3", "summary": "algo", "_rounds": 2, "_active": False,
            "_qa": {"ch": "!", "col": "bold #FBBF24", "state": "manual-review"},
        }
        text = self.panel._row(t)
        self.assertIn("!", text.plain)


class QaEventPollingTestCase(unittest.TestCase):
    """Fase 7.2 — traducción de events[] no vistos a notificaciones; función
    pura (`_unseen_events`) extraída de `_poll_qa` para ser testeable sin un
    App de Textual montado."""

    def test_unseen_events_returns_only_higher_seq_in_order(self):
        from aicli.tui.widgets import _unseen_events
        events = [{"seq": 1, "msg": "a"}, {"seq": 3, "msg": "c"}, {"seq": 2, "msg": "b"}]
        result = _unseen_events(events, last_seen_seq=1)
        self.assertEqual([e["seq"] for e in result], [2, 3])

    def test_unseen_events_empty_when_all_seen(self):
        from aicli.tui.widgets import _unseen_events
        events = [{"seq": 1, "msg": "a"}]
        self.assertEqual(_unseen_events(events, last_seen_seq=5), [])

    def test_unseen_events_empty_list_input(self):
        from aicli.tui.widgets import _unseen_events
        self.assertEqual(_unseen_events([], last_seen_seq=0), [])


class QuestionModalKindTestCase(unittest.TestCase):
    """QA TUI wiring — `_question_modal_kind` traduce el `question` de un
    awaiting_input al tipo de modal a mostrar. Función pura, sin Textual."""

    def test_select_with_options_maps_to_select(self):
        from aicli.tui.widgets import _question_modal_kind
        question = {"kind": "select", "prompt": "?", "options": ["a", "b"]}
        self.assertEqual(_question_modal_kind(question), "select")

    def test_select_without_options_falls_back_to_text(self):
        # kind:"select" sin opciones no alcanza para mostrar un OptionList —
        # cae a InputModal en vez de romper con una lista vacia.
        from aicli.tui.widgets import _question_modal_kind
        question = {"kind": "select", "prompt": "?", "options": []}
        self.assertEqual(_question_modal_kind(question), "text")

    def test_text_kind_maps_to_text(self):
        from aicli.tui.widgets import _question_modal_kind
        question = {"kind": "text", "prompt": "?", "options": None}
        self.assertEqual(_question_modal_kind(question), "text")

    def test_unknown_or_missing_kind_falls_back_to_text(self):
        from aicli.tui.widgets import _question_modal_kind
        self.assertEqual(_question_modal_kind({}), "text")
        self.assertEqual(_question_modal_kind({"kind": "unknown"}), "text")


class QaAnswerRoundTripTestCase(unittest.TestCase):
    """QA TUI wiring — `TicketPanel._on_qa_answer` (callback del modal de
    awaiting_input): con valor persiste + reanuda, sin valor es un no-op.
    No requiere un App montado — `_on_qa_answer` no toca self.app en la rama
    sin valor, y en la rama con valor solo llama a funciones de servicio
    (mockeadas aquí)."""

    def test_on_qa_answer_with_value_writes_answer_and_resumes(self):
        from aicli.tui.widgets import TicketPanel
        panel = TicketPanel()
        panel._qa_awaiting.add("PROJ-1")

        with patch("aicli.services.qa_orchestrator.write_qa_answer") as mock_write, \
             patch("aicli.services.qa_orchestrator.resume_qa") as mock_resume:
            panel._on_qa_answer("PROJ-1", "postgres_local")

        mock_write.assert_called_once_with("PROJ-1", "postgres_local")
        mock_resume.assert_called_once()
        self.assertEqual(mock_resume.call_args.args[0], "PROJ-1")
        self.assertNotIn("PROJ-1", panel._qa_awaiting)

    def test_on_qa_answer_cancelled_is_noop_and_clears_guard(self):
        from aicli.tui.widgets import TicketPanel
        panel = TicketPanel()
        panel._qa_awaiting.add("PROJ-2")

        with patch("aicli.services.qa_orchestrator.write_qa_answer") as mock_write, \
             patch("aicli.services.qa_orchestrator.resume_qa") as mock_resume:
            panel._on_qa_answer("PROJ-2", None)

        mock_write.assert_not_called()
        mock_resume.assert_not_called()
        self.assertNotIn("PROJ-2", panel._qa_awaiting)

    def test_on_qa_answer_empty_string_is_treated_as_no_answer(self):
        from aicli.tui.widgets import TicketPanel
        panel = TicketPanel()
        panel._qa_awaiting.add("PROJ-3")

        with patch("aicli.services.qa_orchestrator.write_qa_answer") as mock_write:
            panel._on_qa_answer("PROJ-3", "")

        mock_write.assert_not_called()
        self.assertNotIn("PROJ-3", panel._qa_awaiting)


class QaAwaitingInputModalGuardTestCase(unittest.IsolatedAsyncioTestCase):
    """QA TUI wiring — guard obligatorio contra apilar modales: si
    `_poll_qa` corre de nuevo mientras el modal de un ticket sigue abierto
    (usuario todavía no respondió), NO debe pushear un segundo modal encima.
    Mismo harness Textual real (`App.run_test()`) que
    QaNotifyMechanismRuntimeIntegrationTestCase ya usa más arriba en este
    archivo — hay precedente establecido, así que se reusa en vez de testear
    solo con mocks de `self.app`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        self.base = Path(self._tmp.name)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def _write_awaiting_status(self, ticket_id: str, **question_overrides) -> None:
        run_dir = self.qa._run_dir(ticket_id)
        status = self.qa._new_status("R1", ticket_id, str(self.base), None)
        status["state"] = "awaiting_input"
        status["question"] = {"kind": "text", "prompt": "Necesito la URL de la BD", "options": None}
        status["question"].update(question_overrides)
        self.qa._write_json_atomic(run_dir / "status.json", status)

    async def test_second_poll_while_modal_open_does_not_stack_another(self):
        from textual.app import App, ComposeResult
        from aicli.tui.widgets import TicketPanel

        self._write_awaiting_status("PROJ-1")

        class _PollHarnessApp(App):
            def compose(self) -> ComposeResult:
                yield TicketPanel()

        app = _PollHarnessApp()
        async with app.run_test() as pilot:
            panel = app.query_one(TicketPanel)
            panel._tickets = [{"id": "PROJ-1", "summary": "x", "_rounds": 0, "_active": False}]

            panel._poll_qa()
            await pilot.pause()
            self.assertEqual(len(app.screen_stack), 2)  # MainScreen-equivalent + InputModal
            self.assertIn("PROJ-1", panel._qa_awaiting)

            # segundo poll: el ticket sigue awaiting_input y el modal sigue
            # abierto (in-flight) — NO debe pushear un segundo modal encima.
            panel._poll_qa()
            await pilot.pause()
            self.assertEqual(len(app.screen_stack), 2)

    async def test_select_question_opens_select_modal(self):
        from textual.app import App, ComposeResult
        from aicli.tui.widgets import TicketPanel
        from aicli.tui.modals import SelectModal

        self._write_awaiting_status("PROJ-2", kind="select", options=["a", "b"])

        class _PollHarnessApp(App):
            def compose(self) -> ComposeResult:
                yield TicketPanel()

        app = _PollHarnessApp()
        async with app.run_test() as pilot:
            panel = app.query_one(TicketPanel)
            panel._tickets = [{"id": "PROJ-2", "summary": "x", "_rounds": 0, "_active": False}]

            panel._poll_qa()
            await pilot.pause()
            self.assertIsInstance(app.screen, SelectModal)

    async def test_text_question_opens_input_modal(self):
        from textual.app import App, ComposeResult
        from aicli.tui.widgets import TicketPanel
        from aicli.tui.modals import InputModal

        self._write_awaiting_status("PROJ-3")

        class _PollHarnessApp(App):
            def compose(self) -> ComposeResult:
                yield TicketPanel()

        app = _PollHarnessApp()
        async with app.run_test() as pilot:
            panel = app.query_one(TicketPanel)
            panel._tickets = [{"id": "PROJ-3", "summary": "x", "_rounds": 0, "_active": False}]

            panel._poll_qa()
            await pilot.pause()
            self.assertIsInstance(app.screen, InputModal)

    async def test_dismissing_modal_clears_guard_allowing_a_future_reprompt(self):
        from textual.app import App, ComposeResult
        from aicli.tui.widgets import TicketPanel

        self._write_awaiting_status("PROJ-4")

        class _PollHarnessApp(App):
            def compose(self) -> ComposeResult:
                yield TicketPanel()

        app = _PollHarnessApp()
        async with app.run_test() as pilot:
            panel = app.query_one(TicketPanel)
            panel._tickets = [{"id": "PROJ-4", "summary": "x", "_rounds": 0, "_active": False}]

            panel._poll_qa()
            await app.workers.wait_for_complete()
            self.assertIn("PROJ-4", panel._qa_awaiting)

            await pilot.press("escape")  # cancela el InputModal
            await pilot.pause()
            self.assertNotIn("PROJ-4", panel._qa_awaiting)


class QaStageChecklistTestCase(unittest.TestCase):
    """QaDetailScreen — `qa_stage_checklist`/`_derive_stage_state`: derivan
    el estado de cada stage a partir de status.json + los *.json de stage ya
    leídos por el llamador. Puras — dicts armados a mano, sin tempdirs."""

    def test_pending_stage_not_reached_yet(self):
        from aicli.tui.screens import qa_stage_checklist
        status = {"state": "repro", "stage": "repro"}
        checklist = qa_stage_checklist(status, repro=None, verify=None, regression=None, verdict=None)
        by_name = {c["name"]: c for c in checklist}
        self.assertEqual(by_name["verify"]["state"], "pending")
        self.assertEqual(by_name["verify"]["ch"], "·")

    def test_running_stage_matches_current_status_stage(self):
        from aicli.tui.screens import qa_stage_checklist
        status = {"state": "verify", "stage": "verify"}
        checklist = qa_stage_checklist(status, repro={"status": "reproduced"}, verify=None,
                                        regression=None, verdict=None)
        by_name = {c["name"]: c for c in checklist}
        self.assertEqual(by_name["repro"]["state"], "done-pass")
        self.assertEqual(by_name["verify"]["state"], "running")

    def test_repro_not_reproduced_is_done_fail(self):
        from aicli.tui.screens import qa_stage_checklist
        status = {"state": "done", "stage": "verdict"}
        checklist = qa_stage_checklist(
            status, repro={"status": "not_reproduced"}, verify=None, regression=None,
            verdict={"verdict": "dudoso", "attempts": 0},
        )
        by_name = {c["name"]: c for c in checklist}
        self.assertEqual(by_name["repro"]["state"], "done-fail")

    def test_verify_pass_is_done_pass(self):
        from aicli.tui.screens import qa_stage_checklist
        status = {"state": "done", "stage": "verdict"}
        checklist = qa_stage_checklist(
            status, repro={"status": "reproduced"}, verify={"status": "pass"},
            regression={"status": "skipped"}, verdict={"verdict": "passed", "attempts": 0},
        )
        by_name = {c["name"]: c for c in checklist}
        self.assertEqual(by_name["verify"]["state"], "done-pass")
        self.assertEqual(by_name["regression"]["state"], "done-pass")  # skipped cuenta como ok

    def test_verify_fail_is_done_fail(self):
        from aicli.tui.screens import qa_stage_checklist
        status = {"state": "correcting", "stage": "correction_1"}
        checklist = qa_stage_checklist(
            status, repro={"status": "reproduced"}, verify={"status": "fail"},
            regression=None, verdict=None,
        )
        by_name = {c["name"]: c for c in checklist}
        self.assertEqual(by_name["verify"]["state"], "done-fail")

    def test_corrector_pending_when_never_needed(self):
        from aicli.tui.screens import qa_stage_checklist
        status = {"state": "done", "stage": "verdict"}
        checklist = qa_stage_checklist(
            status, repro={"status": "reproduced"}, verify={"status": "pass"},
            regression={"status": "pass"}, verdict={"verdict": "passed", "attempts": 0},
        )
        by_name = {c["name"]: c for c in checklist}
        self.assertEqual(by_name["corrector"]["state"], "pending")

    def test_corrector_running_during_correction_attempt(self):
        from aicli.tui.screens import qa_stage_checklist
        status = {"state": "correcting", "stage": "correction_1"}
        checklist = qa_stage_checklist(status, repro={"status": "reproduced"}, verify={"status": "fail"},
                                        regression=None, verdict=None)
        by_name = {c["name"]: c for c in checklist}
        self.assertEqual(by_name["corrector"]["state"], "running")

    def test_corrector_done_pass_after_applied_commit(self):
        from aicli.tui.screens import qa_stage_checklist
        status = {"state": "done", "stage": "verdict"}
        verdict = {"verdict": "passed", "attempts": 1, "reason": "verify_pass_regression_ok"}
        checklist = qa_stage_checklist(status, repro={"status": "reproduced"}, verify={"status": "pass"},
                                        regression={"status": "pass"}, verdict=verdict)
        by_name = {c["name"]: c for c in checklist}
        self.assertEqual(by_name["corrector"]["state"], "done-pass")

    def test_corrector_done_fail_when_aborted(self):
        from aicli.tui.screens import qa_stage_checklist
        status = {"state": "error", "stage": "verdict"}
        verdict = {"verdict": "manual_review", "attempts": 1, "reason": "branch_mismatch_or_detached"}
        checklist = qa_stage_checklist(status, repro={"status": "reproduced"}, verify={"status": "fail"},
                                        regression=None, verdict=verdict)
        by_name = {c["name"]: c for c in checklist}
        self.assertEqual(by_name["corrector"]["state"], "done-fail")


class QaLiveStageTestCase(unittest.TestCase):
    """QaDetailScreen — `qa_live_stage`: qué stage tailear en vivo, y cuándo
    dejar de tratarlo como "en vivo". Pura — mismo estilo que
    QaStageChecklistTestCase, dicts armados a mano, sin tempdirs ni I/O."""

    def test_no_active_stage_returns_none(self):
        from aicli.tui.screens import qa_live_stage
        status = {"state": "pending", "stage": None}
        self.assertIsNone(qa_live_stage(status, repro=None, verify=None, regression=None))

    def test_repro_running_without_artifact_is_live(self):
        from aicli.tui.screens import qa_live_stage
        status = {"state": "repro", "stage": "repro"}
        self.assertEqual(
            qa_live_stage(status, repro=None, verify=None, regression=None), "repro",
        )

    def test_repro_stops_being_live_once_its_json_result_exists(self):
        from aicli.tui.screens import qa_live_stage
        status = {"state": "repro", "stage": "repro"}
        self.assertIsNone(
            qa_live_stage(status, repro={"status": "reproduced"}, verify=None, regression=None),
        )

    def test_verify_running_without_artifact_is_live(self):
        from aicli.tui.screens import qa_live_stage
        status = {"state": "verify", "stage": "verify"}
        result = qa_live_stage(status, repro={"status": "reproduced"}, verify=None, regression=None)
        self.assertEqual(result, "verify")

    def test_verify_stops_being_live_once_verify_json_exists(self):
        from aicli.tui.screens import qa_live_stage
        status = {"state": "verify", "stage": "verify"}
        result = qa_live_stage(
            status, repro={"status": "reproduced"}, verify={"status": "pass"}, regression=None,
        )
        self.assertIsNone(result)

    def test_corrector_attempt_is_live_since_it_has_no_own_json_artifact(self):
        from aicli.tui.screens import qa_live_stage
        status = {"state": "correcting", "stage": "correction_1"}
        result = qa_live_stage(
            status, repro={"status": "reproduced"}, verify={"status": "fail"}, regression=None,
        )
        self.assertEqual(result, "correction_1")

    def test_corrector_stops_being_live_once_pipeline_moves_past_it(self):
        # Tras un intento de corrección, el pipeline reintenta verify — el
        # `stage` activo ya cambió, así que el log de la corrección anterior
        # deja de tailearse (aunque nunca tuvo JSON propio).
        from aicli.tui.screens import qa_live_stage
        status = {"state": "verify", "stage": "verify"}
        result = qa_live_stage(
            status, repro={"status": "reproduced"}, verify=None, regression=None,
        )
        self.assertEqual(result, "verify")

    def test_terminal_state_never_reports_a_live_stage(self):
        from aicli.tui.screens import qa_live_stage
        status = {"state": "done", "stage": "verdict"}
        self.assertIsNone(qa_live_stage(status, repro=None, verify=None, regression=None))

        status = {"state": "error", "stage": "verify"}
        self.assertIsNone(qa_live_stage(status, repro=None, verify=None, regression=None))


class QaDetailScreenLiveTailIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    """QaDetailScreen — confirma que la pantalla realmente renderiza el tail
    del log en vivo del stage activo (no solo que la lógica pura lo elige
    bien). Mismo harness Textual real (`App.run_test()`) que
    QaAwaitingInputModalGuardTestCase, usado acá solo porque hace falta un
    render real — la selección del stage en sí ya está cubierta por
    QaLiveStageTestCase sin montar nada."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    async def test_renders_live_tail_for_currently_running_stage(self):
        from textual.app import App, ComposeResult
        from aicli.tui.screens import QaDetailScreen

        ticket_id = "PROJ-LIVE-1"
        run_dir = self.qa._run_dir(ticket_id)
        status = self.qa._new_status("R1", ticket_id, str(Path(self._tmp.name)), None)
        status["state"] = "verify"
        status["stage"] = "verify"
        self.qa._write_json_atomic(run_dir / "status.json", status)
        live_dir = run_dir / "live"
        live_dir.mkdir(parents=True, exist_ok=True)
        (live_dir / "verify.log").write_text(
            "navegando a /login\nclick en boton\n", encoding="utf-8",
        )

        class _Harness(App):
            def compose(self) -> ComposeResult:
                return iter(())

        app = _Harness()
        async with app.run_test() as pilot:
            await app.push_screen(QaDetailScreen(ticket_id))
            await pilot.pause()
            log = app.screen.query_one("#qd-events")
            rendered = "\n".join(strip.text for strip in log.lines)
            self.assertIn("en vivo: verify", rendered)
            self.assertIn("navegando a /login", rendered)
            self.assertIn("click en boton", rendered)

    async def test_no_live_tail_section_once_stage_has_finished(self):
        from textual.app import App, ComposeResult
        from aicli.tui.screens import QaDetailScreen

        ticket_id = "PROJ-LIVE-2"
        run_dir = self.qa._run_dir(ticket_id)
        status = self.qa._new_status("R1", ticket_id, str(Path(self._tmp.name)), None)
        status["state"] = "done"
        status["stage"] = "verdict"
        self.qa._write_json_atomic(run_dir / "status.json", status)
        self.qa._write_json_atomic(run_dir / "verify.json", {"status": "pass", "checks": []})
        live_dir = run_dir / "live"
        live_dir.mkdir(parents=True, exist_ok=True)
        (live_dir / "verify.log").write_text("esto ya es historia\n", encoding="utf-8")

        class _Harness(App):
            def compose(self) -> ComposeResult:
                return iter(())

        app = _Harness()
        async with app.run_test() as pilot:
            await app.push_screen(QaDetailScreen(ticket_id))
            await pilot.pause()
            log = app.screen.query_one("#qd-events")
            rendered = "\n".join(strip.text for strip in log.lines)
            self.assertNotIn("en vivo", rendered)
            self.assertNotIn("esto ya es historia", rendered)


class LogScreenTestCase(unittest.TestCase):
    """Fase 7.4 — LogScreen(log_path=None, title=...) keyword-defaulted; el
    call site existente (screens.py, SettingsScreen) sigue funcionando con
    los valores por defecto."""

    def test_log_screen_defaults_match_prior_hardcoded_call_site(self):
        from aicli.tui.screens import LogScreen
        from textual.widgets import Static
        screen = LogScreen()
        widgets = list(screen.compose())
        header = next(w for w in widgets if isinstance(w, Static))
        self.assertIn("magna.log", str(header.render()))
        self.assertIn("MAGNA — Logs", str(header.render()))

    def test_log_screen_accepts_custom_log_path_and_title(self):
        from aicli.tui.screens import LogScreen
        from textual.widgets import Static, TextArea
        tmp = tempfile.TemporaryDirectory()
        try:
            log_path = Path(tmp.name) / "evidence.log"
            log_path.write_text("contenido de evidencia QA", encoding="utf-8")
            screen = LogScreen(log_path=log_path, title="QA — PROJ-1")
            widgets = list(screen.compose())
            header = next(w for w in widgets if isinstance(w, Static))
            self.assertIn("QA — PROJ-1", str(header.render()))
            text_area = next(w for w in widgets if isinstance(w, TextArea))
            self.assertIn("contenido de evidencia QA", text_area.text)
        finally:
            tmp.cleanup()

    def test_log_screen_missing_log_path_shows_placeholder(self):
        from aicli.tui.screens import LogScreen
        from textual.widgets import TextArea
        tmp = tempfile.TemporaryDirectory()
        try:
            missing = Path(tmp.name) / "nope.log"
            screen = LogScreen(log_path=missing, title="QA — PROJ-2")
            widgets = list(screen.compose())
            text_area = next(w for w in widgets if isinstance(w, TextArea))
            self.assertIn("sin logs", text_area.text)
        finally:
            tmp.cleanup()


class AggregateTruthTableTestCase(unittest.TestCase):
    """Fase 8.1 — tabla de verdad completa de `qa_runner.aggregate()`,
    incluyendo los caminos de stage error (que es exactamente donde un
    timeout normalizado por `_stage_timeout_result` termina — ver
    QaRunnerStageTimeoutTestCase más abajo, design.md: 'Any stage error/
    timeout ⇒ error'). Las unidades 1-4 solo cubrieron pass/dudoso/manual_
    review como efecto colateral de sus RED tests de pipeline (5.4/5.5); esta
    clase testea `aggregate()` directamente, combinacion por combinacion."""

    def setUp(self):
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

    @staticmethod
    def _stage(schema: str, status):
        return {"schema": schema, "status": status}

    def _repro(self, status):
        return self._stage("qa.repro/1", status)

    def _verify(self, status):
        return self._stage("qa.verify/1", status)

    def _regression(self, status):
        return self._stage("qa.regression/1", status)

    def test_repro_not_reproduced_is_dudoso_regardless_of_other_stages(self):
        repro = {**self._repro("not_reproduced"), "steps": ["intenté reproducir el bug"]}
        verdict = self.runner.aggregate(
            repro=repro, verify=self._verify("pass"),
            regression=self._regression("pass"), attempts=0, commits=[],
        )
        self.assertEqual(verdict["verdict"], "dudoso")
        self.assertFalse(verdict["qa_verified"])
        self.assertEqual(verdict["reason"], "repro_not_reproduced")

    # ── qa-pipeline-verification-gaps 2.3/3.16 — nuevas ramas de la tabla ────

    def test_not_reproduced_with_empty_steps_is_manual_review_no_attempt_evidence(self):
        verdict = self.runner.aggregate(
            repro=self._repro("not_reproduced"), verify=self._verify(None),
            regression=self._regression(None), attempts=0, commits=[],
        )
        self.assertEqual(verdict["verdict"], "manual_review")
        self.assertFalse(verdict["qa_verified"])
        self.assertEqual(verdict["reason"], "repro_no_attempt_evidence")

    def test_repro_blocked_is_manual_review(self):
        verdict = self.runner.aggregate(
            repro={**self._repro("blocked"), "blocked_reason": "DB inalcanzable"},
            verify=self._verify(None), regression=self._regression(None), attempts=0, commits=[],
        )
        self.assertEqual(verdict["verdict"], "manual_review")
        self.assertFalse(verdict["qa_verified"])
        self.assertEqual(verdict["reason"], "repro_blocked")

    def test_aggregate_without_review_kwarg_behaves_exactly_as_before(self):
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("pass"),
            regression=self._regression("skipped"), attempts=0, commits=[],
        )
        self.assertEqual(verdict["verdict"], "passed")
        self.assertTrue(verdict["qa_verified"])

    def test_repro_error_is_error(self):
        verdict = self.runner.aggregate(
            repro=self._repro("error"), verify=self._verify(None),
            regression=self._regression(None), attempts=0, commits=[],
        )
        self.assertEqual(verdict["verdict"], "error")
        self.assertFalse(verdict["qa_verified"])
        self.assertEqual(verdict["reason"], "repro_stage_error")

    def test_verify_error_is_error(self):
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("error"),
            regression=self._regression(None), attempts=0, commits=[],
        )
        self.assertEqual(verdict["verdict"], "error")
        self.assertFalse(verdict["qa_verified"])
        self.assertEqual(verdict["reason"], "stage_error")

    def test_regression_error_is_error_even_if_verify_passes(self):
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("pass"),
            regression=self._regression("error"), attempts=0, commits=[],
        )
        self.assertEqual(verdict["verdict"], "error")
        self.assertFalse(verdict["qa_verified"])

    def test_verify_pass_regression_pass_is_passed(self):
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("pass"),
            regression=self._regression("pass"), attempts=0, commits=[],
        )
        self.assertEqual(verdict["verdict"], "passed")
        self.assertTrue(verdict["qa_verified"])

    def test_verify_pass_regression_skipped_is_passed(self):
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("pass"),
            regression=self._regression("skipped"), attempts=0, commits=[],
        )
        self.assertEqual(verdict["verdict"], "passed")
        self.assertTrue(verdict["qa_verified"])

    def test_verify_pass_regression_fail_below_cap_is_failed_not_passed(self):
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("pass"),
            regression=self._regression("fail"), attempts=0, commits=[],
        )
        self.assertEqual(verdict["verdict"], "failed")
        self.assertFalse(verdict["qa_verified"])

    def test_verify_pass_regression_fail_at_cap_is_manual_review(self):
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("pass"),
            regression=self._regression("fail"), attempts=self.runner.MAX_CORRECTION_ATTEMPTS, commits=[],
        )
        self.assertEqual(verdict["verdict"], "manual_review")
        self.assertFalse(verdict["qa_verified"])

    def test_verify_fail_below_cap_is_failed(self):
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("fail"),
            regression=self._regression(None), attempts=self.runner.MAX_CORRECTION_ATTEMPTS - 1, commits=[],
        )
        self.assertEqual(verdict["verdict"], "failed")
        self.assertFalse(verdict["qa_verified"])

    def test_verify_fail_at_cap_is_manual_review(self):
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("fail"),
            regression=self._regression(None), attempts=self.runner.MAX_CORRECTION_ATTEMPTS, commits=[],
        )
        self.assertEqual(verdict["verdict"], "manual_review")
        self.assertFalse(verdict["qa_verified"])

    def test_verdict_stages_dict_reflects_each_stage_status(self):
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("pass"),
            regression=self._regression("skipped"), attempts=0, commits=[],
        )
        self.assertEqual(
            verdict["stages"],
            {"repro": "reproduced", "verify": "pass", "regression": "skipped", "review": None},
        )

    def test_verdict_stages_dict_includes_review_status_when_review_ran(self):
        review = {"schema": self.runner.REVIEW_SCHEMA, "status": "ok", "security": {"findings": []}}
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("pass"),
            regression=self._regression("skipped"), attempts=0, commits=[], review=review,
        )
        self.assertEqual(verdict["stages"]["review"], "ok")

    def test_verdict_carries_attempts_and_commits_through(self):
        commits = ["fix(qa-auto): correccion automatica 1/2 - x"]
        verdict = self.runner.aggregate(
            repro=self._repro("reproduced"), verify=self._verify("pass"),
            regression=self._regression("skipped"), attempts=1, commits=commits,
        )
        self.assertEqual(verdict["attempts"], 1)
        self.assertEqual(verdict["commits"], commits)


class QaRunnerStageTimeoutTestCase(unittest.TestCase):
    """Fase 8.1 (extension) — un `subprocess.TimeoutExpired` durante repro o
    verify nunca debe propagar y tumbar el pipeline: design.md dice
    explicitamente 'Any stage error/timeout ⇒ error'. Se normaliza al mismo
    status:"error" que ya usa el parseo JSON inválido, ANTES de llegar al
    agregador — así los tests de AggregateTruthTableTestCase de arriba ya
    cubren el destino final de un timeout sin necesitar un status "timeout"
    literal en el esquema."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.project_path = Path(self._tmp.name) / "project"
        self.project_path.mkdir(parents=True, exist_ok=True)
        os.environ.pop("MAGNA_E2E_REPO", None)
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

    def tearDown(self):
        os.environ.pop("MAGNA_E2E_REPO", None)
        self._tmp.cleanup()

    def test_run_repro_stage_timeout_is_stage_error_never_raises(self):
        timeout_exc = subprocess.TimeoutExpired(cmd=["claude", "-p", "..."], timeout=600)
        with patch.object(self.runner.qa_prompts, "invoke_stage", side_effect=timeout_exc):
            result = self.runner.run_repro_stage(self.run_dir, self.project_path, "PROJ-1", "hist", {"db": "x", "url": "y"})
        self.assertEqual(result["status"], "error")
        data = json.loads((self.run_dir / "repro.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "error")

    def test_run_verify_stage_timeout_is_stage_error_never_raises(self):
        timeout_exc = subprocess.TimeoutExpired(cmd=["claude", "-p", "..."], timeout=600)
        with patch.object(self.runner.qa_prompts, "invoke_stage", side_effect=timeout_exc):
            result = self.runner.run_verify_stage(self.run_dir, self.project_path, "PROJ-1", "hist")
        self.assertEqual(result["status"], "error")
        data = json.loads((self.run_dir / "verify.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "error")

    def test_run_regression_stage_timeout_is_stage_error_already_handled(self):
        # La regla es distinta: run_regression_stage ya envuelve TODO su
        # subprocess.run en un except Exception genérico desde la Fase 5/PR3
        # (no es un gap nuevo) — este test confirma esa cobertura preexistente
        # explícitamente, no reintroduce lógica.
        os.environ["MAGNA_E2E_REPO"] = str(self.project_path)
        timeout_exc = subprocess.TimeoutExpired(cmd=["npx", "playwright", "test"], timeout=600)
        with patch.object(self.runner.subprocess, "run", side_effect=timeout_exc):
            result = self.runner.run_regression_stage(self.run_dir, self.project_path)
        self.assertEqual(result["status"], "error")
        data = json.loads((self.run_dir / "regression.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "error")


class FrozenClockStalenessTestCase(unittest.TestCase):
    """Fase 8.2 — `read_qa_status()`'s `heartbeat > 600s` staleness check,
    con un reloj congelado (`time.time` monkeypatcheado) en vez de depender de
    un sleep real de 600s. Cubre los bordes exactos del umbral, no solo un
    valor "bien adentro" del rango como PR4's cobertura original."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        self.base = Path(self._tmp.name)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def _write_status_with_heartbeat(self, ticket_id: str, heartbeat: float, state: str = "verify") -> None:
        run_dir = self.qa._run_dir(ticket_id)
        status = self.qa._new_status("R1", ticket_id, str(self.base), None)
        status["state"] = state
        status["heartbeat"] = heartbeat
        self.qa._write_json_atomic(run_dir / "status.json", status)

    def test_stale_just_over_threshold_with_frozen_clock(self):
        frozen_now = 1_000_000.0
        self._write_status_with_heartbeat("PROJ-960", heartbeat=frozen_now - 601)
        with patch.object(self.qa.time, "time", return_value=frozen_now):
            status = self.qa.read_qa_status("PROJ-960")
        self.assertTrue(status.get("stale"))

    def test_not_stale_exactly_at_threshold_with_frozen_clock(self):
        frozen_now = 1_000_000.0
        self._write_status_with_heartbeat("PROJ-961", heartbeat=frozen_now - 600)
        with patch.object(self.qa.time, "time", return_value=frozen_now):
            status = self.qa.read_qa_status("PROJ-961")
        self.assertFalse(status.get("stale", False))

    def test_not_stale_just_under_threshold_with_frozen_clock(self):
        frozen_now = 1_000_000.0
        self._write_status_with_heartbeat("PROJ-962", heartbeat=frozen_now - 599)
        with patch.object(self.qa.time, "time", return_value=frozen_now):
            status = self.qa.read_qa_status("PROJ-962")
        self.assertFalse(status.get("stale", False))

    def test_frozen_clock_terminal_state_never_marked_stale_even_if_very_old(self):
        frozen_now = 1_000_000.0
        self._write_status_with_heartbeat("PROJ-963", heartbeat=frozen_now - 10_000, state="done")
        with patch.object(self.qa.time, "time", return_value=frozen_now):
            status = self.qa.read_qa_status("PROJ-963")
        self.assertFalse(status.get("stale", False))

    def test_frozen_clock_badge_reflects_stale_as_error(self):
        frozen_now = 1_000_000.0
        self._write_status_with_heartbeat("PROJ-964", heartbeat=frozen_now - 601)
        with patch.object(self.qa.time, "time", return_value=frozen_now):
            badge = self.qa.read_qa_badge("PROJ-964")
        self.assertEqual(badge["state"], "error")

    def test_frozen_clock_awaiting_input_never_stale_even_if_very_old(self):
        frozen_now = 1_000_000.0
        self._write_status_with_heartbeat("PROJ-965", heartbeat=frozen_now - 10_000, state="awaiting_input")
        with patch.object(self.qa.time, "time", return_value=frozen_now):
            status = self.qa.read_qa_status("PROJ-965")
        self.assertFalse(status.get("stale", False))

    def test_frozen_clock_badge_awaiting_input_distinct_even_if_very_old(self):
        frozen_now = 1_000_000.0
        self._write_status_with_heartbeat("PROJ-966", heartbeat=frozen_now - 10_000, state="awaiting_input")
        with patch.object(self.qa.time, "time", return_value=frozen_now):
            badge = self.qa.read_qa_badge("PROJ-966")
        self.assertEqual(badge["state"], "awaiting-input")


class BlackboardSupersedeIntegrationTestCase(unittest.TestCase):
    """Fase 8.3 — integración: una nueva `ctx sync` (trigger_qa) mientras la
    corrida previa del mismo ticket sigue in-progress descarta los artefactos
    parciales de la corrida vieja y arranca limpio (nunca los mezcla); si la
    corrida vieja de todos modos intenta finalizar (proceso detached que aún
    no notó el supersede), jamás puede escribir sobre el estado de la nueva."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner
        self.base = Path(self._tmp.name)
        popen_patcher = patch(
            "aicli.services.qa_orchestrator.subprocess.Popen", return_value=Mock(pid=999),
        )
        popen_patcher.start()
        self.addCleanup(popen_patcher.stop)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def test_resync_mid_run_discards_partials_and_old_run_cannot_finalize(self):
        run_dir = self.qa._run_dir("PROJ-980")
        old_run_id = self.qa.trigger_qa(
            ticket_id="PROJ-980", project_path=self.base, files=["a.py"],
        )
        self.assertIsNotNone(old_run_id)

        # simula progreso in-flight de la corrida vieja (todavia no terminal)
        self.qa._write_json_atomic(
            run_dir / "repro.json", {"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"},
        )
        self.qa._write_json_atomic(
            run_dir / "verify.json", {"schema": self.qa.VERIFY_SCHEMA, "status": "fail"},
        )
        old_status_before_resync = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(old_status_before_resync["state"], "pending")

        new_run_id = self.qa.trigger_qa(
            ticket_id="PROJ-980", project_path=self.base, files=["a.py"],
        )
        self.assertIsNotNone(new_run_id)
        self.assertNotEqual(old_run_id, new_run_id)
        self.assertFalse((run_dir / "repro.json").exists())
        self.assertFalse((run_dir / "verify.json").exists())

        new_status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(new_status["run_id"], new_run_id)
        self.assertEqual(new_status["state"], "pending")

        # la corrida vieja, si de todos modos corre el pipeline (proceso
        # detached que aún no notó el supersede), debe abortar sin tocar nada
        status_path = run_dir / "status.json"
        verdict = self.runner.run_pipeline(
            ticket_id="PROJ-980", project_path=self.base, run_dir=run_dir,
            run_id=old_run_id, status_path=status_path,
            repro_fn=Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"}),
            verify_fn=Mock(), regression_fn=Mock(), correction_fn=Mock(),
        )
        self.assertIsNone(verdict)
        self.assertFalse((run_dir / "verdict.json").exists())

        untouched = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(untouched, new_status)


class SyncTriggerLaunchFailureIntegrationTestCase(unittest.TestCase):
    """Fase 8.4 — integración end-to-end: `Popen` real lanza `OSError` a
    través del call site real de `sync.py` (`trigger_qa` SIN mockear a sí
    misma); confirma que ni `_trigger_qa_guarded` ni `trigger_qa` dejan
    escapar la excepción y que `status.json` queda con
    `state:"error", reason:"launch_failed"`. `_base_dir()`/`_run_dir()` leen
    `MYCONTEXT_HOME` en cada llamada (nunca cacheado), así que no hace falta
    recargar ningún módulo para que este test quede aislado del filesystem
    real."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        from aicli.commands import sync as sync_mod
        from aicli.services import qa_orchestrator as qa_orch
        self.sync_mod = sync_mod
        self.qa = qa_orch
        self.base = Path(self._tmp.name)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def test_sync_trigger_guarded_survives_real_popen_oserror(self):
        with patch("aicli.services.qa_orchestrator.subprocess.Popen", side_effect=OSError("boom")):
            self.sync_mod._trigger_qa_guarded("PROJ-970", self.base, ["a.py"])  # no debe lanzar

        status_path = self.qa._run_dir("PROJ-970") / "status.json"
        data = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(data["state"], "error")
        self.assertEqual(data["reason"], "launch_failed")


class CorrectionLoopThreatMatrixIntegrationTestCase(unittest.TestCase):
    """Fase 8 (extension solicitada explícitamente para esta unidad) — el
    threat-matrix de git ya está probado sobre `_git()` aislado
    (GitDenylistTestCase, PR1) y sobre `run_correction_attempt` para
    branch-mismatch + pathspec-scoped commit (QaRunnerCorrectionTestCase,
    PR1). Esta clase confirma dos casos que faltaban EN EL CONTEXTO real del
    ciclo de corrección: HEAD desacoplado (detached) y que un push real jamás
    ocurre incluso cuando `run_correction_attempt` sí hace un commit local."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.repo = Path(self._tmp.name) / "repo"
        _init_repo(self.repo)
        (self.repo / "tracked.py").write_text("original\n", encoding="utf-8")
        _run_git(["add", "tracked.py"], self.repo)
        _run_git(["commit", "-m", "initial"], self.repo)
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

    def tearDown(self):
        self._tmp.cleanup()

    def test_correction_attempt_aborts_on_detached_head(self):
        _run_git(["checkout", "--detach", "HEAD"], self.repo)
        result = self.runner.run_correction_attempt(
            run_dir=self.run_dir, project_path=self.repo, ticket_id="PROJ-1",
            attempt=1, archivos_tocados=["tracked.py"],
            failure_reason="motivo", branch="fix/PROJ-1",
        )
        self.assertEqual(result["status"], "aborted")
        self.assertIsNone(result["commit"])
        self.assertEqual(_commit_count(self.repo), 1)

    def test_correction_attempt_leaves_real_origin_untouched(self):
        origin = Path(self.repo).parent / "origin.git"
        origin.mkdir(parents=True, exist_ok=True)
        _run_git(["init", "--bare"], origin)
        current_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], self.repo).stdout.strip()
        _run_git(["remote", "add", "origin", str(origin)], self.repo)
        _run_git(["push", "origin", f"HEAD:refs/heads/{current_branch}"], self.repo)
        before = _run_git(["ls-remote", str(origin)], self.repo).stdout

        (self.repo / "tracked.py").write_text("corrected via correction loop\n", encoding="utf-8")
        with patch.object(self.runner.qa_prompts, "invoke_stage", return_value='{"status": "applied", "motivo": "fix"}'):
            result = self.runner.run_correction_attempt(
                run_dir=self.run_dir, project_path=self.repo, ticket_id="PROJ-1",
                attempt=1, archivos_tocados=["tracked.py"],
                failure_reason="motivo", branch=current_branch,
            )

        self.assertEqual(result["status"], "applied")
        self.assertEqual(_commit_count(self.repo), 2)
        after = _run_git(["ls-remote", str(origin)], self.repo).stdout
        self.assertEqual(before, after)


class QaNotifyMechanismRuntimeIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    """Fase 8 (fix de verify-report — CRITICAL) — hasta esta clase, el
    mecanismo de notify de `qa-correction-cycle`/`qa-status-surface` estaba
    confirmado solo por inspección de código: `_advance()`/`_finalize()`
    (qa_runner.py) nunca se habían ejercitado escribiendo eventos reales en
    `status.json`, y `TicketPanel._poll_qa()` (widgets.py) nunca había
    llamado a `self.app.notify()` de verdad — solo la función pura
    `_unseen_events()` estaba testeada, con listas armadas a mano. Este test
    dirige `run_pipeline()` a través de 2 intentos de corrección REALES (con
    commits git reales en un repo desechable) y luego alimenta el
    `status.json` resultante a `TicketPanel._poll_qa()` montado en una App de
    Textual real, confirmando que `app.notify()` se invoca genuinamente para
    cada evento no visto — cerrando el CRITICAL y el WARNING de
    verify-report.md sobre composición de múltiples commits reales."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

        self.repo = Path(self._tmp.name) / "repo"
        _init_repo(self.repo)
        (self.repo / "tracked.py").write_text("original\n", encoding="utf-8")
        _run_git(["add", "tracked.py"], self.repo)
        _run_git(["commit", "-m", "initial"], self.repo)
        self.branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], self.repo).stdout.strip()

        self.ticket_id = "PROJ-960"
        self.run_dir = self.qa._run_dir(self.ticket_id)
        self.run_id = "R-NOTIFY-1"
        status = self.qa._new_status(self.run_id, self.ticket_id, str(self.repo), self.branch)
        self.status_path = self.run_dir / "status.json"
        self.qa._write_json_atomic(self.status_path, status)
        self.qa.write_env_context(self.run_dir, db="magna_test", url="http://localhost:3000", source="user")

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def _correction_with_real_edit(self, **kwargs):
        """Simula lo que haría el corrector real (editar el archivo tocado)
        antes de delegar en el `run_correction_attempt` REAL — así cada
        intento produce un diff no vacio y por lo tanto un commit real y
        distinto, en vez de un `no_changes`."""
        (self.repo / "tracked.py").write_text(f"corrected attempt {kwargs['attempt']}\n", encoding="utf-8")
        return self.runner.run_correction_attempt(**kwargs)

    async def test_pipeline_writes_real_events_and_poll_qa_notifies_from_them(self):
        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"})
        verify_fn = Mock(return_value={"schema": self.qa.VERIFY_SCHEMA, "status": "fail", "checks": []})
        regression_fn = Mock()

        # ── 1) run_pipeline REAL a través de 2 intentos de correccion REALES ──
        with patch.object(self.runner.qa_prompts, "invoke_stage",
                           return_value='{"status": "applied", "motivo": "correccion real de prueba"}'):
            verdict = self.runner.run_pipeline(
                ticket_id=self.ticket_id, project_path=self.repo, run_dir=self.run_dir,
                run_id=self.run_id, status_path=self.status_path,
                files=["tracked.py"], branch=self.branch,
                repro_fn=repro_fn, verify_fn=verify_fn,
                regression_fn=regression_fn, correction_fn=self._correction_with_real_edit,
            )

        self.assertEqual(verdict["verdict"], "manual_review")
        self.assertFalse(verdict["qa_verified"])
        self.assertEqual(verdict["attempts"], self.runner.MAX_CORRECTION_ATTEMPTS)
        self.assertEqual(len(verdict["commits"]), 2)
        self.assertNotEqual(verdict["commits"][0], verdict["commits"][1])
        self.assertEqual(_commit_count(self.repo), 3)  # initial + 2 real correction commits
        regression_fn.assert_not_called()  # verify never "pass" → regression never runs

        status = json.loads(self.status_path.read_text(encoding="utf-8"))
        self.assertEqual(len(status["events"]), 3)
        kinds = [e["kind"] for e in status["events"]]
        self.assertEqual(kinds, ["correction", "correction", "terminal"])
        self.assertIn("Iniciando correccion 1/2", status["events"][0]["msg"])
        self.assertIn("Iniciando correccion 2/2", status["events"][1]["msg"])
        self.assertIn("Verdict: manual_review", status["events"][2]["msg"])

        # ── 2) TicketPanel._poll_qa() REAL, montado en una App de Textual real ──
        from textual.app import App, ComposeResult
        from aicli.tui.widgets import TicketPanel

        class _PollHarnessApp(App):
            def compose(self) -> ComposeResult:
                yield TicketPanel()

        app = _PollHarnessApp()
        async with app.run_test():
            panel = app.query_one(TicketPanel)
            panel._tickets = [{"id": self.ticket_id, "summary": "x", "_rounds": 0, "_active": False}]

            with patch.object(app, "notify") as mock_notify:
                panel._poll_qa()

                self.assertEqual(mock_notify.call_count, 3)
                messages = [call.args[0] for call in mock_notify.call_args_list]
                self.assertTrue(any("Iniciando correccion 1/2" in m for m in messages))
                self.assertTrue(any("Iniciando correccion 2/2" in m for m in messages))
                self.assertTrue(any("Verdict: manual_review" in m for m in messages))
                self.assertTrue(all(m.startswith(f"{self.ticket_id}: ") for m in messages))

                # re-poll con el mismo status.json: ningun evento nuevo → notify no vuelve a llamarse
                panel._poll_qa()
                self.assertEqual(mock_notify.call_count, 3)


class EnvPersistenceTestCase(unittest.TestCase):
    """qa-pipeline-verification-gaps 1.1 — Requirement: Pre-Flight DB/URL
    Confirmation / Supersede on Re-Sync. `env_context.json` vive fuera de
    `_STAGE_ARTIFACTS` a propósito (design.md, decision 8) — debe sobrevivir
    a todo `_reset_blackboard()`, disparado tanto desde `trigger_qa()` como
    desde `resume_qa()`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        self.base = Path(self._tmp.name)
        popen_patcher = patch(
            "aicli.services.qa_orchestrator.subprocess.Popen", return_value=Mock(pid=1234),
        )
        popen_patcher.start()
        self.addCleanup(popen_patcher.stop)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def test_persistent_artifacts_disjoint_from_stage_artifacts(self):
        self.assertFalse(set(self.qa._PERSISTENT_ARTIFACTS) & set(self.qa._STAGE_ARTIFACTS))

    def test_reset_blackboard_preserves_env_context_across_trigger_qa(self):
        run_dir = self.qa._run_dir("PROJ-990")
        run_dir.mkdir(parents=True, exist_ok=True)
        self.qa.write_env_context(run_dir, db="magna_test", url="http://localhost:3000", source="user")

        self.qa.trigger_qa(ticket_id="PROJ-990", project_path=self.base, files=["a.py"])

        self.assertTrue((run_dir / "env_context.json").exists())

    def test_resume_qa_preserves_env_context_json(self):
        run_dir = self.qa._run_dir("PROJ-991")
        status = self.qa._new_status("R1", "PROJ-991", str(self.base), None)
        status["state"] = "awaiting_input"
        status["question"] = {"kind": "text", "prompt": "?", "options": None}
        self.qa._write_json_atomic(run_dir / "status.json", status)
        self.qa.write_env_context(run_dir, db="magna_test", url="http://localhost:3000", source="user")

        self.qa.resume_qa("PROJ-991", self.base)

        self.assertTrue((run_dir / "env_context.json").exists())


class EnvAnswerParsingTestCase(unittest.TestCase):
    """1.3 — Requirement: Pre-Flight DB/URL Confirmation, threat matrix:
    subprocess/shell composition (env answer never reaches an argv)."""

    def setUp(self):
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator

    def test_valid_pair_parses_db_and_url(self):
        db, url = self.qa._parse_env_answer("db=magna_test url=http://localhost:3000")
        self.assertEqual(db, "magna_test")
        self.assertEqual(url, "http://localhost:3000")

    def test_missing_url_half_rejected(self):
        db, url = self.qa._parse_env_answer("db=magna_test")
        self.assertIsNone(db)
        self.assertIsNone(url)

    def test_missing_db_half_rejected(self):
        db, url = self.qa._parse_env_answer("url=http://localhost:3000")
        self.assertIsNone(db)
        self.assertIsNone(url)

    def test_backtick_injection_rejected(self):
        db, url = self.qa._parse_env_answer("db=`rm -rf /` url=http://x")
        self.assertIsNone(db)
        self.assertIsNone(url)

    def test_semicolon_injection_rejected(self):
        db, url = self.qa._parse_env_answer("db=x; rm -rf / url=http://x")
        self.assertIsNone(db)
        self.assertIsNone(url)

    def test_newline_injection_rejected(self):
        db, url = self.qa._parse_env_answer("db=x\nurl=http://x")
        self.assertIsNone(db)
        self.assertIsNone(url)

    def test_over_length_input_rejected(self):
        db, url = self.qa._parse_env_answer("db=" + "a" * 5000 + " url=http://x")
        self.assertIsNone(db)
        self.assertIsNone(url)

    def test_empty_string_rejected(self):
        db, url = self.qa._parse_env_answer("")
        self.assertIsNone(db)
        self.assertIsNone(url)


class EnvContextFileTestCase(unittest.TestCase):
    """1.5 — read_env_context/write_env_context/clear_env_context."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator

    def tearDown(self):
        self._tmp.cleanup()

    def test_read_env_context_none_when_absent(self):
        self.assertIsNone(self.qa.read_env_context(self.run_dir))

    def test_write_then_read_round_trip(self):
        written = self.qa.write_env_context(
            self.run_dir, db="magna_test", url="http://localhost:3000", source="user",
        )
        self.assertEqual(written["schema"], self.qa.ENV_SCHEMA)
        read_back = self.qa.read_env_context(self.run_dir)
        self.assertEqual(read_back["db"], "magna_test")
        self.assertEqual(read_back["url"], "http://localhost:3000")
        self.assertEqual(read_back["source"], "user")

    def test_clear_env_context_removes_file(self):
        self.qa.write_env_context(self.run_dir, db="x", url="y", source="user")
        self.qa.clear_env_context(self.run_dir)
        self.assertIsNone(self.qa.read_env_context(self.run_dir))

    def test_clear_env_context_noop_when_absent(self):
        self.qa.clear_env_context(self.run_dir)  # no debe levantar
        self.assertIsNone(self.qa.read_env_context(self.run_dir))


class EnvPreflightTestCase(unittest.TestCase):
    """1.6 — Requirement: Pre-Flight DB/URL Confirmation, state machine de
    `env_preflight()`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator

    def tearDown(self):
        os.environ.pop("MAGNA_QA_DEFAULT_DB", None)
        os.environ.pop("MAGNA_QA_APP_URL", None)
        self._tmp.cleanup()

    def test_no_context_no_answer_asks_select_question(self):
        env, question = self.qa.env_preflight(self.run_dir, "PROJ-1")
        self.assertIsNone(env)
        self.assertEqual(question["kind"], "select")
        self.assertEqual(question["topic"], "env")

    def test_otro_answer_asks_text_question_without_writing_context(self):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.qa._write_json_atomic(
            self.run_dir / "answer.json", {"value": "Otro (escribir db y url a mano)"},
        )
        env, question = self.qa.env_preflight(self.run_dir, "PROJ-1")
        self.assertIsNone(env)
        self.assertEqual(question["kind"], "text")
        self.assertEqual(question["topic"], "env")
        self.assertFalse((self.run_dir / "answer.json").exists())
        self.assertFalse((self.run_dir / "env_context.json").exists())

    def test_parsed_answer_writes_file_and_consumes_answer(self):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.qa._write_json_atomic(
            self.run_dir / "answer.json", {"value": "db=magna_test url=http://localhost:3000"},
        )
        env, question = self.qa.env_preflight(self.run_dir, "PROJ-1")
        self.assertIsNone(question)
        self.assertEqual(env["db"], "magna_test")
        self.assertEqual(env["url"], "http://localhost:3000")
        self.assertTrue((self.run_dir / "env_context.json").exists())
        self.assertFalse((self.run_dir / "answer.json").exists())

    def test_existing_context_returns_no_question_and_leaves_answer_untouched(self):
        self.qa.write_env_context(self.run_dir, db="already", url="http://x", source="user")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.qa._write_json_atomic(self.run_dir / "answer.json", {"value": "unrelated pending answer"})

        env, question = self.qa.env_preflight(self.run_dir, "PROJ-1")

        self.assertIsNone(question)
        self.assertEqual(env["db"], "already")
        self.assertTrue((self.run_dir / "answer.json").exists())

    def test_malformed_answer_reasks_text_question_without_writing_context(self):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.qa._write_json_atomic(self.run_dir / "answer.json", {"value": "garbage input"})
        env, question = self.qa.env_preflight(self.run_dir, "PROJ-1")
        self.assertIsNone(env)
        self.assertEqual(question["kind"], "text")
        self.assertFalse((self.run_dir / "env_context.json").exists())


class EnvPreflightIntegrationTestCase(unittest.TestCase):
    """1.8 — integración: `resume_qa` tras una respuesta de entorno deja
    persistido `env_context.json`, reusado en la siguiente corrida, y el
    usuario es preguntado exactamente una vez por ticket."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        self.base = Path(self._tmp.name)
        popen_patcher = patch(
            "aicli.services.qa_orchestrator.subprocess.Popen", return_value=Mock(pid=1),
        )
        popen_patcher.start()
        self.addCleanup(popen_patcher.stop)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def test_env_answer_persists_and_reused_across_runs(self):
        ticket_id = "PROJ-992"
        run_dir = self.qa._run_dir(ticket_id)

        env, question = self.qa.env_preflight(run_dir, ticket_id)
        self.assertIsNone(env)
        self.assertIsNotNone(question)

        self.qa.write_qa_answer(ticket_id, "db=magna_test url=http://localhost:3000")
        env, question = self.qa.env_preflight(run_dir, ticket_id)
        self.assertIsNone(question)
        self.assertEqual(env["db"], "magna_test")

        # Un resync (trigger_qa nuevo) para el mismo ticket resetea los
        # artefactos de stage pero reusa el contexto ya confirmado — nunca
        # vuelve a preguntar (Supersede on Re-Sync: sobrevive el reset).
        self.qa.trigger_qa(ticket_id=ticket_id, project_path=self.base, files=["a.py"])
        env2, question2 = self.qa.env_preflight(run_dir, ticket_id)
        self.assertIsNone(question2)
        self.assertEqual(env2["db"], "magna_test")


class EnvPreflightPipelineWiringTestCase(unittest.TestCase):
    """1.9 — `run_pipeline()` corre `env_preflight()` antes de CUALQUIER
    stage y pausa vía `_finalize_awaiting_input` si no hay contexto todavía
    (Requirement: Pre-Flight DB/URL Confirmation, escenario 'First run for a
    ticket asks once')."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner
        self.base = Path(self._tmp.name)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def test_pipeline_pauses_for_env_preflight_before_any_stage(self):
        run_id = "R-ENV"
        run_dir = self.qa._run_dir("PROJ-993")
        status = self.qa._new_status(run_id, "PROJ-993", str(self.base), None)
        status_path = run_dir / "status.json"
        self.qa._write_json_atomic(status_path, status)
        repro_fn = Mock()

        result = self.runner.run_pipeline(
            ticket_id="PROJ-993", project_path=self.base, run_dir=run_dir,
            run_id=run_id, status_path=status_path,
            repro_fn=repro_fn, verify_fn=Mock(), regression_fn=Mock(), correction_fn=Mock(),
        )

        repro_fn.assert_not_called()
        self.assertFalse((run_dir / "verdict.json").exists())
        self.assertEqual(result["state"], "awaiting_input")
        self.assertEqual(result["question"]["topic"], "env")

    def test_pipeline_proceeds_without_pausing_when_env_already_confirmed(self):
        run_id = "R-ENV-2"
        run_dir = self.qa._run_dir("PROJ-994")
        status = self.qa._new_status(run_id, "PROJ-994", str(self.base), None)
        status_path = run_dir / "status.json"
        self.qa._write_json_atomic(status_path, status)
        self.qa.write_env_context(run_dir, db="magna_test", url="http://localhost:3000", source="user")

        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"})
        verify_fn = Mock(return_value={"schema": self.qa.VERIFY_SCHEMA, "status": "pass", "checks": []})
        regression_fn = Mock(return_value={"schema": self.qa.REGRESSION_SCHEMA, "status": "skipped"})

        verdict = self.runner.run_pipeline(
            ticket_id="PROJ-994", project_path=self.base, run_dir=run_dir,
            run_id=run_id, status_path=status_path,
            repro_fn=repro_fn, verify_fn=verify_fn, regression_fn=regression_fn, correction_fn=Mock(),
        )

        repro_fn.assert_called_once()
        self.assertEqual(verdict["verdict"], "passed")


class ReproBlockedPipelineTestCase(unittest.TestCase):
    """2.5/2.6 — Requirement: Repro Stage Isolation ("Environment failure
    attempted but blocked") + Never Correct on Repro Failure ("Blocked
    ticket skips correction"). Un repro `blocked` re-pregunta el entorno UNA
    vez (`MAX_BLOCKED_REPRO_PAUSES = 1`); si sigue bloqueado en el retry,
    cae a `manual_review` — nunca `dudoso`, nunca una corrección."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner
        self.base = Path(self._tmp.name)
        self.run_id = "R1"
        self.run_dir = self.qa._run_dir("PROJ-995")
        status = self.qa._new_status(self.run_id, "PROJ-995", str(self.base), None)
        self.status_path = self.run_dir / "status.json"
        self.qa._write_json_atomic(self.status_path, status)
        self.qa.write_env_context(self.run_dir, db="magna_test", url="http://localhost:3000", source="user")

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def test_first_blocked_repro_pauses_via_env_channel_and_clears_context(self):
        repro_fn = Mock(return_value={
            "schema": self.qa.REPRO_SCHEMA, "status": "blocked", "blocked_reason": "DB inalcanzable",
        })
        correction_fn = Mock()

        result = self.runner.run_pipeline(
            ticket_id="PROJ-995", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=repro_fn, verify_fn=Mock(), regression_fn=Mock(), correction_fn=correction_fn,
        )

        correction_fn.assert_not_called()
        self.assertFalse((self.run_dir / "verdict.json").exists())
        self.assertEqual(result["state"], "awaiting_input")
        self.assertEqual(result["question"]["topic"], "env")
        self.assertEqual(result["question"]["blocked_reason"], "DB inalcanzable")
        self.assertEqual(result["repro_blocked_pauses"], 1)
        self.assertIsNone(self.qa.read_env_context(self.run_dir))  # limpiado para re-preguntar

    def test_second_blocked_repro_falls_through_to_manual_review_never_dudoso(self):
        # Simula el retry tras resume_qa: repro_blocked_pauses ya en 1.
        status = self.qa._read_json_or_none(self.status_path)
        status["repro_blocked_pauses"] = 1
        self.qa._write_json_atomic(self.status_path, status)
        self.qa.write_env_context(self.run_dir, db="magna_test", url="http://localhost:3000", source="user")

        repro_fn = Mock(return_value={
            "schema": self.qa.REPRO_SCHEMA, "status": "blocked", "blocked_reason": "DB inalcanzable de nuevo",
        })
        correction_fn = Mock()

        verdict = self.runner.run_pipeline(
            ticket_id="PROJ-995", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=repro_fn, verify_fn=Mock(), regression_fn=Mock(), correction_fn=correction_fn,
        )

        correction_fn.assert_not_called()
        self.assertEqual(verdict["verdict"], "manual_review")
        self.assertEqual(verdict["reason"], "repro_blocked")
        self.assertNotEqual(verdict["verdict"], "dudoso")


class BlockingSecurityFindingsTestCase(unittest.TestCase):
    """3.2/3.14 — Requirement: Review Stage Contract / Aggregator Sole
    Ownership. `_blocking_security_findings` es la ÚNICA fuente de
    autoridad: la categoría normalizada contra un allowlist cerrado, nunca
    el `severity` que reporte el agente (design decision 13, threat matrix:
    prompt injection via ticket data)."""

    def setUp(self):
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

    def test_allowlisted_category_blocks_regardless_of_low_severity(self):
        review = {"security": {"findings": [
            {"category": "sql_injection", "severity": "low", "file": "a.py", "line": 1, "detail": "x"},
        ]}}
        blocking = self.runner._blocking_security_findings(review)
        self.assertEqual(len(blocking), 1)
        self.assertEqual(blocking[0]["category"], "sql_injection")

    def test_unknown_category_never_blocks_even_at_severe_severity(self):
        review = {"security": {"findings": [
            {"category": "totally_fine", "severity": "severe", "file": "a.py", "line": 1, "detail": "x"},
        ]}}
        self.assertEqual(self.runner._blocking_security_findings(review), [])

    def test_quality_findings_never_consulted(self):
        review = {
            "security": {"findings": []},
            "quality": {"findings": [{"kind": "duplication", "severity": "severe"}]},
        }
        self.assertEqual(self.runner._blocking_security_findings(review), [])

    def test_severity_none_on_allowlisted_category_still_blocks(self):
        # threat matrix: prompt injection via ticket data — un agente
        # comprometido no puede desactivar el bloqueo bajando la severidad.
        review = {"security": {"findings": [
            {"category": "xss", "severity": "none", "file": "a.py", "line": 1, "detail": "x"},
        ]}}
        blocking = self.runner._blocking_security_findings(review)
        self.assertEqual(len(blocking), 1)

    def test_missing_security_section_returns_empty_list(self):
        self.assertEqual(self.runner._blocking_security_findings({}), [])

    def test_category_case_and_whitespace_normalised(self):
        review = {"security": {"findings": [
            {"category": "  SQL_Injection  ", "severity": "low", "file": "a.py", "line": 1, "detail": "x"},
        ]}}
        self.assertEqual(len(self.runner._blocking_security_findings(review)), 1)


class ReviewDiffTestCase(unittest.TestCase):
    """3.4/3.5/3.6/3.7 — `_review_diff`: threat matrix (diff scope blowout,
    git repository selection, push state)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        _init_repo(self.repo)
        (self.repo / "tracked.py").write_text("original\n", encoding="utf-8")
        (self.repo / "other.py").write_text("otro archivo\n", encoding="utf-8")
        _run_git(["add", "."], self.repo)
        _run_git(["commit", "-m", "initial"], self.repo)
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

    def tearDown(self):
        self._tmp.cleanup()

    # ── 3.4 — diff scope blowout ──────────────────────────────────────────

    def test_empty_files_returns_empty_string_with_zero_git_calls(self):
        with patch.object(self.runner, "_git") as mock_git:
            result = self.runner._review_diff(self.repo, [])
        self.assertEqual(result, "")
        mock_git.assert_not_called()

    # ── 3.5/3.6 — git repository selection + push state (fake recorder) ─────

    def test_every_git_call_is_read_only_and_scoped_to_project_path(self):
        calls = []

        def _recorder(args, cwd):
            calls.append((args, cwd))
            return subprocess.CompletedProcess(args, 128, stdout="", stderr="")

        with patch.object(self.runner, "_git", side_effect=_recorder):
            self.runner._review_diff(self.repo, ["tracked.py"])

        self.assertTrue(calls)
        _read_only_verbs = {"merge-base", "diff"}
        for args, cwd in calls:
            self.assertIn(args[0], _read_only_verbs)
            self.assertEqual(Path(cwd), self.repo)

    def test_review_diff_never_constructs_a_denylisted_argv(self):
        import aicli.services.qa_orchestrator as qa_orchestrator
        calls = []

        def _recorder(args, cwd):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="deadbeef\n", stderr="")

        with patch.object(self.runner, "_git", side_effect=_recorder):
            self.runner._review_diff(self.repo, ["tracked.py"])

        for args in calls:
            self.assertNotIn(args[0], qa_orchestrator._GIT_DENYLIST)

    # ── 3.7 — comportamiento real (repo desechable, sin mocks) ───────────────

    def test_only_touched_file_diff_returned_not_whole_repo(self):
        (self.repo / "tracked.py").write_text("modified\n", encoding="utf-8")
        (self.repo / "other.py").write_text("modified tambien\n", encoding="utf-8")

        result = self.runner._review_diff(self.repo, ["tracked.py"])

        self.assertIn("tracked.py", result)
        self.assertNotIn("other.py", result)

    def test_no_base_branch_falls_back_to_working_tree_diff(self):
        (self.repo / "tracked.py").write_text("modified sin base branch\n", encoding="utf-8")
        result = self.runner._review_diff(self.repo, ["tracked.py"])
        self.assertIn("tracked.py", result)
        self.assertIn("modified sin base branch", result)


class ReviewPromptAndStageTestCase(unittest.TestCase):
    """3.9/3.10 — `build_review_prompt` + `run_review_stage`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.project_path = Path(self._tmp.name) / "project"
        self.project_path.mkdir(parents=True, exist_ok=True)
        import aicli.services.qa_prompts as qa_prompts
        importlib.reload(qa_prompts)
        self.qp = qa_prompts
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

    def tearDown(self):
        self._tmp.cleanup()

    def test_build_review_prompt_inlines_conduct_rules_and_diff(self):
        path = self.qp.build_review_prompt(self.run_dir, "PROJ-1", ["a.py", "b.py"], "- old\n+ new")
        content = path.read_text(encoding="utf-8")
        self.assertIn("SOLO LECTURA", content)
        self.assertIn("a.py", content)
        self.assertIn("b.py", content)
        self.assertIn("- old\n+ new", content)
        self.assertIn("qa.review/1", content)
        self.assertIn("security", content)
        self.assertIn("quality", content)

    def test_run_review_stage_empty_files_short_circuits_no_subprocess(self):
        with patch.object(self.runner.qa_prompts, "invoke_stage") as mock_invoke:
            result = self.runner.run_review_stage(self.run_dir, self.project_path, "PROJ-1", [])
        mock_invoke.assert_not_called()
        self.assertEqual(result["status"], "skipped")
        data = json.loads((self.run_dir / "review.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "skipped")
        self.assertEqual(data["security"]["findings"], [])

    def test_run_review_stage_writes_review_json_from_agent_output(self):
        agent_json = json.dumps({
            "status": "ok",
            "security": {"findings": [{"category": "xss", "file": "a.py", "line": 1, "detail": "x", "severity": "low"}]},
            "quality": {"findings": []},
        })
        with patch.object(self.runner, "_review_diff", return_value="- old\n+ new"), \
             patch.object(self.runner.qa_prompts, "invoke_stage", return_value=agent_json):
            result = self.runner.run_review_stage(self.run_dir, self.project_path, "PROJ-1", ["a.py"])
        self.assertEqual(result["status"], "ok")
        data = json.loads((self.run_dir / "review.json").read_text(encoding="utf-8"))
        self.assertEqual(data["security"]["findings"][0]["category"], "xss")

    def test_run_review_stage_unparseable_output_is_stage_error(self):
        with patch.object(self.runner, "_review_diff", return_value=""), \
             patch.object(self.runner.qa_prompts, "invoke_stage", return_value="no es json"):
            result = self.runner.run_review_stage(self.run_dir, self.project_path, "PROJ-1", ["a.py"])
        self.assertEqual(result["status"], "error")

    # ── 3.8 — threat: commit state (repo desechable, sin mocks de git) ──────

    def test_review_run_leaves_index_and_head_byte_identical(self):
        repo = Path(self._tmp.name) / "repo"
        _init_repo(repo)
        (repo / "tracked.py").write_text("original\n", encoding="utf-8")
        _run_git(["add", "tracked.py"], repo)
        _run_git(["commit", "-m", "initial"], repo)
        head_before = _run_git(["rev-parse", "HEAD"], repo).stdout
        index_before = _run_git(["status", "--porcelain"], repo).stdout

        agent_json = json.dumps({"status": "ok", "security": {"findings": []}, "quality": {"findings": []}})
        with patch.object(self.runner.qa_prompts, "invoke_stage", return_value=agent_json):
            self.runner.run_review_stage(self.run_dir, repo, "PROJ-1", ["tracked.py"])

        head_after = _run_git(["rev-parse", "HEAD"], repo).stdout
        index_after = _run_git(["status", "--porcelain"], repo).stdout
        self.assertEqual(head_before, head_after)
        self.assertEqual(index_before, index_after)


class ReviewApplicabilityTestCase(unittest.TestCase):
    """3.11 — `_review_applies` pure predicate."""

    def setUp(self):
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

    def test_applies_when_verify_pass_and_regression_pass(self):
        self.assertTrue(self.runner._review_applies({"status": "pass"}, {"status": "pass"}))

    def test_applies_when_verify_pass_and_regression_skipped(self):
        self.assertTrue(self.runner._review_applies({"status": "pass"}, {"status": "skipped"}))

    def test_does_not_apply_when_verify_fails(self):
        self.assertFalse(self.runner._review_applies({"status": "fail"}, {"status": "pass"}))

    def test_does_not_apply_when_regression_fails(self):
        self.assertFalse(self.runner._review_applies({"status": "pass"}, {"status": "fail"}))


class ReviewAggregatorTestCase(unittest.TestCase):
    """3.13/3.16 — `aggregate(review=...)` truth-table additions."""

    def setUp(self):
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner

    def _base(self, review=None):
        return dict(
            repro={"schema": "qa.repro/1", "status": "reproduced"},
            verify={"schema": "qa.verify/1", "status": "pass"},
            regression={"schema": "qa.regression/1", "status": "skipped"},
            attempts=0, commits=[], review=review,
        )

    def test_review_error_is_manual_review(self):
        verdict = self.runner.aggregate(**self._base(review={"status": "error"}))
        self.assertEqual(verdict["verdict"], "manual_review")
        self.assertEqual(verdict["reason"], "review_stage_error")
        self.assertFalse(verdict["qa_verified"])

    def test_blocking_security_finding_is_manual_review(self):
        review = {"status": "ok", "security": {"findings": [
            {"category": "sql_injection", "severity": "low", "file": "a.py", "line": 1, "detail": "x"},
        ]}}
        verdict = self.runner.aggregate(**self._base(review=review))
        self.assertEqual(verdict["verdict"], "manual_review")
        self.assertEqual(verdict["reason"], "security_finding_severe")
        self.assertFalse(verdict["qa_verified"])

    def test_quality_only_findings_never_move_verdict(self):
        review = {"status": "ok", "security": {"findings": []},
                  "quality": {"findings": [{"kind": "duplication", "file": "a.py", "line": 1, "detail": "x"}]}}
        verdict = self.runner.aggregate(**self._base(review=review))
        self.assertEqual(verdict["verdict"], "passed")
        self.assertTrue(verdict["qa_verified"])

    def test_review_none_still_passes_same_as_before(self):
        verdict = self.runner.aggregate(**self._base(review=None))
        self.assertEqual(verdict["verdict"], "passed")
        self.assertTrue(verdict["qa_verified"])


class ReviewPipelineWiringTestCase(unittest.TestCase):
    """3.11/3.12/4.3 — `run_pipeline` invoca `review_fn` exactamente una vez
    en el camino que pasa, y cero veces cuando regression falla."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)
        self.runner = qa_runner
        self.base = Path(self._tmp.name)
        self.run_id = "R1"
        self.run_dir = self.qa._run_dir("PROJ-996")
        status = self.qa._new_status(self.run_id, "PROJ-996", str(self.base), None)
        self.status_path = self.run_dir / "status.json"
        self.qa._write_json_atomic(self.status_path, status)
        self.qa.write_env_context(self.run_dir, db="magna_test", url="http://localhost:3000", source="user")

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    def test_review_fn_called_once_on_passing_path(self):
        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"})
        verify_fn = Mock(return_value={"schema": self.qa.VERIFY_SCHEMA, "status": "pass", "checks": []})
        regression_fn = Mock(return_value={"schema": self.qa.REGRESSION_SCHEMA, "status": "skipped"})
        review_fn = Mock(return_value={"schema": self.qa.REVIEW_SCHEMA, "status": "ok",
                                        "security": {"findings": []}, "quality": {"findings": []}})

        verdict = self.runner.run_pipeline(
            ticket_id="PROJ-996", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=repro_fn, verify_fn=verify_fn, regression_fn=regression_fn,
            correction_fn=Mock(), review_fn=review_fn,
        )

        review_fn.assert_called_once()
        self.assertEqual(verdict["verdict"], "passed")
        self.assertTrue(verdict["qa_verified"])

    def test_review_fn_never_called_when_regression_fails(self):
        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"})
        verify_fn = Mock(return_value={"schema": self.qa.VERIFY_SCHEMA, "status": "pass", "checks": []})
        regression_fn = Mock(return_value={"schema": self.qa.REGRESSION_SCHEMA, "status": "fail"})
        review_fn = Mock()
        correction_fn = Mock(return_value={"status": "applied", "commit": "fix(qa-auto): x"})

        self.runner.run_pipeline(
            ticket_id="PROJ-996", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=repro_fn, verify_fn=verify_fn, regression_fn=regression_fn,
            correction_fn=correction_fn, review_fn=review_fn,
        )

        review_fn.assert_not_called()

    def test_review_fn_never_called_when_verify_fails(self):
        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"})
        verify_fn = Mock(return_value={"schema": self.qa.VERIFY_SCHEMA, "status": "fail", "checks": []})
        regression_fn = Mock()
        review_fn = Mock()
        correction_fn = Mock(return_value={"status": "applied", "commit": "fix(qa-auto): x"})

        self.runner.run_pipeline(
            ticket_id="PROJ-996", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=repro_fn, verify_fn=verify_fn, regression_fn=regression_fn,
            correction_fn=correction_fn, review_fn=review_fn,
        )

        review_fn.assert_not_called()
        regression_fn.assert_not_called()

    def test_security_finding_from_review_routes_to_manual_review_no_correction(self):
        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "reproduced"})
        verify_fn = Mock(return_value={"schema": self.qa.VERIFY_SCHEMA, "status": "pass", "checks": []})
        regression_fn = Mock(return_value={"schema": self.qa.REGRESSION_SCHEMA, "status": "skipped"})
        review_fn = Mock(return_value={
            "schema": self.qa.REVIEW_SCHEMA, "status": "ok",
            "security": {"findings": [
                {"category": "sql_injection", "severity": "low", "file": "a.py", "line": 1, "detail": "x"},
            ]},
            "quality": {"findings": []},
        })
        correction_fn = Mock()

        verdict = self.runner.run_pipeline(
            ticket_id="PROJ-996", project_path=self.base, run_dir=self.run_dir,
            run_id=self.run_id, status_path=self.status_path,
            repro_fn=repro_fn, verify_fn=verify_fn, regression_fn=regression_fn,
            correction_fn=correction_fn, review_fn=review_fn,
        )

        self.assertEqual(verdict["verdict"], "manual_review")
        self.assertEqual(verdict["reason"], "security_finding_severe")
        correction_fn.assert_not_called()
        data = json.loads((self.run_dir / "verdict.json").read_text(encoding="utf-8"))
        self.assertEqual(data["stages"]["review"], "ok")


class SubprocessHardeningThreatMatrixTestCase(unittest.TestCase):
    """4.1/4.2 — threat matrix: subprocess/shell composition. Un answer de
    entorno con backtick, punto y coma, salto de línea y 5000 caracteres
    nunca llega a un argv — `_parse_env_answer` ya lo rechaza (tasks 1.3/
    1.4); esta clase prueba el flujo completo: `env_preflight` rechaza y
    re-pregunta, y el argv de `invoke_stage` nunca lleva contenido crudo del
    usuario (siempre `[exe, "-p", "Read <path> ..."]`, `shell=False`)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        import aicli.services.qa_orchestrator as qa_orchestrator
        importlib.reload(qa_orchestrator)
        self.qa = qa_orchestrator

    def tearDown(self):
        self._tmp.cleanup()

    def test_malicious_env_answer_rejected_and_reasked(self):
        malicious = "db=`rm -rf /`; url=http://x\n" + "a" * 5000
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.qa._write_json_atomic(self.run_dir / "answer.json", {"value": malicious})

        env, question = self.qa.env_preflight(self.run_dir, "PROJ-1")

        self.assertIsNone(env)
        self.assertEqual(question["kind"], "text")
        self.assertFalse((self.run_dir / "env_context.json").exists())

    def test_invoke_stage_argv_unaffected_by_dangerous_prompt_content(self):
        import aicli.services.qa_prompts as qa_prompts
        importlib.reload(qa_prompts)
        prompt_path = self.run_dir / "prompts" / "repro.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text("contenido con `backtick` y ; punto y coma", encoding="utf-8")

        fake_proc = _FakeProc(['{"status": "reproduced"}'])
        with patch.object(qa_prompts, "_find_claude_windows", return_value=None), \
             patch.object(qa_prompts.subprocess, "Popen", return_value=fake_proc) as mock_popen:
            qa_prompts.invoke_stage(prompt_path, self.run_dir, run_dir=self.run_dir, stage="repro", timeout=5)

        args, kwargs = mock_popen.call_args
        argv = args[0]
        self.assertEqual(len(argv), 3)
        self.assertEqual(argv[1], "-p")
        self.assertTrue(argv[2].startswith("Read "))
        self.assertEqual(kwargs["shell"], False)


class ReviewFindingsEvidenceDigestTestCase(unittest.TestCase):
    """4.5 — Requirement: Review Findings in Evidence Digest. Confirma que
    `LogScreen` (zero TUI code change) ya muestra `security`/`quality` de
    `review.json` verbatim, porque `_write_evidence_log` ahora los escribe
    en texto plano y `LogScreen` solo renderiza el archivo tal cual."""

    def test_log_screen_surfaces_review_findings_from_evidence_log(self):
        from aicli.tui.screens import LogScreen
        from textual.widgets import TextArea
        import aicli.services.qa_runner as qa_runner
        importlib.reload(qa_runner)

        tmp = tempfile.TemporaryDirectory()
        try:
            run_dir = Path(tmp.name)
            repro = {"status": "reproduced"}
            verify = {"status": "pass", "checks": []}
            regression = {"status": "skipped"}
            review = {
                "status": "ok",
                "security": {"findings": [
                    {"category": "sql_injection", "file": "a.py", "line": 10, "detail": "raw query", "severity": "low"},
                ]},
                "quality": {"findings": [
                    {"kind": "duplication", "file": "b.py", "line": 3, "detail": "helper duplicado"},
                ]},
            }
            verdict = {
                "verdict": "manual_review", "qa_verified": False, "reason": "security_finding_severe",
                "attempts": 0, "commits": [],
            }
            qa_runner._write_evidence_log(run_dir, repro, verify, regression, verdict, review=review)

            screen = LogScreen(log_path=run_dir / "evidence.log", title="QA — PROJ-1")
            widgets = list(screen.compose())
            text_area = next(w for w in widgets if isinstance(w, TextArea))
            self.assertIn("sql_injection", text_area.text)
            self.assertIn("raw query", text_area.text)
            self.assertIn("duplication", text_area.text)
            self.assertIn("helper duplicado", text_area.text)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
