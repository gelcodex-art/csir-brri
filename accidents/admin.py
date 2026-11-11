"""Administrator area (/admin/).

What it is for:
  * analyst accounts - add people, reset passwords, switch accounts off;
  * police stations  - check the stations analysts typed in on the report form;
  * reference lists  - regions, districts and towns;
  * reports          - look up any report, and delete one entered by mistake;
  * change history   - who created, edited or approved what (read-only).

Reports are entered and edited in the main app, never here: the app runs the
checks in checks.py and writes the change history, the admin would skip both.
"""
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group, User
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from .models import Accident, AuditLog, District, PoliceStation, Region, StationCode, Town

# Groups and per-table permissions are not used: an account is either an
# analyst or an administrator.
admin.site.unregister(Group)
admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ["username", "full_name", "role", "is_active", "last_login"]
    list_filter = ["is_superuser", "is_active"]
    search_fields = ["username", "first_name", "last_name", "email"]
    ordering = ["username"]
    fieldsets = [
        (None, {"fields": ["username", "password"]}),
        ("Person", {"fields": ["first_name", "last_name", "email"]}),
        ("Access", {"fields": ["is_active", "is_superuser"]}),
        ("Activity", {"fields": ["last_login", "date_joined"]}),
    ]
    add_fieldsets = [
        (None, {"classes": ["wide"], "fields": ["username", "password1", "password2"]}),
        ("Person", {"classes": ["wide"], "fields": ["first_name", "last_name", "email"]}),
        ("Access", {"classes": ["wide"], "fields": ["is_superuser"]}),
    ]
    readonly_fields = ["last_login", "date_joined"]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        f = form.base_fields
        if "is_superuser" in f:
            f["is_superuser"].label = "Administrator"
            f["is_superuser"].help_text = (
                "Administrators can open this admin area: manage accounts, check police "
                "stations and delete reports. Leave unticked for a normal analyst.")
        if "is_active" in f:
            f["is_active"].label = "Can log in"
            f["is_active"].help_text = ("Untick when someone leaves BRRI, instead of deleting the "
                                        "account - their reports and history keep their name.")
        return form

    def save_model(self, request, obj, form, change):
        # You cannot lock yourself out of the admin area.
        if change and obj.pk == request.user.pk and not (obj.is_superuser and obj.is_active):
            obj.is_superuser = obj.is_active = True
            messages.warning(request, "You cannot remove your own administrator access or switch "
                                      "off your own account. Ask another administrator to do it.")
        obj.is_staff = obj.is_superuser   # one switch: administrator or not
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.pk == request.user.pk:
            return False
        return super().has_delete_permission(request, obj)

    @admin.display(description="Name")
    def full_name(self, obj):
        return obj.get_full_name() or "-"

    @admin.display(description="Role", ordering="is_superuser")
    def role(self, obj):
        return "Administrator" if obj.is_superuser else "Analyst"


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ["name", "capital", "n_districts"]
    search_fields = ["name"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_n=Count("districts"))

    @admin.display(description="Districts", ordering="_n")
    def n_districts(self, obj):
        return obj._n


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ["name", "assembly_type", "capital", "region"]
    list_filter = ["assembly_type", "region"]
    search_fields = ["name", "capital"]
    list_select_related = ["region"]


@admin.register(Town)
class TownAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "code", "district", "latitude", "longitude"]
    list_filter = ["kind", "district__region"]
    search_fields = ["name", "code"]
    autocomplete_fields = ["district"]
    list_select_related = ["district"]
    readonly_fields = ["source"]
    list_per_page = 50
    show_full_result_count = False


class StationSourceFilter(admin.SimpleListFilter):
    title = "source"
    parameter_name = "src"

    def lookups(self, request, model_admin):
        return [("osm", "OpenStreetMap"), ("codes", "BRRI code list"),
                ("user", "Added by analysts"), ("csv", "CSV import"),
                ("manual", "Entered in admin")]

    def queryset(self, request, qs):
        v = self.value()
        if v == "osm":
            return qs.filter(source__startswith="osm:")
        if v in ("user", "csv", "codes"):
            return qs.filter(source=v)
        if v == "manual":
            return qs.filter(source="")
        return qs


class StationCodeInline(admin.TabularInline):
    model = StationCode
    extra = 1
    verbose_name = "code"
    verbose_name_plural = "Station codes (region number + station number, e.g. 04086)"


@admin.register(PoliceStation)
class PoliceStationAdmin(admin.ModelAdmin):
    list_display = ["name", "code_list", "kind", "district", "region", "verified", "source_label",
                    "reports"]
    list_filter = ["verified", StationSourceFilter, "kind", "region"]
    search_fields = ["name", "district__name", "codes__code"]
    inlines = [StationCodeInline]
    autocomplete_fields = ["district"]
    readonly_fields = ["source", "added_by"]
    actions = ["mark_verified", "mark_unverified"]
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("district", "region", "added_by").annotate(
            n_reports=Count("accident", distinct=True)).prefetch_related("codes")

    @admin.display(description="Code")
    def code_list(self, obj):
        return ", ".join(c.code for c in obj.codes.all()) or "-"

    @admin.display(description="Reports", ordering="n_reports")
    def reports(self, obj):
        return obj.n_reports

    @admin.display(description="Source")
    def source_label(self, obj):
        if obj.source.startswith("osm:"):
            return "OpenStreetMap"
        return {"user": f"Analyst ({obj.added_by or '?'})", "csv": "CSV import",
                "codes": "BRRI code list", "import": "Excel import"}.get(obj.source, "Admin")

    @admin.action(description="Mark selected stations as verified")
    def mark_verified(self, request, qs):
        self.message_user(request, f"{qs.update(verified=True)} station(s) marked verified.")

    @admin.action(description="Mark selected stations as NOT verified")
    def mark_unverified(self, request, qs):
        self.message_user(request, f"{qs.update(verified=False)} station(s) marked not verified.")


@admin.register(Accident)
class AccidentAdmin(admin.ModelAdmin):
    """Look up and delete only. Reports are created and edited in the main app."""
    list_display = ["__str__", "accident_date", "region", "police_station", "severity", "killed",
                    "injured", "status", "created_by", "open_in_app"]
    list_filter = ["status", "severity", "is_sample", "region"]
    search_fields = ["report_number", "road_name", "police_station__name"]
    date_hierarchy = "accident_date"
    list_select_related = ["region", "police_station", "created_by"]
    fields = ["open_in_app", "report_number", "report_year", "accident_date", "accident_time",
              "region", "road_name", "police_station", "severity", "killed", "injured", "status",
              "analyst_notes", "created_by", "created_at", "reviewed_by", "updated_at"]
    readonly_fields = ["open_in_app", "created_at", "updated_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Full report")
    def open_in_app(self, obj):
        return format_html('<a href="{}">Open report</a>', reverse("accident_detail", args=[obj.pk]))


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """The change history is a record: nobody adds, edits or deletes entries."""
    list_display = ["at", "accident", "user", "action", "note"]
    list_filter = ["action", "user"]
    search_fields = ["accident__report_number", "note"]
    date_hierarchy = "at"
    list_select_related = ["accident", "user"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Entries go only together with their report, when that report is deleted.
        match = request.resolver_match
        return bool(match and (match.url_name or "").startswith("accidents_accident_"))
