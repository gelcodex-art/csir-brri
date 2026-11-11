import uuid

from django.conf import settings
from django.db import models

from . import codebook as cb


def coded(codes, label, **kw):
    """Integer field holding a form code (e.g. 13 Weather: 1..6)."""
    return models.PositiveSmallIntegerField(
        label, choices=cb.choices(codes), null=True, blank=True, **kw
    )


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
class Region(models.Model):
    name = models.CharField(max_length=60, unique=True)
    capital = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class District(models.Model):
    """A Metropolitan, Municipal or District Assembly (MMDA)."""
    TYPES = [("metropolitan", "Metropolitan"), ("municipal", "Municipal"), ("district", "District")]

    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="districts")
    name = models.CharField(max_length=120)
    assembly_type = models.CharField(max_length=12, choices=TYPES, default="district")
    capital = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["region__name", "name"]
        unique_together = [("region", "name")]

    def __str__(self):
        return self.name


class Town(models.Model):
    KINDS = [("city", "City"), ("town", "Town"), ("suburb", "Suburb"), ("village", "Village"),
             ("hamlet", "Hamlet"), ("locality", "Locality")]

    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="towns")
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=KINDS, default="village")
    code = models.CharField("60 Town/Village code", max_length=10, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # e.g. "osm:123456" or "geonames:2306104"; blank for towns added by hand.
    source = models.CharField(max_length=40, blank=True, db_index=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["district", "name"])]

    def __str__(self):
        return f"{self.name} ({self.code})" if self.code else self.name


class PoliceStation(models.Model):
    KINDS = [
        ("national_hq", "National Headquarters"),
        ("regional_hq", "Regional Headquarters"),
        ("divisional_hq", "Divisional Headquarters"),
        ("district_hq", "District Headquarters"),
        ("station", "Police Station"),
        ("post", "Police Post"),
        ("mttd", "MTTD / MTTU office"),
    ]

    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="stations")
    district = models.ForeignKey(District, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="stations", verbose_name="District (MMDA)")
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=14, choices=KINDS, default="station")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # "osm:node/123", "csv", or "user" (added by an analyst from the report form).
    source = models.CharField(max_length=40, blank=True, db_index=True)
    verified = models.BooleanField(default=False, help_text="Checked by BRRI against the official list.")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name="+")

    class Meta:
        ordering = ["name"]
        unique_together = [("region", "name")]

    def __str__(self):
        return self.name


class StationCode(models.Model):
    """The code BRRI writes for a police station: region number + station number
    ("04086" = Eastern, Nsawam). A station can have two: its code in the old
    region and its code in the new one. See station_codes.py."""
    code = models.CharField(max_length=5, unique=True,
                            help_text="Five digits: region number, then station number (04086).")
    station = models.ForeignKey(PoliceStation, on_delete=models.CASCADE, related_name="codes")

    class Meta:
        ordering = ["code"]
        verbose_name = "station code"

    def __str__(self):
        return self.code


# ---------------------------------------------------------------------------
# Accident report (fields 1-28 and 59-69)
# ---------------------------------------------------------------------------
class Accident(models.Model):
    STATUS_SUBMITTED = "submitted"
    STATUS_REVIEWED = "reviewed"
    STATUS_QUERY = "query"
    STATUS_CHOICES = [
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_REVIEWED, "Approved"),
        (STATUS_QUERY, "Needs query"),
    ]

    # Permanent unique id for the record (stable across systems/exports merges).
    client_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # 1-3
    report_number = models.CharField("1 Report number", max_length=30)
    report_year = models.PositiveSmallIntegerField("1 Report year")
    region = models.ForeignKey(Region, on_delete=models.PROTECT, verbose_name="2 Region")
    district = models.ForeignKey(District, on_delete=models.PROTECT, null=True, blank=True)
    town = models.ForeignKey(Town, on_delete=models.PROTECT, null=True, blank=True,
                             verbose_name="Town / village")
    road_name = models.CharField("2 Road name", max_length=150, blank=True)
    police_station = models.ForeignKey(PoliceStation, on_delete=models.PROTECT, null=True,
                                       blank=True, verbose_name="3 Police station")

    # 4-11
    num_vehicles = models.PositiveSmallIntegerField("4 No. of vehicles involved", null=True, blank=True)
    accident_date = models.DateField("5-7 Date of accident (day/month/year)")
    day_of_week = coded(cb.DAY_OF_WEEK, "8 Day of week", editable=False)
    accident_time = models.TimeField("9 Time (24hrs)", null=True, blank=True)
    killed = models.PositiveSmallIntegerField("10 No. casualties killed", default=0)
    injured = models.PositiveSmallIntegerField("11 No. casualties injured", default=0)

    # 12-28
    severity = coded(cb.ACCIDENT_SEVERITY, "12 Accident severity")
    weather = coded(cb.WEATHER, "13 Weather")
    light_conditions = coded(cb.LIGHT_CONDITIONS, "14 Light conditions")
    road_description = coded(cb.ROAD_DESCRIPTION, "15 Road description")
    bridge_river_name = models.CharField("15 Bridge - river name", max_length=100, blank=True)
    road_surface_type = coded(cb.ROAD_SURFACE_TYPE, "16 Road surface type")
    shoulder_type = coded(cb.SHOULDER_TYPE, "17 Shoulder type")
    shoulder_condition = coded(cb.SHOULDER_CONDITION, "18 Shoulder condition")
    road_separation = coded(cb.ROAD_SEPARATION, "19 Road separation")
    road_width_m = models.DecimalField("20 Road width (m)", max_digits=5, decimal_places=1,
                                       null=True, blank=True)
    road_type = coded(cb.ROAD_TYPE, "Road type")
    surface_condition = coded(cb.SURFACE_CONDITION, "21 Surface condition")
    surface_repair = coded(cb.SURFACE_REPAIR, "22 Surface repair")
    location_type = coded(cb.LOCATION_TYPE, "23 Location type")
    traffic_control = coded(cb.TRAFFIC_CONTROL, "24 Traffic control")
    collision_type = coded(cb.COLLISION_TYPE, "25 Collision type")
    hit_and_run = coded(cb.HIT_AND_RUN, "26 Hit and run")
    roadworks = coded(cb.ROADWORKS, "27 Roadworks")
    collision_code = models.CharField("28 Collision code", max_length=4, blank=True,
                                      choices=cb.collision_code_choices())
    speed_limit = models.PositiveSmallIntegerField("Speed limit (km/h)", null=True, blank=True)

    # 59-69 location coding
    loc_type = models.CharField("59 Type", max_length=2, blank=True)
    town_code = models.CharField("60 Town/village code", max_length=10, blank=True)
    km = models.PositiveSmallIntegerField("61 Km", null=True, blank=True)
    hundred_m = models.PositiveSmallIntegerField("62 100m", null=True, blank=True)
    route_number = models.CharField("63 Route number", max_length=10, blank=True)
    x_coordinate = models.CharField("64 X co-ordinate", max_length=10, blank=True)
    y_coordinate = models.CharField("65 Y co-ordinate", max_length=10, blank=True)
    node_1 = models.CharField("66 Node 1", max_length=6, blank=True)
    node_2 = models.CharField("67 Node 2", max_length=6, blank=True)
    direction = coded(cb.VEHICLE_DIRECTION, "68 Direction")
    latitude = models.DecimalField("GPS latitude", max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField("GPS longitude", max_digits=9, decimal_places=6, null=True, blank=True)
    landmark = coded(cb.LANDMARK, "Landmark")
    police_description = models.TextField("69 Police description of accident", blank=True)
    scene_sketch = models.FileField("Sketch of the accident scene", upload_to="sketches/%Y/",
                                    blank=True)
    site_sketch = models.FileField("Site location sketch", upload_to="sketches/%Y/", blank=True)
    site_location_text = models.TextField(
        "Site location (typed)", blank=True,
        help_text="Describe where the accident happened, e.g. 200 m past Ejisu junction, "
                  "towards Kumasi, opposite the Total filling station.")

    # Generated demo record (manage.py load_sample_data); remove with --delete.
    is_sample = models.BooleanField(default=False, editable=False, db_index=True)

    # Workflow
    status =models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_SUBMITTED)
    analyst_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, related_name="+")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-accident_date", "-accident_time"]
        verbose_name = "accident report"
        indexes = [
            models.Index(fields=["accident_date"]),
            models.Index(fields=["region", "accident_date"]),
            models.Index(fields=["report_year", "report_number"]),
        ]

    def __str__(self):
        return f"{self.report_number}/{self.report_year}"

    def save(self, *args, **kwargs):
        if self.accident_date:
            self.day_of_week = self.accident_date.isoweekday()  # Mon=1 ... Sun=7, as on form
        if self.town and not self.town_code:
            self.town_code = self.town.code
        super().save(*args, **kwargs)

    def possible_duplicates(self):
        """Same report number+year, or same date+region+town+time."""
        same_report = models.Q(report_number=self.report_number, report_year=self.report_year)
        same_event = models.Q(accident_date=self.accident_date, region=self.region,
                              town=self.town, accident_time=self.accident_time)
        return Accident.objects.filter(same_report | same_event).exclude(pk=self.pk)


# ---------------------------------------------------------------------------
# Vehicle & driver (fields 29-45), one row per vehicle
# ---------------------------------------------------------------------------
class Vehicle(models.Model):
    accident = models.ForeignKey(Accident, on_delete=models.CASCADE, related_name="vehicles")
    vehicle_no = models.PositiveSmallIntegerField("Veh no.", default=1)
    vehicle_type = coded(cb.VEHICLE_TYPE, "29 Vehicle type")
    registration_no = models.CharField("30 Registration no.", max_length=20, blank=True)
    registration_code = coded(cb.VEHICLE_REG_CODE, "30 Registration code")
    ownership = coded(cb.OWNERSHIP_USAGE, "31 Ownership/usage")
    manoeuvre = coded(cb.VEHICLE_MANOEUVRE, "32 Vehicle manoeuvre")
    damage = coded(cb.VEHICLE_DAMAGE, "33 Vehicle damage")
    defects = coded(cb.VEHICLE_DEFECTS, "34 Defects")
    direction = coded(cb.VEHICLE_DIRECTION, "35 Vehicle direction")
    driver_name = models.CharField("36 Driver name", max_length=120, blank=True)
    driver_sex = coded(cb.SEX, "37 Sex")
    driver_age = models.PositiveSmallIntegerField("38 Age", null=True, blank=True)
    driver_nationality = coded(cb.NATIONALITY, "39 Nationality")
    driver_injury = coded(cb.DRIVER_INJURY, "40 Driver injury")
    licence_no = models.CharField("41 Licence no.", max_length=30, blank=True)
    driver_education = coded(cb.DRIVER_EDUCATION, "Driver's education")
    licence_status = coded(cb.LICENCE_STATUS, "42 Licence status")
    licence_place_of_issue = models.CharField("43 Place of issue", max_length=60, blank=True)
    licence_issue_date = models.DateField("Issue date", null=True, blank=True)
    licence_expiry_date = models.DateField("Expiry date", null=True, blank=True)
    drink_drugs = coded(cb.DRINK_DRUGGED_DRIVING, "44 Drink/drugged driving")
    driver_error = coded(cb.DRIVER_ERROR, "45 Driver error")

    class Meta:
        ordering = ["vehicle_no"]


class PassengerCasualty(models.Model):
    accident = models.ForeignKey(Accident, on_delete=models.CASCADE, related_name="passengers")
    name = models.CharField("Name", max_length=120, blank=True)
    vehicle_no = models.PositiveSmallIntegerField("46 Veh no.", null=True, blank=True)
    sex = coded(cb.SEX, "47 Sex")
    age = models.PositiveSmallIntegerField("48 Age", null=True, blank=True)
    severity = coded(cb.INJURY_SEVERITY, "49 Severity")
    position = coded(cb.PASSENGER_POSITION, "50 Position")
    action = coded(cb.PASSENGER_ACTION, "51 Action")
    helmet_belt = models.BooleanField("Helmet/belt Y/N", null=True, blank=True)


class PedestrianCasualty(models.Model):
    accident = models.ForeignKey(Accident, on_delete=models.CASCADE, related_name="pedestrians")
    name = models.CharField("Name", max_length=120, blank=True)
    vehicle_no = models.PositiveSmallIntegerField("52 Veh no.", null=True, blank=True)
    sex = coded(cb.SEX, "53 Sex")
    age = models.PositiveSmallIntegerField("54 Age", null=True, blank=True)
    severity = coded(cb.INJURY_SEVERITY, "55 Severity")
    action = coded(cb.PEDESTRIAN_ACTION, "56 Action")
    location = coded(cb.PEDESTRIAN_LOCATION, "57 Location")
    drink_drugs = coded(cb.PEDESTRIAN_DRINK_DRUGS, "58 Drink/drugs")
    std = models.BooleanField("STD Y/N", null=True, blank=True)
    nationality = coded(cb.NATIONALITY, "Nationality")


class AuditLog(models.Model):
    accident = models.ForeignKey(Accident, on_delete=models.CASCADE, related_name="audit")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=40)
    note = models.CharField(max_length=255, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]
        verbose_name = "change history entry"
        verbose_name_plural = "change history"
