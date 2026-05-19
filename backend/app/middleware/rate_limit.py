"""
middleware/rate_limit.py — Rate limiting por número de WhatsApp (FASE 7)

CONCEPTO — Rate Limiting:
  Limita cuántas peticiones puede hacer un cliente en una ventana de tiempo.
  Sin rate limiting un solo número podría saturar el backend
  (accidental con bucles, o intencional como DoS básico).

  Algoritmos comunes:
    1. Fixed Window:  contador por ventana fija (ej: max 10 req/minuto).
       Simple pero puede permitir ráfagas al borde de la ventana.

    2. Sliding Window: ventana deslizante, más preciso.
       Guarda el timestamp de cada request → más costoso en memoria.

    3. Token Bucket:  "cubo" de tokens que se repone a tasa fija.
       Permite ráfagas cortas pero limita la tasa sostenida.
       Es el algoritmo que usa Nginx y muchas APIs comerciales.

  Para WhatsApp (mensajería humana) basta con Fixed Window:
  nadie escribe más de 20 mensajes en 60 segundos manualmente.

IMPLEMENTACIÓN:
  Usamos Redis como contador compartido.
  Clave: "rl:{phone}:{ventana_actual}"
  Valor: contador de requests en esa ventana
  TTL:   duración de la ventana (expira automáticamente → reset)

  Operación atómica con INCR + EXPIRE:
    pipeline = redis.pipeline()
    pipeline.incr(key)
    pipeline.expire(key, window_seconds)
    count, _ = pipeline.execute()
    if count > max_requests: → rate limited

  Por qué Redis y no una variable Python:
    En producción el backend corre en múltiples procesos/instancias.
    Un contador en memoria de Python no es compartido entre procesos.
    Redis es el estado compartido centralizado.
"""

import logging
from typing import Optional

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

# Configuración del rate limiter
# Ajustar según el uso esperado: un estudiante normal envía ~5 mensajes/min
RATE_LIMIT_REQUESTS = 20     # máximo de mensajes permitidos en la ventana
RATE_LIMIT_WINDOW_SECONDS = 60  # ventana de tiempo en segundos


async def check_rate_limit(phone: str) -> tuple[bool, int]:
    """
    Verifica si el número de teléfono ha excedido el rate limit.

    Usa el algoritmo Fixed Window con Redis como backend compartido.
    Operación atómica: INCR + EXPIRE en un pipeline para evitar race conditions.

    Args:
        phone: número de WhatsApp, ej "whatsapp:+573001234567"

    Returns:
        (allowed: bool, current_count: int)
        allowed=True  → la petición puede procesarse
        allowed=False → rate limited, rechazar con mensaje de error
    """
    settings = get_settings()
    redis_key = f"rl:{phone}"

    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        async with r:
            # Pipeline atómico: incrementar y establecer TTL en una sola operación
            pipe = r.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, RATE_LIMIT_WINDOW_SECONDS)
            results = await pipe.execute()
            current_count: int = results[0]

        if current_count > RATE_LIMIT_REQUESTS:
            logger.warning(
                "rate_limit_exceeded",
                extra={
                    "phone": phone,
                    "count": current_count,
                    "limit": RATE_LIMIT_REQUESTS,
                    "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
                },
            )
            return False, current_count

        return True, current_count

    except Exception as e:
        # Si Redis no está disponible, PERMITIMOS la petición
        # (fail-open: preferimos servir que bloquear incorrectamente)
        logger.warning(f"rate_limit_check_failed (redis unavailable): {e}")
        return True, 0


async def get_rate_limit_status(phone: str) -> dict:
    """
    Retorna el estado actual del rate limit para un número.
    Usado por el endpoint /admin/stats y para debugging.
    """
    settings = get_settings()
    redis_key = f"rl:{phone}"
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        async with r:
            count = await r.get(redis_key)
            ttl = await r.ttl(redis_key)
        return {
            "phone": phone,
            "requests_in_window": int(count or 0),
            "limit": RATE_LIMIT_REQUESTS,
            "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            "resets_in_seconds": max(ttl, 0),
        }
    except Exception:
        return {"phone": phone, "error": "redis_unavailable"}
