FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps needed by pdfplumber/pytesseract/Pillow at runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

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
