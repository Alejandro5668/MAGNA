"""
Comando oculto — diagnóstico del prefiltro semántico dentro del binario
congelado (PyInstaller). No requiere ANTHROPIC_API_KEY. Sirve como sonda
para `scripts/verify_frozen.ps1`: el único código path dentro de `MAGNA.exe`
que ejercita `chromadb`/`onnxruntime` de punta a punta (upsert real,
descarga del modelo ONNX en frío, query real).
"""
import sys

import typer

app = typer.Typer()


@app.callback(invoke_without_command=True)
def embed_selftest():
    """Prueba upsert/query de Chroma dentro del binario — diagnóstico oculto."""
    try:
        import chromadb
        from aicli.services import embeddings

        collection = _get_selftest_collection()

        docs = [
            ("auth", "login y sesiones"),
            ("pagos", "cobros con tarjeta"),
            ("ui", "componentes visuales"),
        ]
        collection.upsert(
            ids=[name for name, _ in docs],
            documents=[embeddings._text(name, desc) for name, desc in docs],
            metadatas=[{"name": name, "text": embeddings._text(name, desc)} for name, desc in docs],
        )

        res = collection.query(query_texts=["arreglar el login"], n_results=1, include=[])
        top_id = res["ids"][0][0] if res["ids"] and res["ids"][0] else None

        print(f"top-1: {top_id}")
        print(f"chromadb version: {chromadb.__version__}")

        if top_id != "auth":
            print("FAIL: top-1 esperado 'auth'", file=sys.stderr)
            raise typer.Exit(code=1)

        print("OK")
    except typer.Exit:
        raise
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        raise typer.Exit(code=1)


def _get_selftest_collection():
    from aicli.services import embeddings
    import chromadb
    from chromadb.config import Settings

    embeddings.CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(embeddings.CHROMA_PATH),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name="selftest", embedding_function=embeddings._default_ef()
    )
