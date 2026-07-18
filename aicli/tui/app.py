from __future__ import annotations
from pathlib import Path

from textual.app import App

from .screens import MainScreen, ProjectScreen


class MagnaApp(App):
    # Canvas negro — no se pinta; la terminal del usuario es el fondo
    CSS = "Screen { background: transparent; }"

    def on_mount(self) -> None:
        from sqlmodel import Session, select as sql_select
        from aicli.db import engine
        from aicli.db.models import Project

        current = str(Path.cwd())
        with Session(engine) as s:
            project = s.exec(
                sql_select(Project).where(Project.path == current)
            ).first()

        if project:
            self.push_screen(MainScreen(project.name, project.path))
            return

        with Session(engine) as s:
            projects = list(s.exec(sql_select(Project)).all())

        self.push_screen(ProjectScreen(projects))


def run_app() -> None:
    print("\033]0;MAGNA\007", end="", flush=True)
    MagnaApp().run()
