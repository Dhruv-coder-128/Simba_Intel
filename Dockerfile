FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# libpq5: the actual runtime dependency of `psycopg` (requirements.txt has
# the plain package, not psycopg[binary]) - psycopg 3's pure-Python "python"
# implementation dlopen()s the system's libpq.so.5 via ctypes at import
# time, so without this package `import psycopg` (and therefore every DB
# query - Supabase Postgres, see config/settings/base.py) fails outright.
# python:3.12-slim does not include it by default.
#
# tesseract-ocr, previously installed here, has been removed: nothing in
# the app uses it any more (see chat/providers/nvidia_vision_provider.py -
# "No Tesseract, no OCR library, everything must use NVIDIA Vision" -
# pytesseract isn't even in requirements.txt), so it was pure image bloat.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root: gunicorn only ever binds an unprivileged port (8000), so running
# as root buys the container nothing and is the first thing any image
# scanner (Trivy, Docker Scout, ...) flags.
#
# --home /home/app is not optional here. Debian's adduser treats --system
# accounts as service/daemon accounts, not interactive logins - its default
# policy (adduser.conf) is to give them HOME=/nonexistent and never create
# that path on disk at all, on the assumption a daemon manages its own
# state directories explicitly and never needs $HOME for anything. That
# assumption doesn't hold for a Python process: various libraries in this
# app's dependency chain look up $HOME for cache/config directories the
# moment they're needed, and /nonexistent isn't a real, writable directory
# - creating anything under it means writing to /, which only root can do,
# so any such lookup fails with PermissionError. Explicitly giving `app` a
# real home directory (created and chown'd below, and set via ENV HOME so
# every process sees the same value regardless of how it looks HOME up)
# fixes this at the root rather than chasing whichever specific library
# hits it first. --shell /usr/sbin/nologin keeps it a non-interactive
# service account otherwise, same as Debian's own default intent.
#
# STATIC_ROOT (/app/staticfiles) and the transient upload scratch dir
# (/app/uploads) are created HERE, at build time, before the chown below -
# not left for collectstatic/os.makedirs to create at container startup.
# This matters specifically because of how Docker volumes interact with a
# non-root USER: if a directory does not already exist in the image when a
# volume is later mounted at that same path, Docker creates the mount point
# fresh and owns it root:root, regardless of anything chown'd at build time
# (the chown only ever applies to files that exist in the image layer - a
# volume is a separate piece of storage substituted in at container-start
# time, so it was never touched by this RUN step). The app user then gets
# PermissionError on the first write. Pre-creating the directory here means
# that if a volume is ever mounted at /app/staticfiles (e.g. once Nginx is
# introduced and needs to read collectstatic's output directly), Docker's
# own documented behavior - copying a fresh/empty named volume's initial
# content from whatever already exists at that path in the image, ownership
# included - populates it as app:app instead of root:root.
RUN addgroup --system app \
    && adduser --system --ingroup app --home /home/app --shell /usr/sbin/nologin app \
    && mkdir -p /home/app /app/staticfiles /app/uploads \
    && chown -R app:app /home/app /app
ENV HOME=/home/app
USER app

EXPOSE 8000

# Unauthenticated, dependency-light endpoint that checks the app process
# AND the database connection (see simba_web/urls.py's health_check) - the
# same check Render's own healthCheckPath already relies on (render.yaml),
# reused here so `docker compose ps` / `docker inspect` can see container
# health too, not just Render's proxy. Uses Python's own urllib instead of
# curl/wget so no extra package is needed just for this.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request as u,sys; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/health/', timeout=4).status == 200 else 1)"

# --timeout 60, explicit rather than left at gunicorn's own implicit
# default (~30s): originally raised to fix a race between this timeout and
# a since-removed SMTP socket timeout (SMTP is gone entirely - see
# chat/services/resend_backend.py). Kept at 60s regardless: it's still a
# generally more generous, safer worker-silence ceiling for every view in
# this app than the old implicit default, and Resend's HTTP calls (capped
# at 10s/attempt, up to 3 attempts) complete far under it either way.
#
# --workers/--worker-class/--threads: previously unset, which silently
# meant gunicorn's own default of exactly ONE synchronous worker - one
# in-flight request at a time, full stop. Every AI chat/vision/image call in
# this app is a multi-second StreamingHttpResponse; under that default, one
# user's in-progress reply blocked every other request on the whole site
# (including a simple page load) for its entire duration. `gthread` +
# threads=4 gives real concurrency for this app's actual bottleneck (waiting
# on slow external provider HTTP calls, not CPU) far more cheaply in RAM
# than spinning up more full worker processes would. workers=2 is
# deliberately modest (matches CONN_MAX_AGE=600's persistent-connection
# reasoning above - worker_count * thread_count is the ceiling on
# concurrently-held DB connections, so this stays comfortably inside a
# typical managed Postgres's max_connections instead of trading one
# bottleneck for another); raise both once the deployed Postgres plan's
# connection limit and dyno RAM are confirmed to have headroom.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn simba_web.wsgi:application --bind 0.0.0.0:8000 --timeout 60 --workers 2 --worker-class gthread --threads 4"]
