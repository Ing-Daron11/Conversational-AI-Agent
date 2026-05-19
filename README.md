# Asistente Académico por WhatsApp

Sistema de IA conversacional que permite a un estudiante gestionar su vida académica
desde WhatsApp. Combina RAG, agentes LangChain, integración con Google Calendar/Drive
y un panel de administración web.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────────┐
│                     CAPA 1 — CANAL                                  │
│                                                                     │
│   Usuario (WhatsApp)  ──►  Twilio Webhook  ──►  POST /webhook/whatsapp │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                     ┌───────────▼───────────┐
                     │   Rate Limiter (Redis) │  ← FASE 7
                     │   20 req / 60 seg      │
                     └───────────┬───────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│                     CAPA 2 — ORQUESTADOR                            │
│                                                                     │
│   ConversationMemory (Redis TTL 30min)  ← FASE 2                   │
│   AgentExecutor (LangChain)             ← FASE 3                   │
│     ├── search_notes(query)     → RAG tool                         │
│     ├── create_calendar_event() → Google Calendar                  │
│     ├── list_calendar_events()  → Google Calendar                  │
│     ├── delete_calendar_event() → Google Calendar                  │
│     ├── search_drive_files()    → Google Drive                     │
│     └── index_drive_file()      → ingestión desde Drive            │
└──────────┬─────────────────────┬───────────────────────────────────┘
           │                     │
┌──────────▼──────────┐  ┌───────▼────────────────────────────────┐
│   MOTOR IA (LLM)    │  │   PIPELINE RAG — FASE 5                │
│                     │  │                                        │
│ Ollama (local)      │  │  Stage 1 — Bi-encoder retrieval        │
│ qwen3:4b            │  │    query → nomic-embed-text            │
│ Fine-tuning LoRA    │  │    → similarity_search(k=15)           │
│   ← FASE 4          │  │    → top-15 candidatos                 │
│                     │  │                                        │
│ Circuit Breaker     │  │  Stage 2 — Cross-encoder rerank        │
│   ← FASE 7          │  │    (query, doc_i) → score              │
└──────────┬──────────┘  │    ms-marco-MiniLM-L-6-v2             │
           │             │    → top-3 más relevantes              │
           │             └───────┬────────────────────────────────┘
           │                     │
┌──────────▼─────────────────────▼───────────────────────────────────┐
│                     CAPA 4 — ALMACENAMIENTO                        │
│                                                                     │
│  ┌─────────────────────────────────────────┐                       │
│  │ BD VECTORIAL (Chroma local / Pinecone)  │                       │
│  │  Shard "notas"    — apuntes de clase    │                       │
│  │  Shard "tareas"   — enunciados          │                       │
│  │  Shard "examenes" — guías de examen     │                       │
│  └─────────────────────────────────────────┘                       │
│                                                                     │
│  ┌───────────────────────────┐  ┌──────────────────────────────┐  │
│  │ PostgreSQL 15             │  │ Redis 7                      │  │
│  │  - User                   │  │  - session:{phone}  TTL 30m  │  │
│  │  - ConversationMessage    │  │  - rl:{phone}       TTL 60s  │  │
│  └───────────────────────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│                     CAPA 5 — PANEL ADMIN (Next.js 14)              │
│                                                                     │
│  http://localhost:3000                                              │
│   /             → Dashboard (métricas: docs, conversaciones, sesiones) │
│   /documents    → Lista de docs indexados + formulario de subida   │
│   /calendar     → Próximos eventos de Google Calendar              │
│   /auth         → Estado OAuth2 + botón de conexión Google         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Stack tecnológico

| Capa | Tecnología | Versión |
|---|---|---|
| LLM local | Ollama + qwen3:4b | latest |
| Embeddings | nomic-embed-text | latest |
| Re-ranker | ms-marco-MiniLM-L-6-v2 | ~66 MB |
| Orquestador | LangChain | 0.2.16 |
| Backend | FastAPI + Uvicorn | 0.111.0 |
| BD Vectorial (dev) | ChromaDB | 0.5.23 |
| BD Vectorial (prod) | Pinecone | ≥4.0.0 |
| BD Relacional | PostgreSQL | 15 |
| Caché / Sesiones | Redis | 7 |
| Fine-tuning | PEFT/LoRA + TRL | 0.11.1 / 0.9.4 |
| Panel Admin | Next.js 14 + Tailwind | 14.2.0 |
| Mensajería | Twilio WhatsApp API | — |
| Contenedores | Docker Compose | — |

---

## Estructura del proyecto

```
Conversational-AI-Agent/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── webhook.py       # Endpoint Twilio + rate limit + fallbacks
│   │   │   ├── auth.py          # OAuth2 Google
│   │   │   └── admin.py         # API REST para el panel admin
│   │   ├── agent/
│   │   │   ├── orchestrator.py  # AgentExecutor con 6 tools
│   │   │   ├── memory.py        # Redis TTL + PostgreSQL persistente
│   │   │   └── tools/
│   │   │       ├── calendar_mcp.py
│   │   │       └── drive_mcp.py
│   │   ├── rag/
│   │   │   ├── ingestion.py     # Chunking + embedding + store
│   │   │   ├── retriever.py     # Bi-encoder + cross-encoder rerank
│   │   │   ├── embeddings.py    # nomic-embed-text via Ollama
│   │   │   ├── vectorstore.py   # Abstracción Chroma ↔ Pinecone
│   │   │   └── reranker.py      # CrossEncoder ms-marco-MiniLM
│   │   ├── core/
│   │   │   ├── logger.py        # JSON structured logging
│   │   │   └── fallbacks.py     # Circuit breaker + mensajes fallback
│   │   ├── middleware/
│   │   │   └── rate_limit.py    # Fixed-window rate limiting con Redis
│   │   ├── models/
│   │   │   └── database.py      # SQLAlchemy: User, ConversationMessage
│   │   ├── config.py            # pydantic-settings: todas las env vars
│   │   └── main.py              # FastAPI app + lifespan + routers
│   ├── fine_tuning/
│   │   ├── dataset_full.jsonl   # 52 ejemplos de entrenamiento
│   │   └── train.py             # LoRA/PEFT con SFTTrainer
│   ├── tests/
│   │   └── test_integration.py  # 15+ pruebas de integración
│   ├── pytest.ini
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   ├── layout.tsx           # Root layout con Sidebar
│   │   ├── page.tsx             # Dashboard
│   │   ├── documents/
│   │   │   ├── page.tsx         # Lista de documentos (Server Component)
│   │   │   └── UploadForm.tsx   # Formulario de subida (Client Component)
│   │   ├── calendar/
│   │   │   └── page.tsx         # Vista de eventos
│   │   └── auth/
│   │       └── page.tsx         # Estado OAuth2
│   ├── components/
│   │   └── Sidebar.tsx
│   ├── lib/
│   │   └── api.ts               # Fetch wrapper tipado
│   ├── Dockerfile
│   ├── package.json
│   └── .env.local.example
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Guía de inicio rápido

Ver el archivo `.env.example` para las variables de entorno requeridas.

```bash
# 1. Instalar Ollama y descargar modelos
# 2. Copiar y completar .env
# 3. Levantar servicios
docker compose up --build

# 4. Indexar documentos de prueba
docker exec asistente-backend python -c "
from app.rag.ingestion import ingest_file
ingest_file('docs/sample.txt', {'materia': 'IA2'}, collection_name='notas')
"

# 5. Ejecutar tests
docker exec asistente-backend pytest tests/ -v
```

---

## Conceptos académicos implementados

| Concepto | Dónde está en el código | FASE |
|---|---|---|
| **Embeddings** (vectorización semántica) | `rag/embeddings.py` + `rag/ingestion.py` | 1 |
| **Similitud coseno** (recuperación de docs) | `rag/retriever.py` → `similarity_search()` | 1 |
| **Chunking** (chunk_size=512, overlap=50) | `rag/ingestion.py` → `RecursiveCharacterTextSplitter` | 1 |
| **Memoria de conversación** (Redis TTL) | `agent/memory.py` | 2 |
| **MCP / Tool calling** (agentes) | `agent/tools/calendar_mcp.py` | 3 |
| **Fine-tuning LoRA** (PEFT) | `fine_tuning/train.py` | 4 |
| **Sharding lógico** (colecciones) | `rag/vectorstore.py` → `ALL_COLLECTIONS` | 5 |
| **Re-ranking** (cross-encoder) | `rag/reranker.py` | 5 |
| **Pinecone** (BD vectorial cloud) | `rag/vectorstore.py` → `_get_pinecone_store()` | 5 |
| **Rate limiting** (Fixed Window) | `middleware/rate_limit.py` | 7 |
| **Circuit Breaker** | `core/fallbacks.py` | 7 |
| **Logging estructurado JSON** | `core/logger.py` | 7 |
