/**
 * app/auth/page.tsx — Estado de autenticación (ruta "/auth")
 *
 * Muestra el estado de la conexión con Google (Calendar + Drive)
 * y provee el botón para iniciar el flujo OAuth2.
 *
 * El endpoint /auth/status retorna:
 *   {
 *     authenticated: boolean,
 *     scopes: string[],
 *     email?: string,
 *     expires_at?: string
 *   }
 */

async function fetchAuthStatus() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${API_URL}/auth/status`, { cache: "no-store" });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function AuthPage() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const status = await fetchAuthStatus();

  return (
    <div>
      <h2 className="text-2xl font-bold text-slate-800 mb-1">Autenticación</h2>
      <p className="text-sm text-slate-500 mb-6">
        Estado de la conexión con Google (Calendar + Drive)
      </p>

      <div className="bg-white rounded-xl border border-slate-200 p-6 max-w-lg">
        {status === null ? (
          <div className="text-slate-500 text-sm">
            No se pudo conectar con el backend para verificar el estado.
          </div>
        ) : status.authenticated ? (
          <div>
            <div className="flex items-center gap-2 mb-4">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block"></span>
              <span className="font-semibold text-emerald-700">Conectado con Google</span>
            </div>
            {status.email && (
              <p className="text-sm text-slate-600 mb-2">
                <span className="font-medium">Cuenta:</span> {status.email}
              </p>
            )}
            {status.expires_at && (
              <p className="text-sm text-slate-500 mb-4">
                <span className="font-medium">Token expira:</span>{" "}
                {new Date(status.expires_at).toLocaleString("es-ES")}
              </p>
            )}
            <a
              href={`${API_URL}/auth/google`}
              className="text-sm text-indigo-600 hover:underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              Reconectar / actualizar permisos ↗
            </a>
          </div>
        ) : (
          <div>
            <div className="flex items-center gap-2 mb-4">
              <span className="w-2.5 h-2.5 rounded-full bg-slate-300 inline-block"></span>
              <span className="font-semibold text-slate-600">No autenticado</span>
            </div>
            <p className="text-sm text-slate-500 mb-4">
              Para usar las herramientas de Calendar y Drive, debes conectar tu
              cuenta de Google. El sistema guarda el token localmente (no en la nube).
            </p>
            <a
              href={`${API_URL}/auth/google`}
              className="inline-block bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium px-5 py-2 rounded-md transition-colors"
              target="_blank"
              rel="noopener noreferrer"
            >
              Conectar con Google ↗
            </a>
          </div>
        )}
      </div>

      {/* Info técnica */}
      <div className="mt-8 max-w-lg bg-slate-50 rounded-xl border border-slate-200 p-5">
        <h3 className="font-semibold text-slate-700 mb-3 text-sm">Detalles técnicos</h3>
        <div className="space-y-2 text-xs text-slate-500">
          <div>
            <span className="font-medium text-slate-600">Flujo OAuth2:</span>{" "}
            Authorization Code Flow (Google Identity Platform)
          </div>
          <div>
            <span className="font-medium text-slate-600">Scopes:</span>{" "}
            calendar.readonly, calendar.events, drive.readonly
          </div>
          <div>
            <span className="font-medium text-slate-600">Token guardado en:</span>{" "}
            <code className="bg-slate-200 px-1 rounded">google_token.json</code> (backend)
          </div>
          <div>
            <span className="font-medium text-slate-600">Callback URL:</span>{" "}
            <code className="bg-slate-200 px-1 rounded">/auth/google/callback</code>
          </div>
        </div>
      </div>
    </div>
  );
}
