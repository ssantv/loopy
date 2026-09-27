# Loopy — PWA de organización personal multi-usuario

Documento de referencia del proyecto. Todo lo que hay aquí es el contrato de producto acordado; los detalles de implementación se cierran en código pero este documento manda.

- **Repo:** `C:\Users\shan_\Desktop\Aya\Programacion\Loopy`.
- **Alojamiento:** VPS propio en Hostinger (aprox. 2 vCPU / 8 GB RAM).
- **Público:** cualquier persona; perfil Adulto o Niño, **independientes entre sí, sin vínculo ni jerarquía entre cuentas**. El tipo de perfil solo determina qué categorías ve el usuario.
- **Multi-tenant:** los datos de cada usuario son privados (todo filtrado por `user_id`).

---

## 1. Stack

| Capa | Elección |
|---|---|
| Frontend | React + Vite **PWA** (`vite-plugin-pwa` + Workbox) + MUI |
| Backend | Python 3.12 + **FastAPI** (Pydantic v2) |
| Base de datos | **PostgreSQL 16** (Postgres es también la cola de notificaciones; sin Redis) |
| ORM / migraciones | SQLAlchemy 2.0 (async) + Alembic |
| Fechas | `zoneinfo` (tz IANA) + `dateutil.relativedelta` |
| Push Web | `pywebpush` (VAPID) en `asyncio.to_thread` |
| Email | SMTP externo (solo reset de contraseña verificado) |
| Deploy | Docker Compose (app + postgres + caddy TLS) en el VPS |
| Auth | **Solo email + contraseña** (argon2id); sesiones con token opaco en BD, header `Authorization: Bearer` (sin cookies → sin CSRF) |

**Scheduler = Postgres como cola** (outbox + poller). Fiable, sobrevive reinicios, escala sin cambiar de arquitectura.

---

## 2. Modelo de datos

### 2.1 Usuario, sesiones y push

**`users`**
- `id` uuid PK
- `email` citext UNIQUE
- `password_hash` (argon2id)
- `profile_type` `adult` | `child`
- `display_name`
- `timezone` IANA
- `birth_date` (obligatorio al crear perfil de **niño**; adulto no lo usa)
- `notification_tone` — solo niño: `jugueton` | `cercano` | `directo-amistoso` | `directo`
- `tone_source` `auto` | `manual`
- `created_at`, `updated_at`

**`sessions`** — `id`, `user_id` FK, `token_hash`, `expires_at`, `created_at`, `last_seen_at`.

**`push_subscriptions`** — `id`, `user_id` FK, `endpoint` (único), `p256dh`, `auth`, `user_agent`, `last_seen_at`. Varios dispositivos por usuario.

**`password_reset_tokens`** — token con hash, `expires_at`, `used_at`.

### 2.2 Tareas y recurrencias (adulto `general`, niño/hogar, etc.)

**`tasks`**
- `id`, `user_id` FK
- `category`: `general` (adulto) | `hogar` | `colegio-deberes` | `colegio-trabajo` | `puntual` (adulto)
- `title`, `notes`
- `room_id` FK `rooms` NULL (solo `hogar` adulto)
- `subject_id` FK `subjects` NULL (solo niño)
- `due_on` date NULL (día concreto, "para hoy o cualquier fecha futura")
- `due_at` timestamptz NULL (hora exacta; puntuales con push o recurrentes con **hora de aviso opcional**)
- `notify` bool (solo avisa si `due_at` está marcado)
- Recurrencia:
  - `rec_type` `daily` | `weekly_days` | `month_day` | `interval` | `rotation_ref`
  - `rec_interval` int, `rec_unit` `day`|`week`|`month`
  - `rec_week_mask` smallint bitmask (Lun–Dom)
  - `rec_day_of_month` int (`0` = último día del mes)
  - `rec_anchor` date (referencia, desfase de rotación)
  - `rec_next_due` date (cursor)
- Niño:
  - `pending_from_class` bool (deberes no acabados en clase)
  - `est_minutes` int (deberes y trabajos: tiempo estimado)
  - `done_minutes` int (trabajos largos: lo avanzado)
- `last_done_on` date, `archived_at`, `sort`

**`task_completions`** — `id`, `task_id` FK, `done_on` date, `created_at` (historial, fecha real de completado).

**`rotation_groups`** — `id`, `user_id`, `name`, `rec_interval`, `rec_unit`. Las `tasks` llevan `rotation_group_id` + `rotation_index`. La rotación se materializa como tareas `interval` con `rec_anchor` desfasado un periodo entre ítems (1 al mes, otro el mes siguiente, etc.).

### 2.3 Habitaciones (solo adulto, hogar)

**`rooms`** — `id`, `user_id`, `name`, `sort_order`, `color`. Lista editable. Al borrar una habitación, sus tareas pasan a **"Sin habitación"**.

### 2.4 Módulo colegio (niño)

**`subjects`** — `id`, `user_id`, `name`, `color`, `include_weekends` bool (def true), y **fases configurables por asignatura** (no todas las asignaturas necesitan lo mismo):
- `days_resumen` (def 1)
- `days_estudio` (def 1) — puede ser 2 o más si la asignatura lo exige
- `days_practica` (def 1) — **práctica** = ejercicios prácticos (listening en inglés, resolución de problemas en mates…); algunas asignaturas no la requieren (0)
- `days_repaso` (def 1) — repaso
- **Resumen progresivo**: `resumen_total_pages` (def NULL, "¿cuántas hojas tiene el tema?") y `resumen_done_pages` (def 0).
**Sin agrupación por categorías.**

**`exams`** — `id`, `user_id`, `subject_id` FK, `exam_date`, `notes`.

**El plan de estudio es una función pura que se calcula en tiempo de consulta** — no se materializa ni se regenera nada. `plan(examen, asignatura) → [(fecha, fase)]`:

Para un examen en día D con asignatura (resumen=S, estudio=E, práctica=P, repaso=R), solo depende del desplazamiento `X = D − fecha`:

```
X = 1                        → repaso-final   (fijo, no movible, por construcción)
X ∈ [2, 1+R]                 → repaso
X ∈ [2+R, 1+R+P]             → práctica        (listening, problemas…; 0 si no aplica)
X ∈ [2+R+P, 1+R+P+E]         → estudio
X ∈ [2+R+P+E, 1+R+P+E+S]     → resumen
X fuera de ese rango          → sin plan
```

Ejemplo con (resumen=1, estudio=1, práctica=1, repaso=1) — examen el 25/09:

```
21/09 | 22/09 | 23/09   | 24/09          | 25/09
resumen|estudio|práctica| repaso FINAL fijo | D (examen)
```

(Con la fórmula del enunciado original: resumen 2, estudio 4, repaso 3 → `D-10 D-9 | D-8…D-5 | D-4…D-2 | D-1` donde estudio=4, resumen=2, repaso=3.)

- Se evalúa al consultar (hoy, semana, rango); si quedan menos días que el plan completo, las fases se **comprimen solas** hacia atrás. Cero filas que mantener, imposible quedar con datos obsoletos.
- **Repaso final en D-1: fijo y no movible** (viene dado por la función, no por configuración).
- Fines de semana incluidos por defecto (`include_weekends` por asignatura); si se excluyen, el conteo de desplazamiento solo avanza por días válidos.
- Ítems no hechos → quedan visibles como "atrasada" pero **colapsados**.
- Extraescolares: solo contexto (timeline) + entrada del heurístico; no se asigna hora real de estudio.
- Estudio = sugerir N pomodoros por ítem (def 1).
- Sin push por ítem de plan (toggle apagado por defecto); el check-in lista el plan del día.
- `subject_name` se obtiene uniendo examen→asignatura (no se duplica).

**`study_completions`** — lo único que se persiste es el estado "hecho" (porque eso es un evento, no un dato derivado):
- `id`, `user_id`, `exam_id` FK NULL, `subject_id` FK, `date`, `phase` (`resumen`|`estudio`|`practica`|`repaso`|`repaso-final`), `status` (`done`|`skip`), `done_at`.
- Marcar un ítem "hecho" = insertar; deshacer = borrar la fila.
- `status='skip'` = "no hice el resumen del día 12 (estuve enfermo)": desaparece del bloque "atrasada" **sin fingir que se estudió**.
- Clave semántica `(exam_id, date)`: al mover el examen o cambiar la configuración, lo ya estudiado sigue siendo válido (fue un día real).

**Resumen adelantado (sin esperar al examen)** — como el motor de carga hay días con pocos deberes, Loopy puede sugerir acometer el **resumen de una asignatura con antelación**, incluso si esa asignatura aún **no tiene fecha de examen**:

- Es **una sugerencia más del motor de poca carga** ("Hoy te recomiendo que vayas empezando con el resumen de `{subject}` para ir adelantando"), con la misma prioridad por riesgo que los proyectos largos.
- **El resumen es progresivo y parcial** (importante): sin fecha de examen, el temario aún no está terminado, así que el alumno **no puede resumir todo** — avanza "lo que puede" y el progreso se guarda en el tiempo. No hay "done" binario.
  - Se mide por **hojas resumidas**: `resumen_done_pages` frente a `resumen_total_pages` (el alumno dice/hace que el tema tiene N hojas y marca cuántas ha resumido). También puede simplemente avanzar por minutos de sesión; las hojas son lo que hace útil la métrica.
  - Al hacer una sesión de resumen adelantado, se registra `study_completions` con `exam_id NULL`, `phase='resumen'`, `status='done'` **y además se incrementa `resumen_done_pages`**.
- Cuando esa asignatura reciba fecha de examen, el plan hacia atrás trata el resumen según el progreso:
  - `resumen_done_pages` **≥** `resumen_total_pages` → la fase **resumen se omite** (plan = estudio + práctica + repaso + repaso-final): el adelanto se ve recompensado, nada se repite.
  - resumen **parcial** → el ítem de resumen del plan aparece como *"remata el resumen de `{subject}` (llevas X de Y hojas)"* en lugar de empezar de cero.
  - `resumen_total_pages` sin definir → el resumen se trata como trabajo largo (por minutos) y el ítem del plan simplemente sugiere completarlo.
  - Candidatos: asignaturas con examen próximo cuya fase resumen aún no toca **y** asignaturas sin examen programado (para no esperar a que lo pongan).

**`extracurriculars`** — `id`, `user_id`, `name`, `day_of_week` (0–6), `start_time`, `end_time`, `start_on` NULL, `end_on` NULL (opcional por temporada; sin fechas → siempre activo).

**`checkin_configs`** — `id`, `user_id`, `enabled`, `time`, `week_mask`.

**`work_sessions`** — `id`, `user_id`, `kind` (`homework`|`study`|`project`), `task_id` NULL, `planned_seconds`, `actual_seconds`, `completed_at`. Lo registran el **temporizador de deberes** (cuenta atrás con `est_minutes`) y el **pomodoro de estudio** (25 min / 5 min configurable). Compara real vs estimado y suma `done_minutes` a proyectos.

### 2.5 Módulos adulto

**Recordatorios puntuales ("cosas de hoy")** → `tasks.category='puntual'` con `due_on` (siempre en la página principal) + opcionalmente `due_at` + `notify` → push en esa hora. Quedan pendientes y visibles hasta el final del día; si `due_at` ya pasó no se notifica, solo se lista.

**Hora opcional en recurrentes** → las tareas recurrentes pueden llevar `due_at` + `notify` (ej. "tomar pastilla" `daily` a las 21:00 → push diario a las 21:00).

**`shopping_items`** (solo adulto)
- `id`, `user_id`, `name`, `qty` (texto libre), `added_at`, `purchased` bool, `purchased_at`, `source` (`manual`|`plan`), `source_ref` NULL, `deleted_at` NULL.
- Compradas quedan como historial (archivo + deshacer); "quitar" solo borra lo nunca comprado.
- **Botón "Recomendar"**: ítems comprados **≥2 veces en los últimos 90 días** (nombre normalizado), excluye pendientes, ordena por nº de compras (desempate: más reciente). Al añadir, **pre-rellena** la cantidad/unidad más frecuente (editable). Sin IA, cálculo en tiempo de consulta.

**`daily_summary_configs`** (solo adulto) — `id`, `user_id`, `enabled`, `time`, `week_mask`. + **`summary_exceptions`** (`user_id`, `date`, `skip`|`add`) para el "salvo excepción puntual". Contenido del push: tareas de hoy + atrasadas, compra pendiente y menú de hoy. Tap → listado del día.

### 2.6 Menú de comidas (solo adulto)

**`meal_slot_configs`** — `id`, `user_id`, `slot` (`desayuno|almuerzo|comida|merienda|cena`), `enabled`, `default_time` NULL. **Ninguna activa por defecto** (el usuario las enciende).

**`recipe_categories`** — `id`, `user_id` NULL (=globales por defecto: pescado, verdura, legumbre, carne, huevo, pasta/arroz…), `name`, `order`, UNIQUE(`user_id`, `name`). Lista editable no cerrada.

**`category_goals`** — `id`, `user_id`, `recipe_category_id`, `min_per_week`, `max_per_week` NULL (máximos **opcionales**). Defaults: pescado ≥2, verdura ≥4, legumbre ≥2, carne 2–3, huevo ≥1, pasta/arroz 2–3.

**`recipes`** — `id`, `user_id`, `name`, `category_id` FK, `slots` (franjas aptas), `notes`.

**`recipe_ingredients`** — `id`, `recipe_id` FK, `name`, `qty` (**numérico**), `unit` (texto), `sort_order`. Las cantidades se suman (200 g + 100 g = 300 g).

**`meal_plans`** — `id`, `user_id`, `date`, `slot`, `recipe_id` NULL, `free_text` NULL, UNIQUE(`user_id`, `date`, `slot`). **Semanas concretas** con botón "copiar semana anterior". "Qué toca hoy" = consulta por fecha.

**Añadir a la compra**: botón en el plan de la semana (todos los ingredientes de sus recetas) y **botón por receta**. Normaliza nombres y **fusiona** con ítems pendientes; si está comprado, crea línea pendiente nueva; si el plan usa texto libre, se añade a mano.

**Botón "recomendar para huecos"**: rellena franjas sin asignar según déficit de `min_per_week` (y respeta máximos), variedad (no repetir receta en la semana si hay alternativa) y adecuación de la franja.

### 2.7 Outbox de notificaciones (scheduler)

**`notification_outbox`**
- `id`, `user_id`, `kind` (`reminder`|`checkin`|`summary`), `due_at` timestamptz (UTC), `payload` JSONB, `status` (`pending`|`sent`|`failed`|`cancelled`), `attempts`, `next_retry_at` NULL, `last_error`, `sent_at`, `created_at`
- Índices: `(status, due_at)`, `(status, next_retry_at)`.

---

## 3. Motor de recurrencias (semántica cerrada)

### Regla única de visibilidad
Una tarea aparece en el día D si `rec_next_due <= D` y no está completada. Mientras no se marque, `rec_next_due` se queda en el pasado → **sigue apareciendo como "atrasada" hasta cerrarla**.

### Al completar en la fecha real C
| Regla | `next_due` tras completar en C |
|---|---|
| `daily` | `C + 1 día` |
| `interval` días | `C + X días` |
| `interval` semanas | `C + X semanas` |
| `interval` meses | `C + X meses` (relativedelta, clamp fin de mes) |
| `month_day` | siguiente mes que tenga ese día; `0` = último día del mes |
| `weekly_days` | siguiente día de la máscara **estrictamente después de C** |
| `rotation_ref` | `C + periodo × N`, el ítem pasa al final |

### Dos familias
- **Ancladas al calendario** (`weekly_days`, `month_day`, `daily`): el día nominal manda. El día nominal **siempre aparece** (el lunes sale igual aunque lo marques antes desde el listado masivo). Marcar por adelantado **no consume** la ocurrencia futura en este listado.
- **Ancladas al día real** (`interval`, `rotation`): el día real en que lo haces marca el ritmo. Se puede marcar **adelantado** (arenero tocaba martes, se marca el lunes → siguiente = lunes + 3 = jueves).

### `month_day`
- Día 30/31 → **salta** los meses que no lo tengan.
- `rec_day_of_month = 0` → **"último día del mes"** (pagar el alquiler).

**Ejemplo clave (polvo, `weekly_days=[Lunes]`)**: falla el lunes → sigue pendiente el martes; se marca el **miércoles** → siguiente = **lunes siguiente** (sin perderse ni adelantarse).

---

## 4. Módulo niño — detalle

- **Deberes**: mismo día por defecto, `pending_from_class` arriba; `est_minutes` para el plan de la tarde. Alta desde check-in o sección.
- **Trabajos largos**: sugerencia de avance en días de poca carga (carga = minutos totales de obligatorias + bloqueos extraescolares), 20–45 min/día, "proyecto más en riesgo". Nunca obligatorio.
- **Exámenes**: configuración **por asignatura** (resumen/estudio/práctica/repaso), no por categoría — no todas las asignaturas necesitan lo mismo (inglés hace listening, mates resuelve problemas; algunas no requieren práctica). El plan se **calcula en tiempo de consulta** (con repaso final fijo en D-1 y asignación de los demás días justo antes); solo se persiste el "hecho" en `study_completions` (incluye `skip` para saltar un día sin fingir que estudiaste).
- **Resumen adelantado**: en días de poca carga, Loopy puede sugerir empezar el **resumen de una asignatura** aunque no tenga examen aún ("ir adelantando"). El resumen es **progresivo por hojas** (`resumen_done_pages` vs `resumen_total_pages`): no se puede resumir entero si el tema no ha acabado, se avanza lo que se puede. Al fijarse el examen, si el resumen está completo se **omite**; si está parcial sale como *"remata el resumen (llevas X de Y hojas)"*.
- **Vista "organiza tu tarde"**: carga en minutos + extraescolares → sugiere huecos libres para encajar las tareas.
- **Check-in diario** (hora + días configurables): push con el tono del niño → alta rápida con **3 tipos** (deber / examen / proyecto), al guardar: **"Añadir otro"** o **"Guardar"** → listado completo del día. Android: acciones de notificación ("Añadir tareas"/"Ver mi día"); iOS: tocar abre el asistente. Si no responde, nada se pierde (asistente accesible desde la vista del día).
- **Tono de notificaciones por edad** (sugerido automático, sobrescribible):

| Edad | Tono | Ejemplo check-in |
|---|---|---|
| <6 y 6–8 | `jugueton` | "¡Misión del día! ¿Hay tareas nuevas? 🔍" |
| 9–11 | `cercano` | "¡Hola! ¿Te han mandado tareas nuevas hoy? Cuéntamelas" |
| 12–14 | `directo-amistoso` | "Tareas nuevas de hoy, ¿qué te han puesto?" |
| 15+ | `directo` | "¿Alguna tarea nueva hoy?" |

  - `tone_source=auto` → se recalcula al cumplir años; `manual` → no lo pisa.
  - Plantillas en **código** (dict tono→texto por evento), sin migraciones para afinarlas.
  - **Regla transversal: cero apelativos cariñosos** ("cielo", "bonito", "cariño") en ningún tono; la calidez es lenguaje de misión/exclamación, no motes.

---

## 5. Módulo adulto — detalle

- **Recordatorios puntuales** = "cosas para hoy" en la página principal; hora + push opcionales.
- **Hogar por habitaciones**: vistas "Por habitaciones" (tarjetas por `rooms`, con pendientes + **"Adelantadas"** colapsables; marcar una adelantada en esta vista **la consume** y el siguiente es tras hoy) y "Todas" (listado plano del día). Cajón "Sin habitación".
- **Lista de la compra**: pendientes arriba, compradas abajo (archivo/deshacer), quitar solo lo no comprado. + **Recomendar** (90 días / ≥2, cantidad prefilled).
- **Resumen diario**: hora + días + excepciones `skip`/`add`.
- **Menú de comidas**: franjas activables, catálogo + categorías editables + objetivos mín/máx, planificador semanal por fechas con copiar semana, añadir ingredientes a la compra (semana o receta), recomendar huecos.
- **Hora opcional en recurrentes** (tiempo de aviso por tarea).

---

## 6. Listado "Pendientes" (ambos perfiles)

Pestaña global con todas las tareas con ocurrencia pendiente (hoy + atrasadas), checkboxes para **marcado masivo**. En reglas de calendario la marca previa **no consume** futuras; en intervalo **se recalcula desde hoy**. Pensado también para el niño: puede no usar temporizadores, usar la app solo como recordatorio y tachar varias de golpe ("ya acabé todo").

---

## 7. Scheduler de notificaciones (a escala)

- **Outbox en Postgres** + **poller** en el lifespan de FastAPI cada ~15 s:
  `SELECT ... WHERE status='pending' AND due_at <= now() AND (next_retry_at IS NULL OR next_retry_at <= now()) ORDER BY due_at LIMIT 200 FOR UPDATE SKIP LOCKED`.
- Envío con `pywebpush` + VAPID en `asyncio.to_thread`. Multi-dispositivo: todas las `push_subscriptions` del usuario.
- `201` → `sent`; `404/410` → borrar suscripción; `429/5xx` → `attempts++`, backoff exponencial (30 s → 1 m → 5 m → 30 m → 6 h).
- **Hora exacta**: `due_at` convertido a UTC desde la tz del usuario (`zoneinfo`, DST automático).
- El push es notificación, **nunca la fuente de verdad**: si falla o el móvil está offline, los datos están en BD y son correctos al abrir.
- Escala: un poller basta; crecer = más réplicas con la misma outbox (SKIP LOCKED ya lo hace seguro). `notificationclick` abre la app en la sección correcta.

---

## 8. PWA y offline

- `vite-plugin-pwa` + Workbox: precache del app shell, runtime cache `GET /api/*` (NetworkFirst con fallback a caché), instalable.
- Manifest standalone + `apple-touch-icon` (180×180).
- iOS: Web Push desde **iOS 16.4+** y solo con la app **añadida a pantalla de inicio** (aviso en UI).
- SW: handlers `push`, `notificationclick`, `install/activate`.
- Flujo: `POST /api/push/vapid-public-key` → `register` → `pushManager.subscribe` → `POST /api/push/subscribe`.
- Sin IndexedDB en v1. Caché offline básica para consulta.

---

## 9. Seguridad

- argon2id, sesiones opacas con hash en BD (refresh/revocación), rate limiting (login/reset), validación Pydantic, todo filtrado por `user_id`, HTTPS (Caddy + Let's Encrypt). Email solo para reset verificado.
- **Hecho**: rate limit del login en `app/services/ratelimit.py` (ventana deslizante en memoria; 5 fallos por `(email, IP)` en 5 min → `429` + `Retry-After`; un login correcto limpia el contador). Clave por `(email, IP)` leyendo `X-Forwarded-For` porque detrás de Caddy `request.client.host` es el proxy.
  - Es en memoria a propósito (la API corre con un solo worker de uvicorn). Con varios workers o réplicas habría que moverlo a Postgres/Redis.
  - **Hecho**: reset de contraseña por email. `password_reset_tokens` (token hasheado, `expires_at`, `used_at`), `POST /api/auth/password-reset/request` (siempre `202`, sin revelar si el email existe; limitado a 3 por `(email, IP)`) y `POST /api/auth/password-reset/confirm` (cambia la contraseña, marca el token como usado y **revoca todas las sesiones** del usuario). Envío por SMTP con `smtplib` en un hilo; sin `SMTP_HOST` el token se registra en el log solo en desarrollo.

---

## 10. Roadmap

1. **Scaffolding**: estructura de repo, Docker Compose, PWA (Vite) + FastAPI `/health`.
2. **Auth**: usuarios (con `birth_date` en niño), sesiones, rate limit, reset. ✅
3. **Motor de tareas**: `tasks`, recurrencias (daily/weekly/month_day/interval/rotación), "¿qué toca hoy?", completar → recalcular, hora opcional + `notify`.
4. **Niño — colegio**: asignaturas, deberes, trabajos + sugerencias, exámenes + plan hacia atrás, extraescolares, `work_sessions` (temporizador + pomodoro).
5. **Niño — check-in + tono**: alta rápida 3 tipos, plantillas por edad, `tone_source`.
6. **Adulto**: puntuales (cosas de hoy), hogar por habitaciones (adelantadas), compra + Recomendar, resumen diario + excepciones.
7. **Listado "Pendientes"** masivo (ambos perfiles).
8. **Menú**: franjas, categorías + objetivos, recetas + ingredientes, planificador (copiar semana), añadir a compra, recomendar huecos.
9. **Scheduler + push**: outbox, poller, pywebpush, suscripciones, retries.
10. **Deploy VPS + pruebas reales**: Android Chrome, iOS Safari (pantalla de inicio), offline.
11. **Pulido**: logs, `/health`, backups `pg_dump` + copia offsite.

---

## 11. Decisiones abiertas / fuera de alcance (anotadas)

- Temporizadores corriendo en background / push "pomodoro terminado" con la app cerrada: **no fiable en iOS/Android**, fuera de alcance (las sesiones se guardan aunque termine la app en primer plano).
- Audio de prueba en tonos: muy a futuro.
- Cruzar menú con compra "compras habituales": futuro opcional.
- RLS de Postgres: endurecimiento opcional posterior (ahora aislamiento por capa de servicio).