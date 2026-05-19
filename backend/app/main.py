"""
main.py — Punto de entrada de la aplicación FastAPI

Aquí se crea la instancia de la app, se registran los routers
y se configuran los middlewares globales.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.webhook import router as webhook_router
from app.config import get_settings

settings = get_settings()

# ---- Creación de la app ----
app = FastAPI(
    title="Asistente Académico — API",
    description="Backend del asistente académico personal por WhatsApp.",
    version="0.1.0",
    debug=settings.debug,
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
# Cada módulo expone su propio router; aquí los montamos con su prefijo.
app.include_router(webhook_router, prefix="/webhook", tags=["WhatsApp"])


# ---- Health check ----
# Endpoint simple para verificar que el servicio está vivo
# (usado por Docker, load balancers, monitoreo).
@app.get("/health", tags=["Sistema"])
async def health_check():
    return {"status": "ok", "version": "0.1.0"}
