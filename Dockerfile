FROM python:3.13-slim

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONOPTIMIZE=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Install dependencies first: this layer is rebuilt only when requirements.txt
# changes, not on every source edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project. What is *not* copied is governed by .dockerignore -- notably .env,
# which would otherwise stay readable in this layer forever.
COPY . .

# Collect static files. There is no `migrate` step: the project has no models and
# no database, so it had nothing to do beyond baking a throwaway SQLite file into
# the image.
RUN python manage.py collectstatic --noinput --clear

# Drop privileges. Nothing here needs to write to /app -- static files are already
# collected, and the response cache lives in /tmp -- so the application user owns
# nothing and can modify nothing it runs.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 dockerui
USER dockerui

# Expose port
EXPOSE 8000

# `/ui/` answers 200 even when the registry is unreachable (the page renders an
# error banner), which is the intent: this reports on the UI, not on the registry
# behind it. python rather than curl, which the slim image does not ship.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ui/', timeout=4).status < 400 else 1)"]

# Threads, not workers: every request spends its life waiting on the registry, so
# the GIL is released almost the whole time. 2x2 meant four concurrent requests for
# the whole application, and the stats page opens four by itself.
CMD ["gunicorn", "--workers=2", "--threads=8", "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", "DockerUI.wsgi"]
