/**
 * app/layout.tsx — Root Layout (Next.js App Router)
 *
 * CONCEPTO — App Router vs Pages Router:
 *   Next.js 13+ introdujo el App Router (directorio `app/`).
 *   El layout.tsx define la estructura HTML que TODAS las páginas comparten.
 *   No se vuelve a montar entre navegaciones (a diferencia de _app.tsx del Pages Router).
 *
 * Estructura resultante:
 *   <html>
 *     <body>
 *       <div class="flex">
 *         <Sidebar />          ← siempre visible
 *         <main>{children}</main>  ← cambia según la ruta
 *       </div>
 *     </body>
 *   </html>
 */

import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Asistente Académico — Admin",
  description: "Panel de administración del asistente académico por WhatsApp",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es">
      <body className="bg-slate-100 text-slate-900">
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 p-8 overflow-auto">{children}</main>
        </div>
      </body>
    </html>
  );
}
