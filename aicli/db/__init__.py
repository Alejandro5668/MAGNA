import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlmodel import create_engine, SQLModel

from aicli.db import models
from aicli.db.migrations import MIGRATIONS, SCHEMA_VERSION

_db_path = Path.home() / ".mycontext" / "ctx_bd.db"
DATABASE_URL = f"sqlite:///{_db_path}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def _current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT schema_version FROM meta ORDER BY id LIMIT 1").fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0  # table doesn't exist yet — fresh or pre-versioning install


def _stamp_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("DELETE FROM meta")
    conn.execute("INSERT INTO meta (schema_version) VALUES (?)", (version,))
    conn.commit()


def init_db() -> None:
    Path.home().joinpath(".mycontext").mkdir(exist_ok=True)
    SQLModel.metadata.create_all(engine)  # creates any missing tables incl. meta

    with sqlite3.connect(_db_path) as conn:
        current = _current_version(conn)

        if current < SCHEMA_VERSION:
            # backup before touching anything
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = _db_path.with_name(f"ctx_bd_backup_{ts}.db")
            shutil.copy2(_db_path, backup)

            try:
                for migration in MIGRATIONS[current:]:
                    migration(conn)
                _stamp_version(conn, SCHEMA_VERSION)
            except Exception as exc:
                shutil.copy2(backup, _db_path)
                raise RuntimeError(
                    f"Migracion fallida v{current}->v{SCHEMA_VERSION}: {exc}\n"
                    f"DB restaurada desde {backup}"
                ) from exc

            from rich.console import Console as _C
            _C().print(f"  [bold green]✔[/bold green]  [dim]Schema v{current} → v{SCHEMA_VERSION}[/dim]")
