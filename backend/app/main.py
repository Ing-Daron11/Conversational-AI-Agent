"""
main.py — Punto de entrada de la aplicación FastAPI (FASE 7)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.webhook import router as webhook_router
from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.config import get_settings
from app.models.database import init_db
from app.core.logger import setup_logging
from app.core.fallbacks import get_circuit_status

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- STARTUP ----
    setup_logging(settings.log_level)
    init_db()
    logging.getLogger("app").info("startup_complete", extra={"version": "0.5.0"})
    yield
    # ---- SHUTDOWN ----
    logging.getLogger("app").info("shutdown")


app = FastAPI(
    title="Asistente Académico — API",
    description="Backend del asistente académico personal por WhatsApp.",
    version="0.5.0",
    debug=settings.debug,
    lifespan=lifespan,
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Global exception handler ----
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Captura cualquier excepción no manejada.
    Retorna JSON genérico en lugar de un stack trace en texto plano
    (nunca exponer detalles internos al cliente — OWASP A05).
    """
    logger = logging.getLogger("app")
    logger.error(
        "unhandled_exception",
        extra={"path": str(request.url.path), "error": str(exc)},
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor. Consulta los logs para más detalles."},
    )

# ---- Routers ----
app.include_router(webhook_router, prefix="/webhook", tags=["WhatsApp"])
app.include_router(auth_router, prefix="/auth", tags=["Autenticación"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])


# ---- Health check mejorado (FASE 7) ----
@app.get("/health", tags=["Sistema"])
async def health_check():
    """
    Health check extendido: verifica conectividad con Redis, PostgreSQL y Ollama.
    Usado por Docker Compose, load balancers y Kubernetes readiness probes.
    """
    import httpx
    import redis.asyncio as aioredis

    checks: dict = {}

    # Redis
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # PostgreSQL
    try:
        from app.models.database import SessionLocal
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            checks["ollama"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        checks["ollama"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "version": "0.5.0",
        "services": checks,
        "circuit_breakers": get_circuit_status(),
    }


