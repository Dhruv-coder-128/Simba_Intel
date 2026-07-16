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
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn simba_web.wsgi:application --bind 0.0.0.0:8000 --timeout 60"]
