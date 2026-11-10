"""Vercel entry point: serves the Django site as a Python function."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "brri.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
