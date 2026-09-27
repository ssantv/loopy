"""Lógica del menú de comidas (adulto). Planteamiento §2.6.

Franjas, categorías + objetivos eficaces, recetas + ingredientes, planificador
semanal con "copiar semana" y "recomendar para huecos", y añadido a la compra
con fusión por nombre normalizado.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.adult import ShoppingItem
from app.models.menu import (
    SLOTS,
    CategoryGoal,
    MealPlan,
    MealSlotConfig,
    Recipe,
    RecipeCategory,
    slot_bit,
)
from app.models.user import User
from app.services.shopping import normalize_name

# Objetivos por defecto por NOMBRE de categoría global (§2.6).
DEFAULT_GOALS: dict[str, tuple[int, int | None]] = {
    "pescado": (2, None),
    "verdura": (4, None),
    "legumbre": (2, None),
    "carne": (2, 3),
    "huevo": (1, None),
    "pasta/arroz": (2, 3),
}

_QTY = re.compile(r"^([\d]+(?:[.,]\d+)?)\s*(.*)$")


# ---------------------------------------------------------------- consultas

async def categories(db: AsyncSession, user: User) -> list[RecipeCategory]:
    """Categorías globales (user_id NULL) + las propias del usuario, ordenadas."""
    rows = await db.execute(
        select(RecipeCategory)
        .where(RecipeCategory.user_id.is_(None) | (RecipeCategory.user_id == user.id))
        .order_by(RecipeCategory.order, RecipeCategory.name)
    )
    return list(rows.scalars().all())


async def effective_goals(db: AsyncSession, user: User) -> list[dict]:
    """Objetivo eficaz por categoría: fila del usuario o, si no la hay, el
    default por defecto (categorías globales) o 0/sin máximo."""
    cats = await categories(db, user)
    rows = (await db.execute(select(CategoryGoal).where(CategoryGoal.user_id == user.id))).scalars().all()
    custom = {g.recipe_category_id: g for g in rows}
    out: list[dict] = []
    for cat in cats:
        if cat.id in custom:
            g = custom[cat.id]
            out.append(
                {
                    "category_id": cat.id,
                    "name": cat.name,
                    "min_per_week": g.min_per_week,
                    "max_per_week": g.max_per_week,
                    "is_default": False,
                }
            )
        elif cat.user_id is None and cat.name in DEFAULT_GOALS:
            mn, mx = DEFAULT_GOALS[cat.name]
            out.append(
                {
                    "category_id": cat.id,
                    "name": cat.name,
                    "min_per_week": mn,
                    "max_per_week": mx,
                    "is_default": True,
                }
            )
        else:
            out.append(
                {
                    "category_id": cat.id,
                    "name": cat.name,
                    "min_per_week": 0,
                    "max_per_week": None,
                    "is_default": True,
                }
            )
    return out


async def slot_configs(db: AsyncSession, user: User) -> dict[str, bool]:
    """Franjas habilitadas del usuario (ninguna activa por defecto)."""
    found = (await db.execute(select(MealSlotConfig).where(MealSlotConfig.user_id == user.id))).scalars().all()
    by_slot = {c.slot: c for c in found}
    cfg: dict[str, bool] = {}
    for s in SLOTS:
        c = by_slot.get(s)
        cfg[s] = bool(c and c.enabled)
    return cfg


async def plans_in_range(db: AsyncSession, user: User, start: date, end: date) -> list[MealPlan]:
    rows = await db.execute(
        select(MealPlan)
        .options(selectinload(MealPlan.recipe).selectinload(Recipe.ingredients))
        .where(MealPlan.user_id == user.id, MealPlan.date >= start, MealPlan.date <= end)
        .order_by(MealPlan.date, MealPlan.slot)
    )
    return list(rows.scalars().all())


# ---------------------------------------------------------------- recomendar

async def recommend_week(db: AsyncSession, user: User, start: date) -> list[MealPlan]:
    """Rellena huecos (franjas activas sin asignar) de `start..start+6`.

    Puntúa por déficit de `min_per_week` (respetando máximos), variedad (no
    repetir la receta en la semana si hay alternativa) y adecuación de franja.
    """
    end = start + timedelta(days=6)
    plans = await plans_in_range(db, user, start, end)
    occupied = {(p.date, p.slot) for p in plans}
    recipes = (
        (await db.execute(select(Recipe).where(Recipe.user_id == user.id).order_by(Recipe.id))).scalars().all()
    )
    if not recipes:
        return []
    enabled = {s for s in SLOTS if (await slot_configs(db, user)).get(s)}
    goals = {g["category_id"]: g for g in await effective_goals(db, user)}

    cat_usage = Counter(p.recipe.category_id for p in plans if p.recipe)
    recipe_usage = Counter(p.recipe_id for p in plans if p.recipe)

    created: list[MealPlan] = []
    for offset in range(7):
        d = start + timedelta(days=offset)
        for slot in sorted(enabled, key=SLOTS.index):
            if (d, slot) in occupied:
                continue
            pick = _pick(recipes, slot, goals, cat_usage, recipe_usage)
            if pick is None:
                continue
            plan = MealPlan(user_id=user.id, date=d, slot=slot, recipe_id=pick.id)
            db.add(plan)
            created.append(plan)
            occupied.add((d, slot))
            cat_usage[pick.category_id] += 1
            recipe_usage[pick.id] += 1
    await db.commit()
    if not created:
        return []
    ids = [p.id for p in created]
    return (
        (
            await db.execute(
                select(MealPlan).options(selectinload(MealPlan.recipe)).where(MealPlan.id.in_(ids))
            )
        )
        .scalars()
        .all()
    )


def _pick(recipes: list[Recipe], slot: str, goals: dict, cat_usage: Counter, recipe_usage: Counter) -> Recipe | None:
    best: tuple | None = None
    best_recipe: Recipe | None = None
    for r in recipes:
        if not (r.slots_mask & slot_bit(slot)):
            continue
        g = goals.get(r.category_id, {"min_per_week": 0, "max_per_week": None})
        mx = g["max_per_week"]
        if mx is not None and cat_usage[r.category_id] >= mx:
            continue
        deficit = max(0, g["min_per_week"] - cat_usage[r.category_id])
        key = (-deficit, recipe_usage[r.id], cat_usage[r.category_id], r.id)
        if best is None or key < best:
            best, best_recipe = key, r
    return best_recipe


# ---------------------------------------------------------------- copiar

async def copy_week(db: AsyncSession, user: User, from_date: date, to_date: date) -> int:
    """Copia `from_date..+6` a `to_date..+6` (sobrescribe los destinos)."""
    src = await plans_in_range(db, user, from_date, from_date + timedelta(days=6))
    dst_start, dst_end = to_date, to_date + timedelta(days=6)
    existing = await plans_in_range(db, user, dst_start, dst_end)
    for p in existing:
        await db.delete(p)
    await db.flush()
    created = 0
    for p in src:
        db.add(
            MealPlan(
                user_id=user.id,
                date=to_date + (p.date - from_date),
                slot=p.slot,
                recipe_id=p.recipe_id,
                free_text=p.free_text,
            )
        )
        created += 1
    await db.commit()
    return created


# ---------------------------------------------------------------- a la compra

async def add_week_to_shopping(db: AsyncSession, user: User, start: date) -> dict:
    recipes = [p.recipe for p in await plans_in_range(db, user, start, start + timedelta(days=6)) if p.recipe]
    return await _add_recipe_ingredients(db, user, recipes)


async def add_recipe_to_shopping(db: AsyncSession, user: User, recipe_id: int) -> dict:
    recipe = (
        await db.execute(
            select(Recipe)
            .options(selectinload(Recipe.ingredients))
            .where(Recipe.id == recipe_id, Recipe.user_id == user.id)
        )
    ).scalar_one_or_none()
    recipes = [recipe] if recipe is not None else []
    return await _add_recipe_ingredients(db, user, recipes)


async def _add_recipe_ingredients(db: AsyncSession, user: User, recipes: list[Recipe]) -> dict:
    """Fusiona los ingredientes de las recetas en la lista pendiente.

    Nombres normalizados; si ya hay línea pendiente del mismo nombre se suman
    las cantidades (mismas unidades); si solo existe comprada, se crea una nueva
    línea pendiente.
    """
    agg: dict[str, dict] = {}
    for r in recipes:
        for ing in r.ingredients:
            key = normalize_name(ing.name)
            entry = agg.setdefault(key, {"name": ing.name, "qty": 0.0, "unit": ing.unit, "recipes": set()})
            entry["qty"] += float(ing.qty)
            entry["unit"] = ing.unit or entry["unit"]
            entry["recipes"].add(r.name)

    existing = (
        (
            await db.execute(
                select(ShoppingItem).where(
                    ShoppingItem.user_id == user.id,
                    ShoppingItem.deleted_at.is_(None),
                    ShoppingItem.purchased.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    by_name = {normalize_name(i.name): i for i in existing}

    created, updated = 0, 0
    for key, entry in agg.items():
        qty_text = _fmt_qty(entry["qty"], entry["unit"])
        ref = ", ".join(sorted(entry["recipes"])) or None
        item = by_name.get(key)
        if item is None:
            db.add(
                ShoppingItem(
                    user_id=user.id,
                    name=entry["name"],
                    qty=qty_text or None,
                    source="plan",
                    source_ref=ref,
                )
            )
            created += 1
        else:
            item.qty = _merge_qty(item.qty, qty_text)
            item.source = "plan"
            item.source_ref = ref or item.source_ref
            updated += 1
    await db.commit()
    return {"created": created, "updated": updated}


def _fmt_qty(qty: float, unit: str | None) -> str:
    if unit is None and qty <= 1:
        return ""
    if unit:
        return f"{qty:g} {unit}"
    return f"{qty:g}"


def _merge_qty(old: str | None, new_qty: str) -> str | None:
    """Suma numérica cuando ambas cantidades comparten unidad; si no, conserva
    la existente salvo que no haya nada."""
    if not new_qty:
        return old
    if not old:
        return new_qty
    m1, m2 = _QTY.match(old), _QTY.match(new_qty)
    if m1 and m2 and m1.group(2) == m2.group(2):
        total = float(m1.group(1).replace(",", ".")) + float(m2.group(1).replace(",", "."))
        return f"{total:g} {m2.group(2)}".strip()
    return old