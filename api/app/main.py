"""Punto de entrada FastAPI."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import adult, auth, child, extras, menu, pending, push, school, tasks
from app.services.notify import notify_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Scheduler de notificaciones (paso 9): poller + rellenado del outbox.
    notify_task = asyncio.create_task(notify_loop())
    try:
        yield
    finally:
        notify_task.cancel()
        try:
            await notify_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(school.router)
app.include_router(child.router)
app.include_router(extras.router)
app.include_router(adult.router)
app.include_router(push.router)
app.include_router(pending.router)
app.include_router(menu.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "env": settings.env}