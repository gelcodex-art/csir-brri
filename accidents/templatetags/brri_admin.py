from django import template
from django.contrib.auth import get_user_model

from ..models import Accident, AuditLog, PoliceStation

register = template.Library()


@register.simple_tag
def brri_admin_counts():
    """Numbers shown on the admin home page."""
    users = get_user_model().objects.filter(is_active=True)
    return {
        "analysts": users.filter(is_superuser=False).count(),
        "admins": users.filter(is_superuser=True).count(),
        "stations": PoliceStation.objects.count(),
        "stations_to_check": PoliceStation.objects.filter(verified=False).count(),
        "stations_from_analysts": PoliceStation.objects.filter(verified=False, source="user").count(),
        "reports": Accident.objects.count(),
        "samples": Accident.objects.filter(is_sample=True).count(),
        "waiting": Accident.objects.filter(status=Accident.STATUS_SUBMITTED).count(),
        "approved": Accident.objects.filter(status=Accident.STATUS_REVIEWED).count(),
        "query": Accident.objects.filter(status=Accident.STATUS_QUERY).count(),
    }


@register.simple_tag
def brri_stations_to_check():
    """Shown beside "Police stations" in the side menu."""
    return PoliceStation.objects.filter(verified=False).count()


@register.simple_tag
def brri_recent_activity(limit=8):
    """The latest entries of the change history, for the admin home page."""
    return list(AuditLog.objects.select_related("accident", "user")[:limit])


@register.filter
def initial(user):
    """First letter of the person's name, for the round badge beside it."""
    name = (user.get_short_name() or user.get_username() or "?").strip()
    return name[:1].upper()
