FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source code (mounted over in dev via docker-compose)
COPY redthread/ redthread/

EXPOSE 8000

CMD ["uvicorn", "redthread.main:app", "--host", "0.0.0.0", "--port", "8000"]
