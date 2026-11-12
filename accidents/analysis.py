"""
Analysis page: count accidents, vehicles or casualties by any coded field, and
compare the groups by a second field or across two periods.

`build()` returns one table (labels, cells, totals) plus the same numbers shaped
for the chart. Every count runs in the database, grouped, on top of the
accidents the page filters selected.
"""
from collections import Counter
from datetime import date

from django.db.models import Case, Count, F, IntegerField, Sum, Value, When
from django.db.models.functions import ExtractHour, ExtractMonth, ExtractYear, TruncMonth

from . import codebook as cb
from .models import PassengerCasualty, PedestrianCasualty, Vehicle

ACC, VEH, PAS, PED = "accident", "vehicle", "passenger", "pedestrian"
MODELS = {VEH: Vehicle, PAS: PassengerCasualty, PED: PedestrianCasualty}

# What is counted: key -> (label, tables the rows come from).
COUNTS = {
    "accidents": ("Accidents", [ACC]),
    "killed": ("People killed", [ACC]),
    "injured": ("People injured", [ACC]),
    "vehicles": ("Vehicles and drivers", [VEH]),
    "casualties": ("Casualties (drivers, passengers, pedestrians)", [VEH, PAS, PED]),
    "passengers": ("Passenger casualties", [PAS]),
    "pedestrians": ("Pedestrian casualties", [PED]),
}
SHORT = {"vehicles": "Vehicles", "casualties": "Casualties"}     # for table headings

NOT_RECORDED = "Not recorded"
OTHERS = "All others"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
AGE_BANDS = [(5, "0-5"), (15, "6-15"), (25, "16-25"), (35, "26-35"), (45, "36-45"),
             (55, "46-55"), (65, "56-65")]
AGE_LABELS = {i: label for i, (_, label) in enumerate(AGE_BANDS, start=1)}
AGE_LABELS[len(AGE_BANDS) + 1] = "Over 65"
INJURY = {1: "Fatal", 2: "Hospitalised", 3: "Injured Not-Hospitalised", 4: "Uninjured"}

MAX_COLUMNS = 12        # table columns before the smallest are added up as "All others"
MAX_SERIES = 8          # colours on the chart
MAX_CHART_ROWS = 20     # bars on the chart when groups are places


class Var:
    """A field the numbers can be grouped by.

    `field` is an Accident field name (usable whatever is counted), or
    {table: field} for vehicle / casualty fields. Kinds: code (labels from the
    codebook), name (text, largest group first), number, bool, year, month,
    month_of_year, hour, age (bands), const (a fixed label per table).
    """

    def __init__(self, key, label, group, field, kind="code", codes=None, only=None):
        self.key, self.label, self.group = key, label, group
        self.field, self.kind, self.codes, self.only = field, kind, codes or {}, only

    def available(self, count):
        if self.only and count not in self.only:
            return False
        return isinstance(self.field, str) or all(s in self.field for s in COUNTS[count][1])

    def path(self, source):
        if isinstance(self.field, str):
            return self.field if source == ACC else f"accident__{self.field}"
        return self.field[source]

    def expr(self, source):
        path = self.path(source)
        if self.kind == "year":
            return ExtractYear(path)
        if self.kind == "month":
            return TruncMonth(path)
        if self.kind == "month_of_year":
            return ExtractMonth(path)
        if self.kind == "hour":
            return ExtractHour(path)
        if self.kind == "age":      # no age recorded matches no band and stays empty
            bands = [When(**{f"{path}__lte": top}, then=Value(i))
                     for i, (top, _) in enumerate(AGE_BANDS, start=1)]
            bands.append(When(**{f"{path}__gt": AGE_BANDS[-1][0]}, then=Value(len(AGE_BANDS) + 1)))
            return Case(*bands, output_field=IntegerField())
        return F(path)

    def text(self, key):
        if key is None:
            return NOT_RECORDED
        if self.kind == "code":
            return self.codes.get(key, f"Code {key}")
        if self.kind == "age":
            return AGE_LABELS.get(key, str(key))
        if self.kind == "month":
            return key.strftime("%b %Y")
        if self.kind == "month_of_year":
            return MONTHS[key - 1] if 1 <= key <= 12 else str(key)
        if self.kind == "hour":
            return f"{key:02d}:00-{key:02d}:59"
        if self.kind == "bool":
            return "Yes" if key else "No"
        if self.kind == "number" and self.key == "speed_limit":
            return f"{key} km/h"
        return str(key)

    @property
    def by_size(self):          # places: largest first; everything else in its own order
        return self.kind == "name"

    @property
    def upright(self):          # time, age and numbers read left to right
        return self.kind in ("year", "month", "month_of_year", "hour", "age", "number")


def _person(veh, pas="", ped=""):
    return {s: f for s, f in ((VEH, veh), (PAS, pas), (PED, ped)) if f}


VARS = [
    Var("year", "Year", "When", "accident_date", "year"),
    Var("month", "Month (each month in turn)", "When", "accident_date", "month"),
    Var("month_of_year", "Month of the year (January-December)", "When", "accident_date",
        "month_of_year"),
    Var("day_of_week", "Day of week", "When", "day_of_week", codes=cb.DAY_OF_WEEK),
    Var("hour", "Hour of day", "When", "accident_time", "hour"),

    Var("region", "Region", "Where", "region__name", "name"),
    Var("district", "District", "Where", "district__name", "name"),
    Var("police_station", "Police station", "Where", "police_station__name", "name"),
    Var("road_type", "Road type", "Where", "road_type", codes=cb.ROAD_TYPE),
    Var("landmark", "Landmark", "Where", "landmark", codes=cb.LANDMARK),

    Var("severity", "Accident severity", "The accident", "severity", codes=cb.ACCIDENT_SEVERITY),
    Var("collision_type", "Collision type", "The accident", "collision_type",
        codes=cb.COLLISION_TYPE),
    Var("num_vehicles", "Number of vehicles involved", "The accident", "num_vehicles", "number"),
    Var("hit_and_run", "Hit and run", "The accident", "hit_and_run", codes=cb.HIT_AND_RUN),
    Var("weather", "Weather", "The accident", "weather", codes=cb.WEATHER),
    Var("light_conditions", "Light conditions", "The accident", "light_conditions",
        codes=cb.LIGHT_CONDITIONS),

    Var("road_description", "Road description", "The road", "road_description",
        codes=cb.ROAD_DESCRIPTION),
    Var("road_surface_type", "Road surface type", "The road", "road_surface_type",
        codes=cb.ROAD_SURFACE_TYPE),
    Var("surface_condition", "Surface condition", "The road", "surface_condition",
        codes=cb.SURFACE_CONDITION),
    Var("surface_repair", "Surface repair", "The road", "surface_repair", codes=cb.SURFACE_REPAIR),
    Var("shoulder_type", "Shoulder type", "The road", "shoulder_type", codes=cb.SHOULDER_TYPE),
    Var("shoulder_condition", "Shoulder condition", "The road", "shoulder_condition",
        codes=cb.SHOULDER_CONDITION),
    Var("road_separation", "Road separation", "The road", "road_separation",
        codes=cb.ROAD_SEPARATION),
    Var("location_type", "Location type (junction)", "The road", "location_type",
        codes=cb.LOCATION_TYPE),
    Var("traffic_control", "Traffic control", "The road", "traffic_control",
        codes=cb.TRAFFIC_CONTROL),
    Var("roadworks", "Roadworks", "The road", "roadworks", codes=cb.ROADWORKS),
    Var("speed_limit", "Speed limit", "The road", "speed_limit", "number"),

    Var("road_user", "Road user", "The person",
        {VEH: "Drivers and riders", PAS: "Passengers", PED: "Pedestrians"}, "const",
        only=("casualties",)),
    Var("sex", "Sex", "The person", _person("driver_sex", "sex", "sex"), codes=cb.SEX),
    Var("age", "Age group", "The person", _person("driver_age", "age", "age"), "age"),
    Var("injury", "Injury", "The person", _person("driver_injury", "severity", "severity"),
        codes=INJURY),
    Var("nationality", "Nationality", "The person",
        _person("driver_nationality", ped="nationality"), codes=cb.NATIONALITY),

    Var("vehicle_type", "Vehicle type", "The vehicle", {VEH: "vehicle_type"},
        codes=cb.VEHICLE_TYPE),
    Var("ownership", "Ownership / usage", "The vehicle", {VEH: "ownership"},
        codes=cb.OWNERSHIP_USAGE),
    Var("manoeuvre", "Vehicle manoeuvre", "The vehicle", {VEH: "manoeuvre"},
        codes=cb.VEHICLE_MANOEUVRE),
    Var("damage", "Vehicle damage", "The vehicle", {VEH: "damage"}, codes=cb.VEHICLE_DAMAGE),
    Var("defects", "Vehicle defects", "The vehicle", {VEH: "defects"}, codes=cb.VEHICLE_DEFECTS),

    Var("driver_error", "Driver error", "The driver", {VEH: "driver_error"},
        codes=cb.DRIVER_ERROR),
    Var("licence_status", "Licence status", "The driver", {VEH: "licence_status"},
        codes=cb.LICENCE_STATUS),
    Var("drink_driving", "Drink / drugged driving", "The driver", {VEH: "drink_drugs"},
        codes=cb.DRINK_DRUGGED_DRIVING),
    Var("driver_education", "Driver's education", "The driver", {VEH: "driver_education"},
        codes=cb.DRIVER_EDUCATION),

    Var("position", "Position in vehicle", "The passenger", {PAS: "position"},
        codes=cb.PASSENGER_POSITION),
    Var("passenger_action", "Passenger action", "The passenger", {PAS: "action"},
        codes=cb.PASSENGER_ACTION),
    Var("helmet_belt", "Helmet / seat belt worn", "The passenger", {PAS: "helmet_belt"}, "bool"),

    Var("pedestrian_action", "Pedestrian action", "The pedestrian", {PED: "action"},
        codes=cb.PEDESTRIAN_ACTION),
    Var("pedestrian_location", "Pedestrian location", "The pedestrian", {PED: "location"},
        codes=cb.PEDESTRIAN_LOCATION),
    Var("pedestrian_drink", "Pedestrian drink / drugs", "The pedestrian", {PED: "drink_drugs"},
        codes=cb.PEDESTRIAN_DRINK_DRUGS),
]
BY_KEY = {v.key: v for v in VARS}


def variables_for(count):
    """[(group, [Var, ...]), ...] the chosen count can be grouped by, for the dropdowns."""
    groups = {}
    for v in VARS:
        if v.available(count):
            groups.setdefault(v.group, []).append(v)
    return list(groups.items())


def parse_date(text):
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def choices(params):
    """The page's choices from the query string, with anything invalid set to a default."""
    count = params.get("count") if params.get("count") in COUNTS else "accidents"
    row = BY_KEY.get(params.get("rows") or "")
    if not row or not row.available(count):
        row = BY_KEY["region"]
    compare = params.get("compare") or ""
    col = BY_KEY.get(compare)
    if compare != "period" and (not col or col is row or not col.available(count)):
        compare, col = "", None
    show = params.get("show") if col and params.get("show") in ("row", "col") else "n"
    return {"count": count, "row": row, "compare": compare, "col": col, "show": show,
            "b_from": parse_date(params.get("b_from")), "b_to": parse_date(params.get("b_to")),
            "a_from": parse_date(params.get("date_from")), "a_to": parse_date(params.get("date_to"))}


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------
def _cells(count, accidents, row, col=None):
    """{(row key, column key): number} for the chosen count."""
    out = Counter()
    for source in COUNTS[count][1]:
        if source == ACC:
            qs = accidents
        else:
            qs = MODELS[source].objects.filter(accident__in=accidents.order_by())
            if count == "casualties" and source == VEH:
                qs = qs.filter(driver_injury__in=[1, 2, 3])      # injured drivers only
        fixed, grouped = {}, {}
        for name, var in (("row_key", row), ("col_key", col)):
            if var is None:
                fixed[name] = None
            elif var.kind == "const":
                fixed[name] = var.field[source]
            else:
                grouped[name] = var.expr(source)
        total = Sum(count) if count in ("killed", "injured") else Count("pk")
        if grouped:
            records = qs.order_by().annotate(**grouped).values(*grouped).annotate(n=total)
        else:
            records = [qs.order_by().aggregate(n=total)]
        for rec in records:
            key = tuple(None if k == "" else k
                        for k in (rec.get("row_key", fixed.get("row_key")),
                                  rec.get("col_key", fixed.get("col_key"))))
            out[key] += rec["n"] or 0
    return out


def _ordered(var, totals):
    """Keys in display order: by size for places, otherwise natural; not recorded last."""
    keys = [k for k in totals if k is not None]
    if var.by_size:
        keys.sort(key=lambda k: (-totals[k], str(k).lower()))
    else:
        keys.sort()
    return keys + ([None] if None in totals else [])


def _num(n):
    return {"t": f"{n:,}", "v": n}


def _pct(part, whole):
    if not whole:
        return {"t": "-", "v": ""}
    p = 100 * part / whole
    return {"t": f"{p:.1f}%", "v": round(p, 1)}


def _change(a, b):
    diff = b - a
    return {"t": f"{diff:+,}" if diff else "0", "v": diff,
            "cls": "up" if diff > 0 else "down" if diff < 0 else ""}


def _pct_change(a, b):
    if not a:
        return {"t": "-", "v": ""}
    p = 100 * (b - a) / a
    return {"t": f"{p:+.1f}%" if round(p, 1) else "0.0%", "v": round(p, 1),
            "cls": "up" if p > 0 else "down" if p < 0 else ""}


def _span(start, end):
    return f"{start.day} {start:%b %Y} to {end.day} {end:%b %Y}"


def build(ch, accidents, accidents_b=None):
    """The table and chart for choices `ch`. `accidents_b` is the second period's
    accidents when two periods are compared."""
    count, row, col = ch["count"], ch["row"], ch["col"]
    count_label = SHORT.get(count, COUNTS[count][0])
    out = {"count_label": count_label, "row_label": row.label, "note": ""}

    if ch["compare"] == "period":
        a, b = _cells(count, accidents, row), _cells(count, accidents_b, row)
        a = Counter({k[0]: n for k, n in a.items()})
        b = Counter({k[0]: n for k, n in b.items()})
        keys = _ordered(row, {k: a[k] + b[k] for k in set(a) | set(b)})
        label_a, label_b = _span(ch["a_from"], ch["a_to"]), _span(ch["b_from"], ch["b_to"])
        out.update(
            title=f"{count_label} by {row.label.lower()}: two periods compared",
            columns=[label_a, label_b, "Change", "% change"],
            rows=[{"label": row.text(k),
                   "cells": [_num(a[k]), _num(b[k]), _change(a[k], b[k]), _pct_change(a[k], b[k])]}
                  for k in keys],
        )
        ta, tb = sum(a.values()), sum(b.values())
        out["total"] = [_num(ta), _num(tb), _change(ta, tb), _pct_change(ta, tb)]
        series = [{"name": label_a, "data": [a[k] for k in keys]},
                  {"name": label_b, "data": [b[k] for k in keys]}]
        out["chart"] = _chart(row, keys, series, stacked=False)
        return out

    cells = _cells(count, accidents, row, col)
    row_totals, col_totals = Counter(), Counter()
    for (r, c), n in cells.items():
        row_totals[r] += n
        col_totals[c] += n
    grand = sum(row_totals.values())
    rows = _ordered(row, row_totals)

    if col is None:
        out.update(
            title=f"{count_label} by {row.label.lower()}",
            columns=[count_label, "% of total"],
            rows=[{"label": row.text(k), "cells": [_num(row_totals[k]), _pct(row_totals[k], grand)]}
                  for k in rows],
            total=[_num(grand), _pct(grand, grand)],
        )
        out["chart"] = _chart(row, rows, [{"name": count_label,
                                           "data": [row_totals[k] for k in rows]}], stacked=False)
        return out

    # Two fields: one column per group of the second field, smallest folded together.
    cols = _ordered(col, col_totals)
    cols, folded = _fold(cols, col_totals, MAX_COLUMNS)
    if folded:
        out["note"] = (f"{col.label} has {len(cols) - 1 + len(folded)} groups. The "
                       f"{len(cols) - 1} largest are shown; the rest are added up as "
                       f"\"{OTHERS}\".")

    def value(r, c):
        if c is OTHERS:
            return sum(cells[(r, x)] for x in folded)
        return cells[(r, c)]

    def col_total(c):
        return sum(col_totals[x] for x in folded) if c is OTHERS else col_totals[c]

    def col_text(c):
        return OTHERS if c is OTHERS else col.text(c)

    show = ch["show"]
    table = []
    for r in rows:
        if show == "row":
            line = [_pct(value(r, c), row_totals[r]) for c in cols] + [_num(row_totals[r])]
        elif show == "col":
            line = [_pct(value(r, c), col_total(c)) for c in cols] + [_pct(row_totals[r], grand)]
        else:
            line = [_num(value(r, c)) for c in cols] + [_num(row_totals[r])]
        table.append({"label": row.text(r), "cells": line})
    if show == "row":
        total = [_pct(col_total(c), grand) for c in cols] + [_num(grand)]
    else:
        total = [_num(col_total(c)) for c in cols] + [_num(grand)]
    out.update(
        title=f"{count_label} by {row.label.lower()} and {col.label.lower()}",
        col_label=col.label,
        columns=[col_text(c) for c in cols] + [f"Total ({count_label.lower()})" if show == "row"
                                               else "% of total" if show == "col" else "Total"],
        rows=table, total=total,
        total_label=f"Total ({count_label.lower()})" if show == "col" else "Total",
        show=show,
    )

    # Chart: at most MAX_SERIES colours.
    chart_cols, chart_folded = _fold(cols, {c: col_total(c) for c in cols}, MAX_SERIES)
    series = []
    for c in chart_cols:
        members = chart_folded if (c is OTHERS and chart_folded) else [c]
        data = []
        for r in rows:
            n = sum(value(r, m) for m in members)
            if show == "row":
                n = round(100 * n / row_totals[r], 1) if row_totals[r] else 0
            elif show == "col":
                whole = sum(col_total(m) for m in members)
                n = round(100 * n / whole, 1) if whole else 0
            data.append(n)
        series.append({"name": col_text(c), "data": data})
    out["chart"] = _chart(row, rows, series, stacked=show != "col", percent=show != "n")
    return out


def _fold(keys, totals, limit):
    """Keep the `limit - 1` largest keys (in their order) plus OTHERS for the rest."""
    if len(keys) <= limit:
        return keys, []
    plain = [k for k in keys if k is not OTHERS]
    keep = set(sorted(plain, key=lambda k: -totals[k])[:limit - 1])
    folded = [k for k in keys if k not in keep]
    return [k for k in keys if k in keep] + [OTHERS], folded


def _chart(row, keys, series, stacked, percent=False):
    labels = [row.text(k) for k in keys]
    cut = row.by_size and len(labels) > MAX_CHART_ROWS
    if cut:
        labels = labels[:MAX_CHART_ROWS]
        series = [{"name": s["name"], "data": s["data"][:MAX_CHART_ROWS]} for s in series]
    return {"labels": labels, "series": series, "stacked": stacked and len(series) > 1,
            "percent": percent, "horizontal": not row.upright,
            "cut": MAX_CHART_ROWS if cut else 0,
            "empty": not any(n for s in series for n in s["data"])}
