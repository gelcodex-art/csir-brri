"""Import accident reports from an Excel file in the same layout as "Export Excel".

The file name and the sheet names do not matter: each sheet is recognised by its
column headings (reports, vehicles, passengers, pedestrians); other sheets are
ignored. Column order does not matter and extra columns are ignored. Vehicle and
casualty rows belong to a report through their "accident" column, written as
number/year (e.g. 790/2021).

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
    return v is None or (isinstance(v, str) and not v.strip())


def _text(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


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


# What each kind of sheet must contain to be recognised (sheet names do not matter).
KINDS = [
    ("accidents", Accident, {"report_number", "region", "accident_date"}, "accid"),
    ("vehicles", Vehicle, {"accident"}, "veh"),
    ("passengers", PassengerCasualty, {"accident"}, "pass"),
    ("pedestrians", PedestrianCasualty, {"accident"}, "ped"),
]


def _read_sheets(wb):
    """{"accidents": (sheet title, rows), ...} - each sheet recognised by its column headings.

    rows is [(excel row number, {field name: cell value})].
    """
    found = {}
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        try:
            headings = next(rows)
        except StopIteration:
            continue
        best = None
        for kind, model, must, hint in KINDS:
            known = _headings(model)
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
        if name in SKIP or name in LOOKUPS:
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
        self._towns = {}

    def town(self, name, region, district):
        key = (name.lower(), region.pk, district.pk if district else None)
        if key not in self._towns:
            found = None
            # The export writes a town as "Name (code)" when it has a BRRI code.
            for candidate in (name, re.sub(r"\s*\([^()]*\)$", "", name)):
                qs = Town.objects.filter(name__iexact=candidate, district__region=region)
                if district:
                    qs = qs.filter(district=district)
                matches = list(qs[:2])
                if len(matches) == 1:
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
    reports, by_ref = [], {}

    sheets = _read_sheets(wb)
    if "accidents" not in sheets:
        raise ImportProblem(
            "This file does not look like accident data. No sheet has the columns "
            '"Report number", "Region" and "Date of accident". Use the same column '
            'headings as "Export Excel".')
    for n, values in sheets["accidents"][1]:
        problems, notes = [], []
        acc = Accident()
        _fill(acc, values, problems, notes)
        ref = f"{acc.report_number}/{acc.report_year}" if acc.report_number else f"row {n}"
        item = {"row": n, "ref": ref, "obj": acc, "problems": problems, "notes": notes,
                "new_station": None, "vehicles": [], "passengers": [], "pedestrians": []}

        region_name = _text(values.get("region") or "")
        region = places.regions.get(region_name.lower())
        if region is None:
            problems.append(f"2 Region: \"{region_name}\" is not a region in the system."
                            if region_name else "2 Region is missing.")
        else:
            acc.region = region
            name = _text(values.get("district") or "")
            if name:
                acc.district = places.districts.get((region.pk, name.lower()))
                if acc.district is None:
                    notes.append(f"District \"{name}\" was not found in {region}; left empty.")
            name = _text(values.get("town") or "")
            if name:
                acc.town = places.town(name, region, acc.district)
                if acc.town is None:
                    notes.append(f"Town \"{name}\" was not found in {region}; left empty.")
                elif acc.district is None:
                    acc.district = acc.town.district
            name = _text(values.get("police_station") or "")
            if name:
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
        reports.append(item)

    if not reports:
        raise ImportProblem(f'The sheet "{sheets["accidents"][0]}" has the right columns '
                            "but no reports in it.")

    orphans = 0
    for _, model, key in CHILD_SHEETS:
        title, child_rows = sheets.get(key, ("", []))
        for n, values in child_rows:
            parent = by_ref.get(_text(values.get("accident") or ""))
            if parent is None:
                orphans += 1
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
    return {"reports": reports, "orphans": orphans, "n_new": count("new"),
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
