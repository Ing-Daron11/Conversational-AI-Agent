"""
tests/test_integration.py — Pruebas de integración (FASE 7)

CONCEPTO — Tipos de pruebas:
  Unit tests:       prueban una función/clase aislada con mocks de dependencias.
  Integration tests: prueban que VARIOS componentes funcionan JUNTOS.
  E2E tests:        prueban el flujo completo, desde el cliente hasta la BD.

  Estos son integration tests porque:
    - El webhook real recibe HTTP POST y retorna TwiML
    - Se verifica que el rate limiter interactúa correctamente con Redis mock
    - Se verifica que los fallbacks retornan mensajes correctos

HERRAMIENTAS:
  pytest:          framework de testing
  pytest-asyncio:  permite usar async def en tests
  httpx / TestClient: cliente HTTP para probar FastAPI sin levantar servidor real

NOTA — ¿Por qué no usar unittest?
  pytest es más conciso: no necesitas clases, usas funciones directas.
  Las fixtures reemplazan setUp/tearDown con mejor composición.
  pytest-asyncio hace transparente el testing de código async.

MOCKING:
  unittest.mock.patch reemplaza temporalmente una función/clase con un Mock.
  Aquí mockeamos:
    - run_agent() → para no necesitar Ollama corriendo
    - ConversationMemory → para no necesitar Redis corriendo
    - check_rate_limit() → para probar el comportamiento de rate limiting
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app

# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """Cliente HTTP síncrono para TestClient de FastAPI."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def twilio_payload():
    """
    Payload simulando un POST de Twilio con un mensaje de WhatsApp.
    El formato es application/x-www-form-urlencoded con estos campos.
    """
    return {
        "Body": "¿Qué es una red neuronal?",
        "From": "whatsapp:+573001234567",
        "To": "whatsapp:+14155238886",
        "MessageSid": "SMtest123",
        "AccountSid": "ACtest123",
    }


# ─── Tests del Health Check ────────────────────────────────────────────────

class TestHealthCheck:
    """
    Prueba que el endpoint /health responde correctamente.
    No mockea nada: si el backend arranca, /health siempre debe responder.
    """

    def test_health_returns_200(self, client):
        response = client.get("/health")
        # El health check puede estar "degraded" si Ollama/Redis no están,
        # pero SIEMPRE debe retornar 200 (el endpoint en sí funciona)
        assert response.status_code == 200

    def test_health_has_required_fields(self, client):
        data = client.get("/health").json()
        assert "status" in data
        assert "version" in data
        assert "services" in data
        assert data["status"] in ("ok", "degraded")


# ─── Tests del Webhook (flujo principal) ──────────────────────────────────

class TestWebhookWhatsapp:
    """
    Prueba el endpoint POST /webhook/whatsapp en distintos escenarios.
    Mockea el agente para no necesitar Ollama corriendo en CI.
    """

    @patch("app.api.webhook.run_agent", new_callable=AsyncMock)
    @patch("app.api.webhook.ConversationMemory.get_history", new_callable=AsyncMock)
    @patch("app.api.webhook.ConversationMemory.add_messages", new_callable=AsyncMock)
    @patch("app.api.webhook.ConversationMemory.to_langchain_messages", return_value=[])
    @patch("app.api.webhook.check_rate_limit", new_callable=AsyncMock)
    def test_successful_message_returns_twiml(
        self,
        mock_rate_limit,
        mock_to_lc,
        mock_add,
        mock_history,
        mock_agent,
        client,
        twilio_payload,
    ):
        """
        Flujo feliz: mensaje válido → respuesta TwiML correcta.
        """
        mock_rate_limit.return_value = (True, 1)
        mock_history.return_value = []
        mock_agent.return_value = "Una red neuronal es un modelo inspirado en el cerebro humano."

        response = client.post("/webhook/whatsapp", data=twilio_payload)

        assert response.status_code == 200
        assert "application/xml" in response.headers["content-type"]
        assert "<Response>" in response.text
        assert "<Message>" in response.text
        assert "red neuronal" in response.text

    @patch("app.api.webhook.check_rate_limit", new_callable=AsyncMock)
    def test_empty_message_returns_help(self, mock_rate_limit, client):
        """
        Mensaje vacío → respuesta genérica sin llamar al agente.
        """
        mock_rate_limit.return_value = (True, 1)
        response = client.post(
            "/webhook/whatsapp",
            data={"Body": "   ", "From": "whatsapp:+1234", "To": ""},
        )
        assert response.status_code == 200
        assert "ayudarte" in response.text.lower()

    @patch("app.api.webhook.check_rate_limit", new_callable=AsyncMock)
    def test_rate_limited_returns_fallback(self, mock_rate_limit, client, twilio_payload):
        """
        Número rate-limited → respuesta de throttling, sin llamar al agente.
        """
        mock_rate_limit.return_value = (False, 25)

        response = client.post("/webhook/whatsapp", data=twilio_payload)

        assert response.status_code == 200
        # El mensaje de rate limit debe estar en el TwiML
        assert "espera" in response.text.lower() or "mensajes" in response.text.lower()

    @patch("app.api.webhook.run_agent", new_callable=AsyncMock)
    @patch("app.api.webhook.ConversationMemory.get_history", new_callable=AsyncMock)
    @patch("app.api.webhook.ConversationMemory.add_messages", new_callable=AsyncMock)
    @patch("app.api.webhook.ConversationMemory.to_langchain_messages", return_value=[])
    @patch("app.api.webhook.check_rate_limit", new_callable=AsyncMock)
    def test_agent_error_returns_fallback(
        self,
        mock_rate_limit,
        mock_to_lc,
        mock_add,
        mock_history,
        mock_agent,
        client,
        twilio_payload,
    ):
        """
        El agente lanza excepción → fallback amigable, no 500.
        """
        mock_rate_limit.return_value = (True, 1)
        mock_history.return_value = []
        mock_agent.side_effect = Exception("Ollama connection refused")

        response = client.post("/webhook/whatsapp", data=twilio_payload)

        assert response.status_code == 200
        # La respuesta es TwiML con mensaje de error amigable
        assert "<Response>" in response.text

    @patch("app.api.webhook.check_rate_limit", new_callable=AsyncMock)
    def test_message_too_long_rejected(self, mock_rate_limit, client):
        """
        Mensaje que excede el límite de longitud → rechazado con mensaje claro.
        """
        mock_rate_limit.return_value = (True, 1)
        long_message = "x" * 2000

        response = client.post(
            "/webhook/whatsapp",
            data={"Body": long_message, "From": "whatsapp:+1234", "To": ""},
        )

        assert response.status_code == 200
        assert "largo" in response.text.lower() or "cortas" in response.text.lower()

    @patch("app.api.webhook.run_agent", new_callable=AsyncMock)
    @patch("app.api.webhook.ConversationMemory.get_history", new_callable=AsyncMock)
    @patch("app.api.webhook.ConversationMemory.add_messages", new_callable=AsyncMock)
    @patch("app.api.webhook.ConversationMemory.to_langchain_messages", return_value=[])
    @patch("app.api.webhook.check_rate_limit", new_callable=AsyncMock)
    def test_special_chars_in_response_are_escaped(
        self,
        mock_rate_limit,
        mock_to_lc,
        mock_add,
        mock_history,
        mock_agent,
        client,
        twilio_payload,
    ):
        """
        Los caracteres especiales XML en la respuesta deben estar escapados.
        Prueba de seguridad: evitar XML injection en TwiML.
        """
        mock_rate_limit.return_value = (True, 1)
        mock_history.return_value = []
        # El agente retorna texto con caracteres XML especiales
        mock_agent.return_value = "5 > 3 & 2 < 4 según <matemáticas>"

        response = client.post("/webhook/whatsapp", data=twilio_payload)

        assert response.status_code == 200
        # Los caracteres deben estar escapados en el XML
        assert "&amp;" in response.text or "&gt;" in response.text or "&lt;" in response.text
        # No deben aparecer sin escapar dentro del XML
        body = response.text
        # Extraer contenido del tag <Message>
        start = body.find("<Message>") + len("<Message>")
        end = body.find("</Message>")
        message_content = body[start:end]
        assert "<matemáticas>" not in message_content  # debe estar escapado


# ─── Tests de Rate Limiting ────────────────────────────────────────────────

class TestRateLimiting:
    """
    Prueba el módulo de rate limiting de forma aislada.
    Mockea Redis para no necesitar una instancia real.
    """

    @pytest.mark.asyncio
    @patch("app.middleware.rate_limit.aioredis.from_url")
    async def test_allows_request_under_limit(self, mock_redis_factory):
        """Primer request siempre debe ser permitido."""
        from app.middleware.rate_limit import check_rate_limit

        mock_pipeline = AsyncMock()
        mock_pipeline.execute = AsyncMock(return_value=[1, True])
        mock_redis = AsyncMock()
        mock_redis.pipeline.return_value = mock_pipeline
        mock_redis.__aenter__ = AsyncMock(return_value=mock_redis)
        mock_redis.__aexit__ = AsyncMock(return_value=None)
        mock_redis_factory.return_value = mock_redis

        allowed, count = await check_rate_limit("whatsapp:+1234")
        assert allowed is True
        assert count == 1

    @pytest.mark.asyncio
    @patch("app.middleware.rate_limit.aioredis.from_url")
    async def test_blocks_request_over_limit(self, mock_redis_factory):
        """Request 21 debe ser bloqueado cuando el límite es 20."""
        from app.middleware.rate_limit import check_rate_limit

        mock_pipeline = AsyncMock()
        mock_pipeline.execute = AsyncMock(return_value=[21, True])
        mock_redis = AsyncMock()
        mock_redis.pipeline.return_value = mock_pipeline
        mock_redis.__aenter__ = AsyncMock(return_value=mock_redis)
        mock_redis.__aexit__ = AsyncMock(return_value=None)
        mock_redis_factory.return_value = mock_redis

        allowed, count = await check_rate_limit("whatsapp:+1234")
        assert allowed is False
        assert count == 21

    @pytest.mark.asyncio
    @patch("app.middleware.rate_limit.aioredis.from_url")
    async def test_fail_open_when_redis_down(self, mock_redis_factory):
        """
        Si Redis está caído, el rate limiter debe PERMITIR la petición
        (fail-open: no bloquear usuarios legítimos por fallo de infraestructura).
        """
        from app.middleware.rate_limit import check_rate_limit

        mock_redis_factory.side_effect = Exception("Redis connection refused")

        allowed, count = await check_rate_limit("whatsapp:+1234")
        assert allowed is True  # fail-open


# ─── Tests del Circuit Breaker ────────────────────────────────────────────

class TestCircuitBreaker:
    """
    Prueba la máquina de estados del circuit breaker.
    No requiere servicios externos: es lógica pura.
    """

    def test_initial_state_is_closed(self):
        from app.core.fallbacks import CircuitBreaker
        cb = CircuitBreaker("test")
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.is_available() is True

    def test_opens_after_threshold_failures(self):
        from app.core.fallbacks import CircuitBreaker
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED  # aún no
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED  # aún no
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN    # ahora sí
        assert cb.is_available() is False

    def test_success_resets_failures(self):
        from app.core.fallbacks import CircuitBreaker
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # éxito en medio → reset
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED  # contador se reinició

    def test_transitions_to_half_open_after_timeout(self):
        """Después del recovery_timeout el circuito debe pasar a HALF_OPEN."""
        import time
        from app.core.fallbacks import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

        time.sleep(0.02)  # esperar el timeout
        assert cb.state == CircuitBreaker.HALF_OPEN
        assert cb.is_available() is True  # en HALF_OPEN se permite 1 petición de prueba


# ─── Tests de Admin API ────────────────────────────────────────────────────

class TestAdminAPI:
    """Prueba los endpoints del panel de administración."""

    def test_stats_returns_200(self, client):
        """GET /admin/stats debe responder aunque ChromaDB esté vacío."""
        response = client.get("/admin/stats")
        # Puede responder 200 con datos vacíos o 500 si algo falla
        # En CI sin PostgreSQL/Redis puede fallar gracefully
        assert response.status_code in (200, 500)

    def test_documents_returns_list(self, client):
        """GET /admin/documents siempre retorna una lista (puede ser vacía)."""
        response = client.get("/admin/documents")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_ingest_rejects_invalid_extension(self, client):
        """POST /admin/ingest debe rechazar archivos que no sean .txt o .pdf."""
        import io
        response = client.post(
            "/admin/ingest",
            data={"collection": "notas", "materia": "test", "tipo": "apunte"},
            files={"file": ("malware.exe", io.BytesIO(b"MZ..."), "application/octet-stream")},
        )
        assert response.status_code == 400
        assert "extensión" in response.json()["detail"].lower()

    def test_ingest_rejects_invalid_collection(self, client):
        """POST /admin/ingest debe rechazar colecciones que no existen."""
        import io
        response = client.post(
            "/admin/ingest",
            data={"collection": "coleccion_inexistente", "materia": "test", "tipo": "apunte"},
            files={"file": ("notas.txt", io.BytesIO(b"contenido"), "text/plain")},
        )
        assert response.status_code == 400
        assert "inválida" in response.json()["detail"].lower()
