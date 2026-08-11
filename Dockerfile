FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONOPTIMIZE=1

# Collect static files. There is no `migrate` step: the project has no models and
# no database, so it had nothing to do beyond baking a throwaway SQLite file into
# the image.
RUN python manage.py collectstatic --noinput --clear

# Expose port
EXPOSE 8000

# Run the application
CMD ["gunicorn", "--workers=2", "--threads=2", "--bind", "0.0.0.0:8000", "DockerUI.wsgi"]