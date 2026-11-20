"""What each account may do in the app.

Each account has three ticks on its page in the admin area:
  * Can submit reports  - enter new reports and edit them;
  * Can approve reports - set a report's status (Approved / Needs query) and notes;
  * Can do analysis     - the dashboard, the Analysis page and the Excel/CSV exports.
Everyone who can log in can open the records list and read a report.
Administrators can do everything.
"""
from functools import wraps

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import render

SUBMIT = "submit_report"
APPROVE = "approve_report"
ANALYSE = "do_analysis"

# (codename, label on the account page, what it allows)
RIGHTS = [
    (SUBMIT, "Can submit reports", "Enter new accident reports and edit reports."),
    (APPROVE, "Can approve reports",
     "Set a report's status (Approved or Needs query) and write review notes."),
    (ANALYSE, "Can do analysis",
     "Open the dashboard and the Analysis page, and download Excel/CSV exports."),
]
LABELS = {code: label for code, label, _ in RIGHTS}


def can(user, right):
    return bool(user and user.is_authenticated and user.has_perm(f"accidents.{right}"))


def permission(right):
    from .models import Accident
    ct = ContentType.objects.get_for_model(Accident)
    perm, _ = Permission.objects.get_or_create(
        content_type=ct, codename=right, defaults={"name": LABELS[right]})
    return perm


def set_rights(user, rights):
    """Give the account exactly these rights (codenames) of the three."""
    perms = {r: permission(r) for r in LABELS}
    for r, p in perms.items():
        if r in rights:
            user.user_permissions.add(p)
        else:
            user.user_permissions.remove(p)
    for attr in ("_perm_cache", "_user_perm_cache"):   # has_perm reads the new rights
        user.__dict__.pop(attr, None)


def rights_of(user):
    return [r for r in LABELS if can(user, r)]


def role_name(user):
    """Short description of an account, e.g. "Submits, approves"."""
    if user.is_superuser:
        return "Administrator"
    have = {p.codename for p in user.user_permissions.all()}
    words = [w for r, w in ((SUBMIT, "submits"), (APPROVE, "approves"), (ANALYSE, "analysis"))
             if r in have]
    return ", ".join(words).capitalize() if words else "Reads only"


def needs(right):
    """View decorator: a page shown only to accounts with this right."""
    def deco(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not can(request.user, right):
                return render(request, "accidents/no_access.html",
                              {"right": LABELS[right]}, status=403)
            return view(request, *args, **kwargs)
        return wrapped
    return deco
