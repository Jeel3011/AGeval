FROM python:3.11-slim
WORKDIR /app

# Create non-root user for security
RUN groupadd -r ageval && useradd -r -g ageval -d /app -s /sbin/nologin ageval

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Switch to non-root user
USER ageval

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

# Bind to $PORT when set (Render/Fly inject it); default to 8000 for local/compose.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]