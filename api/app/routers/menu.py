"""Router del módulo menú de comidas (solo adulto). Planteamiento §2.6.

Franjas, categorías + objetivos, recetas + ingredientes, plan semanal con
"copiar semana" y "recomendar huecos", y añadido a la compra (fusionando).
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import CategoryGoal, MealPlan, MealSlotConfig, Recipe, RecipeCategory, RecipeIngredient
from app.models.menu import SLOTS, mask_to_slots, slot_bit, slots_to_mask
from app.models.user import User
from app.routers.adult import _require_adult
from app.routers.auth import get_current_user
from app.schemas.menu import (
    AddToShoppingIn,
    AddToShoppingOut,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    CopyWeekIn,
    CopyWeekOut,
    GoalOut,
    GoalPatch,
    MealPlanOut,
    MealPlanSet,
    RecipeIn,
    RecipeOut,
    RecipeUpdate,
    RecommendIn,
    RecommendOut,
    SlotConfigOut,
    SlotConfigPatch,
    SlotConfigsOut,
    WeekPlanOut,
)
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

router = APIRouter(prefix="/api/menu", tags=["menu"])


def _recipe_out(r: Recipe) -> RecipeOut:
    return RecipeOut(
        id=r.id,
        name=r.name,
        category_id=r.category_id,
        slots=mask_to_slots(r.slots_mask),
        notes=r.notes,
        ingredients=[
            {
                "id": ing.id,
                "name": ing.name,
                "qty": float(ing.qty),
                "unit": ing.unit,
                "sort_order": ing.sort_order,
            }
            for ing in r.ingredients
        ],
    )


def _plan_out(p: MealPlan) -> MealPlanOut:
    return MealPlanOut(
        date=p.date,
        slot=p.slot,
        recipe_id=p.recipe_id,
        recipe_name=p.recipe.name if p.recipe else None,
        free_text=p.free_text,
    )


def _check_slot(slot: str) -> None:
    if slot not in SLOTS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Franja inválida")


async def _own_category(category_id: int, user: User, db: AsyncSession) -> RecipeCategory:
    cat = (
        await db.execute(
            select(RecipeCategory).where(
                RecipeCategory.id == category_id,
                (RecipeCategory.user_id.is_(None)) | (RecipeCategory.user_id == user.id),
            )
        )
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoría no encontrada")
    return cat


# ---------------------------------------------------------------- franjas

@router.get("/slots", response_model=SlotConfigsOut)
async def get_slots(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SlotConfigsOut:
    _require_adult(user)
    cfg = await slot_configs(db, user)
    rows = (await db.execute(select(MealSlotConfig).where(MealSlotConfig.user_id == user.id))).scalars().all()
    times = {c.slot: c.default_time for c in rows}
    return SlotConfigsOut(slots=[SlotConfigOut(slot=s, enabled=cfg[s], default_time=times.get(s)) for s in SLOTS])


@router.patch("/slots/{slot}", response_model=SlotConfigOut)
async def patch_slot(
    slot: str,
    payload: SlotConfigPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SlotConfigOut:
    _require_adult(user)
    _check_slot(slot)
    conf = (
        await db.execute(
            select(MealSlotConfig).where(MealSlotConfig.user_id == user.id, MealSlotConfig.slot == slot)
        )
    ).scalar_one_or_none()
    if conf is None:
        conf = MealSlotConfig(user_id=user.id, slot=slot, enabled=False)
        db.add(conf)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None or key == "enabled":
            setattr(conf, key, value)
    await db.commit()
    await db.refresh(conf)
    return SlotConfigOut(slot=conf.slot, enabled=conf.enabled, default_time=conf.default_time)


# ---------------------------------------------------------------- categorías + objetivos

@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[CategoryOut]:
    _require_adult(user)
    return [CategoryOut(**c.__dict__) for c in await categories(db, user)]


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CategoryOut:
    _require_adult(user)
    dup = (
        await db.execute(
            select(RecipeCategory).where(
                RecipeCategory.user_id == user.id,
                RecipeCategory.name.ilike(payload.name.strip()),
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya tienes una categoría con ese nombre")
    max_order = (
        await db.execute(
            select(RecipeCategory)
            .where(RecipeCategory.user_id == user.id)
            .order_by(RecipeCategory.order.desc())
        )
    ).scalars().first()
    cat = RecipeCategory(
        user_id=user.id, name=payload.name.strip(), order=(max_order.order + 1 if max_order else 1)
    )
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return CategoryOut(**cat.__dict__)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def patch_category(
    category_id: int,
    payload: CategoryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CategoryOut:
    _require_adult(user)
    cat = await _own_category(category_id, user, db)
    if cat.user_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Las categorías globales no se renombran")
    if payload.name is not None and payload.name.strip() and payload.name.strip() != cat.name:
        cat.name = payload.name.strip()
        await db.commit()
        await db.refresh(cat)
    return CategoryOut(**cat.__dict__)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    _require_adult(user)
    cat = await _own_category(category_id, user, db)
    if cat.user_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Las categorías globales no se borran")
    has_recipes = (
        await db.execute(select(Recipe.id).where(Recipe.category_id == cat.id, Recipe.user_id == user.id).limit(1))
    ).first()
    if has_recipes is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mueve o borra sus recetas antes")
    await db.delete(cat)
    await db.commit()


@router.get("/goals", response_model=list[GoalOut])
async def get_goals(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[GoalOut]:
    _require_adult(user)
    return [GoalOut(**g) for g in await effective_goals(db, user)]


@router.patch("/goals/{category_id}", response_model=GoalOut)
async def patch_goal(
    category_id: int,
    payload: GoalPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoalOut:
    _require_adult(user)
    await _own_category(category_id, user, db)
    g = (
        await db.execute(
            select(CategoryGoal).where(CategoryGoal.user_id == user.id, CategoryGoal.recipe_category_id == category_id)
        )
    ).scalar_one_or_none()
    if g is None:
        g = CategoryGoal(user_id=user.id, recipe_category_id=category_id, min_per_week=0)
        db.add(g)
    g.min_per_week = payload.min_per_week
    g.max_per_week = payload.max_per_week
    await db.commit()
    await db.refresh(g)
    goals = {x["category_id"]: x for x in await effective_goals(db, user)}
    return GoalOut(**goals[category_id])


@router.delete("/goals/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    category_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    _require_adult(user)
    await db.execute(
        CategoryGoal.__table__.delete().where(
            CategoryGoal.user_id == user.id, CategoryGoal.recipe_category_id == category_id
        )
    )
    await db.commit()


# ---------------------------------------------------------------- recetas

@router.get("/recipes", response_model=list[RecipeOut])
async def list_recipes(
    category_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RecipeOut]:
    _require_adult(user)
    q = select(Recipe).options(selectinload(Recipe.ingredients)).where(Recipe.user_id == user.id)
    if category_id is not None:
        q = q.where(Recipe.category_id == category_id)
    rows = (await db.execute(q.order_by(Recipe.name))).scalars().all()
    return [_recipe_out(r) for r in rows]


@router.post("/recipes", response_model=RecipeOut, status_code=status.HTTP_201_CREATED)
async def create_recipe(
    payload: RecipeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecipeOut:
    _require_adult(user)
    cat = await _own_category(payload.category_id, user, db)
    if cat.user_id is not None and cat.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoría no encontrada")
    bad = [s for s in payload.slots if s not in SLOTS]
    if bad:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Franja inválida")
    recipe = Recipe(
        user_id=user.id,
        name=payload.name.strip(),
        category_id=payload.category_id,
        slots_mask=slots_to_mask(payload.slots),
        notes=payload.notes,
    )
    for i, ing in enumerate(payload.ingredients):
        recipe.ingredients.append(
            RecipeIngredient(name=ing.name.strip(), qty=ing.qty, unit=ing.unit, sort_order=i)
        )
    db.add(recipe)
    await db.commit()
    await db.refresh(recipe)
    refresh_ing = await db.execute(
        select(Recipe).options(selectinload(Recipe.ingredients)).where(Recipe.id == recipe.id)
    )
    return _recipe_out(refresh_ing.scalar_one())


@router.patch("/recipes/{recipe_id}", response_model=RecipeOut)
async def patch_recipe(
    recipe_id: int,
    payload: RecipeUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecipeOut:
    _require_adult(user)
    recipe = (
        await db.execute(
            select(Recipe)
            .options(selectinload(Recipe.ingredients))
            .where(Recipe.id == recipe_id, Recipe.user_id == user.id)
        )
    ).scalar_one_or_none()
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receta no encontrada")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        recipe.name = data["name"].strip()
    if "category_id" in data:
        await _own_category(data["category_id"], user, db)
        recipe.category_id = data["category_id"]
    if "slots" in data:
        bad = [s for s in data["slots"] if s not in SLOTS]
        if bad:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Franja inválida")
        recipe.slots_mask = slots_to_mask(data["slots"])
    if "notes" in data:
        recipe.notes = data["notes"]
    if "ingredients" in data:
        recipe.ingredients.clear()
        for i, ing in enumerate(data["ingredients"]):
            recipe.ingredients.append(
                RecipeIngredient(name=ing["name"].strip(), qty=ing["qty"], unit=ing["unit"], sort_order=i)
            )
    await db.commit()
    await db.refresh(recipe)
    refresh_ing = await db.execute(
        select(Recipe).options(selectinload(Recipe.ingredients)).where(Recipe.id == recipe_id)
    )
    return _recipe_out(refresh_ing.scalar_one())


@router.delete("/recipes/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipe(
    recipe_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    _require_adult(user)
    recipe = (
        await db.execute(select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user.id))
    ).scalar_one_or_none()
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receta no encontrada")
    await db.delete(recipe)
    await db.commit()


# ---------------------------------------------------------------- plan semanal

def _start(start: date) -> date:
    return start - timedelta(days=start.weekday())


@router.get("/plan", response_model=WeekPlanOut)
async def get_plan(
    start: date = Query(description="Inicio de la semana (lunes); se normaliza a lunes"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WeekPlanOut:
    _require_adult(user)
    monday = _start(start)
    rows = await plans_in_range(db, user, monday, monday + timedelta(days=6))
    return WeekPlanOut(start=monday, plans=[_plan_out(p) for p in rows])


@router.put("/plan/{day}/{slot}", response_model=MealPlanOut)
async def set_plan(
    day: date,
    slot: str,
    payload: MealPlanSet,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MealPlanOut:
    _require_adult(user)
    _check_slot(slot)
    if payload.recipe_id is None and (payload.free_text is None or not payload.free_text.strip()):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Indica receta o texto libre")
    if payload.recipe_id is not None:
        recipe = (
            await db.execute(select(Recipe).where(Recipe.id == payload.recipe_id, Recipe.user_id == user.id))
        ).scalar_one_or_none()
        if recipe is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receta no encontrada")
        if not (recipe.slots_mask & slot_bit(slot)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La receta no se ajusta a esa franja")
    row = (
        await db.execute(
            select(MealPlan)
            .options(selectinload(MealPlan.recipe))
            .where(MealPlan.user_id == user.id, MealPlan.date == day, MealPlan.slot == slot)
        )
    ).scalar_one_or_none()
    if row is None:
        row = MealPlan(user_id=user.id, date=day, slot=slot)
        db.add(row)
    row.recipe_id = payload.recipe_id
    row.free_text = payload.free_text.strip() if payload.free_text else None
    await db.commit()
    await db.refresh(row)
    row = (
        await db.execute(select(MealPlan).options(selectinload(MealPlan.recipe)).where(MealPlan.id == row.id))
    ).scalar_one()
    return _plan_out(row)


@router.delete("/plan/{day}/{slot}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_plan(
    day: date, slot: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    _require_adult(user)
    _check_slot(slot)
    await db.execute(
        MealPlan.__table__.delete().where(MealPlan.user_id == user.id, MealPlan.date == day, MealPlan.slot == slot)
    )
    await db.commit()


@router.post("/plan/copy", response_model=CopyWeekOut)
async def copy_week_ep(
    payload: CopyWeekIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CopyWeekOut:
    _require_adult(user)
    copied = await copy_week(db, user, _start(payload.from_date), _start(payload.to_date))
    return CopyWeekOut(copied=copied)


@router.post("/plan/recommend", response_model=RecommendOut)
async def recommend_ep(
    payload: RecommendIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecommendOut:
    _require_adult(user)
    monday = _start(payload.start)
    created = await recommend_week(db, user, monday)
    return RecommendOut(filled=len(created), plans=[_plan_out(p) for p in created])


# ---------------------------------------------------------------- a la compra

@router.post("/shopping", response_model=AddToShoppingOut)
async def add_to_shopping(
    payload: AddToShoppingIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AddToShoppingOut:
    _require_adult(user)
    if payload.recipe_id:
        return AddToShoppingOut(**await add_recipe_to_shopping(db, user, payload.recipe_id))
    if payload.start:
        return AddToShoppingOut(**await add_week_to_shopping(db, user, _start(payload.start)))
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Indica receta o semana")