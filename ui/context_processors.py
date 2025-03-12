# ui/context_processors.py
from pathlib import Path


def version_context(request):
    """Add version to the template context."""
    try:
        version_file = Path(__file__).resolve().parent.parent / "VERSION"
        with open(version_file, "r") as f:
            version = f.read().strip()
    except Exception:
        version = "unknown"

    return {"app_version": version}
