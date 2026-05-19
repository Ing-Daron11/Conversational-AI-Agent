"""
orchestrator.py — Orquestador del Agente IA (LangChain AgentExecutor)

CONCEPTO — Agente vs. Chain:
  Una Chain es un flujo fijo: entrada → paso1 → paso2 → salida.
  Un Agente es dinámico: dado un mensaje, DECIDE qué pasos ejecutar.
  Puede llamar tools en cualquier orden, múltiples veces, o ninguna.

  El agente de este sistema puede:
    1. Responder directamente con conocimiento general (sin tools)
    2. Llamar a search_notes → busca en Chroma (RAG dinámico)
    3. Llamar a list_calendar_events → consulta Google Calendar
    4. Llamar a create_calendar_event → agenda un evento
    5. Llamar a delete_calendar_event → cancela un evento
    6. Encadenar: busca notas Y consulta calendario en el mismo turno

FLUJO INTERNO DEL AGENTE (tool calling loop):
  1. LLM recibe el mensaje + historial + lista de tools disponibles
  2. LLM emite una "acción": qué tool llamar y con qué parámetros
  3. La tool se ejecuta → retorna un resultado
  4. El resultado se agrega al contexto del LLM
  5. LLM decide: ¿necesito otra tool? → repite
                 ¿tengo suficiente info? → genera respuesta final

MEMORIA:
  El historial de conversación (de Redis) se pasa como chat_history.
  El AgentExecutor no maneja memoria por sí solo; nosotros la inyectamos.
"""

import logging
from typing import List

from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langchain.schema import BaseMessage

from app.agent.tools.calendar_mcp import (
    create_calendar_event,
    list_calendar_events,
    delete_calendar_event,
)
from app.agent.tools.drive_mcp import search_drive_files, index_drive_file
from app.rag.retriever import retrieve_context
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ── Tool RAG: búsqueda semántica en notas ─────────────────────────────────────
# Envolvemos retrieve_context como un tool MCP para que el agente
# decida cuándo usarlo, en lugar de llamarlo siempre (como en FASE 1).
# Esto es más eficiente: no se hace RAG si el usuario solo saluda.

@tool
def search_notes(query: str) -> str:
    """
    Busca en las notas y apuntes académicos almacenados del usuario.
    Úsala cuando el usuario pregunte sobre contenido de sus materias,
    quiera saber qué vimos en un tema, o pida un resumen de sus apuntes.

    Args:
        query: término o pregunta a buscar (ej: "backpropagation", "módulo 3")

    Returns:
        Fragmentos relevantes de las notas, o aviso si no hay información.
    """
    context = retrieve_context(query)
    return context if context else "No encontré información sobre ese tema en tus notas."


# ── Lista completa de tools disponibles para el agente ───────────────────────
TOOLS = [
    search_notes,           # RAG dinámico
    create_calendar_event,  # MCP: agendar
    list_calendar_events,   # MCP: consultar agenda
    delete_calendar_event,  # MCP: cancelar
    search_drive_files,     # MCP: buscar en Drive
    index_drive_file,       # MCP: indexar doc de Drive
]

# ── Prompt del agente ─────────────────────────────────────────────────────────
# MessagesPlaceholder("agent_scratchpad") es donde LangChain inyecta
# el historial de tool calls intermedias (el "razonamiento" del agente).

AGENT_SYSTEM_PROMPT = """Eres un asistente académico personal amigable y preciso.
Tu usuario te contacta por WhatsApp para gestionar su vida académica.

HERRAMIENTAS DISPONIBLES:
Tienes acceso a herramientas para buscar en notas, consultar y gestionar
el calendario de Google, y buscar documentos en Google Drive.
Úsalas cuando sea necesario para dar respuestas precisas y actualizadas.

REGLAS:
- Responde siempre en español, de forma concisa (máximo 3-4 oraciones para WhatsApp)
- Usa search_notes cuando pregunten sobre contenido académico o tus apuntes
- Usa list_calendar_events cuando pregunten sobre agenda o eventos futuros
- Antes de crear o cancelar un evento, SIEMPRE confirma los detalles con el usuario
- Si no encuentras información, dilo claramente en lugar de inventar
- Recuerda el contexto de la conversación actual para dar respuestas coherentes"""

AGENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", AGENT_SYSTEM_PROMPT),
    MessagesPlaceholder("chat_history"),      # historial de Redis (FASE 2)
    ("human", "{input}"),                     # mensaje actual del usuario
    MessagesPlaceholder("agent_scratchpad"),  # razonamiento interno del agente
])


def get_agent_executor() -> AgentExecutor:
    """
    Construye y retorna el AgentExecutor configurado.

    create_tool_calling_agent: crea un agente que usa el mecanismo nativo
    de "tool calling" del LLM (Qwen3 lo soporta). El LLM emite las llamadas
    a tools como JSON estructurado, no como texto libre que hay que parsear.

    verbose=True: imprime el razonamiento interno (qué tools llamó, con qué
    parámetros, qué respondieron). Muy útil para entender el funcionamiento.
    """
    llm = ChatOllama(
        model=settings.ollama_model,
        temperature=settings.llm_temperature,
        num_predict=settings.llm_max_tokens,
        base_url=settings.ollama_base_url,
    )

    agent = create_tool_calling_agent(llm, TOOLS, AGENT_PROMPT)

    return AgentExecutor(
        agent=agent,
        tools=TOOLS,
        verbose=True,
        max_iterations=5,
        handle_parsing_errors=True,
    )


async def run_agent(user_message: str, chat_history: List[BaseMessage]) -> str:
    """
    Ejecuta el agente con el mensaje del usuario y el historial de conversación.

    Args:
        user_message:  mensaje actual del usuario
        chat_history:  lista de HumanMessage / AIMessage de Redis (FASE 2)

    Returns:
        Respuesta final del agente, lista para enviar por WhatsApp.
    """
    executor = get_agent_executor()

    result = await executor.ainvoke({
        "input": user_message,
        "chat_history": chat_history,
    })

    reply = result.get("output", "No pude generar una respuesta. Intenta de nuevo.")
    logger.info(f"Agente respondió: {reply[:100]}...")
    return reply

