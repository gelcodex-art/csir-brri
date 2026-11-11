"""Import accident reports from an Excel file in the same layout as "Export Excel".

The file name and the sheet names do not matter: each sheet is recognised by its
column headings (reports, vehicles, passengers, pedestrians); other sheets are
ignored. Column order does not matter and extra columns are ignored. Vehicle and
casualty rows belong to a report through their "accident" column, written as
number/year (e.g. 790/2021).

Files from the old accident database are read too (sheets Attendant_Circumstances,
Vehicle_Details and Casualty_Details, linked by ACCIDENT KEY; "?" means unknown).

Older records are understood as they were written: report number with the year
attached (237/15), the region as its number (1 = Ashanti) and the town only as
its town/village code (0101 = Ashanti, Kumasi) - see codebook.TOWN_CODES.

    plan = read_workbook(file_bytes, user)   # nothing is saved; describes what would happen
    save_plan(plan, user)                    # saves the reports marked "new"

A report is skipped when the same report number, year and region is already in
the system, so importing the same file twice does not create duplicates.
"""
import io
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models, transaction

from . import codebook as cb
from . import station_codes as sc
from .models import (Accident, AuditLog, District, PassengerCasualty, PedestrianCasualty,
                     PoliceStation, Region, Town, Vehicle)

MAX_BYTES = 4 * 1024 * 1024          # the online host accepts uploads up to about 4 MB
CHILD_SHEETS = [("Vehicles", Vehicle, "vehicles"), ("Passengers", PassengerCasualty, "passengers"),
                ("Pedestrians", PedestrianCasualty, "pedestrians")]
# Not read from the file: set by the system, or files that an Excel sheet cannot carry.
SKIP = {"id", "client_uuid", "day_of_week", "scene_sketch", "site_sketch", "created_at",
        "updated_at", "accident"}
LOOKUPS = {"region", "district", "town", "police_station", "created_by", "reviewed_by"}


class ImportProblem(Exception):
    """The file as a whole cannot be read (wrong type, wrong layout, too big)."""


def _blank(v):
    """Empty cell. The old accident database writes "?" for unknown."""
    return v is None or (isinstance(v, str) and v.strip() in ("", "?"))


def _text(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _full_year(year):
    """15 -> 2015, 98 -> 1998; four-digit years are returned as they are."""
    year = int(year)
    if year >= 100:
        return year
    return 2000 + year if year <= date.today().year % 100 + 1 else 1900 + year


def _split_ref(text):
    """'237/15' or '237/2015' -> ('237', 2015). (text, None) when there is no year part."""
    m = re.match(r"^(.*\S)\s*/\s*(\d{2}|\d{4})$", text.strip())
    return (m.group(1).strip(), _full_year(m.group(2))) if m else (text.strip(), None)


REGION_BY_NUMBER = {number: name for name, (number, _) in cb.TOWN_CODES.items()}


def _region_name(text):
    """Region as written in older records: its number ("1"), or "Ashanti Region (1)"."""
    text = text.strip()
    if re.fullmatch(r"\d{1,2}", text):
        return REGION_BY_NUMBER.get(int(text), text)
    text = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", text)            # "Ashanti Region (1)"
    return re.sub(r"\s+region$", "", text, flags=re.I).strip()


def _old_style(values, notes):
    """Rewrite one report row written the older way, before it is checked.

    * report number with the year attached: 237/15 -> number 237, year 2015
    * a two-digit year: 15 -> 2015
    * town/village code typed as a number: 101 -> 0101
    """
    values = dict(values)
    number, year = _split_ref(_text(values.get("report_number") or ""))
    if year:
        values["report_number"] = number
        if _blank(values.get("report_year")):
            values["report_year"] = year
    if not _blank(values.get("report_year")):
        try:
            values["report_year"] = _full_year(float(values["report_year"]))
        except (TypeError, ValueError):
            pass
    elif isinstance(values.get("accident_date"), (date, datetime)):
        values["report_year"] = values["accident_date"].year
        notes.append("No report year given; the year of the accident date is used.")
    code = _text(values.get("town_code") or "")
    if code.isdigit() and len(code) == 3:
        values["town_code"] = code.zfill(4)
    elif code and not code.strip("0"):                  # "0000": no town
        values["town_code"] = None
    for name in ("x_coordinate", "y_coordinate", "node_1", "node_2"):
        if not _blank(values.get(name)) and _text(values[name]) == "0":   # 0 stood for "not given"
            values[name] = None
    return values


# 43 Place of issue: the number in the coding manual -> licensing office code.
# 23 is printed twice in the manual and 25 is missing, so those stay as numbers.
LICENCE_OFFICE = {1: "AS1", 2: "CR4", 3: "AS3", 4: "BA1", 5: "CR1", 6: "CR2", 7: "ER3", 8: "ER1",
                  9: "GR1", 10: "GR2", 11: "NR1", 12: "UE1", 13: "UW1", 14: "VR1", 15: "VR2",
                  16: "VR3", 17: "WR1", 18: "WR2", 19: "VR4", 20: "ER2", 21: "AS4", 22: "AS2",
                  24: "CR3", 26: "BA2", 27: "GR3", 28: "ER4", 29: "AS5"}


def _old_vehicle(values):
    """Rewrite one vehicle row written the older way, before it is checked."""
    values = dict(values)
    plate = _text(values.get("registration_no") or "")
    if plate.isdigit() and len(plate) <= 2:             # 30 holds the registration code, not the plate
        values.setdefault("registration_code", plate)
        values["registration_no"] = None
    place = _text(values.get("licence_place_of_issue") or "")
    if place.isdigit():
        values["licence_place_of_issue"] = LICENCE_OFFICE.get(int(place), place)
    return values


def _convert(field, v):
    """Turn a cell value into the value for a model field. Raises ValueError."""
    if _blank(v):
        if field.has_default() and not field.blank:      # e.g. status, killed, injured
            return field.get_default()
        if isinstance(field, (models.CharField, models.TextField)):
            return ""
        if isinstance(field, models.BooleanField) and not field.null:
            return False
        return field.get_default() if field.has_default() and not field.null else None
    if isinstance(field, (models.CharField, models.TextField)):
        return _text(v)
    if isinstance(field, models.BooleanField):
        if isinstance(v, bool):
            return v
        word = _text(v).lower()
        if word in ("y", "yes", "true", "1"):
            return True
        if word in ("n", "no", "false", "0"):
            return False
        raise ValueError("should be Y or N")
    if isinstance(field, models.IntegerField):
        if isinstance(v, str) and field.choices:
            # A coded field written in words ("Ghanaian", or "1 - Ghanaian") instead of its code.
            word = v.strip().lower()
            for code, label in field.flatchoices:
                if word in (str(label).lower(), str(label).split(" - ", 1)[-1].lower()):
                    return code
        try:
            number = float(v)
        except (TypeError, ValueError):
            raise ValueError("should be a whole number")
        if not number.is_integer() or number < 0:
            raise ValueError("should be a whole number")
        return int(number)
    if isinstance(field, models.DecimalField):
        try:
            return round(Decimal(str(v)), field.decimal_places)
        except InvalidOperation:
            raise ValueError("should be a number")
    if isinstance(field, models.DateField):
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(_text(v), fmt).date()
            except ValueError:
                pass
        raise ValueError("should be a date (day/month/year)")
    if isinstance(field, models.TimeField):
        if isinstance(v, datetime):
            return v.time()
        if isinstance(v, time):
            return v
        for fmt in ("%H:%M", "%H:%M:%S", "%H%M"):
            try:
                return datetime.strptime(_text(v), fmt).time()
            except ValueError:
                pass
        raise ValueError("should be a 24-hour time such as 14:30")
    return v


def _norm(heading):
    """Heading in a comparable form: lower case, single spaces, no punctuation at the ends."""
    return re.sub(r"\s+", " ", str(heading)).strip(" .:").lower()


def _headings(model):
    """{heading text: field name}. A heading also matches without its form number
    ("Report number" as well as "1 Report number") when that is not ambiguous."""
    full, short, clash = {}, {}, set()
    for f in model._meta.fields:
        name = _norm(f.verbose_name)
        full[name] = f.name
        bare = re.sub(r"^[\d\-/ ]+", "", name)
        if bare and bare != name:
            if bare in short:
                clash.add(bare)
            short[bare] = f.name
    for bare, field in short.items():
        if bare not in clash and bare not in full:
            full[bare] = field
    return full


# Headings used by the old accident database (sheets Attendant_Circumstances,
# Vehicle_Details, Casualty_Details), where they differ from the app's own.
# Names starting with "_" are not fields: "_key" is that database's accident key,
# which links the sheets; "_class" is 1 driver, 2 passenger, 3 pedestrian.
OLD_ACCIDENT = {
    "accident key": "_key", "no vehicles involved": "num_vehicles", "date": "accident_date",
    "time": "accident_time", "no casualties killed": "killed", "no casualties injured": "injured",
    "road width": "road_width_m", "hit & run": "hit_and_run", "kilometre post": "km",
    "100m": "hundred_m", "direction of travel": "direction",
    "accident description": "police_description",
}
OLD_VEHICLE = {
    "accident key": "accident", "vehicle reference number": "vehicle_no",
    "vehicle ownership": "ownership", "driver sex": "driver_sex", "driver/rider age": "driver_age",
    "driver nationality": "driver_nationality", "driver/rider injury": "driver_injury",
    "licence number": "licence_no", "drinking and driving": "drink_drugs",
    "drivers error": "driver_error",
}
OLD_CASUALTY = {
    "accident key": "accident", "casualty class": "_class", "vehicle reference no": "vehicle_no",
    "casualty sex": "sex", "casualty age": "age", "casualty injury": "severity",
    "passenger position in veh": "position", "passenger action": "_passenger_action",
    "pedestrian action": "_pedestrian_action", "pedestrian location": "location",
    "drink/drugs": "drink_drugs",
}


def _kinds():
    """(kind, {heading: field}, fields it must have, sheet-name hint). Sheet names do not matter."""
    return [
        ("accidents", {**_headings(Accident), **OLD_ACCIDENT}, {"report_number", "accident_date"}, "accid"),
        ("vehicles", {**_headings(Vehicle), **OLD_VEHICLE}, {"accident"}, "veh"),
        ("passengers", _headings(PassengerCasualty), {"accident"}, "pass"),
        ("pedestrians", _headings(PedestrianCasualty), {"accident"}, "ped"),
        ("casualties", OLD_CASUALTY, {"accident", "_class"}, "casual"),
    ]


def _read_sheets(wb):
    """{"accidents": (sheet title, rows), ...} - each sheet recognised by its column headings.

    rows is [(excel row number, {field name: cell value})].
    """
    found, kinds = {}, _kinds()
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        try:
            headings = next(rows)
        except StopIteration:
            continue
        best = None
        for kind, known, must, hint in kinds:
            columns = {i: known[_norm(h)] for i, h in enumerate(headings)
                       if h is not None and _norm(h) in known}
            if not must <= set(columns.values()) or len(columns) < len(must) + 1:
                continue
            # Most matching columns wins; the sheet name only settles a tie.
            score = (len(columns), hint in ws.title.lower())
            if best is None or score > best[2]:
                best = (kind, columns, score)
        if best is None or best[0] in found:
            continue
        kind, columns, _ = best
        data = []
        for n, row in enumerate(rows, start=2):
            if all(_blank(c) for c in row):
                continue
            data.append((n, {name: row[i] for i, name in columns.items() if i < len(row)}))
        found[kind] = (ws.title, data)
    return found


def _fill(obj, values, problems, notes, label=""):
    """Copy plain (non-lookup) values onto obj and validate them."""
    model = type(obj)
    for name, raw in values.items():
        if name in SKIP or name in LOOKUPS or name.startswith("_"):
            continue
        field = model._meta.get_field(name)
        try:
            setattr(obj, name, _convert(field, raw))
        except ValueError as exc:
            problems.append(f"{label}{field.verbose_name}: \"{raw}\" {exc}.")
    try:
        obj.full_clean(exclude=list(SKIP | LOOKUPS), validate_unique=False)
    except ValidationError as exc:
        for name, errors in exc.error_dict.items():
            field = model._meta.get_field(name)
            for e in errors:
                if e.code == "invalid_choice":      # kept, as the report form also keeps them
                    notes.append(f"{label}{field.verbose_name}: code \"{getattr(obj, name)}\" "
                                 "is not in the code list.")
                elif not any(str(field.verbose_name) in p for p in problems):
                    problems.append(f"{label}{field.verbose_name}: {' '.join(e.messages)}")


class _Places:
    """Finds regions, districts, towns and police stations by the names in the file."""

    def __init__(self):
        self.regions = {r.name.lower(): r for r in Region.objects.all()}
        self.districts = {(d.region_id, d.name.lower()): d for d in District.objects.all()}
        self.stations = {(s.region_id, s.name.lower()): s for s in PoliceStation.objects.all()}
        self.station_codes = sc.stations_by_code()         # {"04086": station}
        self._towns = {}

    SIZE = ["city", "town", "suburb", "village", "hamlet", "locality"]

    def town(self, name, region, district):
        key = (name.lower(), region.pk, district.pk if district else None)
        if key not in self._towns:
            found = None
            # The export writes a town as "Name (code)" when it has a BRRI code.
            for candidate in (name, re.sub(r"\s*\([^()]*\)$", "", name)):
                qs = Town.objects.filter(name__iexact=candidate, district__region=region)
                if district:
                    qs = qs.filter(district=district)
                # Several places can share a name (a city and a hamlet): take the largest.
                matches = sorted(qs[:50], key=lambda t: (self.SIZE.index(t.kind)
                                                         if t.kind in self.SIZE else 9, t.pk))
                if matches:
                    found = matches[0]
                    break
            self._towns[key] = found
        return self._towns[key]


def read_workbook(data, user):
    """Read the file and work out what an import would do. Saves nothing."""
    from openpyxl import load_workbook

    if len(data) > MAX_BYTES:
        raise ImportProblem("The file is larger than 4 MB. Split it into smaller files "
                            "(for example one per year) and import them one at a time.")
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise ImportProblem("This is not an Excel (.xlsx) file that can be read. "
                            "Save it as .xlsx in Excel and try again.")

    places = _Places()
    users = {u.username: u for u in User.objects.all()}
    statuses = {code for code, _ in Accident.STATUS_CHOICES}
    reports, by_ref, by_key = [], {}, {}
    station_codes = 0

    sheets = _read_sheets(wb)
    if "accidents" not in sheets:
        raise ImportProblem(
            "This file does not look like accident data. No sheet has the columns "
            '"Report number" and "Date of accident". Use the same column headings as '
            '"Export Excel".')
    for n, values in sheets["accidents"][1]:
        problems, notes = [], []
        acc = Accident()
        values = _old_style(values, notes)
        _fill(acc, values, problems, notes)
        ref = f"{acc.report_number}/{acc.report_year}" if acc.report_number else f"row {n}"
        item = {"row": n, "ref": ref, "obj": acc, "problems": problems, "notes": notes,
                "new_station": None, "vehicles": [], "passengers": [], "pedestrians": []}

        written = _text(values.get("region") or "")
        code = acc.town_code if len(acc.town_code) == 4 and acc.town_code.isdigit() else ""
        region_name = _region_name(written)
        if not region_name and code:                    # region number is the first half of the code
            region_name = REGION_BY_NUMBER.get(int(code[:2]), "")
        region = places.regions.get(region_name.lower())
        if region is None:
            problems.append(f"2 Region: \"{written}\" is not a region in the system, or a region "
                            "number from 1 to 16." if written else "2 Region is missing.")
        else:
            acc.region = region
            name = _text(values.get("district") or "")
            if name:
                acc.district = places.districts.get((region.pk, name.lower()))
                if acc.district is None:
                    notes.append(f"District \"{name}\" was not found in {region}; left empty.")
            name = _text(values.get("town") or "")
            if not name and code:                       # older records give only the code
                if cb.TOWN_CODES.get(region.name, (None,))[0] != int(code[:2]):
                    notes.append(f"60 Town/village code {code} belongs to another region than "
                                 f"{region}; the code is kept, the town is left empty.")
                else:
                    name = cb.town_code_name(code)
                    if not name:
                        notes.append(f"60 Town/village code {code} is not in the code list; "
                                     "the code is kept, the town is left empty.")
            if name:
                acc.town = places.town(name, region, acc.district)
                if acc.town is None:
                    notes.append(f"Town \"{name}\" was not found in {region}; left empty.")
                elif acc.district is None:
                    acc.district = acc.town.district
            name = _text(values.get("police_station") or "")
            if name.isdigit():
                # A station code (04086). One that is not on the code list is kept in
                # the notes, so that nothing written on the report is lost.
                acc.police_station = places.station_codes.get(sc.clean_code(name))
                if acc.police_station is None:
                    station_codes += 1
                    acc.analyst_notes = (acc.analyst_notes + "\n" if acc.analyst_notes else "") + \
                        f"Police station code: {name}"
                    notes.append(f"3 Police station code {name} is not in the code list; the "
                                 "code is kept in the analyst notes, the station is left empty.")
            elif name:
                acc.police_station = places.stations.get((region.pk, name.lower()))
                if acc.police_station is None:
                    item["new_station"] = name[:120]
                    notes.append(f"Police station \"{name}\" is not in the list; it will be "
                                 "added (unverified).")

        if acc.status not in statuses:
            acc.status = Accident.STATUS_SUBMITTED
        acc.created_by = users.get(_text(values.get("created_by") or "")) or user
        acc.reviewed_by = users.get(_text(values.get("reviewed_by") or ""))
        if acc.accident_date:
            acc.day_of_week = acc.accident_date.isoweekday()
        if acc.town and not acc.town_code:
            acc.town_code = acc.town.code

        if ref in by_ref:
            problems.append(f"Report {ref} appears more than once in the file "
                            f"(also on row {by_ref[ref]['row']}).")
        else:
            by_ref[ref] = item
        if not _blank(values.get("_key")):
            by_key[_text(values["_key"])] = item
        reports.append(item)

    if not reports:
        raise ImportProblem(f'The sheet "{sheets["accidents"][0]}" has the right columns '
                            "but no reports in it.")

    def parent_of(values):
        link = _text(values.get("accident") or "")
        if link in by_key:
            return by_key[link]
        number, year = _split_ref(link)
        return by_ref.get(f"{number}/{year}" if year else number)

    orphans = drivers = 0
    for _, model, key in CHILD_SHEETS:
        title, child_rows = sheets.get(key, ("", []))
        for n, values in child_rows:
            parent = parent_of(values)
            if parent is None:
                orphans += 1
                continue
            if model is Vehicle:
                values = _old_vehicle(values)
            child = model()
            _fill(child, values, parent["problems"], parent["notes"], label=f"{title} row {n}: ")
            parent[key].append(child)

    # The old database keeps drivers, passengers and pedestrians on one casualty sheet.
    title, child_rows = sheets.get("casualties", ("", []))
    for n, values in child_rows:
        parent = parent_of(values)
        if parent is None:
            orphans += 1
            continue
        kind = _text(values.get("_class") or "")
        values = dict(values)
        if kind == "1":             # the driver: already on the vehicle row (37, 38, 40)
            drivers += 1
            continue
        if kind == "2":
            model, key = PassengerCasualty, "passengers"
            values["action"] = values.get("_passenger_action")
            for name in ("location", "drink_drugs"):
                values.pop(name, None)
        elif kind == "3":
            model, key = PedestrianCasualty, "pedestrians"
            values["action"] = values.get("_pedestrian_action")
            values.pop("position", None)
        else:
            parent["problems"].append(f"{title} row {n}: casualty class \"{kind}\" should be "
                                      "1 (driver), 2 (passenger) or 3 (pedestrian).")
            continue
        child = model()
        _fill(child, values, parent["problems"], parent["notes"], label=f"{title} row {n}: ")
        parent[key].append(child)

    # Already in the system?
    years = {r["obj"].report_year for r in reports if r["obj"].report_year}
    existing = set(Accident.objects.filter(report_year__in=years)
                   .values_list("report_number", "report_year", "region_id"))
    for r in reports:
        acc = r["obj"]
        if r["problems"]:
            r["state"] = "error"
        elif (acc.report_number, acc.report_year, acc.region_id) in existing:
            r["state"] = "duplicate"
        else:
            r["state"] = "new"

    count = lambda state: sum(1 for r in reports if r["state"] == state)   # noqa: E731
    return {"reports": reports, "orphans": orphans, "drivers": drivers,
            "station_codes": station_codes, "n_new": count("new"),
            "n_duplicate": count("duplicate"), "n_error": count("error"),
            "n_notes": sum(1 for r in reports if r["notes"] and r["state"] == "new")}


def save_plan(plan, user):
    """Save every report marked "new". Returns how many were saved."""
    todo = [r for r in plan["reports"] if r["state"] == "new"]
    with transaction.atomic():
        for r in todo:
            acc = r["obj"]
            if r["new_station"]:
                acc.police_station, _ = PoliceStation.objects.get_or_create(
                    region=acc.region, name=r["new_station"],
                    defaults={"district": acc.district, "source": "import", "added_by": user})
        Accident.objects.bulk_create([r["obj"] for r in todo], batch_size=500)
        for _, model, key in CHILD_SHEETS:
            children = []
            for r in todo:
                for child in r[key]:
                    child.accident = r["obj"]
                    children.append(child)
            model.objects.bulk_create(children, batch_size=1000)
        AuditLog.objects.bulk_create(
            [AuditLog(accident=r["obj"], user=user, action="imported", note="From an Excel file")
             for r in todo], batch_size=1000)
    return len(todo)
