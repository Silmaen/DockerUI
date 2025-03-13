# DockerUI

A lightweight web interface for browsing Docker registries. This application supports both standard Docker Registry API
and JFrog Artifactory Docker repositories.

## Features

- Browse repositories in Docker registries
- View tags for each repository
- Authentication support for private registries
- Cache mechanism for improved performance
- Support for multiple registry types:
    - Standard Docker Registry
    - JFrog Artifactory

## Installation

### Using Docker Compose (Recommended)

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/DockerUI.git
   cd DockerUI
   ```

2. Create a `.env` file for parameters:
   ```bash
   echo "# Registry settings" > .env
   echo "REGISTRY_URL=https://registry.example.com:5000" >> .env
   echo "REGISTRY_TYPE=classic" >> .env
   echo "REGISTRY_REPO=" >> .env
   echo "REGISTRY_SSL_VERIFY=False" >> .env
   echo "" >> .env
   echo "# App settings" >> .env
   echo "DEBUG=False" >> .env
   echo "SECRET_KEY=your-secure-secret-key" >> .env
   echo "" >> .env
   echo "# Authentication credentials" >> .env
   echo "REGISTRY_USERNAME=username" >> .env
   echo "REGISTRY_PASSWORD=password" >> .env
   ```

3. Run with Docker Compose:
   ```bash
   docker-compose up -d
   ```

4. Access the UI at `http://localhost:8000`

### Manual Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment variables
4. Run the application:
   ```bash
   python manage.py migrate
   python manage.py collectstatic
   python manage.py runserver
   ```

### Upgrading

To upgrade the application, pull the latest changes from the repository and restart the application:

```bash
# get the latest changes
git pull
# stop the actual running service
docker-compose down
# remove the old image to force the build of a new one
docker image rm dockerui_registry-ui
# start the service again
docker-compose up -d
```

## Configuration

### Environment Variables

| Variable              | Description                                      | Default                               | Required            |
|-----------------------|--------------------------------------------------|---------------------------------------|---------------------|
| `REGISTRY_URL`        | URL of the Docker registry                       | `http://registry:5000`                | Yes                 |
| `REGISTRY_TYPE`       | Type of registry (`classic` or `artifactory`)    | `classic`                             | Yes                 |
| `REGISTRY_REPO`       | Repository namespace in registry (if applicable) | `""`                                  | No                  |
| `REGISTRY_SSL_VERIFY` | Enable SSL verification                          | `False`                               | No                  |
| `REGISTRY_USERNAME`   | Username for registry authentication             | `""`                                  | No                  |
| `REGISTRY_PASSWORD`   | Password for registry authentication             | `""`                                  | No                  |
| `SECRET_KEY`          | Django secret key                                | `django-insecure-default-key-for-dev` | Yes (in production) |
| `DEBUG`               | Enable debug mode                                | `False`                               | No                  |

### Registry Types

#### Classic Docker Registry

For standard Docker registries, set:

```yaml
REGISTRY_TYPE=classic
REGISTRY_URL=https://your-registry:5000
```

#### Artifactory Docker Registry

For JFrog Artifactory registries, set:

```yaml
REGISTRY_TYPE=artifactory
REGISTRY_URL=https://artifactory.example.com
REGISTRY_REPO=your-docker-repo
```

## Docker Compose Example

```yaml
services:
  registry-ui:
    build: .
    ports:
      - "8000:8000"
    environment:
      # registry settings
      - REGISTRY_URL=${REGISTRY_URL}
      - REGISTRY_TYPE=${REGISTRY_TYPE}
      - REGISTRY_REPO=${REGISTRY_REPO}
      - REGISTRY_SSL_VERIFY=${REGISTRY_SSL_VERIFY}
      # application settings
      - DEBUG=${DEBUG}
      - SECRET_KEY=${SECRET_KEY}
      # Authentication credentials
      - REGISTRY_USERNAME=${REGISTRY_USERNAME}
      - REGISTRY_PASSWORD=${REGISTRY_PASSWORD}
```

## License

This project is licensed under the terms of the license included in the [LICENSE](LICENSE) file at the root of this
project.