"""
main.py — Punto de entrada de la aplicación FastAPI

Aquí se crea la instancia de la app, se registran los routers
y se configuran los middlewares globales.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.webhook import router as webhook_router
from app.config import get_settings
from app.models.database import init_db

logging.basicConfig(level=logging.INFO)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Eventos de startup y shutdown de la app.
    lifespan reemplaza los decoradores @app.on_event (deprecados en FastAPI moderno).

    Al arrancar: inicializamos las tablas de PostgreSQL.
    Al apagar: podríamos cerrar conexiones, limpiar recursos, etc.
    """
    # ---- STARTUP ----
    # Crea las tablas en PostgreSQL si no existen todavía.
    # En producción se usaría Alembic para migraciones controladas,
    # pero create_all() es suficiente para desarrollo.
    init_db()
    logging.info("Base de datos inicializada correctamente.")
    yield
    # ---- SHUTDOWN ---- (espacio para cleanup futuro)


# ---- Creación de la app ----
app = FastAPI(
    title="Asistente Académico — API",
    description="Backend del asistente académico personal por WhatsApp.",
    version="0.2.0",
    debug=settings.debug,
    lifespan=lifespan,
)

# ---- CORS (necesario para el panel admin Next.js en FASE 6) ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # URL del frontend en desarrollo
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Registro de routers ----
app.include_router(webhook_router, prefix="/webhook", tags=["WhatsApp"])


# ---- Health check ----
@app.get("/health", tags=["Sistema"])
async def health_check():
    return {"status": "ok", "version": "0.2.0"}

