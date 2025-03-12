FROM python:3.12-slim

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

# Run migrations and collect static files
RUN python manage.py migrate
RUN python manage.py collectstatic

# Expose port
EXPOSE 8000

# Run the application
CMD ["gunicorn", "--workers=3", "--threads=2", "--bind", "0.0.0.0:8000", "DockerUI.wsgi"]