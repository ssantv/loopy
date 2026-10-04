"""Modelos ORM. Importar aquí todos los modelos para que Alembic los descubra."""

from app.models.adult import DailySummaryConfig, ShoppingItem, SummaryException
from app.models.appointment import Appointment, AppointmentPerson
from app.models.menu import (
    CategoryGoal,
    MealPlan,
    MealSlotConfig,
    Recipe,
    RecipeCategory,
    RecipeIngredient,
)
from app.models.notify import NotificationOutbox, PushSubscription
from app.models.school import (
    CheckinConfig,
    Exam,
    Extracurricular,
    HomeworkTemplate,
    OffDay,
    ScheduleSlot,
    StudyCompletion,
    WorkSession,
)
from app.models.task import Room, RotationGroup, Subject, Task, TaskCompletion
from app.models.user import PasswordResetToken, Session, User

__all__ = [
    "User",
    "Session",
    "PasswordResetToken",
    "Room",
    "Subject",
    "Task",
    "TaskCompletion",
    "RotationGroup",
    "Exam",
    "StudyCompletion",
    "Extracurricular",
    "ScheduleSlot",
    "OffDay",
    "HomeworkTemplate",
    "WorkSession",
    "CheckinConfig",
    "ShoppingItem",
    "DailySummaryConfig",
    "SummaryException",
    "PushSubscription",
    "NotificationOutbox",
    "MealSlotConfig",
    "RecipeCategory",
    "CategoryGoal",
    "Recipe",
    "RecipeIngredient",
    "MealPlan",
    "Appointment",
    "AppointmentPerson",
]