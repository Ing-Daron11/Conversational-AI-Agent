"""
core/fallbacks.py — Respuestas de fallback cuando los servicios fallan (FASE 7)

CONCEPTO — Degradación elegante (Graceful Degradation):
  Un sistema robusto no se rompe cuando un componente falla.
  En cambio, "degrada" su comportamiento: ofrece una funcionalidad
  reducida en lugar de un error 500 sin contexto.

  Ejemplos de degradación en este sistema:
    - Ollama caído     → mensaje claro + sugerencia
    - Redis caído      → continúa sin memoria de sesión (stateless)
    - ChromaDB vacío   → responde sin contexto RAG
    - Calendar sin auth → responde que necesita conectar Google

CONCEPTO — Circuit Breaker Pattern:
  Cuando un servicio externo falla repetidamente, el circuit breaker
  "abre el circuito": deja de intentar llamarlo por N segundos para
  no saturarlo mientras está en recuperación.
  Estados: CLOSED (normal) → OPEN (falla detectada) → HALF-OPEN (test)
  
  En esta implementación usamos un circuit breaker simple con Redis
  como contador de fallos.

CONCEPTO — Timeout:
  Toda llamada a un servicio externo debe tener un timeout.
  Sin timeout, una llamada lenta puede bloquear el thread/coroutine
  indefinidamente y agotar el pool de conexiones.
  En producción: Ollama timeout ~30s, Calendar ~5s, Redis ~1s.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Mensajes de fallback definidos aquí (no en el LLM) ──────────────────

FALLBACK_LLM_DOWN = (
    "⚠️ El asistente está temporalmente no disponible. "
    "Por favor intenta de nuevo en unos minutos."
)

FALLBACK_NO_CONTEXT = (
    "No encontré información relevante en tus notas para esta pregunta. "
    "¿Puedes darme más detalles o has subido documentos sobre este tema?"
)

FALLBACK_CALENDAR_NO_AUTH = (
    "Para consultar tu calendario necesito que primero conectes tu cuenta de Google. "
    "Visita http://localhost:8000/auth/google desde tu navegador."
)

FALLBACK_RATE_LIMITED = (
    "Estás enviando muchos mensajes muy rápido. "
    "Por favor espera un momento antes de continuar."
)

FALLBACK_MESSAGE_TOO_LONG = (
    "Tu mensaje es demasiado largo para procesarlo. "
    "Por favor divídelo en partes más cortas."
)


# ─── Circuit Breaker simple ────────────────────────────────────────────────

class CircuitBreaker:
    """
    Circuit breaker simple en memoria (para dev).
    En producción usar Redis para compartir estado entre instancias.

    Estados:
      CLOSED   → normal, todo funciona
      OPEN     → demasiados fallos, rechaza peticiones inmediatamente
      HALF_OPEN → periodo de prueba: deja pasar 1 petición para ver si recuperó

    Parámetros:
      failure_threshold: cuántos fallos consecutivos abren el circuito
      recovery_timeout:  segundos en OPEN antes de pasar a HALF_OPEN
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at: Optional[float] = None

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            elapsed = time.monotonic() - (self._opened_at or 0)
            if elapsed >= self.recovery_timeout:
                self._state = self.HALF_OPEN
                logger.info(f"CircuitBreaker[{self.name}]: OPEN → HALF_OPEN (recovery test)")
        return self._state

    def is_available(self) -> bool:
        """Retorna True si el servicio está disponible (circuito cerrado o en prueba)."""
        return self.state in (self.CLOSED, self.HALF_OPEN)

    def record_success(self) -> None:
        """Llamar cuando la petición fue exitosa."""
        if self._state == self.HALF_OPEN:
            logger.info(f"CircuitBreaker[{self.name}]: HALF_OPEN → CLOSED (recovered)")
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        """Llamar cuando la petición falló."""
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state = self.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                f"CircuitBreaker[{self.name}]: CLOSED → OPEN "
                f"({self._failures} fallos consecutivos)"
            )

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "failures": self._failures,
            "threshold": self.failure_threshold,
        }


# ─── Instancias globales de circuit breakers ──────────────────────────────
# Un circuit breaker por servicio externo crítico.

llm_circuit = CircuitBreaker("ollama", failure_threshold=3, recovery_timeout=30.0)
calendar_circuit = CircuitBreaker("google_calendar", failure_threshold=5, recovery_timeout=60.0)
redis_circuit = CircuitBreaker("redis", failure_threshold=5, recovery_timeout=10.0)


def get_circuit_status() -> dict:
    """Retorna el estado de todos los circuit breakers. Usado en /health."""
    return {
        cb.name: cb.get_status()
        for cb in [llm_circuit, calendar_circuit, redis_circuit]
    }
