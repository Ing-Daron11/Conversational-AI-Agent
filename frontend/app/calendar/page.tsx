/**
 * app/calendar/page.tsx — Vista de eventos de Google Calendar (ruta "/calendar")
 *
 * CONCEPTO — Integración OAuth2 con Google:
 *   El backend maneja el flujo OAuth2 completo:
 *     1. /auth/google → redirige a Google
 *     2. Google redirige de vuelta → /auth/google/callback
 *     3. El token se guarda en google_token.json
 *
 *   Este frontend no maneja tokens directamente: solo llama a /admin/events
 *   y el backend verifica si tiene token válido.
 *
 * NOTA: Este es un Server Component que obtiene los eventos en SSR.
 *   Para refrescar sin recargar la página se podría agregar un botón
 *   "Actualizar" con Client Component (router.refresh()), pero se omite
 *   por simplicidad.
 */

import { fetchCalendarEvents, CalendarEventsResponse } from "@/lib/api";

function formatEventDate(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    return date.toLocaleString("es-ES", {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

function EventCard({
  summary,
  start,
  end,
  description,
}: {
  summary: string;
  start: string;
  end: string;
  description: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 hover:border-indigo-300 transition-colors">
      <h4 className="font-semibold text-slate-800">{summary}</h4>
      <div className="mt-2 text-sm text-slate-500 space-y-0.5">
        <p>
          <span className="font-medium text-slate-600">Inicio:</span>{" "}
          {formatEventDate(start)}
        </p>
        <p>
          <span className="font-medium text-slate-600">Fin:</span>{" "}
          {formatEventDate(end)}
        </p>
      </div>
      {description && (
        <p className="mt-2 text-sm text-slate-500 line-clamp-2">{description}</p>
      )}
    </div>
  );
}

export default async function CalendarPage() {
  let data: CalendarEventsResponse | null = null;
  let fetchError: string | null = null;

  try {
    data = await fetchCalendarEvents(undefined, undefined, 15);
  } catch (e) {
    fetchError = e instanceof Error ? e.message : "Error desconocido";
  }

  return (
    <div>
      <h2 className="text-2xl font-bold text-slate-800 mb-1">Calendario</h2>
      <p className="text-sm text-slate-500 mb-6">
        Próximos eventos de Google Calendar
      </p>

      {fetchError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          Error: {fetchError}
        </div>
      )}

      {data && !data.authenticated && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 text-center">
          <p className="text-amber-800 font-medium mb-3">
            No autenticado con Google Calendar
          </p>
          <p className="text-sm text-amber-600 mb-4">
            {data.message}
          </p>
          <a
            href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/auth/google`}
            className="inline-block bg-amber-500 hover:bg-amber-600 text-white text-sm font-medium px-5 py-2 rounded-md transition-colors"
            target="_blank"
            rel="noopener noreferrer"
          >
            Conectar Google Calendar ↗
          </a>
        </div>
      )}

      {data?.authenticated && (
        <>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-slate-500">
              {data.count ?? data.events.length} evento/s en los próximos 30 días
            </p>
            <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-1 rounded-full font-medium">
              ✓ Conectado
            </span>
          </div>

          {data.events.length === 0 ? (
            <div className="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-400">
              No hay eventos próximos en los próximos 30 días.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {data.events.map((event) => (
                <EventCard
                  key={event.id}
                  summary={event.summary}
                  start={event.start}
                  end={event.end}
                  description={event.description}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
