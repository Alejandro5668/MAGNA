from pathlib import Path
from sqlmodel import create_engine, SQLModel
from aicli.db import models

_db_path = Path.home() / ".mycontext" / "ctx_bd.db"
DATABASE_URL = f"sqlite:///{_db_path}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def init_db():
    Path.home().joinpath(".mycontext").mkdir(exist_ok=True)
    SQLModel.metadata.create_all(engine)