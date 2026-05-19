/**
 * components/Sidebar.tsx — Barra de navegación lateral
 *
 * Next.js App Router usa el sistema de archivos para el routing.
 * El link "/" → Dashboard, "/documents" → Documentos, etc.
 *
 * Usamos el hook usePathname() para resaltar el link activo.
 * Como usa hooks del cliente, este componente tiene "use client".
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/", label: "Dashboard", icon: "📊" },
  { href: "/documents", label: "Documentos", icon: "📄" },
  { href: "/calendar", label: "Calendario", icon: "📅" },
  { href: "/auth", label: "Autenticación", icon: "🔑" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 min-h-screen bg-slate-900 text-slate-100 flex flex-col py-8 px-4 gap-2">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-lg font-bold leading-tight">Asistente Académico</h1>
        <p className="text-xs text-slate-400 mt-1">Panel de Administración</p>
      </div>

      {/* Navigation links */}
      <nav className="flex flex-col gap-1">
        {NAV_LINKS.map(({ href, label, icon }) => {
          const isActive = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                isActive
                  ? "bg-indigo-600 text-white font-medium"
                  : "text-slate-300 hover:bg-slate-800 hover:text-white"
              }`}
            >
              <span className="text-base">{icon}</span>
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="mt-auto pt-6 border-t border-slate-700">
        <p className="text-xs text-slate-500">v0.4.0 — FASE 5+6</p>
        <a
          href="http://localhost:8000/docs"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-indigo-400 hover:underline mt-1 block"
        >
          API Docs (Swagger) ↗
        </a>
      </div>
    </aside>
  );
}
