from sqlmodel import SQLModel, Field


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
