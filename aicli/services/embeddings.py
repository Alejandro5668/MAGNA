"""
Prefiltro semántico de módulos vía Chroma (vector store local, embebido).

Un `Module` se embebe como `f"{name}: {description}"` (sin leer archivos) y
se indexa en una colección Chroma por proyecto (`project_{project_id}`).
`query_modules` narrowea el listado de módulos a los top-N más relevantes
para una tarea; cualquier falla degrada al listado completo — el prefiltro
es una optimización, nunca un requisito para que `ctx task` funcione.
"""
import logging
from pathlib import Path

from aicli.db.models import Module

CHROMA_PATH = Path.home() / ".mycontext" / "chroma"
TOP_N = 20

_client = None  # lazy — chromadb solo se importa en el primer uso real


def _default_ef():
    """Import diferido: permite patchear sin descargar el modelo ONNX en tests."""
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    return DefaultEmbeddingFunction()


def get_collection(project_id: int):
    global _client
    if _client is None:
        import chromadb
        from chromadb.config import Settings
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(CHROMA_PATH),
            settings=Settings(anonymized_telemetry=False),
        )
    return _client.get_or_create_collection(
        name=f"project_{project_id}", embedding_function=_default_ef()
    )


def _text(name: str, description: str) -> str:
    return f"{name}: {description}"


def _raw_upsert(collection, rows: list[tuple[int, str, str]]) -> None:
    collection.upsert(
        ids=[str(i) for i, _, _ in rows],
        documents=[_text(n, d) for _, n, d in rows],
        metadatas=[{"name": n, "text": _text(n, d)} for _, n, d in rows],
    )


def upsert_modules(project_id: int, rows: list[tuple[int, str, str]]) -> None:
    """(module_id, name, description). Nunca lanza — el prefiltro es opcional."""
    if not rows:
        return
    try:
        _raw_upsert(get_collection(project_id), rows)
    except Exception as e:
        logging.warning("Chroma upsert falló (project %s): %s", project_id, e)


def _reconcile(collection, modules: list[Module]) -> None:
    """Backfill perezoso + self-heal. Lanza — el caller degrada."""
    got = collection.get(include=["metadatas"])
    stored = dict(zip(got["ids"], got["metadatas"] or []))
    rows = [
        (m.id, m.name, m.description) for m in modules
        if str(m.id) not in stored
        or (stored[str(m.id)] or {}).get("text") != _text(m.name, m.description)
    ]
    if rows:
        logging.info("Chroma backfill: %d módulo(s)", len(rows))
        _raw_upsert(collection, rows)


def query_modules(
    project_id: int, modules: list[Module], task_desc: str, n_results: int = TOP_N
) -> list[Module]:
    if len(modules) <= n_results:
        return modules
    try:
        collection = get_collection(project_id)
        _reconcile(collection, modules)
        res = collection.query(query_texts=[task_desc], n_results=n_results, include=[])
        by_id = {str(m.id): m for m in modules}
        hits = [by_id[i] for i in res["ids"][0] if i in by_id]
        return hits or modules
    except Exception as e:
        logging.warning("Prefiltro semántico deshabilitado: %s", e)
        return modules
