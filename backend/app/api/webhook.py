"""
webhook.py — Endpoint de recepción de mensajes de WhatsApp (Twilio)

FLUJO:
  1. Twilio recibe un mensaje de WhatsApp del usuario
  2. Twilio hace un HTTP POST a este endpoint con los datos del mensaje
  3. Extraemos el texto y el remitente
  4. Generamos una respuesta (en FASE 0: respuesta fija "hola mundo")
  5. Respondemos con TwiML — el XML que Twilio interpreta para enviar
     el mensaje de vuelta al usuario por WhatsApp

CONCEPTO CLAVE — Webhook:
  A diferencia de una API REST donde el cliente pregunta ("polling"),
  en un webhook es el proveedor (Twilio) quien nos notifica en tiempo
  real cuando ocurre un evento (mensaje nuevo). Esto reduce latencia
  y consumo de recursos.
"""

import logging
from fastapi import APIRouter, Form, Request, Response
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


def build_twiml_response(message: str) -> str:
    """
    Construye una respuesta TwiML (Twilio Markup Language).

    TwiML es el formato XML que Twilio entiende para saber qué mensaje
    enviar de vuelta al usuario. El tag <Message> dentro de <Response>
    indica el texto a enviar por WhatsApp.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Message>{message}</Message>"
        "</Response>"
    )


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    Body: str = Form(default=""),       # texto del mensaje del usuario
    From: str = Form(default=""),       # número del remitente (ej: whatsapp:+5219...)
    To: str = Form(default=""),         # número Twilio receptor
):
    """
    Endpoint principal del webhook.

    Twilio envía los datos como form-data (application/x-www-form-urlencoded),
    por eso usamos Form() en los parámetros en lugar de un JSON body.

    En FASE 0: responde con un saludo fijo.
    En FASE 2+: aquí se llamará al orquestador del agente con el mensaje
    y el historial de conversación del usuario.
    """
    logger.info(f"Mensaje recibido de {From}: {Body!r}")

    # --- FASE 0: lógica de respuesta mínima ---
    # Detectamos un saludo simple para demostrar que el flujo funciona.
    # En FASE 2, esto se reemplazará por el orquestador LangChain.
    user_message = Body.strip().lower()

    if user_message in ("hola", "hi", "hello", "buenas"):
        reply = "¡Hola! Soy tu asistente académico. ¿En qué puedo ayudarte?"
    elif user_message == "ping":
        reply = "pong"
    else:
        reply = (
            "Hola, soy tu asistente académico personal. "
            "Aún estoy en configuración inicial. ¡Pronto podré ayudarte con tus notas y calendario!"
        )

    logger.info(f"Respuesta enviada a {From}: {reply!r}")

    # Retornamos TwiML con el Content-Type correcto
    twiml = build_twiml_response(reply)
    return Response(content=twiml, media_type="application/xml")
