"""
core/logger.py — Logging estructurado en formato JSON (FASE 7)

CONCEPTO — ¿Por qué logging estructurado?
  El logging clásico escribe texto libre:
    INFO: Mensaje de whatsapp:+1234 procesado en 1.2s

  El logging estructurado escribe JSON:
    {"level":"INFO","ts":"2026-05-19T10:00:00Z","phone":"whatsapp:+1234",
     "latency_ms":1200,"tools_called":["search_notes"],"event":"request_ok"}

  Beneficio: las entradas son parseables por herramientas como:
    - Grafana Loki (visualización)
    - Elasticsearch + Kibana (búsqueda)
    - Datadog / New Relic (monitoreo)
    - jq (análisis local desde terminal)

  Con texto libre necesitas regex para extraer datos.
  Con JSON puedes filtrar directamente: level=ERROR AND latency_ms > 2000

CONCEPTO — Campos estándar en cada log:
  - ts:          timestamp ISO 8601 (para ordenar y correlacionar eventos)
  - level:       DEBUG / INFO / WARNING / ERROR
  - event:       nombre descriptivo del evento ("request_ok", "llm_timeout", etc.)
  - phone:       número del usuario (para agrupar por sesión)
  - latency_ms:  tiempo de procesamiento (para detectar cuellos de botella)
  - tools_called: qué tools del agente se usaron
  - error:       mensaje de error si aplica

CONCEPTO — Correlation ID (request_id):
  En sistemas distribuidos, una petición pasa por múltiples servicios.
  El correlation ID es un UUID que se pasa entre todos y permite
  reconstruir el flujo completo de una petición en los logs.
"""

import json
import logging
import sys
import time
import uuid
from typing import Any


class JSONFormatter(logging.Formatter):
    """
    Formatter personalizado que serializa cada log record a JSON.
    Todos los logs del sistema usarán este formato si se configura
    el handler raíz con este formatter.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Campos base siempre presentes
        log_entry: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        # Campos de contexto extra (pasados con extra={} en el logger call)
        for field in (
            "phone", "request_id", "latency_ms", "tools_called",
            "user_message", "reply_preview", "error", "status_code",
            "chunks_retrieved", "collection",
        ):
            if hasattr(record, field):
                log_entry[field] = getattr(record, field)

        # Información de excepción si existe
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """
    Configura el sistema de logging global de la aplicación.
    Debe llamarse UNA vez al iniciar la app (en main.py → lifespan).

    En desarrollo puedes usar level="DEBUG" para ver todo.
    En producción usa "INFO" para no saturar los logs.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Silenciar loggers ruidosos de librerías externas
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    logging.getLogger("app").info(
        "Logging estructurado JSON configurado",
        extra={"level": level},
    )


def get_request_id() -> str:
    """Genera un UUID corto para correlacionar logs de una misma petición."""
    return str(uuid.uuid4())[:8]


class RequestLogger:
    """
    Context manager para medir latencia y loguear el resultado de una petición.

    Uso:
        with RequestLogger(logger, phone="whatsapp:+1234") as req_log:
            reply = await run_agent(msg, history)
            req_log.set_reply(reply)
            req_log.set_tools(["search_notes", "list_calendar_events"])
    """

    def __init__(self, logger: logging.Logger, phone: str = "", request_id: str = ""):
        self.logger = logger
        self.phone = phone
        self.request_id = request_id or get_request_id()
        self._start = 0.0
        self._tools: list[str] = []
        self._reply = ""

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def set_tools(self, tools: list[str]) -> None:
        self._tools = tools

    def set_reply(self, reply: str) -> None:
        self._reply = reply

    def __exit__(self, exc_type, exc_val, exc_tb):
        latency_ms = round((time.perf_counter() - self._start) * 1000)
        extra = {
            "phone": self.phone,
            "request_id": self.request_id,
            "latency_ms": latency_ms,
            "tools_called": self._tools,
            "reply_preview": self._reply[:80] if self._reply else "",
        }
        if exc_type:
            extra["error"] = str(exc_val)
            self.logger.error("request_error", extra=extra)
        else:
            self.logger.info("request_ok", extra=extra)
        return False  # no suprimir la excepción
