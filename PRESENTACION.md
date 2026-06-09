# Asistente Académico Conversacional por WhatsApp
### Proyecto Final — Inteligencia Artificial 2

---

## 1. Problema que resolvemos

Un estudiante universitario maneja simultáneamente múltiples materias, fechas de entrega, exámenes y apuntes dispersos. Las soluciones actuales (Google Calendar, Drive, notas de clase) son herramientas aisladas que el estudiante debe consultar por separado.

**La pregunta central del proyecto:**
> ¿Es posible construir un asistente de IA que unifique toda la información académica de un estudiante y sea accesible desde el canal de mensajería que ya usa diariamente — WhatsApp?

**Lo que el asistente puede hacer:**
- Responder preguntas sobre el contenido de los apuntes del estudiante ("¿cómo funciona la backpropagation según mis notas?")
- Crear, listar y eliminar eventos en Google Calendar por lenguaje natural ("agéndame el parcial de IA el viernes a las 10am")
- Buscar archivos en Google Drive
- Mantener una conversación con memoria (recuerda lo que se dijo antes en la misma sesión)
- Funcionar completamente con modelos de IA **locales y gratuitos** (sin OpenAI)

---

## 2. Cómo correr el proyecto

### Requisitos previos

| Herramienta | Para qué | Descarga |
|---|---|---|
| Docker Desktop | Contenedores (backend, frontend, DB, Redis) | [docker.com](https://www.docker.com/products/docker-desktop) |
| Ollama | Correr modelos de IA localmente | [ollama.com](https://ollama.com/download) |
| Cuenta Twilio | Recibir mensajes de WhatsApp | [twilio.com](https://www.twilio.com) |
| Cuenta ngrok | Exponer el servidor local a internet | [ngrok.com](https://dashboard.ngrok.com/signup) |

---

### Paso 1 — Descargar los modelos de IA

```bash
# Modelo de lenguaje (genera las respuestas) ~2.7 GB
ollama pull qwen3.5:2b

# Modelo de embeddings (convierte texto en vectores) ~274 MB
ollama pull nomic-embed-text
```

> **¿Por qué dos modelos?** El modelo de lenguaje genera texto. El modelo de embeddings transforma texto en vectores numéricos para la búsqueda semántica. Son tareas distintas y se optimizan con modelos distintos.

---

### Paso 2 — Configurar variables de entorno

Crear el archivo `.env` en la raíz del proyecto con los siguientes valores:

```env
# ── Twilio (obtener en console.twilio.com) ────────────────────────
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+14155238886

# ── Google OAuth (obtener en console.cloud.google.com) ────────────
GOOGLE_CLIENT_ID=xxxxxxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxx
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# ── Ollama (host.docker.internal porque Ollama corre fuera de Docker)
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen3.5:2b
OLLAMA_EMBED_MODEL=nomic-embed-text

# ── Bases de datos (valores internos de Docker, no cambiar)
DATABASE_URL=postgresql://asistente:asistente123@db:5432/asistente_db
REDIS_URL=redis://redis:6379/0

# ── Seguridad
SECRET_KEY=una_cadena_aleatoria_de_al_menos_32_caracteres
DEBUG=false
LOG_LEVEL=INFO

# ── RAG
USE_PINECONE=false
RERANKER_ENABLED=true
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
```

> **Donde obtener las credenciales de Google:**
> Google Cloud Console → APIs & Services → Credenciales → Crear → OAuth 2.0 → Aplicación web → URI de redirección: `http://localhost:8000/auth/google/callback`
>
> Luego en **OAuth consent screen → Test users** agregar tu correo Gmail para evitar el error 403.

---

### Paso 3 — Levantar todos los servicios

```bash
docker compose up --build
```

Cuando aparezca esto, todo está listo:
```
asistente-backend  | INFO: Application startup complete.
asistente-frontend | ✓ Ready in 4.1s
```

**Servicios disponibles:**
- Panel Admin: http://localhost:3000
- API Backend: http://localhost:8000
- Documentación API (Swagger): http://localhost:8000/docs
- Health Check: http://localhost:8000/health

---

### Paso 4 — Autorizar Google Calendar

Abrir en el navegador:
```
http://localhost:8000/auth/google
```
Completar el flujo OAuth2. Esto permite al asistente leer/escribir el calendario.

---

### Paso 5 — Conectar Twilio para WhatsApp

1. Abrir una nueva terminal y ejecutar:
```bash
ngrok http 8000
# Obtendrás algo como: https://abc123.ngrok-free.app
```

2. En [console.twilio.com](https://console.twilio.com) → **Messaging → Try it out → Send a WhatsApp message → Sandbox Settings**:
   - Campo "When a message comes in": `https://abc123.ngrok-free.app/webhook/whatsapp`
   - Método: HTTP POST

3. Desde tu WhatsApp, enviar el mensaje de activación del sandbox que indica Twilio (ej: `join palabra-palabra`) al número `+1 415 523 8886`.

---

### Paso 6 — Indexar documentos (opcional pero recomendado)

Subir un PDF o TXT de apuntes desde el panel admin en http://localhost:3000/documents, o via terminal:

```bash
curl -X POST http://localhost:8000/admin/ingest \
  -F "file=@mi_apunte.txt" \
  -F "collection=notas" \
  -F "materia=IA2" \
  -F "tipo=apunte"
```

---

### Paso 7 — Probar

Enviar un mensaje por WhatsApp al sandbox de Twilio. Ejemplos:
- `hola, ¿qué puedes hacer?`
- `¿qué dice en mis apuntes sobre redes neuronales?`
- `crea un evento: Examen IA2 el 20 de junio a las 9am`

También se puede probar directamente sin WhatsApp en http://localhost:8000/docs → `POST /webhook/whatsapp`.

---

## 3. Arquitectura del sistema

El sistema está organizado en **5 capas** que corresponden a las 7 fases de desarrollo del proyecto.

```
 Usuario (WhatsApp)
       │
       ▼
┌─────────────────────────────────────────┐
│  CAPA 1 — CANAL (Twilio + FastAPI)      │
│  Rate Limiting · Validación · TwiML     │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  CAPA 2 — MEMORIA (Redis + PostgreSQL)  │
│  Historial de sesión · Persistencia     │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  CAPA 3 — AGENTE (LangChain)            │
│  LLM · Tool Calling · Orquestación      │
└──────┬───────────────────────┬──────────┘
       │                       │
┌──────▼──────┐   ┌────────────▼──────────┐
│  CAPA 4a    │   │  CAPA 4b — RAG        │
│  Google APIs│   │  Embeddings · Chroma  │
│  Calendar   │   │  Reranker · Sharding  │
│  Drive      │   └───────────────────────┘
└─────────────┘
```

---

### Capa 1 — Canal de comunicación (FASE 0 + FASE 7)

**Archivos:** `backend/app/api/webhook.py`, `backend/app/middleware/rate_limit.py`, `backend/app/core/fallbacks.py`

**¿Qué hace?**
Recibe los mensajes de WhatsApp que Twilio envía via HTTP POST, valida que sean correctos y devuelve la respuesta en formato TwiML (Twilio Markup Language — XML que Twilio interpreta para enviar el mensaje de vuelta al usuario).

**Conceptos implementados:**

**Rate Limiting (Fixed Window):**
Cada número de WhatsApp tiene un contador en Redis. Por cada mensaje se incrementa con `INCR` y se pone un TTL de 60 segundos. Si el contador supera 20, se bloquea la petición.
```
Redis key: rl:whatsapp:+573001234567
Valor:      17  (requests en la ventana actual)
TTL:        43s (segundos hasta que se reinicia el contador)
```

**Circuit Breaker:**
Patrón de resiliencia inspirado en los fusibles eléctricos. Si Ollama falla 3 veces seguidas, el circuito se "abre" y durante 30 segundos todas las peticiones reciben un mensaje de error sin intentar llamar al LLM. Después pasa a estado HALF_OPEN para probar si el servicio se recuperó.

```
CLOSED → falla × 3 → OPEN → (espera 30s) → HALF_OPEN → éxito → CLOSED
```

**Fallback messages:**
Si algún servicio falla, el usuario recibe un mensaje amigable en lugar de un error técnico. Principio: nunca dejar al usuario sin respuesta.

**Logging estructurado JSON:**
Cada request genera un log con campos fijos: timestamp, teléfono, request_id, latencia en ms, tools llamadas, preview de la respuesta. Esto permite análisis posterior con herramientas como Grafana o simplemente `grep`.

---

### Capa 2 — Memoria de conversación (FASE 2)

**Archivos:** `backend/app/agent/memory.py`, `backend/app/models/database.py`

**¿Qué hace?**
Permite que el asistente recuerde lo que se dijo antes en la misma conversación. Sin esto, cada mensaje sería tratado de forma independiente y el asistente no podría responder preguntas como "¿y qué más dijiste sobre eso?".

**Arquitectura de dos niveles:**

| | Redis | PostgreSQL |
|---|---|---|
| **Para qué** | Sesión activa | Historial permanente |
| **Velocidad** | ~1ms | ~5ms |
| **Duración** | TTL 30 minutos | Permanente |
| **Cuándo se usa** | Cada mensaje | Al finalizar la sesión |

**¿Por qué Redis para la sesión?**
Redis es una base de datos en memoria (key-value). Acceder al historial de los últimos 10 mensajes tarda ~1ms. Una BD relacional tomaría ~5-10ms. En un sistema de chat donde cada ms importa, esta diferencia es significativa.

**Formato en Redis:**
```
key:   session:whatsapp:+573001234567
valor: [{"role": "user", "content": "hola"},
        {"role": "assistant", "content": "¡Hola! ¿En qué te ayudo?"}]
TTL:   1800 segundos (30 minutos de inactividad)
```

---

### Capa 3 — Agente IA con Tool Calling (FASE 3)

**Archivos:** `backend/app/agent/orchestrator.py`, `backend/app/agent/tools/`

**¿Qué hace?**
Aquí vive el "cerebro" del sistema. En lugar de un flujo fijo (RAG siempre → LLM), se usa un **Agente** que decide dinámicamente qué herramientas necesita para responder cada mensaje.

**Diferencia Chain vs Agente:**

```
CHAIN (flujo fijo):
  mensaje → RAG → LLM → respuesta
  (el RAG se ejecuta SIEMPRE, aunque el usuario solo salude)

AGENTE (flujo dinámico):
  mensaje → LLM decide → ¿necesito buscar notas? → RAG (solo si es necesario)
                      → ¿necesito el calendario?  → Google Calendar API
                      → ¿puedo responder directo?  → respuesta inmediata
```

**Las 6 herramientas disponibles:**

| Tool | Qué hace | Cuándo la usa el agente |
|---|---|---|
| `search_notes` | Búsqueda semántica en apuntes (RAG) | "¿qué es la backpropagation según mis notas?" |
| `create_calendar_event` | Crea evento en Google Calendar | "agéndame el examen el viernes" |
| `list_calendar_events` | Lista próximos eventos | "¿qué tengo esta semana?" |
| `delete_calendar_event` | Elimina un evento | "cancela el evento del lunes" |
| `search_drive_files` | Busca archivos en Google Drive | "busca el PDF de termodinámica" |
| `index_drive_file` | Indexa un archivo de Drive en la BD vectorial | "guarda ese documento en mis notas" |

**¿Cómo sabe el agente qué tool usar?**
LangChain convierte cada función Python decorada con `@tool` en una descripción JSON (nombre + descripción + parámetros). El LLM recibe estas descripciones y emite un JSON indicando qué tool llamar. Este mecanismo se llama **Tool Calling** o **Function Calling** y es nativo en modelos como Qwen3.

**Loop interno del agente:**
```
1. LLM lee: mensaje + historial + lista de tools
2. LLM decide: emite JSON {"tool": "search_notes", "query": "backpropagation"}
3. AgentExecutor ejecuta la tool → obtiene resultado
4. Resultado se agrega al contexto
5. LLM decide: ¿necesito más tools? → loop
               ¿tengo suficiente? → genera respuesta final en texto
```

---

### Capa 4a — Integración con Google APIs (FASE 3)

**Archivos:** `backend/app/agent/tools/calendar_mcp.py`, `backend/app/agent/tools/drive_mcp.py`, `backend/app/api/auth.py`

**¿Qué hace?**
Permite al asistente actuar sobre el mundo real: crear citas en el calendario del estudiante y buscar archivos en su Drive.

**Flujo OAuth2 simplificado:**
```
1. Usuario visita http://localhost:8000/auth/google
2. Backend redirige a Google con los scopes solicitados
3. Usuario acepta en la pantalla de Google
4. Google redirige al backend con un "code"
5. Backend intercambia el code por access_token + refresh_token
6. Tokens se guardan en archivo local (google_token.json)
7. Cada llamada a Calendar/Drive usa el access_token
   (si expira, se renueva automáticamente con el refresh_token)
```

---

### Capa 4b — Pipeline RAG con Re-ranking (FASE 1 + FASE 5)

**Archivos:** `backend/app/rag/`

**¿Qué hace?**
Permite al asistente responder preguntas basándose en los documentos del estudiante (apuntes, guías, enunciados), no solo en el conocimiento general del modelo.

RAG = **R**etrieval **A**ugmented **G**eneration: recuperar contexto relevante y dárselo al LLM para que genere una respuesta fundamentada.

**Pipeline completo en 4 pasos:**

**Paso 1 — Ingestión (al subir un documento):**
```
archivo.pdf
    → cargarlo con PyPDF2
    → dividirlo en chunks de 512 tokens con overlap de 50
       (overlap evita que información importante quede cortada entre chunks)
    → cada chunk → nomic-embed-text → vector de 768 dimensiones
    → guardar (vector + texto + metadatos) en ChromaDB
```

**Paso 2 — Retrieval (bi-encoder, rápido):**
```
query del usuario → nomic-embed-text → vector de consulta
    → similitud coseno contra todos los vectores en ChromaDB
    → retornar top-15 chunks más similares
```

> La **similitud coseno** mide el ángulo entre dos vectores. Un ángulo de 0° (coseno = 1) significa que los vectores apuntan en la misma dirección semántica. No importa la magnitud (longitud), solo la dirección. Por eso es preferida para texto: un apunte corto y uno largo sobre el mismo tema tendrán vectores paralelos.

**Paso 3 — Re-ranking (cross-encoder, preciso):**
```
para cada uno de los 15 candidatos:
    (query, chunk_i) → CrossEncoder.predict() → score de relevancia
retornar top-3 con mayor score
```

> **¿Por qué dos etapas?** El bi-encoder es rápido (compara un vector contra todos) pero impreciso (no analiza la relación entre query y documento). El cross-encoder es lento (analiza cada par query-documento juntos) pero muy preciso. Solución: usar el rápido para filtrar de N→15, y el preciso para filtrar de 15→3.

**Paso 4 — Generación:**
```
[top-3 chunks relevantes] + [mensaje del usuario] → LLM → respuesta
```

**Sharding lógico (colecciones):**
Los documentos se organizan en 3 colecciones según su tipo:
- `notas` — apuntes de clase
- `tareas` — enunciados de trabajos
- `examenes` — guías de estudio

Esto permite búsquedas focalizadas ("busca solo en examenes") o globales ("busca en todo").

---

### Capa 5 — Panel de Administración (FASE 6)

**Archivos:** `frontend/`

**¿Qué hace?**
Interfaz web (Next.js 14) para gestionar el sistema sin necesidad de usar la terminal.

**Páginas:**

| Ruta | Qué muestra |
|---|---|
| `/` | Dashboard: total de documentos indexados por colección, conversaciones totales, sesiones activas en Redis |
| `/documents` | Lista de documentos indexados + formulario para subir nuevos archivos |
| `/calendar` | Próximos eventos del Google Calendar conectado |
| `/auth` | Estado de la conexión OAuth2 con Google + botón para reconectar |

**Arquitectura Next.js — Server vs Client Components:**

Next.js 14 distingue dos tipos de componentes:

- **Server Components** (por defecto): se renderizan en el servidor Node.js. Hacen `fetch` directamente al backend usando el hostname interno de Docker (`http://backend:8000`). El HTML llega listo al navegador.
- **Client Components** (`"use client"`): se ejecutan en el navegador del usuario. Hacen `fetch` a `http://localhost:8000`. Se usan para formularios e interactividad.

> Esta distinción es importante en Docker: `localhost` dentro del contenedor de Next.js no es el backend, sino el propio contenedor. Por eso se usa `API_INTERNAL_URL=http://backend:8000` para SSR y `NEXT_PUBLIC_API_URL=http://localhost:8000` para el navegador.

---

## 4. Decisiones de diseño relevantes

### ¿Por qué Ollama y no OpenAI?

El proyecto usa modelos 100% locales por tres razones:
1. **Costo cero**: sin API key de pago
2. **Privacidad**: los apuntes del estudiante no salen del dispositivo
3. **Académicamente honesto**: demuestra que la IA funcional no requiere APIs propietarias

### ¿Por qué ChromaDB y no solo un array en memoria?

ChromaDB persiste los vectores en disco. Si el servidor se reinicia, los documentos indexados no se pierden. Además, el índice HNSW de Chroma permite búsqueda aproximada eficiente en O(log n) en lugar de O(n) fuerza bruta.

### ¿Por qué Redis para la sesión si ya tenemos PostgreSQL?

Son para cosas distintas. Redis es una BD en memoria optimizada para lecturas/escrituras de alta frecuencia con TTL automático. PostgreSQL es para datos estructurados que deben persistir indefinidamente. La sesión de chat es temporal y necesita ser rápida → Redis. El historial completo es permanente y estructurado → PostgreSQL.

### ¿Por qué el agente y no siempre RAG?

Hacer RAG en cada mensaje es ineficiente y puede introducir ruido. Si el usuario pregunta "¿cuánto es 2+2?", hacer búsqueda semántica en los apuntes solo agrega latencia sin aportar información útil. El agente solo llama `search_notes` cuando el LLM determina que la pregunta requiere contexto del estudiante.

---

## 5. Resumen técnico

| Concepto académico | Implementación | Fase |
|---|---|---|
| Embeddings (vectorización semántica) | `nomic-embed-text` via Ollama | 1 |
| Similitud coseno (recuperación) | ChromaDB `similarity_search()` | 1 |
| Chunking con overlap | `RecursiveCharacterTextSplitter(512, 50)` | 1 |
| Memoria de conversación (Redis TTL) | `agent/memory.py` | 2 |
| Tool Calling / MCP | `create_tool_calling_agent` LangChain | 3 |
| OAuth2 Authorization Code Flow | `api/auth.py` + Google APIs | 3 |
| Fine-tuning LoRA/PEFT | `fine_tuning/train.py` | 4 |
| Sharding de colecciones vectoriales | `rag/vectorstore.py` | 5 |
| Re-ranking bi-encoder → cross-encoder | `rag/reranker.py` | 5 |
| Pinecone (BD vectorial cloud) | `rag/vectorstore.py` (opcional) | 5 |
| Server/Client Components (Next.js) | `frontend/app/` | 6 |
| Rate Limiting Fixed Window | `middleware/rate_limit.py` | 7 |
| Circuit Breaker (3 estados) | `core/fallbacks.py` | 7 |
| Logging estructurado JSON | `core/logger.py` | 7 |
