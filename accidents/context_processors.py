from django.conf import settings


def map_keys(request):
    """Map tile keys the browser needs (TomTom keys are meant for browser use)."""
    return {"tomtom_key": getattr(settings, "TOMTOM_API_KEY", "")}


def rights(request):
    """can_submit / can_approve / can_analyse and the role shown in the top bar."""
    from . import access
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {}
    return {"can_submit": access.can(user, access.SUBMIT),
            "can_approve": access.can(user, access.APPROVE),
            "can_analyse": access.can(user, access.ANALYSE),
            "user_role": access.role_name(user)}
