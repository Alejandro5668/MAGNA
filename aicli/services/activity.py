import time
from sqlmodel import Session
from aicli.db import engine
from aicli.db.models import Activity


def log_activity(command: str, description: str | None = None) -> None:
    try:
        with Session(engine) as session:
            session.add(Activity(command=command, description=description, timestamp=time.time()))
            session.commit()
    except Exception:
        pass  # never break a command due to activity logging
