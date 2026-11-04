FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app app
COPY frontend frontend
COPY schemas schemas
COPY config config
COPY content content
COPY tools tools
COPY scripts scripts
COPY data/samples data/samples
RUN python -m tools.sample_data_generator --out /srv/data/generated && useradd -m -u 10001 app && mkdir -p /data && chown app /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health')"
# Web tier. Scheduled jobs reuse this image: python -m app.jobs.run import|maintenance
CMD ["gunicorn", "app.main:app", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "120"]
