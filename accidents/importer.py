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

Each police station numbers its own reports from 1, so 2/2024 is on many
stations' books: a report is its number and year at its police station (the
region is only used for a report without a station). A report already in the
system is skipped, so importing the same file twice does not create duplicates.
"""
import io
import pickle
import re
import zlib
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models, transaction

from . import codebook as cb
from . import station_codes as sc
from .models import (Accident, AuditLog, District, PassengerCasualty, PedestrianCasualty,
                     PoliceStation, Region, Town, Vehicle)

MAX_BYTES = 70 * 1024 * 1024         # online, the browser sends bigger files in pieces (see views)
CHILD_SHEETS = [("Vehicles", Vehicle, "vehicles"), ("Passengers", PassengerCasualty, "passengers"),
                ("Pedestrians", PedestrianCasualty, "pedestrians")]
# Not read from the file: set by the system, or files that an Excel sheet cannot carry.
SKIP = {"id", "client_uuid", "day_of_week", "scene_sketch", "site_sketch", "created_at",
        "updated_at", "accident"}
LOOKUPS = {"region", "district", "town", "police_station", "created_by", "reviewed_by"}


class ImportProblem(Exception):
    """The file as a whole cannot be read (wrong type, wrong layout, too big)."""


def _blank(v):
    """Empty cell. The old accident database writes "?" or "NA" for unknown."""
    return v is None or (isinstance(v, str) and v.strip().upper() in ("", "?", "NA", "N/A"))


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


def plain_number(text):
    """A report number without its leading zeros: "06" and "006" are report 6.
    Numbers with letters or other signs ("A12", "12B") are kept as written."""
    text = (text or "").strip()
    return str(int(text)) if text.isdigit() else text


def _split_ref(text):
    """'237/15' or '237/2015' -> ('237', 2015). (text, None) when there is no year part."""
    m = re.match(r"^(.*\S)\s*/\s*(\d{2}|\d{4})$", text.strip())
    return (m.group(1).strip(), _full_year(m.group(2))) if m else (text.strip(), None)


REGION_BY_NUMBER = {number: name for name, (number, _) in cb.TOWN_CODES.items()}


def _region_name(text):
    """Region as written in older records: its number, or "Ashanti Region (1)".
    A number is a number however it is written: 5, 05, 005, 5.0 and "Region 05"
    are all region 5."""
    text = text.strip()
    m = re.fullmatch(r"(?:region|r)?\s*0*(\d{1,2})(?:\.0*)?", text, flags=re.I)
    if m:
        return REGION_BY_NUMBER.get(int(m.group(1)), text)
    text = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", text)            # "Ashanti Region (1)"
    return re.sub(r"\s+region$", "", text, flags=re.I).strip()


def _date_shaped_ref(first, second, accident_date):
    """(report number, two-digit year) from a report number Excel made into a date.
    Usually the second part is the year (7/24 -> 24 July); when only the first
    part matches the accident's year, the parts are the other way round."""
    if isinstance(accident_date, (date, datetime)):
        yy = accident_date.year % 100
        if first == yy and second != yy:
            return second, first
    return first, second


def _old_style(values, notes):
    """Rewrite one report row written the older way, before it is checked.

    * report number with the year attached: 237/15 -> number 237, year 2015
    * a two-digit year: 15 -> 2015
    * town/village code typed as a number: 101 -> 0101
    """
    values = dict(values)
    written = values.get("report_number")
    parts = None
    if isinstance(written, (date, datetime)):
        parts = (written.month, written.day)
    elif isinstance(written, str):
        # The same date saved back as text: "07/24/2026", "07/24/" or "07/24/26".
        m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})?\s*", written)
        if m:
            parts = (int(m.group(1)), int(m.group(2)))
    if parts:
        # Excel turns the report number "7/24" into the date 24 July: one part is the
        # number, the other the year. The accident date says which is the year.
        number, year = _date_shaped_ref(*parts, values.get("accident_date"))
        values["report_number"] = f"{number}/{year:02d}"
        notes.append(f"Report number: Excel had changed \"{number}/{year:02d}\" into a date "
                     f"(\"{_text(written) if isinstance(written, str) else f'{written:%d/%m/%Y}'}\"); "
                     "it is read as the report number again.")
    number, year = _split_ref(_text(values.get("report_number") or ""))
    if year:
        values["report_number"] = number
        if _blank(values.get("report_year")):
            values["report_year"] = year
    if not _blank(values.get("report_number")):
        values["report_number"] = plain_number(_text(values["report_number"]))   # 06 -> 6
    if not _blank(values.get("report_year")):
        try:
            values["report_year"] = _full_year(float(values["report_year"]))
        except (TypeError, ValueError):
            pass
    elif isinstance(values.get("accident_date"), (date, datetime)):
        values["report_year"] = values["accident_date"].year
        notes.append("No report year given; the year of the accident date is used.")
    km = values.get("km")
    try:
        km_number = float(km) if not _blank(km) else None
    except (TypeError, ValueError):
        km_number = None
    if km_number is not None and not km_number.is_integer() and km_number >= 0:
        # "73.5" is 73 km and 5 hundred metres (61 Km and 62 100m on the form).
        whole = int(km_number)
        hundreds = int(round((km_number - whole) * 10, 6))
        values["km"] = whole
        if _blank(values.get("hundred_m")):
            values["hundred_m"] = hundreds
            notes.append(f"61 Km: \"{_text(km)}\" is read as {whole} km and {hundreds} hundred metres.")
        else:                               # 100m is filled in already: keep it
            notes.append(f"61 Km: \"{_text(km)}\" is read as {whole} km.")
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
    written = values.get("_registration")
    if not _blank(written) and _blank(values.get("registered_in")):
        values["registered_in"] = OLD_REGISTRATION.get(_text(written))   # other values: unknown
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
    "drivers error": "driver_error", "vehiclekey": "_vkey",
    "vehicle registration": "_registration",          # 0 = Ghanaian, 1 = foreign
}
OLD_REGISTRATION = {"0": 1, "1": 2}                   # -> codebook.REGISTERED_IN
OLD_CASUALTY = {
    "accident key": "accident", "casualty class": "_class", "vehicle reference no": "vehicle_no",
    "casualty sex": "sex", "casualty age": "age", "casualty injury": "severity",
    "passenger position in veh": "position", "passenger action": "_passenger_action",
    "pedestrian action": "_pedestrian_action", "pedestrian location": "location",
    "drink/drugs": "drink_drugs", "casualtykey": "_ckey",
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


# One sheet holding everything (the old database's "flat" export): each row is one
# accident x one vehicle x one casualty, so an accident with 2 vehicles and 3
# casualties fills 6 rows. Each part is taken once, by its key.
FLAT_KEYS = {"accidents": "_key", "vehicles": "_vkey", "casualties": "_ckey"}


def _read_sheets(wb):
    """{"accidents": (sheet title, rows), ...} - each sheet recognised by its column headings.

    rows is [(excel row number, {field name: cell value})]. Only the recognised
    columns of filled rows are kept, so this is much smaller than the file.
    A row whose key was already seen with other values gets "_differs": True.
    """
    found, kinds = {}, _kinds()
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        try:
            headings = next(rows)
        except StopIteration:
            continue
        matches = {}
        for kind, known, must, hint in kinds:
            columns = {i: known[_norm(h)] for i, h in enumerate(headings)
                       if h is not None and _norm(h) in known}
            if not must <= set(columns.values()) or len(columns) < len(must) + 1:
                continue
            # Most matching columns wins; the sheet name only settles a tie.
            matches[kind] = (columns, (len(columns), hint in ws.title.lower()))
        if not matches:
            continue
        flat = ("accidents" in matches and "_vkey" in matches.get("vehicles", ({},))[0].values()
                and "_ckey" in matches.get("casualties", ({},))[0].values())
        if flat:
            parts = [k for k in FLAT_KEYS if k not in found]
        else:
            parts = [max(matches, key=lambda k: matches[k][1])]
            if parts[0] in found:
                continue
        data = {kind: [] for kind in parts}
        first = {kind: {} for kind in parts}          # key -> values of its first row
        for n, row in enumerate(rows, start=2):
            if all(_blank(c) for c in row):
                continue
            for kind in parts:
                columns = matches[kind][0]
                values = {name: row[i] for i, name in columns.items() if i < len(row)}
                if not flat:
                    data[kind].append((n, values))
                    continue
                key = values.get(FLAT_KEYS[kind])
                if _blank(key):                     # e.g. an accident without casualties
                    continue
                seen = first[kind].get(key)
                if seen is None:
                    first[kind][key] = values
                    data[kind].append((n, values))
                elif seen != values:
                    seen["_differs"] = True
        for kind in parts:
            found[kind] = (ws.title, data[kind])
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


def _station_label(acc, new_station=None):
    """Which police station a report is from, for telling reports apart: the
    station, else the code written on it, else the new station's name."""
    label = _station_label_saved(acc.police_station_id, acc.analyst_notes)
    return label or (f"n{new_station.lower()}" if new_station else "")


def _station_label_saved(station_id, notes):
    if station_id:
        return f"s{station_id}"
    m = sc.NOTE.search(notes or "")
    return "c" + (sc.clean_code(m.group(1)) or m.group(1)) if m else ""


def _identity(item):
    """Report number and year at its police station. Each station numbers its own
    reports from 1. The region is only used when the report has no station."""
    acc = item["obj"]
    return _identity_of(acc.report_number, acc.report_year, acc.region_id, item["station"])


def _identity_of(number, year, region_id, station):
    number = plain_number(number)                   # 06 and 6 are the same report
    if station.startswith("s"):                     # a known station: it fixes the region
        return (number, year, station)
    return (number, year, region_id, station)


def read_sheets(data):
    """The recognised columns of the filled rows of the file (see _read_sheets)."""
    from openpyxl import load_workbook

    if len(data) > MAX_BYTES:
        raise ImportProblem(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB. Split it "
                            "into smaller files (for example one per year) and import them one "
                            "at a time.")
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise ImportProblem("This is not an Excel (.xlsx) file that can be read. "
                            "Save it as .xlsx in Excel and try again.")
    try:
        return _read_sheets(wb)
    finally:
        wb.close()


def pack(sheets):
    """Sheets read from a file, compressed, to hold between "Check" and "Import".
    Only what the import uses is kept, not the whole Excel file."""
    return zlib.compress(pickle.dumps(sheets, protocol=pickle.HIGHEST_PROTOCOL), 6)


def unpack(blob):
    return pickle.loads(zlib.decompress(blob))


def read_workbook(data, user):
    """Read the file and work out what an import would do. Saves nothing."""
    return make_plan(read_sheets(data), user)


def make_plan(sheets, user):
    """Work out what an import of these sheets would do. Saves nothing."""
    places = _Places()
    users = {u.username: u for u in User.objects.all()}
    statuses = {code for code, _ in Accident.STATUS_CHOICES}
    reports, by_ref, by_key, by_identity = [], {}, {}, {}
    station_codes = 0
    unknown_codes = {}                                  # code -> {region name: reports}

    if "accidents" not in sheets:
        raise ImportProblem(
            "This file does not look like accident data. No sheet has the columns "
            '"Report number" and "Date of accident". Use the same column headings as '
            '"Export Excel".')
    for n, values in sheets["accidents"][1]:
        problems, notes = [], []
        acc = Accident()
        if values.get("_differs"):
            notes.append("This accident is on several rows with different details; the first "
                         "row is used.")
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
                    by_region = unknown_codes.setdefault(sc.clean_code(name) or name, {})
                    by_region[region.name] = by_region.get(region.name, 0) + 1
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

        # Each police station numbers its own reports, so 2/2024 can be on many
        # stations' books: a report is its number, year, region and station.
        item["station"] = _station_label(acc, item["new_station"])
        item["key"] = None if _blank(values.get("_key")) else _text(values["_key"])
        same = by_identity.get(_identity(item))
        if same is None:
            by_identity[_identity(item)] = item
        elif item["key"] and same["key"] and item["key"] != same["key"]:
            # The database's own accident key says these are two different accidents
            # that were given the same number: both are imported, to be checked.
            notes.append(f"Check the report number: report {ref} of the same police station is "
                         f"also on row {same['row']} (accident key {same['key']}), a different "
                         f"accident (key {item['key']}). Both are imported.")
            same["notes"].append(f"Check the report number: report {ref} of the same police "
                                 f"station is also on row {n} (accident key {item['key']}). "
                                 "Both are imported.")
        else:
            problems.append(f"Report {ref} of the same police station appears more than once "
                            f"in the file (also on row {same['row']}).")
        by_ref.setdefault(ref, item)
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
                if values.get("_differs"):
                    parent["notes"].append(
                        f"Vehicle {_text(values.get('vehicle_no') or '?')} "
                        f"({_text(values.get('_vkey'))}) is on several rows with different "
                        "details; the first row is used.")
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
        if values.get("severity") is not None and _text(values["severity"]) == "0":
            values["severity"] = 9          # recoded data: 1 = killed, 0 = injured
        if values.get("_differs"):
            parent["notes"].append(f"Casualty {_text(values.get('_ckey'))} is on several rows "
                                   "with different details; the first row is used.")
        if kind == "1":            # the driver: already on the vehicle row (37, 38, 40)
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
            # Not known whether a driver, passenger or pedestrian: this person is left
            # out, the rest of the report is still imported.
            parent["notes"].append(
                f"{title} row {n}: casualty {_text(values.get('_ckey') or '')} is left out: its "
                f"casualty class \"{kind}\" should be 1 (driver), 2 (passenger) or 3 (pedestrian).")
            continue
        child = model()
        _fill(child, values, parent["problems"], parent["notes"], label=f"{title} row {n}: ")
        parent[key].append(child)

    # Already in the system?
    years = {r["obj"].report_year for r in reports if r["obj"].report_year}
    existing = set()
    for number, year, region_id, station_id, notes in (
            Accident.objects.filter(report_year__in=years)
            .values_list("report_number", "report_year", "region_id", "police_station_id",
                         "analyst_notes").iterator()):
        existing.add(_identity_of(number, year, region_id,
                                  _station_label_saved(station_id, notes)))
    for r in reports:
        if r["problems"]:
            r["state"] = "error"
        elif _identity(r) in existing:
            r["state"] = "duplicate"
        else:
            r["state"] = "new"

    count = lambda state: sum(1 for r in reports if r["state"] == state)   # noqa: E731
    # Unknown station codes with the regions of their reports (most reports first).
    region_names = {f"{number:02d}": name for number, name in REGION_BY_NUMBER.items()}
    unknown = []
    for code, by_region in sorted(unknown_codes.items(),
                                  key=lambda kv: (-sum(kv[1].values()), kv[0])):
        regions = sorted(by_region.items(), key=lambda kv: (-kv[1], kv[0]))
        unknown.append({"code": code, "reports": sum(by_region.values()), "region": regions[0][0],
                        "regions": regions, "code_region": region_names.get(code[:2], "")})
    return {"reports": reports, "orphans": orphans, "drivers": drivers,
            "station_codes": station_codes, "unknown_codes": unknown, "n_new": count("new"),
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
