FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

# Dependencias
COPY services/worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copiamos el paquete "services" (incluye services/api)
COPY services /app/services

# Worker
COPY services/worker/worker.py /app/worker.py

CMD ["python", "/app/worker.py"]
