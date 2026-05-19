/**
 * app/documents/page.tsx — Gestión de documentos (ruta "/documents")
 *
 * Esta página tiene dos secciones:
 *   1. LISTA de documentos indexados (Server Component — fetch al cargar)
 *   2. FORMULARIO de subida (Client Component — necesita useState/handlers)
 *
 * CONCEPTO — Composición Server + Client:
 *   En App Router podemos mezclar Server y Client Components en la misma ruta.
 *   El Server Component se encarga del fetch inicial de datos (SSR).
 *   El Client Component maneja la interactividad (subida de archivos).
 *   El Client Component se importa como un "leaf" (hoja) del árbol.
 *
 * CONCEPTO — Ingestión desde el panel admin:
 *   El flujo es:
 *     1. Usuario selecciona archivo + colección + metadatos
 *     2. Frontend envía POST /admin/ingest (multipart/form-data)
 *     3. Backend guarda temp → chunking → embedding → Chroma/Pinecone
 *     4. Respuesta con número de chunks indexados
 *     5. La lista se refresca (router.refresh() fuerza re-render del Server Component)
 */

import { fetchDocuments, DocumentItem } from "@/lib/api";
import UploadForm from "./UploadForm";

function DocumentTable({ docs }: { docs: DocumentItem[] }) {
  const collectionColors: Record<string, string> = {
    notas: "bg-indigo-100 text-indigo-700",
    tareas: "bg-amber-100 text-amber-700",
    examenes: "bg-red-100 text-red-700",
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full text-sm bg-white">
        <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-3 text-left">Archivo</th>
            <th className="px-4 py-3 text-left">Materia</th>
            <th className="px-4 py-3 text-left">Tipo</th>
            <th className="px-4 py-3 text-left">Colección</th>
            <th className="px-4 py-3 text-right">Chunks</th>
          </tr>
        </thead>
        <tbody>
          {docs.length === 0 ? (
            <tr>
              <td colSpan={5} className="px-4 py-8 text-center text-slate-400">
                No hay documentos indexados aún. Sube un archivo para comenzar.
              </td>
            </tr>
          ) : (
            docs.map((doc, i) => (
              <tr
                key={`${doc.source_file}-${i}`}
                className="border-t border-slate-100 hover:bg-slate-50 transition-colors"
              >
                <td className="px-4 py-3 font-mono text-xs text-slate-700 truncate max-w-xs">
                  {doc.source_file}
                </td>
                <td className="px-4 py-3 text-slate-600">{doc.materia || "—"}</td>
                <td className="px-4 py-3 text-slate-600 capitalize">{doc.tipo || "—"}</td>
                <td className="px-4 py-3">
                  <span
                    className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                      collectionColors[doc.collection] ?? "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {doc.collection}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono text-indigo-600">
                  {doc.chunk_count}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default async function DocumentsPage() {
  let docs: DocumentItem[] = [];
  let error: string | null = null;

  try {
    docs = await fetchDocuments();
  } catch (e) {
    error = e instanceof Error ? e.message : "Error desconocido";
  }

  return (
    <div>
      <h2 className="text-2xl font-bold text-slate-800 mb-1">Documentos</h2>
      <p className="text-sm text-slate-500 mb-6">
        Archivos indexados en la BD vectorial (ChromaDB / Pinecone)
      </p>

      {/* Formulario de subida — Client Component */}
      <div className="mb-8">
        <UploadForm />
      </div>

      {/* Lista de documentos — Server Component */}
      {error ? (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          Error al cargar documentos: {error}
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-slate-700">
              Documentos indexados ({docs.length} archivos)
            </h3>
            <span className="text-xs text-slate-400">
              {docs.reduce((s, d) => s + d.chunk_count, 0)} chunks totales
            </span>
          </div>
          <DocumentTable docs={docs} />
        </>
      )}
    </div>
  );
}
