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


class QaPromptsTestCase(unittest.TestCase):
    """Fase 4 — prompts de stage + helper de invocación headless."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        import aicli.services.qa_prompts as qa_prompts
        importlib.reload(qa_prompts)
        self.qp = qa_prompts

    def tearDown(self):
        self._tmp.cleanup()

    # ── 4.1 — Requirement: Repro Stage Isolation ─────────────────────────────

    def test_repro_prompt_never_mentions_fix_diff_or_commit(self):
        path = self.qp.build_repro_prompt(self.run_dir, "PROJ-1", "historial de ejemplo")
        content = path.read_text(encoding="utf-8").lower()
        self.assertNotIn("diff", content)
        self.assertNotIn("commit", content)
        self.assertIn("qa.repro/1", content)
        self.assertIn("not_reproduced", content)

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

        fake_result = Mock(stdout='{"status": "reproduced"}')
        with patch.object(self.qp, "_find_claude_windows", return_value=None), \
             patch.object(self.qp.subprocess, "run", return_value=fake_result) as mock_run:
            out = self.qp.invoke_stage(prompt_path, self.run_dir, timeout=5)

        self.assertEqual(out, '{"status": "reproduced"}')
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        argv = args[0]
        self.assertEqual(argv[0], "claude")
        self.assertEqual(argv[1], "-p")
        self.assertNotIn("--output-format", argv)
        self.assertNotIn("--permission-mode", argv)
        self.assertEqual(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 5)


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
            result = self.runner.run_repro_stage(self.run_dir, self.project_path, "PROJ-1", "hist")
        self.assertEqual(result["status"], "reproduced")
        data = json.loads((self.run_dir / "repro.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "reproduced")

    def test_run_repro_stage_unparseable_output_is_stage_error(self):
        with patch.object(self.runner.qa_prompts, "invoke_stage", return_value="no es json"):
            result = self.runner.run_repro_stage(self.run_dir, self.project_path, "PROJ-1", "hist")
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

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    # ── 5.4 — RED: not_reproduced never starts correction ────────────────────

    def test_pipeline_not_reproduced_never_starts_correction(self):
        repro_fn = Mock(return_value={"schema": self.qa.REPRO_SCHEMA, "status": "not_reproduced"})
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


if __name__ == "__main__":
    unittest.main()
