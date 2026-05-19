/**
 * app/page.tsx — Dashboard (ruta "/")
 *
 * CONCEPTO — Server Components vs Client Components:
 *   Por defecto en App Router, los componentes son SERVER COMPONENTS.
 *   Se renderizan en el servidor → el HTML llega al navegador ya listo.
 *   Ventaja: podemos hacer fetch() directamente sin useEffect.
 *   Desventaja: no podemos usar hooks como useState/useEffect.
 *
 *   Este Dashboard usa Server Component para el fetch inicial de stats.
 *   Los datos se cargan en el servidor en cada request.
 *   (En una app real usaríamos React Query o SWR para cache y revalidación.)
 *
 * MÉTRICAS MOSTRADAS:
 *   1. Documentos indexados por colección (desde ChromaDB)
 *   2. Total de conversaciones (desde PostgreSQL)
 *   3. Sesiones activas (desde Redis)
 */

import { fetchStats, SystemStats } from "@/lib/api";

// Tarjeta de métrica reutilizable
function StatCard({
  label,
  value,
  description,
  color,
}: {
  label: string;
  value: string | number;
  description: string;
  color: string;
}) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div className={`text-3xl font-bold ${color}`}>{value}</div>
      <div className="text-sm font-medium text-slate-700 mt-1">{label}</div>
      <div className="text-xs text-slate-400 mt-1">{description}</div>
    </div>
  );
}

// Tabla de documentos por colección (shard)
function ShardTable({ docs }: { docs: Record<string, number> }) {
  const shards = Object.entries(docs);
  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <h3 className="text-sm font-semibold text-slate-700 mb-3">
        Documentos por shard (colección)
      </h3>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-400 border-b border-slate-100">
            <th className="pb-2">Colección</th>
            <th className="pb-2 text-right">Chunks</th>
          </tr>
        </thead>
        <tbody>
          {shards.length === 0 ? (
            <tr>
              <td colSpan={2} className="py-4 text-center text-slate-400">
                Sin documentos indexados
              </td>
            </tr>
          ) : (
            shards.map(([col, count]) => (
              <tr key={col} className="border-b border-slate-50 last:border-0">
                <td className="py-2 font-medium capitalize">{col}</td>
                <td className="py-2 text-right text-indigo-600 font-mono">{count}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default async function DashboardPage() {
  let stats: SystemStats | null = null;
  let error: string | null = null;

  try {
    stats = await fetchStats();
  } catch (e) {
    error = e instanceof Error ? e.message : "Error desconocido";
  }

  return (
    <div>
      <h2 className="text-2xl font-bold text-slate-800 mb-1">Dashboard</h2>
      <p className="text-sm text-slate-500 mb-6">
        Métricas en tiempo real del asistente académico
      </p>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 text-sm text-red-700">
          <strong>Error al conectar con el backend:</strong> {error}
          <br />
          <span className="text-red-500">
            Asegúrate de que el backend FastAPI esté corriendo en{" "}
            {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}
          </span>
        </div>
      )}

      {stats && (
        <>
          {/* Tarjetas de métricas principales */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <StatCard
              label="Chunks indexados"
              value={stats.total_docs}
              description="Fragmentos de documentos en la BD vectorial"
              color="text-indigo-600"
            />
            <StatCard
              label="Conversaciones"
              value={stats.total_conversations}
              description="Mensajes guardados en PostgreSQL"
              color="text-emerald-600"
            />
            <StatCard
              label="Sesiones activas"
              value={stats.redis_active_sessions}
              description="Usuarios activos en Redis (TTL 30 min)"
              color="text-amber-600"
            />
          </div>

          {/* Desglose por shard */}
          <ShardTable docs={stats.docs_per_collection} />

          {/* Info del sistema */}
          <div className="mt-4 text-xs text-slate-400">
            Backend v{stats.version} · Stack: FastAPI + ChromaDB + Redis + PostgreSQL
          </div>
        </>
      )}
    </div>
  );
}
