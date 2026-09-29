FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN DJANGO_DEBUG=false DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000

# One process, several threads: summarize jobs run in an in-process thread
# pool (transcript_generator/jobs.py), so keep a single worker process.
CMD python manage.py migrate --noinput && \
    gunicorn ai_transcriber_app.wsgi:application --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 120
