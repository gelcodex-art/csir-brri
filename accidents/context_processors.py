from django.conf import settings


def map_keys(request):
    """Map tile keys the browser needs (TomTom keys are meant for browser use)."""
    return {"tomtom_key": getattr(settings, "TOMTOM_API_KEY", "")}
