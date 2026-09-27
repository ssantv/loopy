"""Tests del módulo menú de comidas (Roadmap paso 8)."""

from __future__ import annotations

from datetime import date, timedelta

from conftest import make_session_factory
from sqlalchemy import select

from app import models  # noqa: F401 - registra todas las tablas
from app.models.adult import ShoppingItem
from app.models.menu import (
    CategoryGoal,
    MealPlan,
    MealSlotConfig,
    Recipe,
    RecipeCategory,
    RecipeIngredient,
    slots_to_mask,
)
from app.models.user import User
from app.services.menu import (
    add_recipe_to_shopping,
    add_week_to_shopping,
    categories,
    copy_week,
    effective_goals,
    plans_in_range,
    recommend_week,
    slot_configs,
)

GLOBALS = {
    "pescado": (2, None),
    "verdura": (4, None),
    "legumbre": (2, None),
    "carne": (2, 3),
    "huevo": (1, None),
    "pasta/arroz": (2, 3),
}

SLOT_ORDER = ("desayuno", "almuerzo", "comida", "merienda", "cena")

MONDAY = date(2026, 9, 21)  # lunes


async def _session():
    maker = await make_session_factory()
    return maker


async def _user(db) -> int:
    u = User(email=f"menu_{id(db)}@x.com", password_hash="h", profile_type="adult")
    db.add(u)
    await db.flush()
    return u.id


async def _seed_globals(db) -> dict[str, int]:
    """Categorías globales por defecto (user_id NULL), como en la migración."""
    ids: dict[str, int] = {}
    for i, name in enumerate(GLOBALS, start=1):
        c = RecipeCategory(user_id=None, name=name, order=i)
        db.add(c)
        await db.flush()
        ids[name] = c.id
    return ids


async def _recipe(
    db,
    uid: int,
    name: str,
    category_id: int,
    slots: list[str],
    ingredients: list[tuple[str, float, str | None]] | None = None,
) -> int:
    r = Recipe(user_id=uid, name=name, category_id=category_id, slots_mask=slots_to_mask(slots))
    for i, (iname, qty, unit) in enumerate(ingredients or []):
        r.ingredients.append(RecipeIngredient(name=iname, qty=qty, unit=unit, sort_order=i))
    db.add(r)
    await db.flush()
    return r.id


async def _enable_slots(db, uid: int, slots: list[str]) -> None:
    for s in slots:
        db.add(MealSlotConfig(user_id=uid, slot=s, enabled=True))
    await db.flush()


async def _user_row(db, uid: int) -> User:
    return (await db.execute(select(User).where(User.id == uid))).scalar_one()


# ---------------------------------------------------------------- franjas

async def test_slot_configs_default_none_and_enable():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        cfg = await slot_configs(db, await _user_row(db, uid))
        await db.commit()
    assert cfg == {s: False for s in SLOT_ORDER}

    maker2 = await _session()
    async with maker2() as db:
        uid2 = await _user(db)
        await _enable_slots(db, uid2, ["comida", "cena"])
        await db.commit()
        cfg = await slot_configs(db, await _user_row(db, uid2))
    assert cfg["comida"] and cfg["cena"] and not cfg["desayuno"]


# ---------------------------------------------------------------- categorías + objetivos

async def test_categories_globals_and_own():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        await _seed_globals(db)
        own = RecipeCategory(user_id=uid, name="postres", order=1)
        db.add(own)
        await db.commit()
        cats = await categories(db, await _user_row(db, uid))
        names = [c.name for c in cats]
    assert "pescado" in names and "postres" in names
    assert len(cats) == 7


async def test_effective_goals_defaults():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        await _seed_globals(db)
        await db.commit()
        goals = {g["name"]: g for g in await effective_goals(db, await _user_row(db, uid))}
    for name, (mn, mx) in GLOBALS.items():
        assert goals[name]["min_per_week"] == mn
        assert goals[name]["max_per_week"] == mx
        assert goals[name]["is_default"] is True


async def test_goal_override_and_reset():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        ids = await _seed_globals(db)
        carne = ids["carne"]
        db.add(CategoryGoal(user_id=uid, recipe_category_id=carne, min_per_week=5, max_per_week=None))
        await db.commit()
        goals = {g["name"]: g for g in await effective_goals(db, await _user_row(db, uid))}
        assert goals["carne"]["min_per_week"] == 5 and goals["carne"]["max_per_week"] is None
        assert goals["carne"]["is_default"] is False


# ---------------------------------------------------------------- recomendar

async def test_recommend_fills_enabled_cells_with_variety():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        ids = await _seed_globals(db)
        await _enable_slots(db, uid, ["comida", "cena"])
        for i in range(5):
            await _recipe(db, uid, f"sopa{i}", ids["verdura"], ["comida", "cena"])
        await db.commit()
        created = await recommend_week(db, await _user_row(db, uid), MONDAY)
        usage = {}
        for p in created:
            usage[p.recipe_id] = usage.get(p.recipe_id, 0) + 1
        assert len(created) == 14  # 2 franjas × 7 días
        assert max(usage.values()) - min(usage.values()) <= 1  # variedad: reparto equilibrado


async def test_recommend_respects_max_per_week():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        ids = await _seed_globals(db)
        await _enable_slots(db, uid, ["comida", "cena"])
        for i in range(3):
            await _recipe(db, uid, f"chuleta{i}", ids["carne"], ["comida", "cena"])
        await db.commit()
        created = await recommend_week(db, await _user_row(db, uid), MONDAY)
    assert len(created) == 3  # carne tiene max 3


async def test_recommend_fills_only_compatible_slot():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        ids = await _seed_globals(db)
        await _enable_slots(db, uid, ["desayuno", "cena"])
        for i in range(3):
            await _recipe(db, uid, f"merluza{i}", ids["pescado"], ["cena"])
        await db.commit()
        created = await recommend_week(db, await _user_row(db, uid), MONDAY)
    assert len(created) == 7  # solo cena (7 días); desayuno queda vacío


async def test_recommend_no_recipes_returns_empty():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        await _seed_globals(db)
        await _enable_slots(db, uid, ["comida"])
        await db.commit()
        created = await recommend_week(db, await _user_row(db, uid), MONDAY)
    assert created == []


# ---------------------------------------------------------------- copiar

async def test_copy_week_overwrites_destination():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        ids = await _seed_globals(db)
        rid = await _recipe(db, uid, "lentejas", ids["legumbre"], ["comida"])
        db.add(MealPlan(user_id=uid, date=MONDAY, slot="comida", recipe_id=rid))
        db.add(MealPlan(user_id=uid, date=MONDAY + timedelta(days=1), slot="cena", free_text="pizza"))
        await db.commit()
        nxt = MONDAY + timedelta(days=7)
        user = await _user_row(db, uid)
        copied = await copy_week(db, user, MONDAY, nxt)
        plans = await plans_in_range(db, user, nxt, nxt + timedelta(days=6))
        assert copied == 2
        assert {p.slot for p in plans if p.recipe_id is not None} == {"comida"}
        assert {p.slot for p in plans if p.free_text} == {"cena"}


# ---------------------------------------------------------------- a la compra

async def test_add_recipe_to_shopping_creates_and_merges():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        ids = await _seed_globals(db)
        rid = await _recipe(
            db,
            uid,
            "pollo al horno",
            ids["carne"],
            ["comida"],
            [("pollo", 2, "kg"), ("patatas", 4, "ud")],
        )
        await db.commit()
        user = await _user_row(db, uid)

        first = await add_recipe_to_shopping(db, user, rid)
        assert first == {"created": 2, "updated": 0}
        second = await add_recipe_to_shopping(db, user, rid)
        assert second == {"created": 0, "updated": 2}

        lines = (await db.execute(select(ShoppingItem).where(ShoppingItem.user_id == uid))).scalars().all()
        by_name = {i.name: i for i in lines}
        assert by_name["pollo"].qty == "4 kg"
        assert by_name["patatas"].qty == "8 ud"
        assert {i.source for i in lines} == {"plan"}


async def test_add_week_aggregates_shared_ingredient():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        ids = await _seed_globals(db)
        r1 = await _recipe(db, uid, "pan", ids["legumbre"], ["comida"], [("harina", 300, "g")])
        r2 = await _recipe(db, uid, "tortitas", ids["legumbre"], ["comida"], [("harina", 200, "g")])
        db.add(MealPlan(user_id=uid, date=MONDAY, slot="comida", recipe_id=r1))
        db.add(MealPlan(user_id=uid, date=MONDAY + timedelta(days=1), slot="comida", recipe_id=r2))
        await db.commit()
        user = await _user_row(db, uid)
        result = await add_week_to_shopping(db, user, MONDAY)
        lines = (await db.execute(select(ShoppingItem).where(ShoppingItem.user_id == uid))).scalars().all()
    assert result == {"created": 1, "updated": 0}
    assert len(lines) == 1
    assert lines[0].qty == "500 g"
    assert lines[0].source_ref == "pan, tortitas"


async def test_add_recipe_creates_new_when_only_purchased():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        ids = await _seed_globals(db)
        rid = await _recipe(db, uid, "tortilla", ids["huevo"], ["comida"], [("huevos", 6, "ud")])
        db.add(ShoppingItem(user_id=uid, name="huevos", qty="6 ud", source="manual", purchased=True))
        await db.commit()
        user = await _user_row(db, uid)
        result = await add_recipe_to_shopping(db, user, rid)
        pending = (
            await db.execute(
                select(ShoppingItem).where(ShoppingItem.user_id == uid, ShoppingItem.purchased.is_(False))
            )
        ).scalars().all()
    assert result == {"created": 1, "updated": 0}
    assert len(pending) == 1  # línea pendiente nueva aunque esté comprada
    assert pending[0].qty == "6 ud"