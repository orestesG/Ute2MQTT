# Imagen base: inyectada por HA Supervisor en modo Add-on; python:3.11-slim en Docker Compose
ARG BUILD_FROM=python:3.11-slim
FROM $BUILD_FROM

WORKDIR /app

# En imágenes Alpine de HA (base-python) puede faltar pip o libffi para cryptography
RUN if command -v apk > /dev/null 2>&1; then \
      apk add --no-cache gcc musl-dev libffi-dev openssl-dev python3-dev; \
    fi

# Install dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application
COPY *.py .
COPY ute ./ute

# Entrypoint unificado (HA Add-on y Docker Compose)
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
