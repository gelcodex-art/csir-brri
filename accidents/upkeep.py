"""Bring the database up to date after a new version is put online.

A new version can bring changes to the tables (migrations) or a corrected police
station code list. Both used to need setup-online.bat on the office PC; an
administrator can now do it from the admin home page ("Update the database").
"""
import io
import re

from django.core.management import call_command
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor

from . import station_codes as sc


def _key(name):
    from .management.commands.load_station_codes import key
    return key(name)


def pending():
    """{"migrations": n, "codes": n}: table changes not applied yet, and station
    codes missing from the database or pointing at a station with another name."""
    try:
        executor = MigrationExecutor(connection)
        migrations = len(executor.migration_plan(executor.loader.graph.leaf_nodes()))
    except DatabaseError:
        migrations = 0
    codes = 0
    try:
        from . import codebook as cb
        from .models import Region, StationCode
        have_regions = set(Region.objects.values_list("name", flat=True))
        in_db = {number for name, (number, _) in cb.TOWN_CODES.items() if name in have_regions}
        saved = dict(StationCode.objects.values_list("code", "station__name"))
        for code, name in sc.all_codes().items():
            if int(sc.ALIASES.get(code, code)[:2]) not in in_db:
                continue                       # region not in this database: nothing to do
            if code not in saved:
                codes += 1
            elif code not in sc.ALIASES and _key(saved[code]) != _key(name):
                codes += 1
    except DatabaseError:
        pass
    return {"migrations": migrations, "codes": codes, "any": bool(migrations or codes)}


def run():
    """Apply the table changes and load the code list. Returns what was done, in words."""
    out = io.StringIO()
    call_command("migrate", interactive=False, verbosity=1, stdout=out)
    applied = len(re.findall(r"Applying .+\.\.\. OK", out.getvalue()))
    out = io.StringIO()
    call_command("load_station_codes", stdout=out, stderr=io.StringIO())
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    return (f"{applied} table change(s) applied. " if applied else "") + (lines[-1] if lines else "")
