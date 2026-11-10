"""
Load Ghana police stations from OpenStreetMap (data/sources/osm_police_ghana.json).

OpenStreetMap has ~400 named police locations in Ghana; the Ghana Police Service
runs many more. Missing stations are added by analysts from the report form
(marked unverified) or in bulk:  manage.py import_locations stations.csv --stations

Cleaning rules:
  * drop checkpoints/barriers, barracks/quarters, training schools, customs,
    prisons, fire service and non-traffic units (SWAT, DOVVSU)
  * generic names ("Police Station", "District Police Headquarters", ...) get
    the nearest town's name: "Walewale District Police Headquarters"
  * names are tidied ("Ghana Police Service-Enchi" -> "Enchi Police Station")
  * each station is classified (regional/divisional/district HQ, station,
    post, MTTD) and placed in its region and district by GPS position
  * duplicates (same name within 1.5 km) are merged

Re-running is safe: stations are matched by their OpenStreetMap id; stations
used in accident reports, or added/edited by hand, are never deleted.

Download/refresh the source file first (see README, "Police stations").
"""
import json
import re

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accidents.geo import SRC, Locator, km
from accidents.models import Accident, PoliceStation
from accidents.views import LOCATIONS_CACHE_KEY

EXCLUDE = re.compile(
    r"barrier|check ?point|police check\b|barracks|\bquarters\b|residentia|training|school|depot|"
    r"customs|immigration|fire\s*service|prison|charge office|buildings|container|swat|"
    r"dovvsu|domestic violence|^old police|^cpc$|^as\. police|^police national$|^municipal prisons",
    re.I)

# Whole name is generic -> needs the nearest town's name in front.
GENERIC = {
    "police", "police station", "ghana police", "ghana police service", "ghana police station",
    "new police station", "police post", "police headquarters", "district police headquarters",
    "divisional police headquarters", "divisional police office", "regional police headquarters",
    "mttu", "mttu police station", "districts police", "central police station",
    "regional mttu office", "district police",
}

FIXES = [
    (r"Headquat?ers?", "Headquarters"), (r"\bSation\b", "Station"), (r"\bPolices\b", "Police"),
    (r"\bPolice Police\b", "Police"), (r"\bM\.?T\.?T\.?U\.?\b", "MTTU"), (r"\bHQ\b", "Headquarters"),
    (r"\bGuttter\b", "Gutter"), (r"\bRégional\b", "Regional"),
]

# A few OSM names that need a hand-written tidy version.
OVERRIDES = {
    "Ghana Police Service Headquarters(Aowin Municipal-Enchi)": "Enchi District Police Headquarters",
    "Ghana Police Service District Headquarters & Central Police Station Nkawkaw": "Nkawkaw District Police Headquarters",
    "Ghana Police Service - Community 18 District Headquarters": "Community 18 District Police Headquarters",
    "Ghana National Police Headquarter": "Ghana Police Service National Headquarters",
    "Ghana police headquaters Ashaiman": "Ashaiman Divisional Police Headquarters",
    "Ghana Police Service, Bekwai Office": "Bekwai Police Station",
    "Aburi District Police Headquarters, Aburi/Akuapem": "Aburi District Police Headquarters",
    "District Police Headquarters Kintampo South -Jema": "Jema District Police Headquarters",
    "District Police Headquarters - Kpetoe": "Kpetoe District Police Headquarters",
    "Yamfo Ghana Police Service": "Yamfo Police Station",
    "Ghana Police Service MTTU Anyinam": "Anyinam MTTU",
    "Esiama Divisional District Police HQ": "Esiama Divisional Police Headquarters",
    "Tema Regional Patrol Police Headquarters": "Tema Regional Police Headquarters",
    "Regional Police Headquarters, Ashanti": "Ashanti Regional Police Headquarters",
    "Police Headquarters Cape Coast": "Central Regional Police Headquarters",
    "Savannah Police Regional Headquarters": "Savannah Regional Police Headquarters",
    "Ring Road Post - KNUST": "KNUST Ring Road Police Post",
    "Kpeshie Divisional Police Station": "Kpeshie Divisional Police Headquarters",
    "Ghana Police Dome Post": "Dome Police Post",
    "Weija Division Headquarters": "Weija Divisional Police Headquarters",
    "Dodowa Divisional Headquarters": "Dodowa Divisional Police Headquarters",
}

# Names for particular OSM objects whose tag is only generic ("Central Police Station").
NAMES_BY_ID = {
    "way/571757264": "Kumasi Central Police Station",   # Adum, Kumasi
}

KEEP_UPPER = {"MTTU", "KNUST", "UCC", "KSTU", "UBIDS", "SCC", "TLOC", "TOPP", "CTU", "II"}


def tidy_words(name):
    words = []
    for w in name.split():
        core = re.sub(r"[^A-Za-z.]", "", w)
        if core.upper() in KEEP_UPPER or re.fullmatch(r"([A-Za-z]\.)+[A-Za-z]?\.?", core or "-"):
            # Abbreviations: MTTU, KNUST, A.G.A
            words.append(w.upper())
        elif w.islower() or w.isupper() and len(core) > 3:
            words.append(w[:1].upper() + w[1:].lower())
        else:
            words.append(w[:1].upper() + w[1:])
    return " ".join(words)


def clean_name(raw):
    """Return (name, is_generic) for an OSM police name."""
    raw = re.sub(r"\s+", " ", raw.strip())
    if raw in OVERRIDES:
        return OVERRIDES[raw], False
    name = raw
    for pat, rep in FIXES:
        name = re.sub(pat, rep, name, flags=re.I)
    # "Ghana Police Service - X", "Ghana Police Service X", "Ghana police station X", "(X)"
    m = re.match(r"^Ghana Police (?:Service|Station)\s*[-,]?\s*\(?(.+?)\)?$", name, re.I)
    if m and m.group(1).lower() not in ("", "service"):
        name = m.group(1).strip() + " Police Station"
    name = tidy_words(name)
    if not name or name.lower() in GENERIC:
        return name, True
    if re.search(r"\bPolice$", name):          # "Offinso Police" -> "Offinso Police Station"
        name += " Station"
    elif not re.search(r"police|mttu|headquarters", name, re.I):
        name += " Police Station"
    return name, False


def classify(name):
    n = name.lower()
    if "national headquarters" in n:
        return "national_hq"
    if "regional" in n and ("headquarters" in n or "mttu" in n):
        return "mttd" if "mttu" in n else "regional_hq"
    if "mttu" in n or "mttd" in n:
        return "mttd"
    if "division" in n:
        return "divisional_hq"
    if "district" in n and ("headquarters" in n or "police district" in n):
        return "district_hq"
    if "headquarters" in n:
        return "district_hq"
    if "post" in n:
        return "post"
    return "station"


GENERIC_SUFFIX = {
    "regional_hq": "Regional Police Headquarters", "divisional_hq": "Divisional Police Headquarters",
    "district_hq": "District Police Headquarters", "mttd": "MTTU", "post": "Police Post",
}


class Command(BaseCommand):
    help = "Load police stations in Ghana from OpenStreetMap."

    @transaction.atomic
    def handle(self, *args, **opts):
        path = SRC / "osm_police_ghana.json"
        if not path.exists():
            raise CommandError(f"Missing {path}. See README, 'Police stations'.")
        elements = json.loads(path.read_text(encoding="utf-8"))["elements"]
        loc = Locator()

        kept, dropped, unplaced = [], 0, 0
        for el in elements:
            tags = el.get("tags", {})
            if tags.get("police") in ("checkpoint", "barracks") or tags.get("amenity") != "police":
                dropped += 1
                continue
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lng = el.get("lon") or el.get("center", {}).get("lon")
            raw = (tags.get("name") or "").strip()
            if lat is None or EXCLUDE.search(raw):
                dropped += 1
                continue
            fixed = NAMES_BY_ID.get(f"{el['type']}/{el['id']}")
            if fixed:
                name, generic = fixed, False
            else:
                name, generic = clean_name(raw) if raw else ("", True)
            district = loc.district_at(lat, lng)
            if district is None:
                unplaced += 1
                continue
            if generic and classify(name) == "regional_hq":
                name = f"{district.region.name} Regional Police Headquarters"
            elif generic:
                # Name it after the nearest town or suburb.
                near = (loc.nearest_town(lat, lng, max_km=3, kinds={"city", "town", "suburb"})
                        or loc.nearest_town(lat, lng, max_km=2))
                if not near:
                    unplaced += 1
                    continue
                kind = classify(name or "Police Station")
                suffix = GENERIC_SUFFIX.get(kind, "Police Station")
                if "central" in name.lower():
                    suffix = "Central Police Station"
                name = f"{near[0]} {suffix}"
            kept.append({"name": tidy_words(name), "kind": classify(name), "lat": lat, "lng": lng,
                         "district": district, "source": f"osm:{el['type']}/{el['id']}"})

        # Merge duplicates: same name within 1.5 km (keep the first).
        unique, merged = [], 0
        for s in kept:
            twin = next((u for u in unique if u["name"].lower() == s["name"].lower()
                         and (km(u["lat"], u["lng"], s["lat"], s["lng"]) < 1.5
                              or s["kind"] in ("regional_hq", "national_hq"))), None)
            if twin:
                merged += 1
                continue
            unique.append(s)

        # Same name, different place, same region -> add the district to tell them apart.
        seen = {}
        for s in unique:
            key = (s["district"].region_id, s["name"].lower())
            if key in seen:
                for x in (seen[key], s):
                    if "(" not in x["name"]:
                        x["name"] = f"{x['name']} ({x['district'].name})"
            else:
                seen[key] = s

        def in_use(station):
            return Accident.objects.filter(police_station=station).exists()

        # 1. Remove OSM stations that are no longer in the cleaned data (unless used).
        wanted = {s["source"] for s in unique}
        removed = 0
        for obj in PoliceStation.objects.filter(source__startswith="osm:").exclude(source__in=wanted):
            if not in_use(obj):
                obj.delete()
                removed += 1

        # 2. Create / update. If another station already has the target name in
        #    the region (hand-entered, or an earlier duplicate), merge into it.
        existing = {p.source: p for p in PoliceStation.objects.filter(source__in=wanted)}
        created = updated = 0
        for s in unique:
            fields = dict(region=s["district"].region, district=s["district"], name=s["name"],
                          kind=s["kind"], latitude=round(s["lat"], 6), longitude=round(s["lng"], 6))
            obj = existing.get(s["source"])
            other = (PoliceStation.objects.filter(region=fields["region"], name__iexact=fields["name"])
                     .exclude(pk=obj.pk if obj else None).first())
            if other:
                for k in ("district", "kind", "latitude", "longitude"):
                    if getattr(other, k) in (None, ""):
                        setattr(other, k, fields[k])
                other.save()
                if obj and not in_use(obj):
                    obj.delete()
                updated += 1
            elif obj:
                for k, v in fields.items():
                    setattr(obj, k, v)
                obj.save()
                updated += 1
            else:
                PoliceStation.objects.create(source=s["source"], **fields)
                created += 1

        cache.delete(LOCATIONS_CACHE_KEY)
        by_kind = {}
        for s in unique:
            by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + 1
        self.stdout.write(self.style.SUCCESS(
            f"Police stations: {PoliceStation.objects.count()} in database "
            f"(created {created}, updated {updated}, removed {removed})"))
        self.stdout.write("  by kind: " + ", ".join(f"{k} {v}" for k, v in sorted(by_kind.items(), key=lambda x: -x[1])))
        self.stdout.write(f"  dropped (checkpoints, barracks, schools...): {dropped}, "
                          f"unnamed/unplaceable: {unplaced}, duplicates merged: {merged}")
