FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

ARG PAB_UID=999
ARG PAB_GID=999

RUN groupadd --gid "${PAB_GID}" pab \
    && useradd --uid "${PAB_UID}" --gid pab --home-dir /app \
        --no-create-home --no-log-init --shell /usr/sbin/nologin pab

COPY --chown=pab:pab backend ./backend
RUN mkdir -p /app/backend/staticfiles /app/backend/media \
    && chown -R pab:pab /app/backend/staticfiles /app/backend/media

USER pab

RUN DJANGO_DEBUG=True \
    DJANGO_SECRET_KEY=development-only-build-key \
    python backend/manage.py collectstatic --noinput

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=3)"

CMD ["gunicorn", "--chdir", "backend", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "config.wsgi:application"]
