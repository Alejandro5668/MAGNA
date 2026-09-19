"""
Tests unitarios para aicli.services.embeddings — prefiltro semántico Chroma.
Ejecutar: .venv\\Scripts\\python.exe -m pytest tests/test_module_prefilter.py -v

Usa unittest.mock.patch sobre chromadb — sin descarga real de modelo ONNX en
los tests unitarios (mirror del estilo de test_prompt_caching.py /
test_structured_output.py). El test de integración (skipUnless) usa un EF
real stubeado y un PersistentClient real contra un tmp dir.
"""
import shutil
import sys
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from aicli.commands import init as init_cmd
from aicli.commands import file_cmd
from aicli.commands import sync as sync_cmd
from aicli.db.models import Module, Project
from aicli.services import embeddings


def _make_module(id_: int, name: str, description: str = "desc", file_path: str = "path.py", project_id: int = 1) -> Module:
    return Module(
        id=id_,
        project_id=project_id,
        name=name,
        description=description,
        file_path=file_path,
        content_path="",
        created_at="2026-01-01",
    )


class ResetClientMixin(unittest.TestCase):
    def setUp(self):
        embeddings._client = None

    def tearDown(self):
        embeddings._client = None


class GetCollectionTestCase(ResetClientMixin):

    @patch("chromadb.PersistentClient")
    def test_telemetry_disabled(self, mock_client_cls):
        embeddings.get_collection(1)

        _, kwargs = mock_client_cls.call_args
        settings = kwargs["settings"]
        self.assertFalse(settings.anonymized_telemetry)

    @patch("chromadb.PersistentClient")
    def test_per_project_collection_naming(self, mock_client_cls):
        mock_instance = mock_client_cls.return_value
        embeddings.get_collection(42)

        mock_instance.get_or_create_collection.assert_called_once()
        _, kwargs = mock_instance.get_or_create_collection.call_args
        self.assertEqual(kwargs["name"], "project_42")

    @patch("chromadb.PersistentClient")
    def test_client_is_lazily_reused_across_calls(self, mock_client_cls):
        embeddings.get_collection(1)
        embeddings.get_collection(2)

        mock_client_cls.assert_called_once()


class TextAndUpsertTestCase(ResetClientMixin):

    def test_text_composition_is_exact(self):
        self.assertEqual(embeddings._text("mod_a", "hace cosas"), "mod_a: hace cosas")

    def test_raw_upsert_document_shape(self):
        collection = MagicMock()
        rows = [(1, "mod_a", "hace cosas")]

        embeddings._raw_upsert(collection, rows)

        _, kwargs = collection.upsert.call_args
        self.assertEqual(kwargs["ids"], ["1"])
        self.assertEqual(kwargs["documents"], ["mod_a: hace cosas"])
        self.assertEqual(kwargs["metadatas"], [{"name": "mod_a", "text": "mod_a: hace cosas"}])

    @patch("aicli.services.embeddings.get_collection")
    def test_upsert_modules_builds_document_from_name_and_description_only(self, mock_get_collection):
        mock_collection = mock_get_collection.return_value
        # Rows are (id, name, description) tuples only — no file_path/content_path
        # is ever read to build the embedding text.
        rows = [(1, "mod_a", "desc a")]

        embeddings.upsert_modules(1, rows)

        _, kwargs = mock_collection.upsert.call_args
        self.assertEqual(kwargs["documents"], ["mod_a: desc a"])

    @patch("aicli.services.embeddings.get_collection")
    def test_upsert_modules_never_raises(self, mock_get_collection):
        mock_get_collection.return_value.upsert.side_effect = RuntimeError("boom")

        try:
            embeddings.upsert_modules(1, [(1, "mod_a", "desc")])
        except Exception:
            self.fail("upsert_modules no debe propagar excepciones")

    @patch("aicli.services.embeddings.get_collection")
    def test_upsert_modules_empty_rows_skips_collection_entirely(self, mock_get_collection):
        embeddings.upsert_modules(1, [])
        mock_get_collection.assert_not_called()


class ReconcileTestCase(ResetClientMixin):

    def test_missing_id_is_upserted(self):
        collection = MagicMock()
        collection.get.return_value = {"ids": [], "metadatas": []}
        modules = [_make_module(1, "mod_a", "desc a")]

        embeddings._reconcile(collection, modules)

        collection.upsert.assert_called_once()
        _, kwargs = collection.upsert.call_args
        self.assertEqual(kwargs["ids"], ["1"])

    def test_stale_metadata_text_is_reupserted(self):
        collection = MagicMock()
        collection.get.return_value = {
            "ids": ["1"], "metadatas": [{"name": "mod_a", "text": "mod_a: old desc"}]
        }
        modules = [_make_module(1, "mod_a", "new desc")]

        embeddings._reconcile(collection, modules)

        collection.upsert.assert_called_once()
        _, kwargs = collection.upsert.call_args
        self.assertEqual(kwargs["documents"], ["mod_a: new desc"])

    def test_matching_text_is_skipped(self):
        collection = MagicMock()
        collection.get.return_value = {
            "ids": ["1"], "metadatas": [{"name": "mod_a", "text": "mod_a: desc a"}]
        }
        modules = [_make_module(1, "mod_a", "desc a")]

        embeddings._reconcile(collection, modules)

        collection.upsert.assert_not_called()


class QueryModulesTestCase(ResetClientMixin):

    def _make_n_modules(self, n):
        return [_make_module(i, f"mod_{i}", f"desc {i}") for i in range(1, n + 1)]

    @patch("aicli.services.embeddings.get_collection")
    def test_at_or_below_20_returns_input_unchanged_no_chroma_call(self, mock_get_collection):
        modules = self._make_n_modules(20)

        result = embeddings.query_modules(1, modules, "tarea")

        self.assertEqual(result, modules)
        mock_get_collection.assert_not_called()

    @patch("aicli.services.embeddings.get_collection")
    def test_above_20_calls_reconcile_and_query_and_maps_ids_back_to_module(self, mock_get_collection):
        modules = self._make_n_modules(25)
        collection = mock_get_collection.return_value
        collection.get.return_value = {
            "ids": [str(m.id) for m in modules],
            "metadatas": [{"name": m.name, "text": embeddings._text(m.name, m.description)} for m in modules],
        }
        top_ids = [str(i) for i in range(1, 21)]
        collection.query.return_value = {"ids": [top_ids]}

        result = embeddings.query_modules(1, modules, "tarea")

        collection.query.assert_called_once()
        self.assertEqual([m.id for m in result], list(range(1, 21)))
        self.assertTrue(all(isinstance(m, Module) for m in result))

    @patch("aicli.services.embeddings.get_collection")
    def test_exception_returns_full_modules_list_no_raise(self, mock_get_collection):
        modules = self._make_n_modules(25)
        mock_get_collection.side_effect = RuntimeError("chroma down")

        result = embeddings.query_modules(1, modules, "tarea")

        self.assertEqual(result, modules)


@unittest.skipUnless(find_spec("chromadb"), "chromadb no instalado")
class ChromaIntegrationTestCase(unittest.TestCase):
    """Ejercita las formas reales de upsert/get/query contra un PersistentClient
    real en un directorio temporal, con un EF stubeado (sin descarga ONNX)."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        embeddings._client = None

    def tearDown(self):
        embeddings._client = None
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_real_upsert_reconcile_query_shapes(self):
        import chromadb
        from chromadb.config import Settings

        class _StubEF:
            def __call__(self, input):
                return [[float(len(t) % 7 + 1)] * 8 for t in input]

            def embed_query(self, input):
                return self(input)

            def name(self):
                return "stub"

            def is_legacy(self):
                return False

        client = chromadb.PersistentClient(path=self._tmpdir, settings=Settings(anonymized_telemetry=False))
        collection = client.get_or_create_collection(name="project_1", embedding_function=_StubEF())

        modules = [_make_module(i, f"mod_{i}", f"desc {i}") for i in range(1, 26)]

        with patch("aicli.services.embeddings.get_collection", return_value=collection):
            result = embeddings.query_modules(1, modules, "tarea de prueba")

        self.assertLessEqual(len(result), 20)
        self.assertTrue(all(isinstance(m, Module) for m in result))


def _memory_engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    return eng


class WriteSiteUpsertTestCase(unittest.TestCase):
    """Phase 3 — every code path that writes/updates a Module row calls
    embeddings.upsert_modules AFTER session.commit() (ids must exist
    post-commit) with (id, name, description) tuples for touched rows."""

    def setUp(self):
        self.engine = _memory_engine()
        with Session(self.engine) as session:
            project = Project(name="p", path=str(Path("/tmp/p")), stack="python", created_at="2026-01-01")
            session.add(project)
            session.commit()
            session.refresh(project)
            self.project = project

    @patch("aicli.services.embeddings.upsert_modules")
    @patch("aicli.commands.init._write_md_atomic")
    def test_init_save_modules_upserts_touched_rows_post_commit(self, mock_write_md, mock_upsert):
        with patch.object(init_cmd, "engine", self.engine):
            modules = [{"name": "mod_a", "description": "desc a", "file_path": "a.py"}]
            init_cmd._save_modules(modules, self.project)

        mock_upsert.assert_called_once()
        args, _ = mock_upsert.call_args
        self.assertEqual(args[0], self.project.id)
        rows = args[1]
        self.assertEqual(len(rows), 1)
        _, name, desc = rows[0]
        self.assertEqual((name, desc), ("mod_a", "desc a"))

    @patch("aicli.services.embeddings.upsert_modules")
    @patch("aicli.commands.file_cmd._write_md_atomic")
    def test_file_cmd_save_zone_modules_upserts_touched_rows_post_commit(self, mock_write_md, mock_upsert):
        with patch.object(file_cmd, "engine", self.engine):
            modules = [{"name": "zona_a", "description": "desc zona", "file_path": "zona/a.py"}]
            file_cmd._save_zone_modules(modules, self.project)

        mock_upsert.assert_called_once()
        args, _ = mock_upsert.call_args
        self.assertEqual(args[0], self.project.id)
        rows = args[1]
        self.assertEqual(len(rows), 1)
        _, name, desc = rows[0]
        self.assertEqual((name, desc), ("zona_a", "desc zona"))

    @patch("aicli.services.embeddings.upsert_modules")
    @patch("aicli.commands.sync._write_md_atomic")
    @patch("aicli.commands.sync.analyze_file_deep")
    @patch("aicli.commands.sync._get_diff", return_value="")
    @patch("aicli.commands.sync._check_php_syntax", return_value=[])
    @patch("aicli.commands.sync._changed_files")
    def test_sync_new_module_branch_upserts_once_after_loop(
        self, mock_changed, mock_php, mock_diff, mock_analyze, mock_write_md, mock_upsert
    ):
        mock_changed.return_value = {"nuevo.py"}
        mock_analyze.return_value = ("# Nuevo modulo\ndoc", 42)

        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        (Path(tmpdir) / "nuevo.py").write_text("pass", encoding="utf-8")
        with Session(self.engine) as session:
            proj = session.get(Project, self.project.id)
            proj.path = str(Path(tmpdir))
            session.add(proj)
            session.commit()

        with patch.object(sync_cmd, "engine", self.engine), \
             patch("pathlib.Path.cwd", return_value=Path(tmpdir)), \
             patch("aicli.commands.sync._read_session_task", return_value=""):
            sync_cmd._sync_impl(ask_fn=lambda *a, **k: "", confirm_fn=lambda *a, **k: False)

        mock_upsert.assert_called_once()
        args, _ = mock_upsert.call_args
        self.assertEqual(args[0], self.project.id)
        rows = args[1]
        self.assertEqual(len(rows), 1)
        _, name, _desc = rows[0]
        self.assertEqual(name, "nuevo")

    @patch("aicli.services.embeddings.upsert_modules")
    @patch("aicli.commands.init._write_md_atomic")
    @patch("aicli.commands.init.generate_module_content")
    @patch("aicli.commands.init.module_needs_update", return_value=True)
    def test_init_update_project_single_row_upsert_post_commit(
        self, mock_needs_update, mock_generate, mock_write_md, mock_upsert
    ):
        mock_generate.return_value = ("# doc", 10)
        with Session(self.engine) as session:
            module = Module(
                project_id=self.project.id, name="mod_x", description="desc x",
                file_path="x.py", content_path="", created_at="2026-01-01",
            )
            session.add(module)
            session.commit()
            session.refresh(module)

        with patch.object(init_cmd, "engine", self.engine), \
             patch("pathlib.Path.read_text", return_value="source code"):
            init_cmd._update_project(self.project, Path("/tmp/p"))

        mock_upsert.assert_called_once()
        args, _ = mock_upsert.call_args
        self.assertEqual(args[0], self.project.id)
        rows = args[1]
        self.assertEqual(len(rows), 1)
        _, name, _desc = rows[0]
        self.assertEqual(name, "mod_x")


if __name__ == "__main__":
    unittest.main()
