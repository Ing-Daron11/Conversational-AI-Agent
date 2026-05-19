/**
 * lib/api.ts — Capa de comunicación con el backend FastAPI
 *
 * CONCEPTO — ¿Por qué centralizar las llamadas HTTP aquí?
 *   En lugar de escribir fetch() directamente en cada componente,
 *   creamos funciones tipadas. Beneficios:
 *     1. Un solo lugar para cambiar la URL base (NEXT_PUBLIC_API_URL)
 *     2. Manejo de errores centralizado
 *     3. TypeScript garantiza que los datos que llegan son del tipo esperado
 *
 * NOTA: NEXT_PUBLIC_* variables son expuestas al navegador por Next.js.
 *   Variables sin el prefijo son solo accesibles en el servidor (SSR).
 *   Como este es un panel admin puramente client-side, usamos NEXT_PUBLIC_.
 */

// Server Components corren dentro del contenedor Docker → usan el hostname interno "backend".
// Client Components corren en el navegador del usuario → usan localhost:8000.
// typeof window === 'undefined' es true solo en Node.js (SSR), false en el browser.
const API_URL =
  typeof window === "undefined"
    ? (process.env.API_INTERNAL_URL ?? "http://backend:8000")
    : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");

// ─── Tipos que espejean los modelos Pydantic del backend ─────────────────

export interface SystemStats {
  docs_per_collection: Record<string, number>;
  total_docs: number;
  total_conversations: number;
  redis_active_sessions: number;
  version: string;
}

export interface DocumentItem {
  source_file: string;
  materia: string;
  tipo: string;
  collection: string;
  chunk_count: number;
}

export interface IngestResponse {
  success: boolean;
  chunks_indexed: number;
  file_name: string;
  collection: string;
  message: string;
}

export interface CalendarEvent {
  id: string;
  summary: string;
  start: string;
  end: string;
  description: string;
}

export interface CalendarEventsResponse {
  authenticated: boolean;
  events: CalendarEvent[];
  count?: number;
  message?: string;
  auth_url?: string;
}

// ─── Funciones de API ─────────────────────────────────────────────────────

/**
 * Obtiene las métricas generales del sistema.
 * Llama a GET /admin/stats
 */
export async function fetchStats(): Promise<SystemStats> {
  const res = await fetch(`${API_URL}/admin/stats`);
  if (!res.ok) throw new Error(`Error ${res.status}: ${res.statusText}`);
  return res.json();
}

/**
 * Lista los documentos indexados, opcionalmente filtrados por colección.
 * Llama a GET /admin/documents?collection=<collection>
 */
export async function fetchDocuments(collection?: string): Promise<DocumentItem[]> {
  const url = collection
    ? `${API_URL}/admin/documents?collection=${collection}`
    : `${API_URL}/admin/documents`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Error ${res.status}: ${res.statusText}`);
  return res.json();
}

/**
 * Sube e indexa un archivo en la BD vectorial.
 * Llama a POST /admin/ingest (multipart/form-data)
 *
 * NOTA: Usamos FormData nativo del navegador para multipart.
 * fetch() con FormData como body configura automáticamente el
 * Content-Type: multipart/form-data; boundary=...
 */
export async function ingestDocument(
  file: File,
  collection: string,
  materia: string,
  tipo: string,
): Promise<IngestResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("collection", collection);
  form.append("materia", materia);
  form.append("tipo", tipo);

  const res = await fetch(`${API_URL}/admin/ingest`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail ?? `Error ${res.status}`);
  }
  return res.json();
}

/**
 * Obtiene los próximos eventos del Google Calendar.
 * Llama a GET /admin/events?start=...&end=...&max_results=...
 */
export async function fetchCalendarEvents(
  start?: string,
  end?: string,
  maxResults = 10,
): Promise<CalendarEventsResponse> {
  const params = new URLSearchParams({ max_results: String(maxResults) });
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const res = await fetch(`${API_URL}/admin/events?${params.toString()}`);
  if (!res.ok) throw new Error(`Error ${res.status}: ${res.statusText}`);
  return res.json();
}
