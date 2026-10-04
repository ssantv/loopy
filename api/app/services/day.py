"""Los bloques fijos de un día, en orden, y los huecos que quedan entre ellos.

`day_load` responde cuánto ocupa el día. Esto responde **qué** lo ocupa y de quién
es, que es lo que necesita el timeline para poder dibujar una línea honesta: un
"60 min" sin nombre no dice si hay que llevar a alguien o si oneself tiene cita.

Cuatro tipos de bloque, y la diferencia importa al leerlos:

- `cita`: la creó un adulto de la cuenta. Si además les afecta a niños, van en
  `affected`.
- `extraescolar`: la del propio usuario. Le ocupa solo a él.
- `extraescolar_compartida`: la de un hijo suya que hay que llevar. Le ocupa a él
  **y** al adulto, que es justo lo que hace que el día del adulto pierda el hueco.
- `comida`: una franja de comida activada. Solo se **muestra**: no resta de la
  carga del día (ver `Timeline`).

Las compartidas se listan una vez por hijo, no unidas: para el cálculo de minutos sí
se unen (ver `_minutos_unidos`), pero para mostrar hay que poder decir "llevar a
Lucía" y "llevar a Dani", que son dos viajes distintos aunque coincidan en hora.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.appointment import Appointment, AppointmentPerson
from app.models.menu import MealPlan, MealSlotConfig
from app.models.user import User
from app.services.appointments import citas_de
from app.services.load import day_load
from app.services.schedule import extras_compartidas_de, load_school_calendar
from app.services.tramos import une

CITA = "cita"
EXTRAESCOLAR = "extraescolar"
COMPARTIDA = "extraescolar_compartida"
COMIDA = "comida"

# Cuánto dura cada franja de comida.
#
# No hay ningún campo que lo guarde: `meal_slot_configs` solo tiene la hora
# (`default_time`). Son convenciones nuestras, no un dato que alguien haya escrito,
# y por eso van en una constante y no en la base de datos: si mañana se deciden otros
# valores, se cambian aquí y se ve el cambio en un sitio.
MINUTOS_POR_FRANJA = {
    "desayuno": 30,
    "almuerzo": 30,
    "comida": 60,
    "merienda": 20,
    "cena": 45,
}


@dataclass(frozen=True)
class Bloque:
    """Un rato que no se puede usar para otra cosa, con nombre y responsable."""

    kind: str
    title: str
    start: time
    end: time
    minutes: int
    place: str | None = None
    affected: tuple[str, ...] = ()
    cita_id: int | None = None
    extra_id: int | None = None
    slot: str | None = None


def _minutos(a: time, b: time) -> int:
    return max(0, (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute))


async def _citas_del_dia(db: AsyncSession, user_id: int, day: date) -> list[Appointment]:
    """Citas del usuario que caen en `day`.

    Reutiliza `citas_de` a propósito, aunque aquí solo haga falta el `Appointment`.
    Es la misma función que cuenta los minutos de `day-load`: si el timeline
    filtrara por su cuenta, cualquier diferencia entre las dos reglas (qué es una
    cita semanal, cuándo deja de existir) produciría dos días distintos para el
    mismo día, y el fallo aparecería semanas después y en el sitio equivocado.
    """
    return [o.cita for o in await citas_de(db, user_id, day)]


async def _nombres_por_cita(db: AsyncSession, citas: list[Appointment]) -> dict[int, list[str]]:
    """Nombre de los niños a los que afecta cada una de esas citas."""
    if not citas:
        return {}
    filas = (
        await db.execute(
            select(AppointmentPerson.cita_id, User.display_name)
            .join(User, User.id == AppointmentPerson.user_id)
            .where(AppointmentPerson.cita_id.in_([c.id for c in citas]))
            .order_by(User.display_name)
        )
    ).all()
    salida: dict[int, list[str]] = {}
    for cita_id, nombre in filas:
        salida.setdefault(cita_id, []).append(nombre or "?")
    return salida


async def _nombres_de_hijos(db: AsyncSession, parent_id: int) -> dict[int, str]:
    filas = (
        await db.execute(select(User.id, User.display_name).where(User.parent_id == parent_id))
    ).all()
    return {uid: (nombre or "?") for uid, nombre in filas}


async def _comidas_del_dia(db: AsyncSession, user: User, day: date) -> list[Bloque]:
    """Franjas de comida activadas que caen en `day`, con lo que haya planificado.

    Solo para adultos: el módulo de menú es suyo (§2.6) y un niño no tiene ni
    `meal_slot_configs` ni menú, así que preguntárselo solo daría una lista vacía
    con un paso extra por kid.

    Una franja activada **sin hora** no se pinta: sin `default_time` no hay sitio
    donde ponerla, y un bloque en las 00:00 sería peor que no tener bloque.
    """
    if user.profile_type != "adult":
        return []
    cfgs = (
        (
            await db.execute(
                select(MealSlotConfig).where(
                    MealSlotConfig.user_id == user.id, MealSlotConfig.enabled.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    if not cfgs:
        return []

    planes = {
        p.slot: p
        for p in (
            await db.execute(
                select(MealPlan)
                .options(selectinload(MealPlan.recipe))
                .where(MealPlan.user_id == user.id, MealPlan.date == day)
            )
        )
        .scalars()
        .all()
    }

    bloques: list[Bloque] = []
    for cfg in cfgs:
        if cfg.default_time is None:
            continue
        minutos = MINUTOS_POR_FRANJA.get(cfg.slot, 30)
        ini = cfg.default_time.hour * 60 + cfg.default_time.minute
        # Una cena a las 23:30 se sale del día. Se recorta al último minuto en vez
        # de dar la vuelta a medianoche: un bloque que empieza y acaba en el mismo
        # minuto es ruido, y un tramo "23:30–00:15" estaría hablando de mañana.
        fin = min(ini + minutos, 24 * 60 - 1)
        if fin <= ini:
            continue
        plan = planes.get(cfg.slot)
        plato = None
        if plan is not None:
            plato = plan.recipe.name if plan.recipe is not None else plan.free_text
        bloques.append(
            Bloque(
                kind=COMIDA,
                # Sin plato planificado se muestra la franja, que es lo que el
                # usuario activó: "desayuno" es más útil que un "Desayuno" vacío.
                title=plato or cfg.slot.capitalize(),
                start=cfg.default_time,
                end=time(fin // 60, fin % 60),
                minutes=fin - ini,
                slot=cfg.slot,
            )
        )
    return bloques


async def day_blocks(db: AsyncSession, user: User, day: date) -> list[Bloque]:
    """Todo lo que ocupa `day` a `user`, de más temprano a más tarde.

    El `User` entero y no solo su id porque las comidas dependen de que sea adulto:
    el menú es de adulto y preguntarle al niño costaría una consulta para nada.
    """
    user_id = user.id
    citas = await _citas_del_dia(db, user_id, day)
    nombres = await _nombres_por_cita(db, citas)

    bloques: list[Bloque] = [
        Bloque(
            kind=CITA,
            title=c.title,
            start=c.start_time,
            end=c.end_time,
            minutes=c.minutos,
            place=c.place,
            affected=tuple(nombres.get(c.id, [])),
            cita_id=c.id,
        )
        for c in citas
    ]

    cal = await load_school_calendar(db, user_id)
    for e in cal.extras_on(day):
        bloques.append(
            Bloque(
                kind=EXTRAESCOLAR,
                title=e.name,
                start=e.start_time,
                end=e.end_time,
                minutes=_minutos(e.start_time, e.end_time),
                extra_id=e.id,
            )
        )

    # Las de los hijos que además le ocupan a él: el bloque es del niño, pero el
    # adulto tiene que estar ahí, y el timeline tiene que decirlo.
    hijos = await _nombres_de_hijos(db, user_id)
    for e in await extras_compartidas_de(db, user_id, day):
        bloques.append(
            Bloque(
                kind=COMPARTIDA,
                title=e.name,
                start=e.start_time,
                end=e.end_time,
                minutes=_minutos(e.start_time, e.end_time),
                affected=(hijos.get(e.user_id, "?"),),
                extra_id=e.id,
            )
        )

    # Las comidas van al final y solo se pintan: se cuentan en los huecos, no en la
    # carga. Ver `Timeline`.
    bloques.extend(await _comidas_del_dia(db, user, day))

    bloques.sort(key=lambda b: (b.start, b.end, b.title))
    return bloques


# Horas que se consideran "en juego" al medir el hueco libre. De madrugada a las
# tres no hay nada que colocar, así que contar ese rato como disponible haría que
# cualquier día pareciera tener horas de sobra.
VENTANA_DIA = (7 * 60, 23 * 60)


def _a_minutos(t: time) -> int:
    """Una hora del día en minutos desde medianoche, el formato que usa `tramos`."""
    return t.hour * 60 + t.minute


@dataclass(frozen=True)
class Hueco:
    """Un tramo sin nada encima, en el que sí se puede colocar algo."""

    start: time
    end: time
    minutes: int


def _huecos(bloques: list[Bloque]) -> tuple[Hueco, ...]:
    """Los tramos de la ventana del día que no cubre ningún bloque.

    Se calcula por unión de los bloques y complemento, no restando: dos citas
    solapadas dejan un solo hueco, no dos, y restar sin más contaría el solape como
    tiempo disponible dos veces.

    Los bloques que caen fuera de la ventana (una extraescolar a las 6:00) se
    recortan a ella en vez de ignorarse, porque el rato que sí está dentro sigue
    dejando menos hueco.
    """
    ini, fin = VENTANA_DIA
    ocupados = une(
        (max(ini, _a_minutos(b.start)), min(fin, _a_minutos(b.end))) for b in bloques
    )

    huecos: list[Hueco] = []
    cursor = ini
    for a, z in ocupados:
        if a > cursor:
            huecos.append(Hueco(start=time(cursor // 60, cursor % 60), end=time(a // 60, a % 60), minutes=a - cursor))
        cursor = max(cursor, z)
    if cursor < fin:
        huecos.append(Hueco(start=time(cursor // 60, cursor % 60), end=time(fin // 60, fin % 60), minutes=fin - cursor))
    return tuple(huecos)


@dataclass(frozen=True)
class Timeline:
    """Los bloques del día y los huecos que quedan, en la misma unidad.

    `blocked_minutes` y `free_minutes` cuadran sobre la ventana del día salvo por dos
    cosas, y las dos son a propósito:

    - Las comidas se muestran y parten los huecos, pero **no se cobran**: comer ocupa
      el día, y si restaran de la carga, activar desayuno y cena le quitaría hora y
      pico de estudio a quien ya tiene el plan repartido.
    - Los huecos se recortan a 07:00-23:00, así que un bloque fuera de la ventana
      (una extraescolar a las 6:00) suma a `blocked_minutes` sin quitar hueco.

    Lo que sí cuadra es lo solapado: `blocked_minutes` cuenta cada minuto una vez, y
    por eso ninguna cita se pisa dos veces.

    Por eso los huecos se mandan aparte: quien quiera saber cuánto se puede estudiar
    usa `blocked_minutes`, y quien quiera saber cuándo puede colocar algo, los huecos.
    """

    blocks: tuple[Bloque, ...]
    blocked_minutes: int
    free_minutes: int
    huecos: tuple[Hueco, ...] = ()


async def day_timeline(db: AsyncSession, user: User, day: date) -> Timeline:
    """Timeline de `day`: qué ocupa el día y cuánto queda.

    `blocked_minutes` sale de `day_load` y no de sumar los bloques, a propósito.
    Los dos endpoints tienen que decir lo mismo sobre el mismo día: si el timeline
    contara de otra manera, la interfaz enseñaría dos cifras incompatibles y no
    habría forma de saber cuál era la buena.
    """
    bloques = await day_blocks(db, user, day)
    carga = await day_load(db, user, day)
    huecos = _huecos(list(bloques))
    return Timeline(
        blocks=tuple(bloques),
        blocked_minutes=carga.blocked_minutes,
        free_minutes=sum(h.minutes for h in huecos),
        huecos=huecos,
    )