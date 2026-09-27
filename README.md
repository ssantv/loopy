# Loopy

App de organización personal multiusuario con **dos perfiles independientes por cuenta**: **Adulto** (recordatorios, hogar, compra, menú, resumen diario) y **Niño** (deberes, trabajos, exámenes con plan de estudio automático, check-in diario).

> Fase actual: **pasos 7, 8 y 9** — listado global de **Pendientes** por ambos perfiles con marcado masivo; **Menú de comidas** adulto (franjas, categorías+objetivos, recetas+ingredientes, plan semanal con copiar/recomendar/añadir a compra); y **scheduler + push** (outbox, poller VAPID con reintentos, suscripción Web Push desde la PWA); sobre el módulo adulto (hogar, compra, resumen diario, menú) y el módulo niño (colegio + plan de estudio + check-in).

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

Ver la planificación funcional completa en [`Planteamiento.md`](Planteamiento.md).

## Seguridad

- Sesiones con token opaco hasheado en BD (`sha256`), sin JWT. TTL 30 días.
- **Rate limit del login**: 5 intentos fallidos por `(email, IP)` en una ventana de 5 min → `429` con cabecera `Retry-After`. Sólo cuenta los fallos, y un login correcto limpia el contador. Ajustable con `LOGIN_MAX_ATTEMPTS` y `LOGIN_WINDOW_SECONDS` en `.env`.
- **Reset de contraseña por email** (`/olvide-password`): token de un solo uso guardado hasheado, caduca en 30 min, limitado a 3 peticiones por `(email, IP)`. Al confirmar, se cambia la contraseña y **se revocan todas las sesiones** del usuario.
  - El endpoint de petición siempre responde `202` con el mismo texto exista o no la cuenta, para no permitir enumerar qué emails están registrados.
  - Requiere SMTP: con `SMTP_HOST` vacío no se envían correos (en desarrollo el token se registra en el log). **En producción hay que rellenar `SMTP_*` o el reset no llegará a nadie.**
- Aislamiento por capa de servicio: todas las consultas se filtran por `user_id`.
- HTTPS con Caddy + Let's Encrypt en el despliegue.