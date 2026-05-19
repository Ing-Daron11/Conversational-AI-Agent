"""
calendar_mcp.py — MCP Tools para Google Calendar

CONCEPTO MCP (Model Context Protocol):
  MCP es el estándar de Anthropic para conectar LLMs con servicios externos.
  Cada "tool" define un contrato que el LLM entiende:
    - nombre:       identificador único ("create_calendar_event")
    - descripción:  texto en lenguaje natural que guía al LLM sobre CUÁNDO usarlo
    - input_schema: JSON Schema de los parámetros (el LLM los infiere del mensaje)

  Ejemplo: el usuario dice "agéndame clase de álgebra el viernes a las 10 am"
  El LLM lee las descripciones de los tools disponibles y decide:
    → llamar a create_calendar_event(
          title="Clase de Álgebra",
          date="2026-05-22",         ← el LLM convierte "viernes" a fecha ISO
          time="10:00",
          description=""
      )

AUTENTICACIÓN GOOGLE:
  Usamos OAuth2 con un archivo token.json en disco.
  Flujo de primera vez:
    1. El admin visita GET /auth/google → redirige a Google
    2. El admin autoriza → Google redirige a /auth/google/callback
    3. El callback guarda el token en TOKEN_PATH
    4. Desde ese momento las tools lo usan automáticamente
    5. El token se refresca automáticamente al expirar
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from langchain_core.tools import tool
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Ruta donde se almacena el token OAuth2 (generado en /auth/google/callback)
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "../../../../google_token.json")
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _get_calendar_service():
    """
    Construye el cliente de Google Calendar API autenticado.

    Carga el token guardado en disco y lo refresca si está expirado.
    Si no existe token, lanza una excepción descriptiva.
    """
    token_path = os.path.abspath(TOKEN_PATH)

    if not os.path.exists(token_path):
        raise RuntimeError(
            "No hay token de Google guardado. "
            "El administrador debe autenticarse primero en GET /auth/google"
        )

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # Refrescar token si está expirado (Google emite tokens de 1 hora)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Guardar el token refrescado
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


# ─────────────────────────────────────────────────────────────
# TOOLS MCP — decoradas con @tool de LangChain
# El docstring ES la descripción que el LLM lee para decidir
# cuándo y cómo llamar cada tool. Debe ser claro y en el mismo
# idioma que el sistema (español en este caso).
# ─────────────────────────────────────────────────────────────

@tool
def create_calendar_event(
    title: str,
    date: str,
    time: str,
    description: str = "",
    duration_minutes: int = 60,
) -> str:
    """
    Crea un nuevo evento en Google Calendar del usuario.
    Úsala cuando el usuario quiera agendar, programar o crear una cita, clase o reunión.

    Args:
        title: nombre del evento (ej: "Clase de Cálculo", "Reunión de proyecto")
        date: fecha en formato ISO YYYY-MM-DD (ej: "2026-05-22")
        time: hora en formato HH:MM de 24h (ej: "10:00", "15:30")
        description: descripción opcional del evento
        duration_minutes: duración del evento en minutos (por defecto 60)

    Returns:
        Confirmación con el link al evento creado o mensaje de error.
    """
    try:
        service = _get_calendar_service()

        # Construir datetime de inicio y fin
        start_dt = datetime.fromisoformat(f"{date}T{time}:00")
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        # Formato RFC3339 requerido por la API de Google Calendar
        tz = "America/Bogota"  # ajustar según zona horaria del usuario
        event_body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
            "end":   {"dateTime": end_dt.isoformat(),   "timeZone": tz},
        }

        created = service.events().insert(
            calendarId="primary",
            body=event_body,
        ).execute()

        link = created.get("htmlLink", "")
        logger.info(f"Evento creado: {title} el {date} a las {time}")
        return f"Evento '{title}' creado para el {date} a las {time}. Ver: {link}"

    except RuntimeError as e:
        return f"Error de autenticación: {e}"
    except Exception as e:
        logger.error(f"Error al crear evento: {e}")
        return f"No se pudo crear el evento: {e}"


@tool
def list_calendar_events(start_date: str, end_date: str) -> str:
    """
    Lista los eventos de Google Calendar en un rango de fechas.
    Úsala cuando el usuario pregunte qué tiene agendado, qué eventos hay, o su agenda.

    Args:
        start_date: fecha de inicio en formato ISO YYYY-MM-DD (ej: "2026-05-19")
        end_date: fecha de fin en formato ISO YYYY-MM-DD (ej: "2026-05-25")

    Returns:
        Lista de eventos en el rango dado, o mensaje si no hay eventos.
    """
    try:
        service = _get_calendar_service()

        # La API requiere formato RFC3339 con hora y timezone
        time_min = f"{start_date}T00:00:00Z"
        time_max = f"{end_date}T23:59:59Z"

        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=10,
        ).execute()

        events = result.get("items", [])

        if not events:
            return f"No tienes eventos agendados entre {start_date} y {end_date}."

        lines = [f"Eventos del {start_date} al {end_date}:"]
        for ev in events:
            start = ev["start"].get("dateTime", ev["start"].get("date", ""))
            # Formatear la fecha legible
            try:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                readable = dt.strftime("%A %d/%m a las %H:%M")
            except Exception:
                readable = start
            lines.append(f"• {ev.get('summary', 'Sin título')} — {readable}")

        return "\n".join(lines)

    except RuntimeError as e:
        return f"Error de autenticación: {e}"
    except Exception as e:
        logger.error(f"Error al listar eventos: {e}")
        return f"No se pudieron obtener los eventos: {e}"


@tool
def delete_calendar_event(event_title: str, date: str) -> str:
    """
    Cancela (elimina) un evento de Google Calendar por su título y fecha.
    Úsala cuando el usuario quiera cancelar, eliminar o borrar una cita o evento.

    Args:
        event_title: título del evento a cancelar (ej: "Clase de Álgebra")
        date: fecha del evento en formato ISO YYYY-MM-DD (ej: "2026-05-22")

    Returns:
        Confirmación de cancelación o mensaje de error.
    """
    try:
        service = _get_calendar_service()

        # Buscar el evento por título en esa fecha
        time_min = f"{date}T00:00:00Z"
        time_max = f"{date}T23:59:59Z"
        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            q=event_title,  # búsqueda por texto
            singleEvents=True,
        ).execute()

        events = result.get("items", [])
        if not events:
            return f"No encontré un evento llamado '{event_title}' el {date}."

        # Eliminar el primer evento que coincida
        event_id = events[0]["id"]
        service.events().delete(calendarId="primary", eventId=event_id).execute()

        logger.info(f"Evento eliminado: {event_title} el {date}")
        return f"Evento '{event_title}' del {date} cancelado correctamente."

    except RuntimeError as e:
        return f"Error de autenticación: {e}"
    except Exception as e:
        logger.error(f"Error al cancelar evento: {e}")
        return f"No se pudo cancelar el evento: {e}"

