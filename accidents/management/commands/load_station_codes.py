"""Put BRRI's police station codes in the database (see station_codes.py).

For each code the station is looked for by name in its region; if it is not in
the system yet it is added (marked verified: it is on BRRI's own list). Running
the command again changes nothing. Reports imported earlier, which kept their
station code in the analyst notes, get their station filled in.
"""
import re

from django.core.management.base import BaseCommand
from django.db import transaction

from accidents import codebook as cb
from accidents import station_codes as sc
from accidents.models import Accident, PoliceStation, Region, StationCode

NOISE = re.compile(r"\b(police|station|post|headquarters|hq|district|divisional|municipal|command)\b")
PREFER = ["station", "district_hq", "divisional_hq", "post", "mttd", "regional_hq", "national_hq"]
NOTE = re.compile(r"^Police station code: (\d+)\s*$", re.M)


def key(name):
    """'Nsawam Police Station' and 'NSAWAM' compare equal."""
    name = NOISE.sub(" ", name.lower().replace("&", " and "))
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


class Command(BaseCommand):
    help = "Load the police station code list and link the stations to their codes."

    @transaction.atomic
    def handle(self, *args, **options):
        number_region = {number: name for name, (number, _) in cb.TOWN_CODES.items()}
        regions = {r.name: r for r in Region.objects.all()}
        by_key = {}
        for st in PoliceStation.objects.all():
            by_key.setdefault((st.region_id, key(st.name)), []).append(st)
        have = {c.code: c for c in StationCode.objects.all()}
        names = sc.all_codes()
        made = matched = linked = 0
        station_of = {}

        def station_for(code):
            """The station a code stands for, found by name or added."""
            nonlocal made, matched
            code = sc.ALIASES.get(code, code)
            if code in station_of:
                return station_of[code]
            if code in have:
                station_of[code] = have[code].station
                return station_of[code]
            region = regions.get(number_region.get(int(code[:2]), ""))
            if region is None:
                return None
            found = by_key.get((region.pk, key(names[code])), [])
            if found:
                st = min(found, key=lambda s: PREFER.index(s.kind) if s.kind in PREFER else 99)
                matched += 1
            else:
                st, _ = PoliceStation.objects.get_or_create(
                    region=region, name=f"{names[code]} Police Station",
                    defaults={"source": "codes", "verified": True})
                by_key.setdefault((region.pk, key(st.name)), []).append(st)
                made += 1
            station_of[code] = st
            return st

        for code in sorted(names):
            if code in have:
                continue
            st = station_for(code)
            if st is None:
                self.stderr.write(f"{code}: its region is not in the database - skipped.")
                continue
            have[code] = StationCode.objects.create(code=code, station=st)
            linked += 1

        # Reports imported before the list existed carry the code in their notes.
        filled = 0
        for acc in Accident.objects.filter(police_station__isnull=True,
                                           analyst_notes__contains="Police station code:"):
            m = NOTE.search(acc.analyst_notes)
            code = sc.clean_code(m.group(1)) if m else ""
            if code in have:
                notes = NOTE.sub("", acc.analyst_notes).strip()
                Accident.objects.filter(pk=acc.pk).update(police_station=have[code].station,
                                                          analyst_notes=notes)
                filled += 1

        self.stdout.write(self.style.SUCCESS(
            f"{len(have)} station codes in the system ({linked} added now: {matched} matched "
            f"stations already in the list, {made} new stations added). "
            f"{filled} earlier report(s) got their station from the code."))
