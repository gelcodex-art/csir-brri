from django import template
from django.contrib.auth import get_user_model

from ..models import Accident, PoliceStation

register = template.Library()


@register.simple_tag
def brri_admin_counts():
    """Numbers shown on the admin home page task cards."""
    users = get_user_model().objects.filter(is_active=True)
    return {
        "analysts": users.filter(is_superuser=False).count(),
        "admins": users.filter(is_superuser=True).count(),
        "stations": PoliceStation.objects.count(),
        "stations_to_check": PoliceStation.objects.filter(verified=False).count(),
        "stations_from_analysts": PoliceStation.objects.filter(verified=False, source="user").count(),
        "reports": Accident.objects.count(),
        "samples": Accident.objects.filter(is_sample=True).count(),
    }
