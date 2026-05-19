# ============================================================
# Dockerfile — Backend FastAPI
# Imagen base: python:3.11-slim (ligera, sin paquetes extra)
# ============================================================

FROM python:3.11-slim

# Directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiamos primero solo requirements.txt para aprovechar la caché
# de capas Docker: si el código cambia pero no las dependencias,
# no se reinstala todo en cada rebuild.
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto del código fuente
COPY . .

EXPOSE 8000

# En producción se quitaría --reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
