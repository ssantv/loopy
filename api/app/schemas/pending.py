"""Schemas del listado global de pendientes (Roadmap paso 7)."""

from datetime import date

from pydantic import BaseModel, Field

from app.schemas.task import TaskOut


class PendingList(BaseModel):
    overdue: list[TaskOut]
    today: list[TaskOut]


class BulkCompleteRequest(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=200)


class BulkError(BaseModel):
    task_id: int
    detail: str


class BulkCompleteResponse(BaseModel):
    completed: list[int]
    errors: list[BulkError]
    done_on: date