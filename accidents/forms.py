import re
import secrets
from datetime import date

from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.forms import inlineformset_factory

from . import codebook as cb
from .importer import _full_year, _split_ref
from .models import (Accident, PassengerCasualty, PedestrianCasualty, PoliceStation, Region,
                     Vehicle)

YES_NO = [("", "---------"), ("true", "Y"), ("false", "N")]
BLANK = "Select..."      # shown in a dropdown until an option is chosen


def _code_list(choices, current):
    """Dropdown choices; a saved value that is not in the manual's list stays selectable."""
    known = {c for c, _ in choices}
    extra = [(current, f"{current} (not in the code list)")] if current and current not in known else []
    return [("", BLANK)] + choices + extra


def _style(form):
    for name, field in form.fields.items():
        w = field.widget
        if isinstance(w, forms.Select):
            w.attrs.setdefault("class", "inp")
            if getattr(field, "empty_label", None) is not None:      # region, station
                field.empty_label = BLANK
            elif not isinstance(w, forms.NullBooleanSelect):
                choices = list(field.choices)
                if choices and choices[0][0] == "":
                    field.choices = [("", BLANK)] + choices[1:]
        elif isinstance(w, forms.Textarea):
            w.attrs.update({"class": "inp", "rows": 3})
        elif not isinstance(w, (forms.CheckboxInput, forms.ClearableFileInput)):
            w.attrs.setdefault("class", "inp")


class FirstAdminForm(UserCreationForm):
    """Creates the very first account, which is always an administrator."""
    setup_code = forms.CharField(label="Setup code", widget=forms.PasswordInput,
                                 help_text="The DJANGO_SETUP_CODE value set for this site.")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["first_name", "last_name", "email", "username"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not settings.FIRST_ADMIN_CODE:
            del self.fields["setup_code"]
        for name in ("first_name", "last_name"):
            self.fields[name].required = True
        self.fields["username"].help_text = "The name you will log in with."
        self.fields["password1"].help_text = "At least 8 characters, and not only numbers."
        self.fields["password2"].help_text = ""
        _style(self)

    def clean_setup_code(self):
        code = self.cleaned_data["setup_code"]
        if not secrets.compare_digest(code.encode(), settings.FIRST_ADMIN_CODE.encode()):
            raise forms.ValidationError("That setup code is not correct.")
        return code

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = user.is_superuser = True
        if commit:
            user.save()
        return user


class AccidentForm(forms.ModelForm):
    new_police_station = forms.CharField(
        label="Station not in the list? Type its name", max_length=120, required=False,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Dzodze Police Station"}),
        help_text="It is added to the station list (marked unverified) for this region.")

    # 5-7 Day/Month/Year are one date picker. 8 Day of week is worked out from it.
    day_of_week_display = forms.CharField(
        label="8 Day of week", required=False, disabled=True,
        help_text="Filled in automatically from the date.")

    # Sections follow the paper form. The vehicle, passenger and pedestrian
    # tables (29-58) are shown between SECTIONS[:7] and SECTIONS[7:].
    LOCATION_SECTION = "Site location"
    SECTIONS = [
        ("Report (1)", ["report_number", "report_year"]),
        ("Where (2-3)", ["region", "road_name", "police_station",
                         "new_police_station"]),
        # Drawn by _location.html: the typed description plus the map pin.
        (LOCATION_SECTION, ["site_location_text", "latitude", "longitude"]),
        ("Vehicles, date & time (4-9)", ["num_vehicles", "accident_date", "day_of_week_display", "accident_time"]),
        ("Casualties & severity (10-12)", ["killed", "injured", "severity"]),
        ("Road & conditions (13-22)", ["weather", "light_conditions", "road_description",
                                       "bridge_river_name", "road_surface_type", "shoulder_type",
                                       "shoulder_condition", "road_separation", "road_width_m",
                                       "road_type", "surface_condition", "surface_repair"]),
        ("Junction & collision (23-28)", ["location_type", "traffic_control", "collision_type",
                                          "hit_and_run", "roadworks", "collision_code",
                                          "speed_limit"]),
        ("Location coding (59-68)", ["loc_type", "town_code", "km", "hundred_m",
                                     "route_number", "x_coordinate", "y_coordinate",
                                     "node_1", "node_2", "direction", "landmark"]),
        ("Description & sketches (69)", ["police_description", "scene_sketch", "site_sketch"]),
    ]
    SECTIONS_BEFORE_PEOPLE = 7
    # Form-only fields -> what the record detail page shows instead.
    DETAIL_FIELDS = {"day_of_week_display": "day_of_week", "new_police_station": None}

    class Meta:
        model = Accident
        # District and town are not entered: the district is worked out from the map pin.
        exclude = ["client_uuid", "status", "analyst_notes", "created_by", "reviewed_by",
                   "district", "town"]
        labels = {"accident_date": "5-7 Date of accident", "latitude": "Latitude",
                  "longitude": "Longitude", "site_location_text": "Describe the place"}
        help_texts = {"site_location_text": "The landmark or junction as the police wrote it, "
                                            "e.g. Tech Roundabout, or 200 m past Ejisu junction "
                                            "towards Kumasi."}
        widgets = {
            "latitude": forms.NumberInput(attrs={"step": "any", "placeholder": "e.g. 6.674500"}),
            "longitude": forms.NumberInput(attrs={"step": "any", "placeholder": "e.g. -1.571600"}),
            "accident_date": forms.DateInput(attrs={"type": "date", "min": "1990-01-01"},
                                             format="%Y-%m-%d"),
            "accident_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)
        if self.instance.accident_date:
            self.initial["day_of_week_display"] = self.instance.get_day_of_week_display() or ""
        self.fields["accident_date"].widget.attrs["max"] = date.today().isoformat()
        self.fields["day_of_week_display"].widget.attrs.update(
            {"readonly": True, "tabindex": "-1", "placeholder": "Set from the date"})
        # 10-12 are counted by the page from the drivers, passengers and
        # pedestrians entered (app.js); checks.py still verifies them on save.
        counted = "Counted automatically from the people you enter below."
        self.fields["killed"].help_text = counted
        self.fields["injured"].help_text = counted
        self.fields["severity"].help_text = "Worked out automatically from the people you enter below."
        self.fields["bridge_river_name"].label = "15 Bridge - name of the river"
        self.fields["collision_code"].help_text = ("From the coding manual. The first digit is the kind "
                                                   "of collision (1 pedestrian, 4 head on, 5 rear end...).")
        # 1 Report number: old reports are written with the year attached (237/15).
        self.fields["report_number"].help_text = ("You can type it with the year, e.g. 237/15. "
                                                  "The year box is then filled in for you.")
        self.fields["report_number"].widget.attrs["placeholder"] = "e.g. 237 or 237/15"
        self.fields["report_year"].help_text = "Two digits are enough: 15 becomes 2015."
        # 2 Region: listed with its number from the coding manual (1 = Ashanti), in
        # number order, so the number can be typed on the keyboard to choose it.
        numbers = {name: number for name, (number, _) in cb.TOWN_CODES.items()}
        regions = sorted(Region.objects.all(), key=lambda r: (numbers.get(r.name, 99), r.name))
        self.fields["region"].choices = [("", BLANK)] + [
            (r.pk, f"{numbers[r.name]} - {r.name}" if r.name in numbers else r.name) for r in regions]
        self.fields["region"].help_text = "Choose the name, or type the region number (1 = Ashanti)."
        # 60 Town/village code: the manual's towns for the region chosen in 2.
        # The page swaps the list when the region changes (app.js, "town-codes").
        saved = self.instance.town_code or ""
        self.fields["town_code"] = forms.ChoiceField(
            label=Accident._meta.get_field("town_code").verbose_name, required=False,
            choices=_code_list(cb.town_code_choices(self._region_name()), saved),
            help_text="Towns from the coding manual for the region chosen in 2. "
                      "You can type the code, e.g. 0101.",
            widget=forms.Select(attrs={"class": "inp"}))

    def _region_name(self):
        rid = self.data.get(self.add_prefix("region")) if self.is_bound else (
            self.instance.region_id or self.initial.get("region"))
        try:
            return Region.objects.get(pk=int(rid)).name if rid else ""
        except (ValueError, TypeError, Region.DoesNotExist):
            return ""

    def town_codes(self):
        """{region id: [[code, label], ...]} for the page script."""
        names = dict(Region.objects.values_list("name", "id"))
        return {names[n]: cb.town_code_choices(n) for n in cb.TOWN_CODES if n in names}

    def _section_list(self, specs):
        return [(title, [self[n] for n in names]) for title, names in specs]

    def location_section(self):
        return self.LOCATION_SECTION

    def sections(self):
        return self._section_list(self.SECTIONS)

    def sections_before_people(self):
        return self._section_list(self.SECTIONS[:self.SECTIONS_BEFORE_PEOPLE])

    def sections_after_people(self):
        return self._section_list(self.SECTIONS[self.SECTIONS_BEFORE_PEOPLE:])

    def clean_report_year(self):
        year = self.cleaned_data["report_year"]
        return _full_year(year) if year is not None else year      # 15 -> 2015

    def clean(self):
        data = super().clean()
        # "237/15" typed in the report number: number 237, year 2015.
        number, year = _split_ref(data.get("report_number") or "")
        if year:
            data["report_number"], data["report_year"] = number, year
            if "report_year" in self.errors:        # the year box was left empty
                del self.errors["report_year"]
        acc_date = data.get("accident_date")
        if acc_date and acc_date > date.today():
            self.add_error("accident_date", "The accident date is in the future.")
        elif acc_date and acc_date.year < 1990:
            self.add_error("accident_date", "The accident date is before 1990 - check.")
        region = data.get("region")
        station = data.get("police_station")
        new_station = re.sub(r"\s+", " ", data.get("new_police_station") or "").strip()
        data["new_police_station"] = new_station
        if station and new_station:
            self.add_error("new_police_station",
                           "Choose a station from the list or type a new one, not both.")
        if station and region and station.region_id != region.id:
            self.add_error("police_station", "This police station is not in the selected region.")
        # Map pin: both numbers or neither, and inside Ghana.
        lat, lng = data.get("latitude"), data.get("longitude")
        if (lat is None) != (lng is None):
            self.add_error("latitude" if lat is None else "longitude",
                           "The map pin needs both latitude and longitude.")
        elif lat is not None and not (4.5 <= lat <= 11.3 and -3.4 <= lng <= 1.3):
            self.add_error("latitude", "The map pin is outside Ghana - place it again on the map.")
        acc_date = data.get("accident_date")
        report_year = data.get("report_year")
        if acc_date and report_year and abs(acc_date.year - report_year) > 1:
            self.add_error("report_year", "Report year is far from the accident date - check.")
        return data

    def resolve_new_station(self, user):
        """Return the station typed in 'new_police_station', creating it if needed."""
        name = self.cleaned_data.get("new_police_station")
        if not name:
            return None
        region = self.cleaned_data["region"]
        if not re.search(r"police|mttu|mttd|headquarters", name, re.I):
            name += " Police Station"
        existing = PoliceStation.objects.filter(region=region, name__iexact=name).first()
        if existing:
            return existing
        return PoliceStation.objects.create(
            region=region, name=name,
            source="user", verified=False, added_by=user)


class _RowForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class VehicleForm(_RowForm):
    class Meta:
        model = Vehicle
        exclude = ["accident"]
        widgets = {
            "licence_issue_date": forms.DateInput(attrs={"type": "date"}),
            "licence_expiry_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # No default number: the page numbers each vehicle section (1, 2, 3...),
        # so every section shown counts as a vehicle, even with few details.
        # It is not shown either: the section title says "Vehicle 1", "Vehicle 2"...
        self.fields["vehicle_no"].initial = None
        self.fields["vehicle_no"].widget = forms.HiddenInput()
        # 43 Place of issue: the licence offices in the coding manual, stored as "AS1".
        self.fields["licence_place_of_issue"] = forms.ChoiceField(
            label="43 Place of issue", required=False,
            choices=_code_list([(k, f"{k} - {v}") for k, v in cb.LICENCE_PLACE.items()],
                               self.instance.licence_place_of_issue or ""),
            widget=forms.Select(attrs={"class": "inp"}))
        self.fields["registration_code"].help_text = "Filled in from the number plate. Change it if wrong."


class PassengerForm(_RowForm):
    class Meta:
        model = PassengerCasualty
        exclude = ["accident"]
        widgets = {"helmet_belt": forms.NullBooleanSelect()}


class PedestrianForm(_RowForm):
    class Meta:
        model = PedestrianCasualty
        exclude = ["accident"]
        widgets = {"std": forms.NullBooleanSelect()}


VehicleFormSet = inlineformset_factory(Accident, Vehicle, form=VehicleForm, extra=0, can_delete=True)
PassengerFormSet = inlineformset_factory(Accident, PassengerCasualty, form=PassengerForm,
                                         extra=0, can_delete=True)
PedestrianFormSet = inlineformset_factory(Accident, PedestrianCasualty, form=PedestrianForm,
                                          extra=0, can_delete=True)


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Accident
        fields = ["status", "analyst_notes"]
        widgets = {"analyst_notes": forms.Textarea(attrs={"rows": 3, "class": "inp"}),
                   "status": forms.Select(attrs={"class": "inp"})}
