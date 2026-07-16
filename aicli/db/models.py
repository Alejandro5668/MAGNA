import time as _time
from sqlmodel import SQLModel, Field


class Meta(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    schema_version: int = Field(default=0)


class Activity(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    command: str
    description: str | None = Field(default=None)
    timestamp: float = Field(default_factory=_time.time)


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    path: str
    stack: str
    created_at: str

class Module(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key='project.id')
    name: str
    description: str
    file_path: str
    content_path: str
    created_at: str
    last_updated_at: float | None = Field(default=None)
    category: str | None = Field(default=None)
    domain: str | None = Field(default=None)


class ModuleLesson(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key='project.id')
    file_path: str
    ticket_id: str
    date: str
    lesson: str
    lesson_type: str = Field(default="gotcha")
