# Deployment & Environment Rules

This rule documents production hosting, container configuration, and environment setup for Simba Intel.

## Hosting & Runtime Architecture

Simba Intel is deployed to **Render** using a containerized Docker runtime, backed by a managed PostgreSQL 16 database.

```
Incoming Request
       │
       ▼
Render TLS Termination / Proxy (simba-intel.onrender.com)
       │
       ▼ (HTTP port 8000)
Gunicorn WSGI Server:
  --workers 2 --worker-class gthread --threads 4 --timeout 60
       │
       ├─► Whitenoise (Compressed Manifest Static Files)
       ├─► Django Application (simba_web.wsgi)
       └─► PostgreSQL 16 (Render Managed Database)
```

## Production Guidelines

1. **Gunicorn Worker & Thread Settings**:
   - Gunicorn runs with `--workers 2 --worker-class gthread --threads 4 --timeout 60`.
   - The threaded worker model (`gthread`) is essential because AI streaming responses hold connections open while waiting for external provider HTTP chunks.
   - Do NOT increase `workers` arbitrarily without checking PostgreSQL `max_connections`, since `workers * threads` defines the peak concurrent DB connection limit.

2. **Connection Pooling (`CONN_MAX_AGE`)**:
   - `CONN_MAX_AGE` must remain `0` (or match the deployed pooler configuration) to close database connections at the end of each request, preventing `EMAXCONNSESSIONS` errors.
   - `DatabaseResilienceMiddleware` intercepts transient pool exhaustion and serves branded 503 retry views rather than crashing with unhandled 500s.

3. **Uptime & Health Checks**:
   - The health check endpoint is `/health/` (`simba_web.urls.health_check`).
   - It performs a lightweight `SELECT 1` probe against PostgreSQL and explicitly calls `connection.close()` in its `finally` block to prevent health checks from leaking connections.

4. **Transactional Email via HTTPS**:
   - Render's outbound network blocks standard SMTP ports (`smtp.gmail.com:587`).
   - All system emails (verification links, password recovery) route via HTTPS through the Resend API (`chat.services.resend_backend.ResendEmailBackend`).
   - Do NOT switch `EMAIL_BACKEND` to SMTP for production deployments.

5. **Static File Handling**:
   - Static assets are collected via `python manage.py collectstatic --noinput`.
   - Whitenoise serves assets with cache-busting hashes (`CompressedManifestStaticFilesStorage`).
   - If static file collection fails, check for missing referenced files in CSS or template URLs.
