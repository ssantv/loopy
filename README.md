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