"""Schemas del módulo menú de comidas (paso 8)."""

from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel, Field

SLOT_NAMES = ("desayuno", "almuerzo", "comida", "merienda", "cena")


class SlotConfigOut(BaseModel):
    slot: str
    enabled: bool
    default_time: time | None = None


class SlotConfigsOut(BaseModel):
    slots: list[SlotConfigOut]


class SlotConfigPatch(BaseModel):
    enabled: bool | None = None
    default_time: time | None = None


class CategoryOut(BaseModel):
    id: int
    name: str
    user_id: int | None = None
    order: int


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)


class GoalOut(BaseModel):
    category_id: int
    name: str
    min_per_week: int = 0
    max_per_week: int | None = None
    is_default: bool = True


class GoalPatch(BaseModel):
    min_per_week: int = Field(default=0, ge=0, le=30)
    max_per_week: int | None = Field(default=None, ge=0, le=30)


class RecipeIngredientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    qty: float = Field(default=1, ge=0)
    unit: str | None = Field(default=None, max_length=40)


class RecipeIngredientOut(BaseModel):
    id: int
    name: str
    qty: float
    unit: str | None = None
    sort_order: int = 0


class RecipeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category_id: int
    slots: list[str] = Field(default_factory=list)
    notes: str | None = None
    ingredients: list[RecipeIngredientIn] = Field(default_factory=list)


class RecipeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: int | None = None
    slots: list[str] | None = None
    notes: str | None = None
    ingredients: list[RecipeIngredientIn] | None = None


class RecipeOut(BaseModel):
    id: int
    name: str
    category_id: int
    slots: list[str] = Field(default_factory=list)
    notes: str | None = None
    ingredients: list[RecipeIngredientOut] = Field(default_factory=list)


class MealPlanSet(BaseModel):
    recipe_id: int | None = None
    free_text: str | None = Field(default=None, max_length=200)


class MealPlanOut(BaseModel):
    date: date
    slot: str
    recipe_id: int | None = None
    recipe_name: str | None = None
    free_text: str | None = None


class WeekPlanOut(BaseModel):
    start: date
    plans: list[MealPlanOut] = Field(default_factory=list)


class CopyWeekIn(BaseModel):
    from_date: date
    to_date: date


class CopyWeekOut(BaseModel):
    copied: int


class RecommendIn(BaseModel):
    start: date


class RecommendOut(BaseModel):
    filled: int
    plans: list[MealPlanOut] = Field(default_factory=list)


class AddToShoppingIn(BaseModel):
    recipe_id: int | None = None
    start: date | None = None


class AddToShoppingOut(BaseModel):
    created: int
    updated: int