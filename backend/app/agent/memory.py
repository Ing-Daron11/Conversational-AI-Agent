"""
memory.py — Gestión de memoria de conversación con Redis

CONCEPTO — ¿Por qué Redis para sesiones?
  Redis es una base de datos en memoria (key-value). Es ideal para sesiones
  porque:
    1. Velocidad: las lecturas/escrituras son microsegundos (no ms como en SQL)
    2. TTL nativo: cada clave puede tener un tiempo de expiración automático
    3. Sin overhead: no necesitamos hacer SELECT ni JOIN para leer el historial

  Alternativa sin Redis: guardar el historial en un dict en memoria del proceso.
  Problema: no escala (si hay varios workers, cada uno tiene su propia memoria)
  y se pierde al reiniciar el servidor.

DISEÑO DE LA SESIÓN:
  Clave Redis:  "session:{numero_limpio}"   ej: "session:+5219..."
  Valor:        JSON  →  [{"role": "user", "content": "..."}, ...]
  TTL:          1800 segundos (30 min) — ventana deslizante:
                cada mensaje nuevo reinicia el contador.

MÚLTIPLES USUARIOS:
  Cada número de WhatsApp = clave separada en Redis.
  100 usuarios simultáneos → 100 claves independientes, sin interferencia.

FLUJO COMPLETO:
  Usuario envía mensaje
    → get_history(phone)       [lee de Redis]
    → LLM genera respuesta
    → add_messages(phone, ...)  [escribe en Redis, reinicia TTL]
    → BackgroundTask: save_to_db(phone, history) [persiste en PostgreSQL]
"""

import json
import logging
from typing import List

import redis.asyncio as aioredis
from langchain.schema import HumanMessage, AIMessage, BaseMessage

from app.config import get_settings

logger = logging.getLogger(__name__)

# ---- Parámetros configurables ----
SESSION_TTL = 30 * 60       # 1800 seg = 30 minutos de inactividad
MAX_HISTORY_MESSAGES = 10   # últimos 10 mensajes (5 turnos de conversación)
                            # más mensajes = más contexto pero más tokens al LLM


class ConversationMemory:
    """
    Gestiona el historial de conversación por usuario en Redis.
    Todos los métodos son async para no bloquear el event loop de FastAPI.
    """

    _client: aioredis.Redis = None

    @classmethod
    def _get_client(cls) -> aioredis.Redis:
        """Singleton: crea el cliente Redis solo la primera vez."""
        if cls._client is None:
            settings = get_settings()
            cls._client = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,   # retorna str en lugar de bytes
            )
        return cls._client

    @staticmethod
    def _session_key(phone: str) -> str:
        """
        Genera la clave Redis para el número dado.
        Normalizamos eliminando el prefijo 'whatsapp:' de Twilio.
        """
        clean = phone.replace("whatsapp:", "").strip()
        return f"session:{clean}"

    @classmethod
    async def get_history(cls, phone: str) -> List[dict]:
        """
        Retorna el historial de mensajes de la sesión activa.
        Si no hay sesión (primera vez o TTL expirado) → lista vacía.
        """
        raw = await cls._get_client().get(cls._session_key(phone))
        return json.loads(raw) if raw else []

    @classmethod
    async def add_messages(cls, phone: str, user_msg: str, assistant_msg: str) -> None:
        """
        Agrega el par (usuario → asistente) al historial y reinicia el TTL.

        Guardamos de a pares para mantener la coherencia conversacional:
        siempre un turno de usuario seguido de un turno del asistente.

        Truncamos al MAX_HISTORY_MESSAGES para no superar el context
        window del LLM al construir el prompt en el siguiente turno.
        """
        client = cls._get_client()
        history = await cls.get_history(phone)

        history.append({"role": "user",      "content": user_msg})
        history.append({"role": "assistant", "content": assistant_msg})

        # Truncar: quedarse con los mensajes más recientes
        history = history[-MAX_HISTORY_MESSAGES:]

        # setex → SET + EXpire en una sola operación atómica
        await client.setex(cls._session_key(phone), SESSION_TTL, json.dumps(history))
        logger.debug(f"Historial Redis actualizado para {phone}: {len(history)} mensajes")

    @classmethod
    def to_langchain_messages(cls, history: List[dict]) -> List[BaseMessage]:
        """
        Convierte el historial JSON en objetos LangChain.

        LangChain espera una lista de BaseMessage para construir
        la conversación. El LLM los recibe como contexto previo
        y puede referirse a información mencionada antes.

        Ejemplo de lo que el LLM "ve":
          HumanMessage("me llamo Juan")
          AIMessage("¡Hola Juan! ¿En qué puedo ayudarte?")
          HumanMessage("¿cómo me llamo?")   ← pregunta actual
          → LLM responde "Te llamas Juan"   ← gracias al historial
        """
        messages: List[BaseMessage] = []
        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))
        return messages

    @classmethod
    async def clear_session(cls, phone: str) -> None:
        """Elimina la sesión de Redis (se llama al persistir en PostgreSQL)."""
        await cls._get_client().delete(cls._session_key(phone))
        logger.info(f"Sesión Redis eliminada para {phone}")

