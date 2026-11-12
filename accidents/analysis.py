"""
Analysis page. Two kinds of analysis, the ones every statistics package
(SPSS, Stata, R) starts with:

  counts    a frequency table of one field (count, %, % of recorded, running %),
            a cross-table of two fields with a chi-square test, or the same
            field in two periods with the change tested;
  summary   a number (people killed per accident, driver age...) summarised
            by group: N, mean, median, standard deviation, lowest, highest,
            with a one-way analysis of variance.

`build()` returns one table (labels, cells, totals), the test results in plain
words, and the same numbers shaped for the chart. Counts run in the database,
grouped, on top of the accidents the page filters selected.
"""
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from urllib.parse import urlencode

from django.db.models import Case, Count, F, IntegerField, Sum, Value, When
from django.db.models.functions import ExtractHour, ExtractMonth, ExtractYear, TruncMonth

from . import codebook as cb
from . import stats
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
SUMS = ("killed", "injured")        # added up from the report, not rows that are counted

# Numbers that can be averaged: key -> (label, the count whose rows carry it, {table: field}).
NUMS = {
    "killed": ("People killed per accident", "accidents", {ACC: "killed"}),
    "injured": ("People injured per accident", "accidents", {ACC: "injured"}),
    "num_vehicles": ("Vehicles involved per accident", "accidents", {ACC: "num_vehicles"}),
    "speed_limit": ("Speed limit (km/h)", "accidents", {ACC: "speed_limit"}),
    "road_width": ("Road width (m)", "accidents", {ACC: "road_width_m"}),
    "driver_age": ("Age of drivers and riders", "vehicles", {VEH: "driver_age"}),
    "casualty_age": ("Age of casualties (all road users)", "casualties",
                     {VEH: "driver_age", PAS: "age", PED: "age"}),
    "passenger_age": ("Age of passenger casualties", "passengers", {PAS: "age"}),
    "pedestrian_age": ("Age of pedestrian casualties", "pedestrians", {PED: "age"}),
}

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
TREND_KINDS = ("year", "month")     # split by these, the chart is a line over time


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


# Ready-made questions: one click sets every choice on the page.
ANALYSIS_KEYS = ("mode", "num", "count", "rows", "compare", "show", "sort", "b_from", "b_to")
QUESTIONS = [
    ("When", [
        ("At what time of day do accidents happen?", {"rows": "hour"}),
        ("On which days of the week?", {"rows": "day_of_week"}),
        ("In which months of the year?", {"rows": "month_of_year"}),
        ("Are accidents going up or down over the years?", {"rows": "year"}),
        ("Month by month: are accidents rising or falling?", {"rows": "month"}),
        ("Are deaths rising or falling?", {"count": "killed", "rows": "month"}),
        ("Is each level of severity rising or falling?", {"rows": "month", "compare": "severity"}),
        ("How does this year compare with last year?", {"rows": "severity", "compare": "period"}),
    ]),
    ("Where", [
        ("Which regions have the most accidents?", {"rows": "region"}),
        ("Which districts have the most deaths?", {"count": "killed", "rows": "district"}),
        ("On what type of road?", {"rows": "road_type"}),
    ]),
    ("Who", [
        ("Who gets hurt: drivers, passengers or pedestrians?",
         {"count": "casualties", "rows": "road_user", "compare": "injury", "show": "row"}),
        ("Which age groups are hurt most?", {"count": "casualties", "rows": "age"}),
        ("Are more men or women hurt?", {"count": "casualties", "rows": "sex"}),
        ("How old are the drivers, by type of vehicle?",
         {"mode": "summary", "num": "driver_age", "rows": "vehicle_type"}),
    ]),
    ("What and why", [
        ("Which kinds of collision are the deadliest?",
         {"rows": "collision_type", "compare": "severity", "show": "row"}),
        ("Are accidents in the dark more serious?",
         {"rows": "light_conditions", "compare": "severity", "show": "row"}),
        ("Does the weather change how serious accidents are?",
         {"rows": "weather", "compare": "severity", "show": "row"}),
        ("Which vehicles are involved most?",
         {"count": "vehicles", "rows": "vehicle_type", "sort": "size"}),
        ("What mistakes do drivers make?",
         {"count": "vehicles", "rows": "driver_error", "sort": "size"}),
        ("What were pedestrians doing when they were hit?",
         {"count": "pedestrians", "rows": "pedestrian_action", "sort": "size"}),
    ]),
]


def _year_before(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:              # 29 February
        return d.replace(year=d.year - 1, day=28)


def questions(params, today=None):
    """[(group, [{text, url, active}, ...]), ...]. A question keeps the page's filters
    (region, severity...) and replaces only the analysis choices."""
    today = today or date.today()
    skip = ANALYSIS_KEYS + ("download", "page")
    out = []
    for group, items in QUESTIONS:
        links = []
        for text, q in items:
            q, drop = dict(q), skip
            if q.get("compare") == "period":    # 1 January to today, this year and last
                start = date(today.year, 1, 1)
                q.update(date_from=f"{_year_before(start):%d/%m/%Y}",
                         date_to=f"{_year_before(today):%d/%m/%Y}",
                         b_from=f"{start:%d/%m/%Y}", b_to=f"{today:%d/%m/%Y}")
                drop = skip + ("date_from", "date_to")
            keep = [(k, v) for k in params if k not in drop for v in params.getlist(k) if v]
            active = (all(params.get(k, "") == v for k, v in q.items())
                      and not any(params.get(k) for k in ANALYSIS_KEYS if k not in q))
            links.append({"text": text, "url": "?" + urlencode(keep + list(q.items())),
                          "active": active})
        out.append((group, links))
    return out


def _share(part, whole):
    return f"{100 * part / whole:.1f}%" if whole else "-"


def _and(names):
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def variables_for(count):
    """[(group, [Var, ...]), ...] the chosen count can be grouped by, for the dropdowns."""
    groups = {}
    for v in VARS:
        if v.available(count):
            groups.setdefault(v.group, []).append(v)
    return list(groups.items())


def parse_date(text):
    """A date typed as day/month/year (31/12/2025) or as yyyy-mm-dd; None if neither."""
    text = (text or "").strip()
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})", text)
    try:
        if m:
            day, month, year = (int(x) for x in m.groups())
            return date(year + 2000 if year < 100 else year, month, day)
        return date.fromisoformat(text)
    except ValueError:
        return None


def choices(params):
    """The page's choices from the query string, with anything invalid set to a default."""
    mode = "summary" if params.get("mode") == "summary" else "counts"
    num = params.get("num") if params.get("num") in NUMS else "killed"
    if mode == "summary":
        count = NUMS[num][1]
    else:
        count = params.get("count") if params.get("count") in COUNTS else "accidents"
    row = BY_KEY.get(params.get("rows") or "")
    if not row or not row.available(count):
        row = BY_KEY["region"]
    compare = params.get("compare") or ""
    col = BY_KEY.get(compare)
    if mode == "summary" or (compare != "period"
                             and (not col or col is row or not col.available(count))):
        compare, col = "", None
    show = params.get("show") if col and params.get("show") in ("row", "col", "total") else "n"
    return {"mode": mode, "num": num, "count": count, "row": row, "compare": compare,
            "col": col, "show": show, "by_size": params.get("sort") == "size",
            "b_from": parse_date(params.get("b_from")), "b_to": parse_date(params.get("b_to")),
            "a_from": parse_date(params.get("date_from")), "a_to": parse_date(params.get("date_to"))}


# ---------------------------------------------------------------------------
# Reading the numbers
# ---------------------------------------------------------------------------
def _sources(count, accidents):
    """(table, rows) the count is made of, for the accidents the filters chose."""
    for source in COUNTS[count][1]:
        if source == ACC:
            yield source, accidents.order_by()
            continue
        qs = MODELS[source].objects.filter(accident__in=accidents.order_by())
        if count == "casualties" and source == VEH:
            qs = qs.filter(driver_injury__in=[1, 2, 3])      # injured drivers only
        yield source, qs


def _cells(count, accidents, row, col=None):
    """{(row key, column key): number} for the chosen count."""
    out = Counter()
    for source, qs in _sources(count, accidents):
        fixed, grouped = {}, {}
        for name, var in (("row_key", row), ("col_key", col)):
            if var is None:
                fixed[name] = None
            elif var.kind == "const":
                fixed[name] = var.field[source]
            else:
                grouped[name] = var.expr(source)
        total = Sum(count) if count in SUMS else Count("pk")
        if grouped:
            records = qs.annotate(**grouped).values(*grouped).annotate(n=total)
        else:
            records = [qs.aggregate(n=total)]
        for rec in records:
            key = tuple(None if k == "" else k
                        for k in (rec.get("row_key", fixed.get("row_key")),
                                  rec.get("col_key", fixed.get("col_key"))))
            out[key] += rec["n"] or 0
    return out


def _values(num, accidents, row):
    """{row key: [every recorded value]} of a number, e.g. the ages of drivers by region."""
    _, count, fields = NUMS[num]
    out = defaultdict(list)
    for source, qs in _sources(count, accidents):
        field = fields[source]
        qs = qs.exclude(**{field: None})
        if row.kind == "const":
            pairs = ((row.field[source], v) for v in qs.values_list(field, flat=True))
        else:
            pairs = qs.annotate(row_key=row.expr(source)).values_list("row_key", field)
        for key, value in pairs:
            out[None if key == "" else key].append(float(value))
    return out


def _ordered(var, totals, by_size=False):
    """Keys in display order: by size for places (or when asked), otherwise natural;
    not recorded last."""
    keys = [k for k in totals if k is not None]
    if by_size or var.by_size:
        keys.sort(key=lambda k: (-totals[k], str(k).lower()))
    else:
        keys.sort()
    return keys + ([None] if None in totals else [])


def _num(n):
    return {"t": f"{n:,}", "v": n}


def _dec(x, places=2):
    if x is None:
        return {"t": "-", "v": ""}
    return {"t": f"{x:,.{places}f}", "v": round(x, places)}


def _pct(part, whole):
    if not whole:
        return {"t": "-", "v": ""}
    p = 100 * part / whole
    return {"t": f"{p:.1f}%", "v": round(p, 1)}


def _blank():
    return {"t": "", "v": ""}


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
    return f"{start:%d/%m/%Y} to {end:%d/%m/%Y}"


def build(ch, accidents, accidents_b=None):
    """The table, tests and chart for choices `ch`. `accidents_b` is the second
    period's accidents when two periods are compared."""
    if ch["mode"] == "summary":
        return _summary(ch, accidents)
    count, row = ch["count"], ch["row"]
    out = {"count_label": SHORT.get(count, COUNTS[count][0]), "row_label": row.label,
           "note": "", "tests": []}
    if ch["compare"] == "period":
        return _periods(ch, out, accidents, accidents_b)
    cells = _cells(count, accidents, row, ch["col"])
    if ch["col"] is None:
        return _one_way(ch, out, cells)
    return _two_way(ch, out, cells)


# ---------------------------------------------------------------------------
# One field: frequency table
# ---------------------------------------------------------------------------
def _one_way(ch, out, cells):
    row, count_label = ch["row"], out["count_label"]
    totals = Counter({r: n for (r, _), n in cells.items()})
    keys = _ordered(row, totals, ch["by_size"])
    if not ch["by_size"]:
        keys = _timeline(row, keys)
    grand = sum(totals.values())
    valid = grand - totals.get(None, 0)
    with_valid = None in totals                 # some reports have the field empty
    with_running = row.upright and not ch["by_size"]

    columns = [count_label, "% of total"]
    if with_valid:
        columns.append("% of recorded")
    if with_running:
        columns.append("Running %")
    rows, running = [], 0
    for k in keys:
        line = [_num(totals[k]), _pct(totals[k], grand)]
        if with_valid:
            line.append(_blank() if k is None else _pct(totals[k], valid))
        if with_running:
            running += 0 if k is None else totals[k]
            line.append(_blank() if k is None else _pct(running, valid))
        rows.append({"label": row.text(k), "cells": line})
    total = [_num(grand), _pct(grand, grand)]
    if with_valid:
        total.append(_pct(valid, valid))
    if with_running:
        total.append(_blank())
    out.update(title=f"{count_label} by {row.label.lower()}", columns=columns, rows=rows,
               total=total)
    units = count_label.lower()
    guide = [("% of total", f"Each group's share of all the {units} counted.")]
    if with_valid:
        guide.append(("% of recorded", "The share after leaving out the reports where this "
                      "field was left empty. Use it when many reports have the field empty."))
    if with_running:
        guide.append(("Running %", "The groups added up from the top. Where it passes 50%, "
                      "half of everything has happened by that point."))
    out["guide"] = guide

    found = []
    real = sorted((k for k in keys if k is not None and totals[k] > 0), key=lambda k: -totals[k])
    if grand:
        found.append(f"{grand:,} {units} in this selection.")
    if len(real) >= 2:
        top = real[0]
        found.append(f"The largest group is {row.text(top)} with {totals[top]:,} "
                     f"({_share(totals[top], grand)} of the total).")
        if len(real) >= 5:
            three = sum(totals[k] for k in real[:3])
            found.append(f"The three largest ({_and(row.text(k) for k in real[:3])}) together "
                         f"make up {_share(three, grand)} of the total.")
        if len(real) >= 3:
            found.append(f"The smallest is {row.text(real[-1])} with {totals[real[-1]]:,}.")
    if grand and totals.get(None):
        found.append(f"{row.label} was left empty for {totals[None]:,} "
                     f"({_share(totals[None], grand)}).")
    out["findings"] = found
    series = [{"name": count_label, "data": [totals[k] for k in keys]}]
    trend = _trend(ch, keys, totals, units) if trending(ch) else None
    if trend:
        test, fitted, found, guide, partial_at = trend
        out["tests"].append(test)
        out["findings"] = found
        out["guide"] += guide
        series.append({"name": "Trend", "data": fitted, "trend": True})
    out["chart"] = _chart(ch, keys, series, stacked=False)
    if trend:
        out["chart"]["partial"] = partial_at
        if partial_at:
            out["guide"].append(("Dotted end of the line", "A dashed piece of the line and a "
                                 "hollow dot mark a period the dates only partly cover, or one "
                                 "that is not over yet. Its number will look low."))
    return out


# ---------------------------------------------------------------------------
# Two fields: cross-table with a chi-square test
# ---------------------------------------------------------------------------
def _two_way(ch, out, cells):
    count, row, col, show = ch["count"], ch["row"], ch["col"], ch["show"]
    count_label = out["count_label"]
    row_totals, col_totals = Counter(), Counter()
    for (r, c), n in cells.items():
        row_totals[r] += n
        col_totals[c] += n
    grand = sum(row_totals.values())
    rows = _ordered(row, row_totals, ch["by_size"])
    if not ch["by_size"]:
        rows = _timeline(row, rows)

    # One column per group of the second field, the smallest folded together.
    cols, folded = _fold(_ordered(col, col_totals), col_totals, MAX_COLUMNS)
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

    units = count_label.lower()
    found = [f"{grand:,} {units} in this selection."] if grand else []
    pairs = [(value(r, c), r, c) for r in rows for c in cols if r is not None and c is not None]
    if len(pairs) > 1 and max(pairs, key=lambda x: x[0])[0] > 0:
        n, r, c = max(pairs, key=lambda x: x[0])
        found.append(f"The most common combination is {row.text(r)} with {col_text(c)}: {n:,}.")
    marks = {}
    if count not in SUMS:
        test, marks, more = _association(row, col, rows, cols, value, units, col_text)
        if test:
            out["tests"].append(test)
            out["marks"] = bool(marks)
            found += more
    out["findings"] = found
    how = {
        "n": ("Numbers", "Each cell is how many fall in that row's group and that column's "
              "group at once. To compare groups of different sizes fairly, change \"Show as\" "
              "to \"% of each row\"."),
        "row": ("% of each row", "Every row adds up to 100%. Read across a row to see how that "
                "group splits; read down a column to compare the groups with each other."),
        "col": ("% of each column", "Every column adds up to 100%. Read down a column to see "
                "which groups it is made of."),
        "total": ("% of the whole table", "All the cells together add up to 100%."),
    }
    guide = [how[show]]
    if out["tests"]:
        guide += [
            ("Linked or not", "The test asks: if the two fields had nothing to do with each "
             "other, how often would a pattern this strong turn up by chance? That chance is "
             "p. Below 0.05 (5 times in 100) is the usual line for saying the link is real."),
            ("Strength of the link", "Cram\u00e9r's V runs from 0 (no link) to 1 (one field "
             "fully decides the other). A link can be real and still weak."),
        ]
    out["guide"] = guide

    table = []
    for r in rows:
        if show == "row":
            line = [_pct(value(r, c), row_totals[r]) for c in cols] + [_num(row_totals[r])]
        elif show == "col":
            line = [_pct(value(r, c), col_total(c)) for c in cols] + [_pct(row_totals[r], grand)]
        elif show == "total":
            line = [_pct(value(r, c), grand) for c in cols] + [_pct(row_totals[r], grand)]
        else:
            line = [_num(value(r, c)) for c in cols] + [_num(row_totals[r])]
        for c, cell in zip(cols, line):
            if (r, c) in marks:
                cell["cls"] = marks[(r, c)]
        table.append({"label": row.text(r), "cells": line})
    if show in ("row", "total"):
        total = [_pct(col_total(c), grand) for c in cols]
        total.append(_num(grand) if show == "row" else _pct(grand, grand))
    else:
        total = [_num(col_total(c)) for c in cols] + [_num(grand)]
    number_total = f"Total ({count_label.lower()})"
    out.update(
        title=f"{count_label} by {row.label.lower()} and {col.label.lower()}",
        col_label=col.label,
        columns=[col_text(c) for c in cols] + [number_total if show == "row" else
                                               "Total" if show == "n" else "% of total"],
        rows=table, total=total,
        total_label=number_total if show == "col" else "Total",
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
            elif show == "total":
                n = round(100 * n / grand, 1) if grand else 0
            data.append(n)
        series.append({"name": col_text(c), "data": data})
    out["chart"] = _chart(ch, rows, series, stacked=show != "col", percent=show != "n")
    return out


def _strength(v):
    return "very weak" if v < 0.1 else "weak" if v < 0.3 else "moderate" if v < 0.5 else "strong"


def _association(row, col, rows, cols, value, units, col_text):
    """Chi-square test of whether two fields are related, on the table as shown but
    without "Not recorded" (as SPSS, Stata and R do). Returns the result in words and
    {(row, column): "hi" | "lo"} for cells well above / below what no link would give."""
    rows = [r for r in rows if r is not None]
    cols = [c for c in cols if c is not None]
    rows = [r for r in rows if sum(value(r, c) for c in cols) > 0]
    cols = [c for c in cols if sum(value(r, c) for r in rows) > 0]
    if len(rows) < 2 or len(cols) < 2:
        return None, {}, []
    table = [[value(r, c) for c in cols] for r in rows]
    row_sum = [sum(line) for line in table]
    col_sum = [sum(line) for line in zip(*table)]
    n = sum(row_sum)
    chi2, small, marks, standing_out = 0.0, 0, {}, []
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            expected = row_sum[i] * col_sum[j] / n
            chi2 += (table[i][j] - expected) ** 2 / expected
            small += expected < 5
            spread = expected * (1 - row_sum[i] / n) * (1 - col_sum[j] / n)
            residual = (table[i][j] - expected) / math.sqrt(spread) if spread > 0 else 0
            if abs(residual) >= 1.96:
                marks[(r, c)] = "hi" if residual > 0 else "lo"
                standing_out.append((abs(residual), residual > 0, -i, -j))
    df = (len(rows) - 1) * (len(cols) - 1)
    p = stats.chi2_p(chi2, df)
    v = math.sqrt(chi2 / (n * min(len(rows) - 1, len(cols) - 1)))
    a, b = row.label, col.label.lower()
    found = []
    if p < 0.05:
        headline = (f"{a} and {b} are related: a pattern this strong would rarely appear by "
                    f"chance ({stats.p_text(p)}). The link is {_strength(v)}.")
        seen = set()
        for _, _, i, j in sorted(standing_out, reverse=True):   # ties: the higher cell
            i, j = -i, -j
            if i in seen or not row_sum[i]:
                continue
            here, overall = 100 * table[i][j] / row_sum[i], 100 * col_sum[j] / n
            if abs(here - overall) < 2:         # real but too small to matter to a reader
                continue
            seen.add(i)
            found.append(f"{row.text(rows[i])}: {here:.1f}% are {col_text(cols[j])}, "
                         f"{'higher' if here > overall else 'lower'} than the {overall:.1f}% "
                         "across all groups.")
            if len(seen) == 3:
                break
    else:
        headline = (f"No clear link between {a.lower()} and {b}: differences of this size "
                    f"could easily be chance ({stats.p_text(p)}).")
        marks = {}
        found.append(f"The split by {b} is much the same in every {a.lower()} group.")
    test = {
        "name": "Chi-square test", "question": "Are the two fields linked?",
        "headline": headline,
        "detail": (f"Chi-square = {chi2:,.2f}, degrees of freedom = {df}, {stats.p_text(p)}, "
                   f"Cramér's V = {v:.2f}. Based on {n:,} {units} with both fields recorded."),
        "warning": "",
    }
    cells = len(rows) * len(cols)
    if small / cells > 0.2:
        test["warning"] = (f"{small} of the {cells} cells expect fewer than 5 {units}, so read "
                           "this test with care. It becomes reliable with more reports, or "
                           "with a field that has fewer groups.")
    return test, marks, found


# ---------------------------------------------------------------------------
# One field in two periods
# ---------------------------------------------------------------------------
def _periods(ch, out, accidents, accidents_b):
    count, row, count_label = ch["count"], ch["row"], out["count_label"]
    a = Counter({k[0]: n for k, n in _cells(count, accidents, row).items()})
    b = Counter({k[0]: n for k, n in _cells(count, accidents_b, row).items()})
    keys = _ordered(row, {k: a[k] + b[k] for k in set(a) | set(b)}, ch["by_size"])
    days_a = (ch["a_to"] - ch["a_from"]).days + 1
    days_b = (ch["b_to"] - ch["b_from"]).days + 1
    tested = count not in SUMS

    def real(x, y):
        """Is the change more than chance? Compares the two counts allowing for the
        lengths of the periods."""
        n = x + y
        if n < 10:
            return {"t": "Too few to tell", "v": "Too few to tell"}
        share = days_b / (days_a + days_b)
        z = (y - n * share) / math.sqrt(n * share * (1 - share))
        word = "Yes" if stats.normal_p(z) < 0.05 else "No"
        return {"t": word, "v": word}

    def line(x, y):
        cells = [_num(x), _num(y), _change(x, y), _pct_change(x, y)]
        return cells + [real(x, y)] if tested else cells

    label_a, label_b = _span(ch["a_from"], ch["a_to"]), _span(ch["b_from"], ch["b_to"])
    out.update(
        title=f"{count_label} by {row.label.lower()}: two periods compared",
        columns=[label_a, label_b, "Change", "% change"] + (["More than chance?"] if tested else []),
        rows=[{"label": row.text(k), "cells": line(a[k], b[k])} for k in keys],
        total=line(sum(a.values()), sum(b.values())),
    )
    units = count_label.lower()
    total_a, total_b = sum(a.values()), sum(b.values())
    found = [f"First period: {total_a:,} {units}. Second period: {total_b:,}."]
    if total_a and total_b != total_a:
        change = f"{abs(100 * (total_b - total_a) / total_a):.1f}%"
        sure = real(total_a, total_b)["t"] if tested else ""
        found.append(f"That is {'up' if total_b > total_a else 'down'} {change}"
                     + (", more than chance alone would give." if sure == "Yes" else
                        ", but a change of this size could be chance." if sure == "No" else "."))
    moved = sorted(((b[k] - a[k], i) for i, k in enumerate(keys) if k is not None))
    if moved and moved[-1][0] > 0:
        k = keys[moved[-1][1]]
        found.append(f"Biggest rise: {row.text(k)} ({a[k]:,} to {b[k]:,}).")
    if moved and moved[0][0] < 0:
        k = keys[moved[0][1]]
        found.append(f"Biggest fall: {row.text(k)} ({a[k]:,} to {b[k]:,}).")
    out["findings"] = found
    guide = [("Change", "The second period minus the first. A plus sign means more than before."),
             ("% change", "The change as a share of the first period's number.")]
    if tested:
        guide.append(("More than chance?", "Numbers go up and down a little by themselves. "
                      "\"Yes\" means a change this large would happen by chance fewer than 5 "
                      "times in 100, so something probably did change. \"No\" means it could "
                      "just be the usual ups and downs."))
    out["guide"] = guide
    notes = []
    if days_a != days_b:
        notes.append(f"The periods are not the same length ({days_a:,} and {days_b:,} days). "
                     "Change and % change compare the plain numbers"
                     + ("; the chance test allows for the lengths." if tested else "."))
    out["note"] = " ".join(notes)
    series = [{"name": label_a, "data": [a[k] for k in keys]},
              {"name": label_b, "data": [b[k] for k in keys]}]
    out["chart"] = _chart(ch, keys, series, stacked=False)
    return out


# ---------------------------------------------------------------------------
# A number summarised by group
# ---------------------------------------------------------------------------
def _describe(values):
    n = len(values)
    return [_num(n), _dec(statistics.fmean(values) if n else None),
            _dec(statistics.median(values) if n else None, 1),
            _dec(statistics.stdev(values) if n > 1 else None),
            _dec(min(values) if n else None, 1), _dec(max(values) if n else None, 1)]


def _summary(ch, accidents):
    row, label = ch["row"], NUMS[ch["num"]][0]
    groups = _values(ch["num"], accidents, row)
    means = {k: statistics.fmean(v) for k, v in groups.items()}
    keys = _ordered(row, means, ch["by_size"])
    everything = [x for v in groups.values() for x in v]
    out = {
        "count_label": label, "row_label": row.label, "tests": [],
        "title": f"{label} by {row.label.lower()}",
        "columns": ["Number recorded", "Mean", "Median", "Std. deviation", "Lowest", "Highest"],
        "rows": [{"label": row.text(k), "cells": _describe(groups[k])} for k in keys],
        "total": _describe(everything), "total_label": "All together",
        "note": "",
        "guide": [
            ("Number recorded", "How many reports have this number filled in."),
            ("Mean", "The ordinary average: everything added up, divided by how many."),
            ("Median", "The middle value: half are below it and half above. A few very large "
             "values pull the mean up but hardly move the median."),
            ("Std. deviation", "How spread out the values are. Small means most are close to "
             "the mean; large means they vary a lot."),
        ],
    }
    test = _anova([groups[k] for k in keys if k is not None], row.label.lower())
    if test:
        out["tests"].append(test)
        out["guide"].append(
            ("Do the averages differ?", "The test asks how often averages this far apart would "
             "turn up by chance if the groups were really the same. That chance is p. Below "
             "0.05 (5 times in 100) is the usual line for saying the difference is real."))
    found = []
    if everything:
        found.append(f"Across all {len(everything):,} recorded values the mean is "
                     f"{statistics.fmean(everything):,.1f} and the median is "
                     f"{statistics.median(everything):,.1f}.")
    named = [i for i, k in enumerate(keys) if k is not None]
    solid = sorted((means[keys[i]], i) for i in named if len(groups[keys[i]]) >= 5)
    if len(solid) >= 2 and solid[-1][0] > solid[0][0]:
        high, low = keys[solid[-1][1]], keys[solid[0][1]]
        found.append(f"Highest average: {row.text(high)} ({means[high]:,.1f}). "
                     f"Lowest: {row.text(low)} ({means[low]:,.1f}).")
        if len(solid) < len(named):
            found.append("Groups with fewer than 5 recorded values are left out of that "
                         "comparison: too few to give a steady average.")
    out["findings"] = found
    out["chart"] = _chart(ch, keys, [{"name": "Mean", "data": [round(means[k], 2) for k in keys]}],
                          stacked=False, decimals=True)
    return out


def _anova(groups, by):
    """One-way analysis of variance: do the group means differ by more than chance?"""
    groups = [g for g in groups if g]
    n, k = sum(len(g) for g in groups), len(groups)
    if k < 2 or n - k < 1:
        return None
    grand = sum(sum(g) for g in groups) / n
    between = sum(len(g) * (statistics.fmean(g) - grand) ** 2 for g in groups)
    within = sum(sum((x - m) ** 2 for x in g) for g in groups for m in [statistics.fmean(g)])
    if within <= 0:
        return None
    f = (between / (k - 1)) / (within / (n - k))
    p = stats.f_p(f, k - 1, n - k)
    if p < 0.05:
        headline = (f"The average differs by {by}: differences this large would rarely appear "
                    f"by chance ({stats.p_text(p)}).")
    else:
        headline = (f"No clear difference in the average by {by}: differences of this size "
                    f"could easily be chance ({stats.p_text(p)}).")
    return {"name": "Analysis of variance (one-way)", "headline": headline, "warning": "",
            "question": "Do the group averages really differ?",
            "detail": f"F({k - 1}, {n - k:,}) = {f:,.2f}, {stats.p_text(p)}. Based on {n:,} "
                      f"recorded values in {k} groups."}


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------
def _fold(keys, totals, limit):
    """Keep the `limit - 1` largest keys (in their order) plus OTHERS for the rest."""
    if len(keys) <= limit:
        return keys, []
    plain = [k for k in keys if k is not OTHERS]
    keep = set(sorted(plain, key=lambda k: -totals[k])[:limit - 1])
    folded = [k for k in keys if k not in keep]
    return [k for k in keys if k in keep] + [OTHERS], folded


def trending(ch):
    """Split by year or month in time order: the chart is a line and a trend is fitted."""
    return ch["row"].kind in TREND_KINDS and not ch["by_size"] and ch["compare"] != "period"


def _timeline(var, keys):
    """Every year / month from the first to the last, so a quiet one shows as 0
    instead of disappearing from the line."""
    real = [k for k in keys if k is not None]
    if var.kind not in TREND_KINDS or len(real) < 2:
        return keys
    tail = [None] if None in keys else []
    if var.kind == "year":
        return list(range(min(real), max(real) + 1)) + tail
    first, last = min(real), max(real)
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(first.replace(year=y, month=m, day=1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out + tail


def _bounds(var, key):
    if var.kind == "year":
        return date(key, 1, 1), date(key, 12, 31)
    after = date(key.year + key.month // 12, key.month % 12 + 1, 1)
    return key, after - timedelta(days=1)


def _trend(ch, keys, totals, units, today=None):
    """Straight-line trend (least squares) through the counts per year or month, with the
    test of whether its slope is more than chance. A year or month the dates only partly
    cover (or that is not over yet) is left out: its low count would drag the line down."""
    row = ch["row"]
    step = row.kind
    today = today or date.today()
    upto = min(today, ch["a_to"]) if ch["a_to"] else today
    points, partial, partial_at = [], [], []
    for i, k in enumerate(keys):
        if k is None:
            continue
        start, end = _bounds(row, k)
        if upto < end or (ch["a_from"] and ch["a_from"] > start):
            partial.append(row.text(k))
            partial_at.append(i)
        else:
            points.append((i, totals[k]))
    n = len(points)
    if n < 3:
        return None
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx
    start = my - slope * mx
    resid = sum((y - start - slope * x) ** 2 for x, y in points)
    if slope == 0:
        f, p = 0.0, 1.0
    else:
        f = slope ** 2 / (max(resid, 1e-12) / (n - 2) / sxx)
        p = stats.f_p(f, 1, n - 2)
    lo, hi = points[0][0], points[-1][0]
    fitted = [round(start + slope * i, 2) if lo <= i <= hi else None for i in range(len(keys))]

    each = f"each {step}"
    if p < 0.05:
        way = "up" if slope > 0 else "down"
        headline = (f"The number of {units} is going {way}: about {abs(slope):,.1f} "
                    f"{'more' if slope > 0 else 'fewer'} {each} on average. A trend this steady "
                    f"would rarely appear by chance ({stats.p_text(p)}).")
        direction = (f"Overall direction: {'rising' if slope > 0 else 'falling'}, by about "
                     f"{abs(slope):,.1f} {each}.")
    else:
        headline = (f"No clear trend up or down: the changes from {step} to {step} could easily "
                    f"be chance ({stats.p_text(p)}).")
        direction = "Overall direction: no clear rise or fall."
    test = {
        "name": "Linear trend", "question": "Is there a real trend up or down?",
        "headline": headline, "warning": "",
        "detail": (f"Straight line fitted by least squares to {n} {step}s: change per {step} = "
                   f"{slope:+,.2f}, F(1, {n - 2}) = {f:,.2f}, {stats.p_text(p)}. The line runs "
                   f"from {fitted[lo]:,.1f} to {fitted[hi]:,.1f}."),
    }
    warnings = []
    if n < 6:
        warnings.append(f"Only {n} full {step}s to go on, so treat this as a rough guide. "
                        "It becomes more reliable as more data comes in.")
    # A long stretch with no reports at all usually means reports were not entered for that
    # time, not that there were no accidents; it bends the trend line.
    gap, run = [], []
    for i, y in points:
        run = run + [i] if y == 0 else []
        if len(run) > len(gap):
            gap = run
    if len(gap) >= (6 if step == "month" else 2):
        warnings.append(f"There are no reports at all from {row.text(keys[gap[0]])} to "
                        f"{row.text(keys[gap[-1]])}. That usually means reports for that time "
                        "were not entered, not that no accidents happened, and it bends the "
                        "trend line. For a fairer trend, set the From date in the filters to "
                        "after the gap.")
    test["warning"] = " ".join(warnings)

    busiest = max(points, key=lambda pt: (pt[1], -pt[0]))
    quietest = min(points, key=lambda pt: (pt[1], pt[0]))
    found = [
        f"{sum(totals.values()):,} {units} in this selection.",
        f"Busiest {step}: {row.text(keys[busiest[0]])} with {busiest[1]:,}. "
        f"Quietest: {row.text(keys[quietest[0]])} with {quietest[1]:,}.",
        f"On average {my:,.1f} {units} a {step}.",
        direction,
    ]
    if partial:
        found.append(f"{_and(partial)} {'is' if len(partial) == 1 else 'are'} left out of the "
                     f"trend: the dates chosen only cover part of {'it' if len(partial) == 1 else 'them'}, "
                     "or it is not over yet.")
    guide = [
        ("Trend line", f"The dashed line is the straight line that fits the {step}s best. It "
         f"shows the general direction and smooths out the ups and downs from one {step} to "
         "the next."),
        ("Is there a real trend?", "The test asks how often a slope this steep would turn up "
         "by chance if nothing were really changing. Below 0.05 (5 times in 100) is the usual "
         "line for calling it a real trend."),
    ]
    if step == "month":
        guide.append(("Seasons", "Monthly numbers rise and fall with the seasons (holidays, "
                      "the rains). Over two years or more the trend line is a fair guide; over "
                      "a few months a busy season can fool it."))
    return test, fitted, found, guide, partial_at


def _chart(ch, keys, series, stacked, percent=False, decimals=False):
    row = ch["row"]
    line = trending(ch)
    labels = [row.text(k) for k in keys]
    if line and keys and keys[-1] is None:     # "Not recorded" has no place on a time line
        labels = labels[:-1]
        series = [dict(s, data=s["data"][:-1]) for s in series]
    cut = row.by_size and len(labels) > MAX_CHART_ROWS
    if cut:
        labels = labels[:MAX_CHART_ROWS]
        series = [{"name": s["name"], "data": s["data"][:MAX_CHART_ROWS]} for s in series]
    return {"labels": labels, "series": series,
            "stacked": stacked and not line and len(series) > 1, "line": line,
            "percent": percent, "decimals": decimals,
            "horizontal": not row.upright or ch["by_size"],
            "cut": MAX_CHART_ROWS if cut else 0,
            "empty": not any(n for s in series for n in s["data"])}
