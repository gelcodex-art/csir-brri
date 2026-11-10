"""Server-side geography helpers (district lookup by GPS point, nearest town)."""
import math
from pathlib import Path

from django.conf import settings
from shapely.geometry import Point
from shapely.strtree import STRtree

from .models import District, Town

SRC = Path(settings.BASE_DIR) / "data" / "sources"


def km(lat1, lng1, lat2, lng2):
    dlat = (lat2 - lat1) * 111.0
    dlng = (lng2 - lng1) * 111.0 * math.cos(math.radians(lat1))
    return math.hypot(dlat, dlng)


class Locator:
    """Find the District (MMDA) containing a point, and the nearest named town.

    Uses the same boundary file and name clean-up as load_ghana_locations, so
    results match the districts stored in the database.
    """

    def __init__(self):
        from .management.commands.load_ghana_locations import adm2_features  # same boundaries

        by_name = {d.name: d for d in District.objects.select_related("region")}
        self.geoms, self.districts = [], []
        for name, g in adm2_features():
            d = by_name.get(name)
            if d is None:
                continue
            self.geoms.append(g)
            self.districts.append(d)
        self.tree = STRtree(self.geoms)
        self.towns = list(Town.objects.exclude(latitude=None).values_list(
            "id", "district_id", "name", "kind", "latitude", "longitude"))
        self.town_district = {}

    def district_at(self, lat, lng, tolerance_deg=0.03):
        p = Point(lng, lat)
        hits = self.tree.query(p, predicate="intersects")
        if len(hits):
            d = self.districts[hits[0]]
        else:
            i = self.tree.nearest(p)
            d = self.districts[i] if self.geoms[i].distance(p) < tolerance_deg else None
        # Guan District (2022) has no boundary yet: it is the part of the old
        # Hohoe polygon whose towns were moved to Guan by load_ghana_locations.
        if d is not None and d.name == "Hohoe Municipal":
            near = self.nearest_town(lat, lng, max_km=3)
            if near and near[1] != d.id:
                d = District.objects.get(pk=near[1])
        return d

    def nearest_town(self, lat, lng, max_km=5.0, kinds=None):
        """(town_name, district_id, distance_km) of the closest town, or None."""
        best = None
        for _id, did, name, kind, tlat, tlng in self.towns:
            if kinds and kind not in kinds:
                continue
            if abs(float(tlat) - lat) > 0.1 or abs(float(tlng) - lng) > 0.1:
                continue
            d = km(lat, lng, float(tlat), float(tlng))
            if d <= max_km and (best is None or d < best[2]):
                best = (name, did, d)
        return best
