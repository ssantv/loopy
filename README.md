# Loopy

App de organización personal multiusuario con **dos perfiles independientes por cuenta**: **Adulto** (recordatorios, hogar, compra, menú, resumen diario) y **Niño** (deberes, trabajos, exámenes con plan de estudio automático, check-in diario).

> Estado actual: el **modelo familiar** está cerrado — la cuenta del niño la crea un adulto y entra con nombre y PIN —, y el **contexto escolar** está montado: horario semanal, días sin cole, plantillas de deber y reparto del plan de estudio saltando los días sin clase, con tope diario de estudio por niño.
>
> Lo siguiente en el roadmap: **Mi día** (la principal como pantalla única de decisión) → temporizador y avisos inteligentes → **Organiza tu tarde** (adulto) → calendario y offline → cierre.

## Navegación

Pensada para pantallas pequeñas y para quien tiene dificultades de organización, así que hay **una sola puerta de entrada y muy pocas decisiones**:

- **Siempre 3 destinos de primer nivel**, en el mismo orden: **Mi día** · **Colegio** (niño) o **Casa** (adulto) · **Calendario**.
- En **móvil** van en una **barra fija abajo** (al alcance del pulgar); en escritorio, en la cabecera.
- "Mi día" está siempre visible y marcado, así que nunca se pierde el camino de vuelta.
- Las páginas de un área (**Menú/Compra/Resumen**, **Check-in**) van en una subnavegación dentro del área, no en la barra.
- **"Salir"** está en el menú de usuario de la cabecera, para no competir con la navegación.
- Todo lo accionable está en la principal: qué toca hoy, atrasadas, adelantadas, deberes con cuenta atrás, próximos exámenes y el calendario.
- En el área de **Colegio**, la subnavegación incluye **Perfil**, que es donde se configura el curso del niño y sus asignaturas.

## Perfil del niño

Todo lo que el planificador necesita saber del niño está en **Colegio → Perfil**, en un solo sitio:

- **Curso** ("5º de Primaria"), para tener el contexto a la vista.
- **Asignaturas**, cada una con su **color**. Ese color es el que identifica la asignatura en el calendario, así que es la "forma de marcar" los planes: el punto de cada día lleva el color de su asignatura, y una **leyenda** al pie del mes traduce color → asignatura.
- **Tiempo por asignatura**, en **minutos**: "Matemáticas unas 3 horas". Es el único dato que se configura; el número de sesiones y el reparto entre fases (resumen / estudio / práctica / repaso) los calcula la app a partir de ahí.
- **Excepciones por examen**: si un examen concreto se sale de la pauta (un temazo puntual), se le puede dar su propio tiempo sin tocar el resto de la asignatura. Se borra volviendo al valor general.

> Nota: el campo de peso por fase (`1,1,1,1` por defecto) reparte las sesiones entre fases, y un `0` descarta esa fase — así es como se quita la práctica en una asignatura que no la tiene.

## Contexto escolar

El planificador necesita saber **cuándo se toca cada asignatura** y **cuándo no hay clase**. Eso se configura en **Colegio → Horario** y en **Colegio → Días sin cole**:

- **Horario semanal**: qué días se tiene cada asignatura. No se guardan horas, solo qué días, porque es lo que hace falta para lo único que se calcula con él: **la fecha límite de un deber** ("el próximo día que tengo esta asignatura").
- **Días sin cole**: rangos de vacaciones, puentes o semana de exámenes. Se pueden solapar; al consultar solo importa la unión.
- **Plantillas de deber**: "Ficha de mates", "Leer 20 min", para el alta rápida del check-in.
- **Tope diario de estudio**, en minutos, por niño.

La convención de días es `0 = lunes … 6 = domingo` en todo el proyecto.

Dos fechas distintas en un deber, que es lo que evita el clásico "me lo puso hoy, es para mañana":

- **`assigned_on`** — el día en que le pusieron el deber. Lo pone el servidor.
- **`due_on`** — la fecha límite. Si el deber viene de una asignatura, se calcula como el **próximo día de clase de esa asignatura**, saltando días sin cole. Si viene de un plan de estudio o de un extraescolar, manda su propia fecha.

El reparto del plan de estudio **respeta el tope diario** y **nunca desplaza una sesión hacia delante**: si un día ya está lleno, la sesión cae hacia atrás, y lo que no cabe se devuelve como `unplaced_study_minutes` en vez de fingir que sí.

Un deber nunca se borra por perder el rastro de quién lo creó o de qué extraescolar venía: `created_by` y `extracurricular_id` son `ON DELETE SET NULL`.

## Cuentas de niño

Cada menor tiene su propia cuenta, creada por un adulto desde **Casa → Familia**. **No tiene email**: entra con su nombre y un PIN de 4 o 6 cifras que elige el adulto. El PIN se guarda hasheado con Argon2id y **no se puede recuperar**, así que se enseña una sola vez, al crearlo, con el aviso de que hay que apuntarlo.

Hay **dos puertas de entrada**, porque son dos personas distintas y no se mezclan: `/login` para el adulto (email y contraseña) y `/nino` para el menor (nombre y PIN).

El nombre es la clave de entrada del niño, así que **no puede repetirse entre cuentas**: solo entra quien haga coincidir nombre *y* PIN, y si dos cuentas coincidieran en ambos, la entrada quedaría bloqueada por completo en lugar de adivinar. Por eso Familia avisa antes de dar de alta un nombre repetido. El nombre se compara con mayúsculas y minúsculas, como en la entrada.

- El PIN está limitado a 5 intentos fallidos por `(nombre, IP)` en 5 min → `429` con `Retry-After`, igual que el login del adulto.
- Cada cuenta de niño está aislada: todo se filtra por `user_id` y ninguna lista de un niño ve los datos de otro.

## Stack

| Capa | Tecnología |
|---|---|
| API | Python 3.12+ · FastAPI · SQLAlchemy 2 (async) · Alembic |
| Base de datos | PostgreSQL 16 |
| Frontend | React · Vite · TypeScript · MUI · PWA (Workbox) |
| Push | pywebpush (VAPID) |
| Despliegue | Docker Compose (+ Caddy TLS) en VPS Hostinger |

## Estructura

```
api/          Backend FastAPI
frontend/     PWA React + MUI
deploy/       Docker Compose de producción + Caddy
docs/         Notas técnicas
```

## Desarrollo

### API

```bash
cd api
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
cp .env.example .env          # ajustar DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Vite escucha también en la red local (`host: true`), así que para revisar el diseño en el móvil de verdad, con el móvil en el mismo WiFi:

```bash
ipconfig   # busca tu IPv4, p. ej. 192.168.1.43
```

y abre `http://<tu-ip>:5173` en el navegador del móvil. Ojo: eso deja la app accesible para cualquiera de tu red local, solo para desarrollo.

Ver la planificación funcional completa en [`Planteamiento.md`](Planteamiento.md).

## Seguridad

- Sesiones con token opaco hasheado en BD (`sha256`), sin JWT. TTL 30 días.
- **Rate limit del login**: 5 intentos fallidos por `(email, IP)` en una ventana de 5 min → `429` con cabecera `Retry-After`. Sólo cuenta los fallos, y un login correcto limpia el contador. Ajustable con `LOGIN_MAX_ATTEMPTS` y `LOGIN_WINDOW_SECONDS` en `.env`.
- **Reset de contraseña por email** (`/olvide-password`): token de un solo uso guardado hasheado, caduca en 30 min, limitado a 3 peticiones por `(email, IP)`. Al confirmar, se cambia la contraseña y **se revocan todas las sesiones** del usuario.
  - El endpoint de petición siempre responde `202` con el mismo texto exista o no la cuenta, para no permitir enumerar qué emails están registrados.
  - Requiere SMTP: con `SMTP_HOST` vacío no se envían correos (en desarrollo el token se registra en el log). **En producción hay que rellenar `SMTP_*` o el reset no llegará a nadie.**
- Aislamiento por capa de servicio: todas las consultas se filtran por `user_id`.
- HTTPS con Caddy + Let's Encrypt en el despliegue.