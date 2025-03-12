# ui/views.py
import requests
from django.conf import settings
from django.shortcuts import render


def get_registry_data(endpoint):
    url = f"{settings.REGISTRY_URL}{endpoint}"
    try:
        response = requests.get(url, verify=settings.REGISTRY_SSL_VERIFY)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.RequestException as e:
        return None, f"Error connecting to registry: {str(e)}"


def index(request):
    return render(request, 'ui/index.html')

def repository_list(request):
    data, error_message = get_registry_data("/v2/_catalog")

    repositories = []
    if data and 'repositories' in data:
        repositories = data['repositories']

    # Group repositories by namespace
    namespaces = {}
    for repo in repositories:
        parts = repo.split('/')
        if len(parts) > 1:
            namespace = parts[0]
            repo_name = '/'.join(parts[1:])
            if namespace not in namespaces:
                namespaces[namespace] = []
            namespaces[namespace].append({'full_name': repo, 'name': repo_name})
        else:
            if 'default' not in namespaces:
                namespaces['default'] = []
            namespaces['default'].append({'full_name': repo, 'name': repo})

    context = {
        'namespaces': namespaces,
        'error_message': error_message
    }
    return render(request, 'ui/repository_list.html', context)


def repository_detail(request, repository):
    data, error_message = get_registry_data(f"/v2/{repository}/tags/list")

    tags = []
    if data and 'tags' in data:
        tags = data['tags']

    context = {
        'repository': repository,
        'tags': tags,
        'error_message': error_message
    }
    return render(request, 'ui/repository_detail.html', context)
