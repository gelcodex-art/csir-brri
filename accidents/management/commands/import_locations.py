"""
Import districts, towns and town codes (field 60), and/or police stations, from CSV.

Towns CSV columns (header row required; latitude/longitude/code optional):
    region,district,town,code,latitude,longitude

Police stations CSV columns (only region and station are required):
    region,district,station,kind,latitude,longitude
  kind: national_hq, regional_hq, divisional_hq, district_hq, station, post, mttd
  Stations imported from a CSV are marked verified (it is assumed to be an
  official list), unless --unverified is given (e.g. a list compiled by BRRI
  staff that still has to be checked). Existing stations with the same name in
  the region are updated; --unverified never un-verifies a checked station.

Usage:
    python manage.py import_locations data/towns.csv
    python manage.py import_locations data/stations.csv --stations
    python manage.py import_locations data/kumasi_stations_unverified.csv --stations --unverified
Re-running is safe: existing rows are updated, not duplicated.
"""
import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accidents.models import District, PoliceStation, Region, Town


def _clean(v):
    return (v or "").strip()


class Command(BaseCommand):
    help = "Import districts/towns/codes or police stations from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--stations", action="store_true", help="File is a police station list")
        parser.add_argument("--unverified", action="store_true",
                            help="Stations still need checking: add them as unverified")

    @transaction.atomic
    def handle(self, csv_path, stations=False, unverified=False, **opts):
        regions = {r.name.lower(): r for r in Region.objects.all()}
        created = updated = 0
        problems = []
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            reader.fieldnames = [h.strip().lower() for h in reader.fieldnames or []]
            for line, row in enumerate(reader, start=2):
                region = regions.get(_clean(row.get("region")).lower())
                if not region:
                    problems.append(f"line {line}: unknown region '{row.get('region')}'")
                    continue
                if stations:
                    name = _clean(row.get("station"))
                    if not name:
                        continue
                    fields = {} if unverified else {"verified": True}
                    dname = _clean(row.get("district"))
                    if dname:
                        d = District.objects.filter(region=region, name__iexact=dname).first()
                        if d:
                            fields["district"] = d
                        else:
                            problems.append(f"line {line}: unknown district '{dname}' (station kept)")
                    kind = _clean(row.get("kind")).lower()
                    if kind:
                        if kind in dict(PoliceStation.KINDS):
                            fields["kind"] = kind
                        else:
                            problems.append(f"line {line}: unknown kind '{kind}' (station kept)")
                    for key in ("latitude", "longitude"):
                        val = _clean(row.get(key))
                        if val:
                            fields[key] = float(val)
                    obj = PoliceStation.objects.filter(region=region, name__iexact=name).first()
                    if obj:
                        for k, v in fields.items():
                            setattr(obj, k, v)
                        obj.save()
                        updated += 1
                    else:
                        PoliceStation.objects.create(region=region, name=name, source="csv", **fields)
                        created += 1
                    continue

                dname, tname = _clean(row.get("district")), _clean(row.get("town"))
                if not dname:
                    problems.append(f"line {line}: missing district")
                    continue
                district, _ = District.objects.get_or_create(region=region, name=dname)
                if not tname:
                    continue
                defaults = {"code": _clean(row.get("code"))}
                for key in ("latitude", "longitude"):
                    val = _clean(row.get(key))
                    if val:
                        defaults[key] = float(val)
                existing = Town.objects.filter(district=district, name__iexact=tname).first()
                if existing:
                    for k, v in defaults.items():
                        if v:
                            setattr(existing, k, v)
                    existing.save()
                    updated += 1
                else:
                    Town.objects.create(district=district, name=tname, **defaults)
                    created += 1

        for p in problems[:50]:
            self.stderr.write(p)
        if len(problems) > 50:
            self.stderr.write(f"... and {len(problems) - 50} more problems")
        if problems and not (created or updated):
            raise CommandError("Nothing imported.")
        from django.core.cache import cache
        from accidents.views import LOCATIONS_CACHE_KEY
        cache.delete(LOCATIONS_CACHE_KEY)
        self.stdout.write(self.style.SUCCESS(
            f"Created {created}, updated {updated}, skipped {len(problems)} rows."))
