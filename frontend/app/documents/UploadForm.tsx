/**
 * app/documents/UploadForm.tsx — Formulario de subida de documentos
 *
 * Client Component: necesita useState para manejar el estado del formulario
 * y useRouter para refrescar la lista tras una ingestión exitosa.
 *
 * CONCEPTO — Subida multipart/form-data:
 *   El input type="file" devuelve un objeto File del navegador.
 *   FormData es la API nativa del navegador para construir multipart/form-data.
 *   fetch() detecta automáticamente FormData y configura el header correcto.
 *   No necesitamos configurar Content-Type manualmente (el browser agrega el boundary).
 */

"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { ingestDocument, IngestResponse } from "@/lib/api";

const COLLECTIONS = ["notas", "tareas", "examenes"] as const;
const TIPOS = ["apunte", "tarea", "examen", "guia", "otro"] as const;

export default function UploadForm() {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);

  const [collection, setCollection] = useState<string>("notas");
  const [materia, setMateria] = useState("");
  const [tipo, setTipo] = useState<string>("apunte");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<IngestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Selecciona un archivo primero.");
      return;
    }

    setLoading(true);
    setResult(null);
    setError(null);

    try {
      const response = await ingestDocument(file, collection, materia, tipo);
      setResult(response);
      // Refrescar la lista de documentos (re-ejecuta el Server Component)
      router.refresh();
      // Limpiar el input de archivo
      if (fileRef.current) fileRef.current.value = "";
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-white rounded-xl border border-slate-200 p-6"
    >
      <h3 className="font-semibold text-slate-700 mb-4">Indexar nuevo documento</h3>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
        {/* Archivo */}
        <div className="sm:col-span-2">
          <label className="block text-xs font-medium text-slate-600 mb-1">
            Archivo (.txt o .pdf)
          </label>
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.pdf"
            className="block w-full text-sm text-slate-600 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:bg-indigo-50 file:text-indigo-700 file:text-sm file:font-medium hover:file:bg-indigo-100 cursor-pointer"
            required
          />
        </div>

        {/* Colección (shard) */}
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">
            Colección (shard)
          </label>
          <select
            value={collection}
            onChange={(e) => setCollection(e.target.value)}
            className="w-full rounded-md border border-slate-300 text-sm px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            {COLLECTIONS.map((c) => (
              <option key={c} value={c} className="capitalize">
                {c}
              </option>
            ))}
          </select>
        </div>

        {/* Tipo */}
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">
            Tipo de documento
          </label>
          <select
            value={tipo}
            onChange={(e) => setTipo(e.target.value)}
            className="w-full rounded-md border border-slate-300 text-sm px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            {TIPOS.map((t) => (
              <option key={t} value={t} className="capitalize">
                {t}
              </option>
            ))}
          </select>
        </div>

        {/* Materia */}
        <div className="sm:col-span-2">
          <label className="block text-xs font-medium text-slate-600 mb-1">
            Materia (opcional)
          </label>
          <input
            type="text"
            value={materia}
            onChange={(e) => setMateria(e.target.value)}
            placeholder="ej: Inteligencia Artificial 2"
            className="w-full rounded-md border border-slate-300 text-sm px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
        </div>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white text-sm font-medium px-5 py-2 rounded-md transition-colors"
      >
        {loading ? "Indexando..." : "Subir e Indexar"}
      </button>

      {/* Feedback */}
      {result && (
        <div className="mt-4 bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-sm text-emerald-700">
          ✓ {result.message} ({result.chunks_indexed} chunks en &apos;{result.collection}&apos;)
        </div>
      )}
      {error && (
        <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          ✗ {error}
        </div>
      )}
    </form>
  );
}
