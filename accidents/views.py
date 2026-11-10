import csv
import hashlib
import io
import json
import uuid
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.db.models import Count, Q, Sum
from django.db.models.fields.files import FieldFile
from django.db.models.functions import TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import codebook as cb
from .checks import check_report
from .forms import (AccidentForm, FirstAdminForm, PassengerFormSet, PedestrianFormSet, ReviewForm,
                    VehicleFormSet)
from .models import (Accident, AuditLog, District, PassengerCasualty, PedestrianCasualty,
                     PoliceStation, Region, Town, Vehicle)


# ---------------------------------------------------------------------------
# First run: with no accounts at all, the first visitor creates the administrator
# ---------------------------------------------------------------------------
def database_problem():
    """None when the accounts table can be read; otherwise a plain-words reason."""
    try:
        User.objects.exists()
        return None
    except DatabaseError as exc:
        text = str(exc).lower()
        if settings.ON_VERCEL and not settings.DATABASE_URL:
            return ("DATABASE_URL is not set on Vercel. Add it under Settings > Environment "
                    "Variables (the Supabase Transaction pooler line), then Redeploy.")
        if "does not exist" in text or "no such table" in text:
            return ("The site reached the database, but it is empty: the tables have not been "
                    "created yet. On the office PC, double-click setup-online.bat and paste the "
                    "same connection line that is saved in Vercel.")
        if "password" in text or "authentication" in text:
            return ("The database refused the password in DATABASE_URL. Correct the line in "
                    "Vercel (Settings > Environment Variables), then Redeploy.")
        return ("The site could not connect to the database. Check that DATABASE_URL in Vercel "
                "is the Supabase Transaction pooler line, then Redeploy.")


def _database_page(request, problem):
    return render(request, "registration/db_problem.html", {"problem": problem}, status=503)


class LoginOrSetupView(LoginView):
    def dispatch(self, request, *args, **kwargs):
        problem = database_problem()
        if problem:
            return _database_page(request, problem)
        if not User.objects.exists():
            return redirect("first_admin")
        return super().dispatch(request, *args, **kwargs)


def first_admin(request):
    problem = database_problem()
    if problem:
        return _database_page(request, problem)
    if User.objects.exists():           # closed for good once any account exists
        return redirect("login")
    form = FirstAdminForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            if User.objects.exists():
                return redirect("login")
            user = form.save()
        login(request, user)
        messages.success(request, "Administrator account created. You can now add your analysts.")
        return redirect("admin:auth_user_add")
    return render(request, "registration/first_admin.html", {"form": form})


# ---------------------------------------------------------------------------
# Shared filtering (list, dashboard, export all use the same query string)
# ---------------------------------------------------------------------------
def filtered_accidents(request):
    qs = Accident.objects.select_related("region", "district", "town", "police_station")
    g = request.GET
    if g.get("date_from"):
        qs = qs.filter(accident_date__gte=g["date_from"])
    if g.get("date_to"):
        qs = qs.filter(accident_date__lte=g["date_to"])
    if g.get("region"):
        qs = qs.filter(region_id=g["region"])
    if g.get("location"):
        qs = qs.filter(site_location_text__iexact=g["location"].strip())
    if g.get("police_station"):
        qs = qs.filter(police_station_id=g["police_station"])
    if g.get("severity"):
        qs = qs.filter(severity=g["severity"])
    if g.get("status"):
        qs = qs.filter(status=g["status"])
    if g.get("q"):
        q = g["q"]
        qs = qs.filter(Q(report_number__icontains=q) | Q(road_name__icontains=q)
                       | Q(town__name__icontains=q) | Q(district__name__icontains=q)
                       | Q(police_station__name__icontains=q) | Q(police_description__icontains=q)
                       | Q(site_location_text__icontains=q))
    return qs


def site_locations():
    """Distinct site locations typed on reports, for the Location filter dropdown."""
    seen = {}
    rows = (Accident.objects.exclude(site_location_text="")
            .values_list("site_location_text", "region_id").order_by("-updated_at"))
    for text, region_id in rows:
        name = text.strip()
        if name and name.lower() not in seen:
            seen[name.lower()] = {"name": name, "region_id": region_id or ""}
    return sorted(seen.values(), key=lambda x: x["name"].lower())


def filter_context(request):
    params = request.GET.copy()
    params.pop("page", None)
    return {
        "sample_count": Accident.objects.filter(is_sample=True).count(),
        "regions": Region.objects.all(),
        "filter_locations": site_locations(),
        "filter_stations": PoliceStation.objects.order_by("name").values(
            "id", "name", "region_id", "district_id"),
        "severities": cb.choices(cb.ACCIDENT_SEVERITY),
        "statuses": Accident.STATUS_CHOICES,
        "f": request.GET,
        "querystring": params.urlencode(),
    }


def _label(codes, value):
    return codes.get(value, "Not recorded") if value is not None else "Not recorded"


def _series(rows, key, codes=None):
    out = []
    for r in rows:
        k = r[key]
        out.append({"label": _label(codes, k) if codes is not None else (k or "Not recorded"),
                    "n": r["n"]})
    return out


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    qs = filtered_accidents(request)
    totals = qs.aggregate(n=Count("id"), killed=Sum("killed"), injured=Sum("injured"),
                          fatal=Count("id", filter=Q(severity=1)))

    by_region = list(qs.values("region__name").annotate(n=Count("id"), killed=Sum("killed"))
                     .order_by("-n"))
    by_severity = _series(qs.values("severity").annotate(n=Count("id")).order_by("severity"),
                          "severity", cb.ACCIDENT_SEVERITY)
    by_month = [{"label": r["m"].strftime("%Y-%m"), "n": r["n"], "killed": r["killed"] or 0}
                for r in qs.annotate(m=TruncMonth("accident_date")).values("m")
                .annotate(n=Count("id"), killed=Sum("killed")).order_by("m") if r["m"]]
    road_users = {
        "Drivers/riders": Vehicle.objects.filter(accident__in=qs, driver_injury__in=[1, 2, 3]).count(),
        "Passengers": PassengerCasualty.objects.filter(accident__in=qs).count(),
        "Pedestrians": PedestrianCasualty.objects.filter(accident__in=qs).count(),
    }

    points = list(qs.exclude(latitude=None).exclude(longitude=None)
                  .values("id", "latitude", "longitude", "severity", "report_number",
                          "report_year", "accident_date", "killed")[:5000])
    map_points = [{"id": p["id"], "lat": float(p["latitude"]), "lng": float(p["longitude"]),
                   "sev": p["severity"], "ref": f'{p["report_number"]}/{p["report_year"]}',
                   "date": p["accident_date"].isoformat(), "killed": p["killed"]} for p in points]

    # Blackspots: accidents grouped into ~500m grid cells.
    cell = 0.005
    grid = Counter()
    fatal_grid = Counter()
    for p in map_points:
        key = (round(p["lat"] / cell), round(p["lng"] / cell))
        grid[key] += 1
        fatal_grid[key] += p["killed"] or 0
    blackspots = [{"lat": k[0] * cell, "lng": k[1] * cell, "n": n, "killed": fatal_grid[k]}
                  for k, n in grid.most_common(15) if n >= 2]
    town_spots = list(qs.exclude(town=None).values("town__name", "district__name", "region__name")
                      .annotate(n=Count("id"), killed=Sum("killed")).order_by("-n")[:15])

    # The dashboard shows four charts: per month, by region, by severity, by road user.
    charts = {
        "month": by_month,
        "region": [{"label": r["region__name"], "n": r["n"]} for r in by_region],
        "severity": by_severity,
        "road_users": [{"label": k, "n": v} for k, v in road_users.items()],
    }
    stations = [{"name": n, "district": d or "", "lat": float(la), "lng": float(ln)}
                for n, d, la, ln in PoliceStation.objects.exclude(latitude=None)
                .values_list("name", "district__name", "latitude", "longitude")]
    by_station = list(qs.exclude(police_station=None)
                      .values("police_station__name", "region__name")
                      .annotate(n=Count("id"), killed=Sum("killed")).order_by("-n")[:15])
    ctx = {"stations": stations, "by_station": by_station, "totals": totals, "charts": charts,
           "map_points": map_points, "blackspots": blackspots, "town_spots": town_spots,
           **filter_context(request)}
    return render(request, "accidents/dashboard.html", ctx)


# ---------------------------------------------------------------------------
# List / detail
# ---------------------------------------------------------------------------
@login_required
def accident_list(request):
    qs = filtered_accidents(request)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "accidents/list.html",
                  {"page": page, "total": qs.count(), **filter_context(request)})


def _all_values(obj):
    """(label, value) for every field entered on a row, e.g. a vehicle - nothing left out."""
    rows = []
    for f in obj._meta.concrete_fields:
        if f.primary_key or f.is_relation:
            continue
        val = getattr(obj, f.name)
        if f.choices:
            val = getattr(obj, f"get_{f.name}_display")() if val is not None else ""
        elif isinstance(val, bool):
            val = "Yes" if val else "No"
        elif hasattr(val, "strftime"):
            val = val.strftime("%d %b %Y")
        rows.append((f.verbose_name, val))
    return rows


@login_required
def accident_detail(request, pk):
    acc = get_object_or_404(Accident.objects.select_related(
        "region", "district", "town", "police_station", "created_by", "reviewed_by"), pk=pk)
    review = ReviewForm(instance=acc)
    sections = []
    for title, names in AccidentForm.SECTIONS:
        rows = []
        for n in names:
            if n in AccidentForm.DETAIL_FIELDS:   # form-only boxes (5/6/7, 8, new station)
                n = AccidentForm.DETAIL_FIELDS[n]
                if n is None:
                    continue
            f = Accident._meta.get_field(n)
            val = getattr(acc, n)
            if f.choices:
                val = getattr(acc, f"get_{n}_display")() if val is not None else ""
            elif n == "town_code" and cb.town_code_name(val):
                val = f"{val} - {cb.town_code_name(val)}"
            ps = acc.police_station
            if n == "police_station" and ps and ps.source == "user" and not ps.verified:
                val = f"{ps} (new station added by an analyst - not yet checked)"
            rows.append((f.verbose_name, val, n in ("scene_sketch", "site_sketch"),
                         f.get_internal_type() == "TextField"))   # long text gets a full row
        sections.append((title, rows))
    return render(request, "accidents/detail.html", {
        "a": acc, "sections": sections, "review": review,
        "vehicle_cards": [(v.vehicle_no, _all_values(v)) for v in acc.vehicles.all()],
        "duplicates": acc.possible_duplicates()[:10],
        "vehicles": acc.vehicles.all(), "passengers": acc.passengers.all(),
        "pedestrians": acc.pedestrians.all(), "audit": acc.audit.select_related("user")[:30],
    })


@login_required
@require_POST
def accident_review(request, pk):
    acc = get_object_or_404(Accident, pk=pk)
    form = ReviewForm(request.POST, instance=acc)
    if form.is_valid():
        acc = form.save(commit=False)
        if acc.status == Accident.STATUS_REVIEWED:
            acc.reviewed_by = request.user
        acc.save()
        AuditLog.objects.create(accident=acc, user=request.user,
                                action=f"status: {acc.get_status_display()}",
                                note=acc.analyst_notes[:255])
        messages.success(request, f"Status saved: {acc.get_status_display()}.")
    return redirect("accident_detail", pk=pk)


# ---------------------------------------------------------------------------
# Create / edit
# ---------------------------------------------------------------------------
LOCATIONS_CACHE_KEY = "locations-json-v1"


def locations_json():
    """(etag, bytes) of every district/town/station; cached until locations change."""
    hit = cache.get(LOCATIONS_CACHE_KEY)
    if hit:
        return hit
    payload = {
        "regions": list(Region.objects.values_list("id", "name")),
        "districts": list(District.objects.values_list("id", "region_id", "name", "assembly_type")),
        # [id, district_id, name, kind, code, lat, lng]
        "towns": [[i, d, n, k, c, float(la) if la is not None else None,
                   float(ln) if ln is not None else None]
                  for i, d, n, k, c, la, ln in Town.objects.order_by("name").values_list(
                      "id", "district_id", "name", "kind", "code", "latitude", "longitude")],
        # [id, region_id, district_id, name, kind, lat, lng]
        "stations": [[i, r, d, n, k, float(la) if la is not None else None,
                      float(ln) if ln is not None else None]
                     for i, r, d, n, k, la, ln in PoliceStation.objects.order_by("name").values_list(
                         "id", "region_id", "district_id", "name", "kind", "latitude", "longitude")],
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    result = (hashlib.md5(body).hexdigest(), body)
    cache.set(LOCATIONS_CACHE_KEY, result, None)
    return result


@receiver([post_save, post_delete], sender=Region)
@receiver([post_save, post_delete], sender=District)
@receiver([post_save, post_delete], sender=Town)
@receiver([post_save, post_delete], sender=PoliceStation)
def _locations_changed(**kwargs):
    cache.delete(LOCATIONS_CACHE_KEY)
    cache.delete_many([GEO_CACHE_KEY + n for n in GEO_FILES])


# Boundary files for the maps. The files on disk carry the database ids of the
# PC that built them; another database (e.g. the online one) numbers its regions
# and districts differently, so the ids are filled in by name when served.
GEO_FILES = ("ghana", "regions", "districts")
GEO_CACHE_KEY = "geo-json-v1-"
GEO_DIR = Path(__file__).resolve().parent / "static" / "accidents" / "geo"


def _geo_body(name):
    hit = cache.get(GEO_CACHE_KEY + name)
    if hit:
        return hit
    data = json.loads((GEO_DIR / f"{name}.geojson").read_text(encoding="utf-8"))
    if name != "ghana":
        regions = json.loads((GEO_DIR / "regions.geojson").read_text(encoding="utf-8"))
        file_region = {f["properties"]["id"]: f["properties"]["name"] for f in regions["features"]}
        region_id = dict(Region.objects.values_list("name", "id"))
        district_id = {(r, n): i for i, r, n in District.objects.values_list("id", "region_id", "name")}
        for f in data["features"]:
            p = f["properties"]
            if name == "regions":
                p["id"] = region_id.get(p.get("name"))
            else:
                p["region_id"] = region_id.get(file_region.get(p.get("region_id")))
                p["id"] = district_id.get((p["region_id"], p.get("name")))
    body = json.dumps(data, separators=(",", ":")).encode()
    cache.set(GEO_CACHE_KEY + name, body, None)
    return body


@login_required
def geo_api(request, name):
    if name not in GEO_FILES:
        return HttpResponse(status=404)
    try:
        body = _geo_body(name)
    except FileNotFoundError:        # not packaged with the server: use the plain static file
        return redirect(f"/static/accidents/geo/{name}.geojson")
    resp = HttpResponse(body, content_type="application/json")
    resp["Cache-Control"] = "private, max-age=300"
    return resp


def locations_api(request):
    etag, body = locations_json()
    quoted = f'"{etag}"'
    if request.headers.get("If-None-Match") == quoted:
        resp = HttpResponse(status=304)
    else:
        resp = HttpResponse(body, content_type="application/json")
    resp["ETag"] = quoted
    resp["Cache-Control"] = "no-cache"  # always revalidate; 304 when unchanged
    return resp


@login_required
def pins_api(request):
    """Places pinned on earlier reports whose description matches ?q= (map search)."""
    q = (request.GET.get("q") or "").strip()
    pins, seen = [], set()
    if len(q) >= 3:
        rows = (Accident.objects.exclude(latitude=None).exclude(longitude=None)
                .exclude(site_location_text="").filter(site_location_text__icontains=q)
                .order_by("-updated_at")
                .values_list("site_location_text", "latitude", "longitude",
                             "report_number", "report_year")[:40])
        for text, lat, lng, number, year in rows:
            name = " ".join(text.split())[:80]
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            pins.append({"name": name, "lat": float(lat), "lng": float(lng),
                         "report": f"{number}/{year}"})
            if len(pins) == 5:
                break
    return JsonResponse({"pins": pins})


_locator = None


def district_of_pin(lat, lng):
    """District (MMDA) containing a map pin, or None. Never stops a report being saved."""
    global _locator
    try:
        if _locator is None:
            from .geo import Locator          # reads the boundary file once (about 2 s)
            _locator = Locator()
        if not _locator.geoms:
            return None
        d = _locator.district_at(float(lat), float(lng))
        return District.objects.filter(pk=d.pk, name=d.name).first() if d else None
    except Exception:                          # boundary file missing, etc.
        return None


@login_required
def accident_edit(request, pk=None):
    instance = get_object_or_404(Accident, pk=pk) if pk else None
    data = request.POST if request.method == "POST" else None
    files = request.FILES if request.method == "POST" else None
    form = AccidentForm(data, files, instance=instance,
                        initial=None if instance else {"report_year": date.today().year})
    vfs = VehicleFormSet(data, instance=instance, prefix="vehicles")
    pfs = PassengerFormSet(data, instance=instance, prefix="passengers")
    dfs = PedestrianFormSet(data, instance=instance, prefix="pedestrians")

    check_errors, check_warnings, field_problems = [], [], []
    if request.method == "POST":
        basic_ok = all([form.is_valid(), vfs.is_valid(), pfs.is_valid(), dfs.is_valid()])
        # Consistency checks (see checks.py): errors block saving; warnings can be
        # overridden with "Save anyway" (confirm_warnings=1).
        check_errors, check_warnings = check_report(form, vfs, pfs, dfs)
        confirmed = request.POST.get("confirm_warnings") == "1"
        valid = basic_ok and not check_errors and (confirmed or not check_warnings)
        if not valid:
            field_problems = _field_problems(form, vfs, pfs, dfs)
            _highlight(check_errors, form, vfs, pfs, dfs)
        if valid:
            with transaction.atomic():
                acc = form.save(commit=False)
                new_station = form.resolve_new_station(request.user)
                if new_station:
                    acc.police_station = new_station
                    messages.info(request, f"Police station \"{new_station}\" added to the list "
                                           "(unverified until checked by an admin).")
                if instance is None:
                    acc.created_by = request.user
                # The district comes from the map pin (it is not asked on the form).
                if acc.latitude is not None and ({"latitude", "longitude"} & set(form.changed_data)
                                                 or acc.district_id is None):
                    acc.district = district_of_pin(acc.latitude, acc.longitude) or acc.district
                acc.save()
                for fs in (vfs, pfs, dfs):
                    fs.instance = acc
                    fs.save()
                if instance is None:
                    action = "created"
                elif acc.status == Accident.STATUS_REVIEWED:
                    action = "edited after approval"
                else:
                    action = "edited"
                AuditLog.objects.create(accident=acc, user=request.user, action=action)
            messages.success(request, f"Accident {acc} saved.")
            return redirect("accident_detail", pk=acc.pk)

    return render(request, "accidents/form.html", {
        "form": form, "vfs": vfs, "pfs": pfs, "dfs": dfs, "instance": instance,
        "problems": field_problems + check_errors, "warnings": check_warnings,
        "files_lost": bool(request.FILES) and request.method == "POST",
    })


ROW_NAMES = {"vehicles": "Vehicle", "passengers": "Passenger row", "pedestrians": "Pedestrian row"}


def _field_problems(form, vfs, pfs, dfs):
    """Ordinary field errors (required, invalid value...) as {msg, anchor} for the summary."""
    out = []
    for name, errs in form.errors.items():
        label = form.fields[name].label if name in form.fields else ""
        for e in errs:
            out.append({"msg": f"{label}: {e}" if label else e,
                        "anchor": f"id_{name}" if name in form.fields else ""})
    for prefix, fs in (("vehicles", vfs), ("passengers", pfs), ("pedestrians", dfs)):
        for i, f in enumerate(fs.forms):
            for name, errs in f.errors.items():
                label = f.fields[name].label if name in f.fields else ""
                for e in errs:
                    out.append({"msg": f"{ROW_NAMES[prefix]} {i + 1}: {label}: {e}",
                                "anchor": f"id_{prefix}-{i}-{name}"})
        for e in fs.non_form_errors():
            out.append({"msg": e, "anchor": f"{prefix}-section"})
    return out


def _highlight(check_errors, form, vfs, pfs, dfs):
    """Mark the fields named by consistency errors so they show in red."""
    sets = {"vehicles": vfs, "passengers": pfs, "pedestrians": dfs}
    for p in check_errors:
        a = p["anchor"]
        if not a.startswith("id_"):
            continue
        name = a[3:]
        prefix, _, rest = name.partition("-")
        try:
            if prefix in sets and rest:
                idx, field = rest.split("-", 1)
                f = sets[prefix].forms[int(idx)]
                if field not in f.errors:
                    f.errors.setdefault(field, f.error_class()).append(p["msg"])
            elif name in form.fields and name not in form.errors:
                form.errors[name] = form.error_class([p["msg"]])
        except (ValueError, IndexError):
            pass


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def _export_value(obj, field):
    v = getattr(obj, field.name)
    if field.is_relation:
        return str(v) if v else ""
    if isinstance(v, FieldFile):
        return v.name or ""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, datetime) and v.tzinfo:
        return timezone.localtime(v).replace(tzinfo=None)  # Excel has no time zones
    return v


def _fields(model, skip=()):
    return [f for f in model._meta.fields if f.name not in skip]


@login_required
def export(request, fmt):
    qs = filtered_accidents(request).select_related("created_by", "reviewed_by")
    afields = _fields(Accident, skip=("client_uuid",))

    if fmt == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="accidents.csv"'
        resp.write("﻿")  # Excel-friendly UTF-8
        w = csv.writer(resp)
        w.writerow([str(f.verbose_name) for f in afields])
        for a in qs.iterator():
            w.writerow([_export_value(a, f) for f in afields])
        return resp

    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    sheets = [
        ("Accidents", afields, qs),
        ("Vehicles", _fields(Vehicle), Vehicle.objects.filter(accident__in=qs).select_related("accident")),
        ("Passengers", _fields(PassengerCasualty),
         PassengerCasualty.objects.filter(accident__in=qs).select_related("accident")),
        ("Pedestrians", _fields(PedestrianCasualty),
         PedestrianCasualty.objects.filter(accident__in=qs).select_related("accident")),
    ]
    first = True
    for title, fields, rows in sheets:
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = title
        ws.append([str(f.verbose_name) for f in fields])
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for obj in rows:
            ws.append([_export_value(obj, f) for f in fields])

    ws = wb.create_sheet("Codebook")
    ws.append(["Field", "Code", "Meaning"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for f in _fields(Accident) + _fields(Vehicle) + _fields(PassengerCasualty) + _fields(PedestrianCasualty):
        for code, label in (f.flatchoices or []):
            if code not in (None, ""):
                ws.append([str(f.verbose_name), code, label.split(" - ", 1)[-1]])
    for code, place in cb.LICENCE_PLACE.items():
        ws.append(["43 Place of issue", code, place])
    for region, (rnum, towns) in cb.TOWN_CODES.items():
        for i, town in enumerate(towns, start=1):
            ws.append(["60 Town/village code", f"{rnum:02d}{i:02d}", f"{town} ({region})"])

    buf = io.BytesIO()
    wb.save(buf)
    resp = HttpResponse(buf.getvalue(), content_type=(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
    resp["Content-Disposition"] = 'attachment; filename="accidents.xlsx"'
    return resp


# ---------------------------------------------------------------------------
# Import from Excel (administrators): upload -> summary -> confirm
# ---------------------------------------------------------------------------
IMPORT_SHOWN = 300      # rows listed on the summary page


@login_required
def accident_import(request):
    from .importer import ImportProblem, read_workbook, save_plan

    if not request.user.is_staff:
        messages.error(request, "Only administrators can import reports from Excel.")
        return redirect("accident_list")

    ctx = {}
    if request.method == "POST":
        token = request.POST.get("token", "")
        upload = request.FILES.get("file")
        try:
            if token:                                   # step 2: confirmed
                held = cache.get(f"import:{request.user.pk}:{token}")
                if not held:
                    raise ImportProblem("That file is no longer held (it is kept for one hour). "
                                        "Choose the file again.")
                saved = save_plan(read_workbook(held["data"], request.user), request.user)
                cache.delete(f"import:{request.user.pk}:{token}")
                plural = "" if saved == 1 else "s"
                messages.success(request, f"{saved} report{plural} imported from {held['name']}.")
                return redirect("accident_list")
            if not upload:
                raise ImportProblem("Choose an Excel file first.")
            data = upload.read()                        # step 1: show what would happen
            plan = read_workbook(data, request.user)
            token = uuid.uuid4().hex
            cache.set(f"import:{request.user.pk}:{token}", {"data": data, "name": upload.name}, 3600)
            order = {"error": 0, "new": 1, "duplicate": 2}
            listed = sorted(plan["reports"], key=lambda r: (order[r["state"]], r["row"]))
            ctx = {"plan": plan, "token": token, "filename": upload.name,
                   "hidden": max(0, len(listed) - IMPORT_SHOWN),
                   "rows": [{"row": r["row"], "ref": r["ref"], "state": r["state"],
                             "region": r["obj"].region if r["obj"].region_id else "",
                             "date": r["obj"].accident_date, "n_vehicles": len(r["vehicles"]),
                             "n_casualties": len(r["passengers"]) + len(r["pedestrians"]),
                             "problems": r["problems"], "notes": r["notes"]}
                            for r in listed[:IMPORT_SHOWN]]}
        except ImportProblem as exc:
            ctx = {"problem": str(exc)}
    return render(request, "accidents/import.html", ctx)


# ---------------------------------------------------------------------------
# Offline mode was removed. Browsers that installed the old offline service
# worker fetch this replacement on their next visit: it deletes the offline
# caches, unregisters itself and reloads open pages from the server.
# ---------------------------------------------------------------------------
SW_REMOVAL = """
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) await caches.delete(key);
    await self.registration.unregister();
    for (const client of await self.clients.matchAll({ type: "window" })) client.navigate(client.url);
  })());
});
"""


def service_worker_removal(request):
    resp = HttpResponse(SW_REMOVAL, content_type="application/javascript")
    resp["Cache-Control"] = "no-cache"
    return resp
