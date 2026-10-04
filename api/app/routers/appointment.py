"""Citas de la familia: bloques fijos que no se mueven.

Solo las crea el perfil adulto, porque es el que conoce la agenda. Al crearla dice a
quién afecta: a él solo, o a él y a alguno de sus niños. Esa información no es
decorativa: una cita que afecta a un niño le descuenta a **ese** niño el rato en su
propio día, que es como un niño se entera de que el lunes hay dentista.

Un niño no puede crear ni tocar citas, pero sí las ve en su carga del día si le
afectan.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.appointment import Appointment, AppointmentPerson
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentOut,
    AppointmentPersonOut,
    AppointmentUpdate,
)
from app.services.appointments import citas_de
from app.services.clock import hoy

router = APIRouter(prefix="/api/appointments", tags=["appointments"])


def _require_adult(user: User) -> None:
    if user.profile_type != "adult":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Las citas las crea el perfil adulto",
        )


async def _hijos_de(adult: User, db: AsyncSession) -> list[User]:
    return list(
        (await db.execute(select(User).where(User.parent_id == adult.id).order_by(User.display_name))).scalars().all()
    )


async def _afectados_validos(adult: User, ids: list[int], db: AsyncSession) -> list[User]:
    """Traduce ids de niños a usuarios, rechazando los que no son de esta cuenta.

    Sin esto, un adulto podría colgar de su cita al hijo de otro: bastante grave,
    porque ese niño vería en su día un bloque que no es suyo y el adulto podría
    dejar de verlo en el suyo.
    """
    if not ids:
        return []
    hijos = await _hijos_de(adult, db)
    por_id = {h.id: h for h in hijos}
    malos = [i for i in ids if i not in por_id]
    if malos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Estas personas no son niños de tu cuenta: {malos}",
        )
    return [por_id[i] for i in dict.fromkeys(ids)]


async def _get_owned(cita_id: int, user: User, db: AsyncSession) -> Appointment:
    cita = (
        await db.execute(
            select(Appointment)
            .where(Appointment.id == cita_id)
            .options(selectinload(Appointment.afectados))
        )
    ).scalar_one_or_none()
    # Solo el adulto que la creó la edita. Los niños la ven en su carga, pero no la
    # tocan: quien organiza la casa es el adulto.
    if cita is None or cita.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cita no encontrada")
    return cita


def _out(cita: Appointment, afectados: list[AppointmentPersonOut]) -> AppointmentOut:
    return AppointmentOut(
        id=cita.id,
        owner_id=cita.owner_id,
        title=cita.title,
        place=cita.place,
        notes=cita.notes,
        date=cita.first_on,
        start_time=cita.start_time,
        end_time=cita.end_time,
        repeats_weekly=cita.repeats_weekly,
        until=cita.until,
        minutes=cita.minutos,
        affected=afectados,
    )


async def _nombres_afectados(cita: Appointment, db: AsyncSession) -> list[AppointmentPersonOut]:
    """Nombres de los afectados: `selectinload` carga las filas puente pero no sabe
    el `display_name`, que vive en `users`."""
    if not cita.afectados:
        return []
    ids = [ap.user_id for ap in cita.afectados]
    nombres = dict(
        (await db.execute(select(User.id, User.display_name).where(User.id.in_(ids)))).all()
    )
    return [
        AppointmentPersonOut(id=ap.user_id, display_name=nombres.get(ap.user_id) or "?")
        for ap in cita.afectados
    ]


async def _salida(cita: Appointment, db: AsyncSession) -> AppointmentOut:
    return _out(cita, await _nombres_afectados(cita, db))


# ---------------------------------------------------------------- CRUD


@router.get("", response_model=list[AppointmentOut])
async def listar(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
) -> list[AppointmentOut]:
    """Citas que me afectan en un rango de fechas. Sin rango, solo el día de hoy.

    El "hoy" es el del usuario, no el del servidor: en Chile pueden ser 8 horas de
    diferencia, y el listado volvería vacío justo en las últimas horas del día.

    Devuelve cada cita una vez, aunque la persona sea a la vez su creadora y una de
    los afectados: ese caso real (el cumpleaños de un hijo, que también es del
    adulto) saldría duplicado por preguntar dos veces a `citas_de`.
    """
    _require_adult(user)
    primero = desde or hoy(user)
    ultimo = hasta or primero

    vistas: dict[int, Appointment] = {}
    for i in range((ultimo - primero).days + 1):
        for o in await citas_de(db, user.id, primero + timedelta(days=i)):
            vistas.setdefault(o.cita.id, o.cita)

    salida = [await _salida(cita, db) for cita in vistas.values()]
    salida.sort(key=lambda c: (c.date, c.start_time))
    return salida


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def crear(
    payload: AppointmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AppointmentOut:
    _require_adult(user)
    hijos = await _afectados_validos(user, payload.affected_user_ids, db)
    cita = Appointment(
        owner_id=user.id,
        title=payload.title.strip(),
        place=payload.place,
        notes=payload.notes,
        first_on=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        repeats_weekly=payload.repeats_weekly,
        until=payload.until,
    )
    cita.afectados = [AppointmentPerson(user_id=h.id) for h in hijos]
    db.add(cita)
    await db.flush()
    await db.commit()
    return await _salida(cita, db)


@router.patch("/{cita_id}", response_model=AppointmentOut)
async def editar(
    cita_id: int,
    payload: AppointmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AppointmentOut:
    _require_adult(user)
    cita = await _get_owned(cita_id, user, db)
    cambios = payload.model_dump(exclude_unset=True)
    afectados_ids = cambios.pop("affected_user_ids", None)

    for key, value in cambios.items():
        if value is not None:
            setattr(cita, "first_on" if key == "date" else key, value)

    # Apagar la repetición sin poner fecha dejaría un `until` colgando que no
    # significa nada, así que los dos campos van siempre juntos.
    if cita.until is not None and not cita.repeats_weekly:
        cita.until = None
    if cita.end_time <= cita.start_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La cita tiene que terminar después de empezar",
        )
    if cita.until is not None and cita.until < cita.first_on:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La cita no puede repetirse hasta un día anterior al primero",
        )

    if afectados_ids is not None:
        hijos = await _afectados_validos(user, afectados_ids, db)
        await db.execute(delete(AppointmentPerson).where(AppointmentPerson.cita_id == cita.id))
        cita.afectados = [AppointmentPerson(user_id=h.id) for h in hijos]

    await db.flush()
    await db.commit()
    await db.refresh(cita)
    return await _salida(cita, db)


@router.delete("/{cita_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar(
    cita_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    _require_adult(user)
    cita = await _get_owned(cita_id, user, db)
    await db.delete(cita)
    await db.commit()


@router.get("/day/{day}", response_model=list[AppointmentOut])
async def del_dia(
    day: date,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AppointmentOut]:
    """Citas de un día, para pintar la línea de tiempo.

    Es lo mismo que el listado con rango, pero con un objetivo distinto: aquí
    importa el orden y el hueco entre una cita y la siguiente, no editar nada.
    """
    return [await _salida(o.cita, db) for o in await citas_de(db, user.id, day)]