"""Put BRRI's police station codes in the database (see station_codes.py).

For each code the station is looked for by name in its region; if it is not in
the system yet it is added (marked verified: it is on BRRI's own list). When the
list has been corrected, codes already in the database are moved to the station
with the corrected name (or a misread station name is corrected), and stations
made from the list that nothing uses any more are removed. Running the command
again changes nothing. Reports imported earlier, which kept their
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
        have = {c.code: c for c in StationCode.objects.select_related("station")}
        names = sc.all_codes()
        made = matched = linked = moved = renamed = 0
        station_of = {}

        # Codes already in the database whose station no longer has the listed name
        # (the list was corrected): point them at the right station.
        listed = {}                                   # region id -> keys of names on the list
        for code, name in names.items():
            region = regions.get(number_region.get(int(code[:2]), ""))
            if region:
                listed.setdefault(region.pk, set()).add(key(name))
        for code in sorted(have):
            if code not in names or code in sc.ALIASES:
                continue
            row, want = have[code], key(names[code])
            st = row.station
            if key(st.name) == want:
                continue
            found = by_key.get((st.region_id, want), [])
            if found:
                row.station = min(found, key=lambda s: PREFER.index(s.kind) if s.kind in PREFER else 99)
                moved += 1
            elif (st.source == "codes" and key(st.name) not in listed.get(st.region_id, set())
                  and not StationCode.objects.filter(station=st).exclude(code=code).exists()
                  and not Accident.objects.filter(police_station=st).exists()):
                # A station made from a misread name, not used yet: correct its name.
                old = by_key.get((st.region_id, key(st.name)), [])
                if st in old:
                    old.remove(st)
                st.name = f"{names[code]} Police Station"
                st.save(update_fields=["name"])
                by_key.setdefault((st.region_id, key(st.name)), []).append(st)
                renamed += 1
                continue
            else:
                row.station, _ = PoliceStation.objects.get_or_create(
                    region_id=st.region_id, name=f"{names[code]} Police Station",
                    defaults={"source": "codes", "verified": True})
                by_key.setdefault((st.region_id, want), []).append(row.station)
                made += 1
                moved += 1
            row.save(update_fields=["station"])
        # Old codes follow the station of their new-region code.
        for code, target in sc.ALIASES.items():
            if code in have and target in have and have[code].station_id != have[target].station_id:
                have[code].station = have[target].station
                have[code].save(update_fields=["station"])
                moved += 1
        # Stations made from the list that no code or report uses any more.
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

        # Stations made from the list that no code or report uses any more
        # (left over after a code moved to its corrected station).
        used = set(StationCode.objects.values_list("station_id", flat=True)) | set(
            Accident.objects.exclude(police_station=None).values_list("police_station_id", flat=True))
        unused = [pk for pk in PoliceStation.objects.filter(source="codes").values_list("pk", flat=True)
                  if pk not in used]
        removed = len(unused)
        PoliceStation.objects.filter(pk__in=unused).delete()

        # Reports imported before the list existed carry the code in their notes.
        filled = sc.link_reports()

        self.stdout.write(self.style.SUCCESS(
            f"{len(have)} station codes in the system ({linked} added now: {matched} matched "
            f"stations already in the list, {made} new stations added; {moved} code(s) moved "
            f"to the right station, {renamed} station name(s) corrected, {removed} unused "
            f"station(s) removed). "
            f"{filled} earlier report(s) got their station from the code."))
