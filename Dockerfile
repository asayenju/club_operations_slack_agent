FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
COPY student-org-agent/requirements.txt ./student-org-agent/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r student-org-agent/requirements.txt

COPY common ./common
COPY decisions ./decisions
COPY ingestion_api ./ingestion_api
COPY memoryAnswer ./memoryAnswer
COPY reconciliation ./reconciliation
COPY registrations ./registrations
COPY tools ./tools
COPY student-org-agent ./student-org-agent

EXPOSE 8000

CMD ["sh", "-c", "uvicorn ingestion_api.main:app --host 0.0.0.0 --port ${INGESTION_PORT:-8000}"]
