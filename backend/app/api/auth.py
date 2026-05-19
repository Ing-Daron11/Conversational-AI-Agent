"""
auth.py — Router de autenticación Google OAuth2

CONCEPTO — OAuth2:
  OAuth2 es el protocolo estándar para que una aplicación acceda a
  recursos de un usuario en un servicio externo (Google, GitHub, etc.)
  SIN necesitar las credenciales del usuario.

  Flujo Authorization Code (el que usamos):
    1. La app redirige al usuario a Google → pantalla de consentimiento
    2. El usuario acepta → Google redirige a nuestra callback URL con un "code"
    3. La app intercambia el "code" por un access_token + refresh_token
    4. La app guarda el token en disco → lo usa para llamar a las APIs de Google
    5. Cuando expira (1 hora), el refresh_token obtiene uno nuevo automáticamente

  Este flujo solo lo hace el ADMINISTRADOR una vez. Los estudiantes
  (usuarios de WhatsApp) no necesitan autenticarse con Google.

ENDPOINTS:
  GET /auth/google           → redirige al consent screen de Google
  GET /auth/google/callback  → recibe el código, guarda el token

CONFIGURACIÓN REQUERIDA en .env:
  GOOGLE_CLIENT_ID=...        (desde Google Cloud Console)
  GOOGLE_CLIENT_SECRET=...
  GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

SETUP INICIAL (solo una vez):
  1. Crear proyecto en https://console.cloud.google.com
  2. Habilitar Google Calendar API y Google Drive API
  3. Crear credenciales OAuth2 "Web Application"
  4. Agregar http://localhost:8000/auth/google/callback como URI autorizada
  5. Visitar GET /auth/google con el browser del admin
"""

import json
import logging
import os

from fastapi import APIRouter
from fastapi.responses import RedirectResponse, JSONResponse
from google_auth_oauthlib.flow import Flow

from app.config import get_settings

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)
settings = get_settings()

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
]

TOKEN_PATH = os.path.join(
    os.path.dirname(__file__), "../../../google_token.json"
)


def _build_flow() -> Flow:
    """
    Construye el flujo OAuth2 de Google a partir de las credenciales en config.
    """
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uris": [settings.google_redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=settings.google_redirect_uri,
    )


@router.get("/google", summary="Iniciar autenticación con Google")
def google_auth_start():
    """
    Paso 1: Redirige al admin al consent screen de Google.
    Visitar este endpoint desde el navegador del administrador.

    Si GOOGLE_CLIENT_ID no está configurado, retorna instrucciones.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Google OAuth no configurado",
                "instrucciones": [
                    "1. Ve a https://console.cloud.google.com",
                    "2. Crea un proyecto y habilita Calendar API + Drive API",
                    "3. Crea credenciales OAuth2 'Web Application'",
                    "4. Agrega http://localhost:8000/auth/google/callback como URI autorizada",
                    "5. Agrega GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET al archivo .env",
                ]
            }
        )

    flow = _build_flow()
    # access_type=offline → Google entrega refresh_token (necesario para renovar)
    # prompt=consent → fuerza la pantalla de consentimiento (recomendado en desarrollo)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    return RedirectResponse(url=auth_url)


@router.get("/google/callback", summary="Callback de Google OAuth")
def google_auth_callback(code: str, state: str = ""):
    """
    Paso 2: Google redirige aquí con un 'code' tras el consentimiento del admin.
    Intercambiamos el code por tokens y los guardamos en disco.
    """
    if not code:
        return JSONResponse(status_code=400, content={"error": "Código de autorización faltante"})

    try:
        flow = _build_flow()
        # Intercambiar el código por tokens
        flow.fetch_token(code=code)

        token_path = os.path.abspath(TOKEN_PATH)
        # Guardar token en disco (incluye refresh_token para renovación automática)
        with open(token_path, "w") as f:
            f.write(flow.credentials.to_json())

        logger.info(f"Token de Google guardado en {token_path}")
        return JSONResponse(content={
            "status": "ok",
            "mensaje": "Autenticación exitosa. Las tools de Google Calendar y Drive ya están disponibles.",
            "token_guardado_en": token_path,
        })

    except Exception as e:
        logger.error(f"Error en callback de Google: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Error al obtener token: {e}"}
        )


@router.get("/status", summary="Estado de la autenticación con Google")
def auth_status():
    """Verifica si el token de Google está guardado y es válido."""
    token_path = os.path.abspath(TOKEN_PATH)
    if not os.path.exists(token_path):
        return {"autenticado": False, "mensaje": "Sin token. Visita GET /auth/google"}

    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        return {
            "autenticado": True,
            "expirado": creds.expired,
            "tiene_refresh_token": bool(creds.refresh_token),
        }
    except Exception as e:
        return {"autenticado": False, "error": str(e)}
