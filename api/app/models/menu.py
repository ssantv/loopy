"""Modelos del módulo menú de comidas (adulto). Planteamiento §2.6.

Franjas fijas `desayuno|almuerzo|comida|merienda|cena`; las recetas declaran a
qué franjas van bien (bitmask) y el planificador semanal guarda una receta o
texto libre por (fecha, franja).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

SLOTS = ("desayuno", "almuerzo", "comida", "merienda", "cena")


def _now() -> datetime:
    return datetime.now(UTC)


def slot_bit(slot: str) -> int:
    return 1 << SLOTS.index(slot)


def slots_to_mask(slots: list[str]) -> int:
    return sum(slot_bit(s) for s in slots)


def mask_to_slots(mask: int) -> list[str]:
    return [s for i, s in enumerate(SLOTS) if mask & (1 << i)]


class MealSlotConfig(Base):
    """Franja activable (ninguna activa por defecto)."""

    __tablename__ = "meal_slot_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    slot: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("user_id", "slot", name="uq_slot_config_user_slot"),)


class RecipeCategory(Base):
    """Categoría de receta. `user_id` NULL = globales por defecto (pescado,
    verdura, legumbre, carne, huevo, pasta/arroz…); el usuario puede añadir las
    suyas propias."""

    __tablename__ = "recipe_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_recipe_category_user_name"),)

    recipes: Mapped[list[Recipe]] = relationship(back_populates="category")


class CategoryGoal(Base):
    """Objetivo semanal por categoría (mínimos y máximos opcionales).

    Sin fila → se aplica el goal por defecto (ver servicios.menu.DEFAULT_GOALS).
    """

    __tablename__ = "category_goals"
    __table_args__ = (UniqueConstraint("user_id", "recipe_category_id", name="uq_goal_user_category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    recipe_category_id: Mapped[int] = mapped_column(
        ForeignKey("recipe_categories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    min_per_week: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Recipe(Base):
    """Receta con ingredientes y franjas aptas (bitmask de `SLOTS`)."""

    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("recipe_categories.id", ondelete="RESTRICT"), nullable=False)
    slots_mask: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    category: Mapped[RecipeCategory] = relationship(back_populates="recipes")
    ingredients: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeIngredient.sort_order"
    )


class RecipeIngredient(Base):
    """Ingrediente (nombre + cantidad numérica + unidad). Se suman al fusionar."""

    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")


class MealPlan(Base):
    """Asignación (fecha, franja) → receta o texto libre. UNIQUE(user, date, slot)."""

    __tablename__ = "meal_plans"
    __table_args__ = (UniqueConstraint("user_id", "date", "slot", name="uq_meal_plan_day_slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    slot: Mapped[str] = mapped_column(String(16), nullable=False)
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True)
    free_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    recipe: Mapped[Recipe | None] = relationship()