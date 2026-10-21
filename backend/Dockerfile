FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# AWS RDS root CA bundle. Required for asyncpg/psycopg2 to verify the
# RDS server cert (it's signed by an AWS root not in the default trust
# store). Loaded by app/db/session.py when DB_SSL_CA_BUNDLE is set.
RUN curl -fsSL -o /etc/ssl/certs/rds-global-bundle.pem \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Build-time commit SHA → Bugsnag app_version and the /health "version" field
# (deploy-aws.yml passes --build-arg GIT_SHA=<commit>).
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA

# Create a non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
