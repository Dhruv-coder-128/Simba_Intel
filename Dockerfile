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

# --timeout 60, explicit rather than left at gunicorn's own default (also
# ~30s): that implicit default was nearly tied with EMAIL_TIMEOUT (also
# 30s), and since gunicorn's silence clock starts the instant a request
# arrives while EMAIL_TIMEOUT's clock only starts once the SMTP socket call
# itself begins, gunicorn's SIGKILL was winning the race - killing the
# worker while still blocked inside socket.create_connection(), before the
# lower-level timeout ever got a chance to raise a catchable, logged
# exception. See simba_web/settings.py's EMAIL_TIMEOUT comment for the full
# root-cause writeup. 60s leaves generous headroom over the now-10s
# EMAIL_TIMEOUT for normal request overhead, and is strictly more lenient
# than the previous implicit ~30s for every other view too (nothing else in
# this app needed the tighter default).
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn simba_web.wsgi:application --bind 0.0.0.0:8000 --timeout 60"]
