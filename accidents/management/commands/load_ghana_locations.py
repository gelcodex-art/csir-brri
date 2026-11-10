"""
Load every region, MMDA (district/municipal/metropolitan assembly) and named
settlement in Ghana.

Sources (downloaded into data/sources/, see README):
  * geoBoundaries GHA ADM1 (16 regions, from OpenStreetMap)
  * geoBoundaries GHA ADM2 (260 MMDAs, from USAID / Ghana Statistical Service)
    + Guan District (created 2022, no published boundary yet)
  * OpenStreetMap places (city, town, village, hamlet, suburb ...) via Overpass
  * GeoNames GH populated places

Each settlement is placed in its district by point-in-polygon, so the
region -> district -> town hierarchy is consistent. OSM and GeoNames entries
for the same place (same name within 3 km) are merged.

Re-running is safe: towns are matched by their source id, records referenced
by accident reports are never deleted, and towns added by hand are kept.

Also writes simplified boundary files used by the maps:
  accidents/static/accidents/geo/regions.geojson
  accidents/static/accidents/geo/districts.geojson
"""
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from shapely.geometry import MultiPoint, Point, mapping, shape
from shapely.ops import unary_union, voronoi_diagram
from shapely.strtree import STRtree

from accidents.models import Accident, District, PoliceStation, Region, Town
from accidents.views import LOCATIONS_CACHE_KEY

SRC = Path(settings.BASE_DIR) / "data" / "sources"
GEO_OUT = Path(settings.BASE_DIR) / "accidents" / "static" / "accidents" / "geo"

# Source spellings -> names as used by the Ministry of Local Government.
NAME_FIXES = {
    "Accra Metropolis": "Accra Metropolitan",
    "Sekondi Takoradi Metropolis": "Sekondi-Takoradi Metropolitan",
    "Sefwi-Wiawso": "Sefwi Wiawso Municipal",
    "Bolga East": "Bolgatanga East",
    "Lower Manya": "Lower Manya Krobo",
    "Upper Manya": "Upper Manya Krobo",
    "Assin Fosu": "Assin Central Municipal",
    "Kasena Nankana East": "Kasena Nankana Municipal",
    "Denkyembour": "Denkyembour",
}
# Assemblies with municipal status whose source name omits the word.
MUNICIPAL = {
    "Ga East", "Ayawaso West", "La Dade-Kotopon", "La-Nkwantanang-Madina", "Kpone Katamanso",
    "Savelugu", "Sagnerigu", "Nsawam Adoagyiri", "Akwapem North", "Kwahu West", "Yilo Krobo",
    "Lower Manya Krobo", "Abuakwa South", "West Akim", "Ejura-Sekyedumase", "Kwabre East",
    "Atwima Nwabiagya South", "Awutu Senya East", "Tarkwa Nsuaem", "Prestea-Huni Valley",
    "Nzema East", "Atebubu Amantin", "Nkoranza South", "Sunyani West", "Lawra", "Jirapa",
    "Nandom", "Sissala East", "Builsa North", "Gushegu", "West Gonja", "East Mamprusi",
    "Jomoro", "Ketu South",
}
EXTRA_DISTRICTS = [("Oti", "Guan", "district")]  # created 2022
# Guan District = the SALL traditional areas, formerly in Hohoe Municipal (Volta).
# The 2019 boundaries still place them in Hohoe, so they are moved by name.
GUAN_PREFIXES = ("Santrokofi", "Akpafu", "Lolobi", "Likpe")

OSM_KIND = {"city": "city", "town": "town", "village": "village", "hamlet": "hamlet",
            "isolated_dwelling": "hamlet", "suburb": "suburb", "neighbourhood": "suburb",
            "quarter": "suburb", "locality": "locality"}
KIND_RANK = {"city": 0, "town": 1, "suburb": 2, "village": 3, "hamlet": 4, "locality": 5}


# Assemblies not used: their area is shared among the bordering assemblies,
# each part going to the nearest one. Kumasi Metropolitan is split among
# Asokwa, Kwadaso, Oforikrom, Old Tafo, Suame and Asokore Mampong Municipal.
DISSOLVED = {"Kumasi Metropolitan"}


def adm2_features():
    """[(clean MMDA name, shapely geometry)] from gha_ADM2, with DISSOLVED merged away."""
    data = load_json(SRC / "gha_ADM2.geojson")
    feats = []
    for f in data["features"]:
        g = shape(f["geometry"])
        feats.append([tidy(f["properties"]["shapeName"]), g if g.is_valid else g.buffer(0)])
    for gone in DISSOLVED:
        area = next((g for n, g in feats if n == gone), None)
        if area is None:
            continue
        feats = [x for x in feats if x[0] != gone]
        edge = area.buffer(0.0005)
        pts, owners = [], []
        for i, (_n, g) in enumerate(feats):
            if not g.intersects(edge):
                continue
            border = g.boundary.intersection(edge)
            steps = max(2, int(border.length / 0.0002))      # a point every ~20 m
            for k in range(steps + 1):
                pts.append(border.interpolate(k / steps, normalized=True))
                owners.append(i)
        tree = STRtree(pts)
        parts = defaultdict(list)
        for cell in voronoi_diagram(MultiPoint(pts), envelope=area.buffer(0.05)).geoms:
            inside = [j for j in tree.query(cell) if cell.covers(pts[j])]
            if inside:
                parts[owners[inside[0]]].append(cell.intersection(area))
        for i, pieces in parts.items():
            feats[i][1] = unary_union([feats[i][1], *pieces]).buffer(0)
    return [tuple(x) for x in feats]


def tidy(name):
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"(?<=[a-z])/(?=[a-z])", "-", name, flags=re.I)
    # Capitalise each part of hyphenated names: Ejura-sekyedumase -> Ejura-Sekyedumase
    name = "-".join(p[:1].upper() + p[1:] for p in name.split("-"))
    return NAME_FIXES.get(name, name)


def assembly_type(name):
    if "Metropolitan" in name:
        return "metropolitan"
    if "Municipal" in name or name in MUNICIPAL:
        return "municipal"
    return "district"


def norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def km(a, b):
    dlat = (a[0] - b[0]) * 111.0
    dlng = (a[1] - b[1]) * 111.0 * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlng)


def load_json(path):
    if not path.exists():
        raise CommandError(f"Missing {path}. See README: 'Location data sources'.")
    return json.loads(path.read_text(encoding="utf-8"))


def osm_places():
    data = load_json(SRC / "osm_places_ghana.json")
    for el in data["elements"]:
        tags = el.get("tags", {})
        name = tags.get("name:en") or tags.get("name")
        kind = OSM_KIND.get(tags.get("place"))
        if name and kind and "lat" in el:
            yield {"name": name.strip(), "kind": kind, "lat": el["lat"], "lng": el["lon"],
                   "source": f"osm:{el['id']}"}


def geonames_places():
    path = SRC / "geonames" / "GH.txt"
    if not path.exists():
        return
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row[6] != "P" or row[7] in ("PPLQ", "PPLW", "PPLH", "PPLCH"):
                continue
            code, pop = row[7], int(row[14] or 0)
            if code in ("PPLC", "PPLA"):
                kind = "city"
            elif code == "PPLA2" or pop >= 5000:
                kind = "town"
            elif code == "PPLX":
                kind = "suburb"
            else:
                kind = "village"
            yield {"name": row[1].strip(), "kind": kind, "lat": float(row[4]),
                   "lng": float(row[5]), "source": f"geonames:{row[0]}"}


def write_overlay(path, features, tolerance):
    out = []
    for props, geom in features:
        g = geom.simplify(tolerance, preserve_topology=True)
        gj = mapping(g)

        def rnd(c):
            if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
                return [round(c[0], 4), round(c[1], 4)]
            return [rnd(x) for x in c]

        gj = {"type": gj["type"], "coordinates": rnd(gj["coordinates"])}
        out.append({"type": "Feature", "properties": props, "geometry": gj})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": out},
                               separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


class Command(BaseCommand):
    help = "Load all regions, districts (MMDAs) and towns of Ghana from open data."

    @transaction.atomic
    def handle(self, *args, **opts):
        # ---- Regions -----------------------------------------------------------
        adm1 = load_json(SRC / "gha_ADM1.geojson")
        region_geoms = {}
        for f in adm1["features"]:
            name = f["properties"]["shapeName"].replace(" Region", "").strip()
            region_geoms[name] = shape(f["geometry"])
            Region.objects.get_or_create(name=name)
        regions = {r.name: r for r in Region.objects.all()}

        # ---- Districts ---------------------------------------------------------
        rtree_names = list(region_geoms)
        rtree = STRtree([region_geoms[n] for n in rtree_names])
        district_geoms, district_objs = [], []
        keep_district_ids = set()
        for name, geom in adm2_features():
            pt = geom.representative_point()
            hits = [rtree_names[i] for i in rtree.query(pt, predicate="intersects")]
            region_name = hits[0] if hits else rtree_names[rtree.nearest(pt)]
            d, _ = District.objects.update_or_create(
                region=regions[region_name], name=name,
                defaults={"assembly_type": assembly_type(name)})
            keep_district_ids.add(d.id)
            district_geoms.append(geom)
            district_objs.append(d)
        for region_name, name, kind in EXTRA_DISTRICTS:
            d, _ = District.objects.update_or_create(
                region=regions[region_name], name=name, defaults={"assembly_type": kind})
            keep_district_ids.add(d.id)

        dtree = STRtree(district_geoms)

        def district_for(lat, lng):
            p = Point(lng, lat)
            hits = dtree.query(p, predicate="intersects")
            if len(hits):
                return district_objs[hits[0]]
            i = dtree.nearest(p)
            # Accept points just off the coast/border (within ~3 km); drop the rest.
            return district_objs[i] if district_geoms[i].distance(p) < 0.03 else None

        # Old districts (e.g. earlier seed names, DISSOLVED) not used by a report are
        # removed; their police stations move to the district at their position.
        stale = District.objects.exclude(id__in=keep_district_ids)
        for d in stale:
            if not Accident.objects.filter(district=d).exists():
                for s in PoliceStation.objects.filter(district=d):
                    new = (district_for(float(s.latitude), float(s.longitude))
                           if s.latitude is not None else None)
                    s.district = new
                    s.save(update_fields=["district"])
                Town.objects.filter(district=d, accident__isnull=True).delete()
                if not d.towns.exists():
                    d.delete()

        # ---- Towns -------------------------------------------------------------
        kept = []                       # final list of dicts
        by_name = defaultdict(list)     # (district_id, normalized name) -> [entries]
        skipped_outside = merged = 0
        for source in (osm_places(), geonames_places()):
            for p in source:
                d = district_for(p["lat"], p["lng"])
                if d is None:
                    skipped_outside += 1
                    continue
                key = (d.id, norm(p["name"]))
                dup = next((e for e in by_name[key] if km((e["lat"], e["lng"]), (p["lat"], p["lng"])) < 3), None)
                if dup:
                    merged += 1
                    if KIND_RANK[p["kind"]] < KIND_RANK[dup["kind"]]:
                        dup["kind"] = p["kind"]
                    continue
                p["district"] = d
                by_name[key].append(p)
                kept.append(p)

        # Places added by users on the report form (source "user") are kept like hand-entered ones.
        existing = {t.source: t for t in Town.objects.exclude(source__in=["", "user"])}
        to_create, to_update = [], []
        for p in kept:
            t = existing.pop(p["source"], None)
            fields = dict(district=p["district"], name=p["name"], kind=p["kind"],
                          latitude=round(p["lat"], 6), longitude=round(p["lng"], 6),
                          source=p["source"])
            if t:
                for k, v in fields.items():
                    setattr(t, k, v)
                to_update.append(t)
            else:
                to_create.append(Town(**fields))
        Town.objects.bulk_create(to_create, batch_size=2000)
        Town.objects.bulk_update(to_update, ["district", "name", "kind", "latitude", "longitude"],
                                 batch_size=2000)
        guan = District.objects.get(region__name="Oti", name="Guan")
        hohoe = District.objects.filter(name="Hohoe Municipal").first()
        guan_q = Town.objects.none()
        for prefix in GUAN_PREFIXES:
            guan_q = guan_q | Town.objects.filter(district=hohoe, name__istartswith=prefix)
        moved_guan = guan_q.update(district=guan)
        # Sourced towns that disappeared from the data, unless used by a report.
        removed = 0
        for t in existing.values():
            if not Accident.objects.filter(town=t).exists():
                t.delete()
                removed += 1
        # Hand-entered/seeded towns that now duplicate a sourced one.
        for t in Town.objects.filter(source__in=["", "user"]):
            if t.latitude is None or Accident.objects.filter(town=t).exists():
                continue
            twins = by_name.get((t.district_id, norm(t.name)), [])
            if any(km((float(t.latitude), float(t.longitude)), (e["lat"], e["lng"])) < 3 for e in twins):
                t.delete()

        # ---- Map overlays --------------------------------------------------------
        GEO_OUT.mkdir(parents=True, exist_ok=True)
        write_overlay(GEO_OUT / "ghana.geojson",                    # national outline (map mask)
                      [({"name": "Ghana"}, unary_union(list(region_geoms.values())).buffer(0))], 0.004)
        rsize = write_overlay(GEO_OUT / "regions.geojson",
                              [({"id": regions[n].id, "name": n}, g) for n, g in region_geoms.items()],
                              0.005)
        dsize = write_overlay(GEO_OUT / "districts.geojson",
                              [({"id": d.id, "name": d.name, "region_id": d.region_id}, g)
                               for d, g in zip(district_objs, district_geoms)], 0.003)

        cache.delete(LOCATIONS_CACHE_KEY)
        counts = defaultdict(int)
        for p in kept:
            counts[p["kind"]] += 1
        self.stdout.write(self.style.SUCCESS(
            f"Regions: {Region.objects.count()}  Districts: {District.objects.count()}  "
            f"Towns: {Town.objects.count()}"))
        self.stdout.write("  by kind: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])))
        self.stdout.write(f"  merged duplicates: {merged}, outside Ghana skipped: {skipped_outside}, "
                          f"removed stale: {removed}, moved to Guan: {moved_guan}")
        self.stdout.write(f"  overlays: regions {rsize // 1024} KB, districts {dsize // 1024} KB")
