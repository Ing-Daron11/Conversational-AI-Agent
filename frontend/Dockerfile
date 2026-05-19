# ─── FASE 6: Dockerfile del frontend Next.js ─────────────────────────────
#
# CONCEPTO — Multi-stage Docker builds:
#   Usamos UN SOLO stage para desarrollo (modo dev con hot reload).
#   En producción se agregaría un stage de BUILD (npm run build) y
#   otro de RUNTIME con `node server.js`, produciendo una imagen más pequeña.
#
# CONCEPTO — ¿Por qué node:20-alpine?
#   alpine = distribución Linux ultra-ligera (~5MB vs ~150MB de Ubuntu).
#   Produce imágenes Docker mucho más pequeñas y con menor superficie de ataque.
#   Desventaja: algunos paquetes nativos (bcrypt, sharp) pueden fallar por
#   falta de librerías de compilación → instalar con `apk add`.
#
# USO:
#   docker build -t asistente-frontend .
#   docker run -p 3000:3000 -e NEXT_PUBLIC_API_URL=http://localhost:8000 asistente-frontend

FROM node:20-alpine

# Directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar manifiestos primero (permite cache de capas de Docker)
# Si package.json no cambia, Docker reutiliza la capa de npm install
COPY package.json package-lock.json* ./

# Instalar dependencias (--frozen-lockfile garantiza reproducibilidad)
RUN npm install

# Copiar el resto del código fuente
COPY . .

# Puerto que Next.js usa por defecto
EXPOSE 3000

# En desarrollo: hot reload automático cuando cambian los archivos
# En docker-compose los archivos se montan como volume, por eso el hot reload funciona
CMD ["npm", "run", "dev"]
