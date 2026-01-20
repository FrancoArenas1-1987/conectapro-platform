FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

# Dependencias (ruta desde context raíz)
COPY services/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copiamos el paquete "services" (incluye services/api)
COPY services /app/services

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
