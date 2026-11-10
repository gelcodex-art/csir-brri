import uuid

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from .models import Accident, District, PoliceStation, Region, Town


def mgmt(prefix, total=0, initial=0):
    return {f"{prefix}-TOTAL_FORMS": str(total), f"{prefix}-INITIAL_FORMS": str(initial),
            f"{prefix}-MIN_NUM_FORMS": "0", f"{prefix}-MAX_NUM_FORMS": "1000"}


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class AccidentFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_locations", stdout=open("nul" if __import__("os").name == "nt" else "/dev/null", "w"))
        cls.user = User.objects.create_user("analyst", password="pw-12345-test")
        cls.region = Region.objects.get(name="Ashanti")
        cls.district = District.objects.get(region=cls.region)
        cls.town = Town.objects.get(district=cls.district)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client.login(username="analyst", password="pw-12345-test")

    def payload(self, **extra):
        data = {
            "client_uuid": str(uuid.uuid4()),
            "report_number": "123", "report_year": "2026",
            "region": self.region.pk, "district": self.district.pk, "town": self.town.pk,
            "road_name": "Kumasi-Accra Rd", "accident_time": "18:30",
            "accident_date": "2026-11-02",
            # 1 killed (passenger, 49=1) and 1 injured (driver of vehicle 1, 40=2) -> severity 1.
            "killed": "1", "injured": "1", "severity": "1", "weather": "3", "collision_type": "1",
            "light_conditions": "1",
            "confirm_warnings": "1",   # most tests are not about the reminders (see check tests)
            "latitude": "6.690000", "longitude": "-1.620000",
            **mgmt("vehicles", 2), **mgmt("passengers", 1), **mgmt("pedestrians", 0),
            "vehicles-0-vehicle_no": "1", "vehicles-0-vehicle_type": "5", "vehicles-0-driver_error": "4",
            "vehicles-0-driver_injury": "2",
            "vehicles-1-vehicle_no": "2", "vehicles-1-vehicle_type": "1",
            "passengers-0-vehicle_no": "1", "passengers-0-severity": "1", "passengers-0-position": "4",
        }
        data.update(extra)
        return data

    def edit_payload(self, a, **extra):
        """POST data for editing saved report `a`, as the edit page would send it."""
        data = {k: v for k, v in self.payload().items() if not k.startswith(("vehicles-", "passengers-"))}
        vehicles = list(a.vehicles.order_by("vehicle_no"))
        passengers = list(a.passengers.all())
        data.update(mgmt("vehicles", len(vehicles), len(vehicles)))
        data.update(mgmt("passengers", len(passengers), len(passengers)))
        for i, v in enumerate(vehicles):
            data.update({f"vehicles-{i}-id": v.pk, f"vehicles-{i}-vehicle_no": v.vehicle_no,
                         f"vehicles-{i}-vehicle_type": v.vehicle_type or "",
                         f"vehicles-{i}-driver_injury": v.driver_injury or ""})
        for i, p in enumerate(passengers):
            data.update({f"passengers-{i}-id": p.pk, f"passengers-{i}-vehicle_no": p.vehicle_no or "",
                         f"passengers-{i}-severity": p.severity or "",
                         f"passengers-{i}-position": p.position or ""})
        data["num_vehicles"] = len(vehicles)
        data.update(extra)
        return data

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get("/").status_code, 302)
        r = self.client.post("/accidents/new/", self.payload())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Accident.objects.count(), 0)

    def test_form_renders(self):
        r = self.client.get("/accidents/new/")
        self.assertContains(r, "13 Weather")
        # District and town are not asked: the district comes from the map pin.
        for gone in ('id="id_district"', 'id="id_town"', 'id="town-search"'):
            self.assertNotContains(r, gone)
        for there in ('id="pick-map"', 'id="id_latitude"', 'id="id_site_location_text"', "picker.js"):
            self.assertContains(r, there)

    # ---- Codes from the BRRI coding manual -------------------------------------------
    def test_manual_codes_on_the_form(self):
        page = self.client.get("/accidents/new/").content.decode()
        self.assertIn('<optgroup label="5 - Same direction (rear end)">', page)
        self.assertIn("51 - Vehicle moves into vehicle ahead", page)
        self.assertIn("AS1 - Kumasi", page)                      # 43 Place of issue
        self.assertIn("1 - AS - Ashanti", page)                  # 30 Registration code
        self.assertIn("4 - Europe/North America", page)          # 39 Nationality
        self.assertIn('"0126", "0126 - Asokore Mampong"', page)  # 60 list for the page script
        self.client.post("/accidents/new/", self.payload(**{
            "collision_code": "51", "town_code": "0101", "vehicles-0-licence_place_of_issue": "AS1",
            "vehicles-0-registration_code": "1", "vehicles-0-driver_nationality": "1"}))
        a = Accident.objects.get()
        v = a.vehicles.get(vehicle_no=1)
        self.assertEqual((a.collision_code, a.town_code), ("51", "0101"))
        self.assertEqual((v.licence_place_of_issue, v.registration_code, v.driver_nationality), ("AS1", 1, 1))
        detail = self.client.get(f"/accidents/{a.pk}/")
        self.assertContains(detail, "51 - Vehicle moves into vehicle ahead")
        self.assertContains(detail, "0101 - Kumasi")
        edit = self.client.get(f"/accidents/{a.pk}/edit/")
        self.assertContains(edit, '<option value="0101" selected>0101 - Kumasi</option>')

    def test_town_code_must_belong_to_the_region(self):
        r = self.client.post("/accidents/new/", self.payload(town_code="0501"))   # Accra, not Ashanti
        self.assertIn("town_code", r.context["form"].errors)
        self.assertEqual(Accident.objects.count(), 0)

    def test_old_values_not_in_the_manual_are_kept(self):
        self.client.post("/accidents/new/", self.payload())
        a = Accident.objects.get()
        Accident.objects.filter(pk=a.pk).update(town_code="0199")
        a.vehicles.filter(vehicle_no=1).update(licence_place_of_issue="Hamburg")
        page = self.client.get(f"/accidents/{a.pk}/edit/").content.decode()
        self.assertIn("0199 (not in the code list)", page)
        self.assertIn("Hamburg (not in the code list)", page)
        data = self.edit_payload(a)
        data.update({"town_code": "0199", "vehicles-0-licence_place_of_issue": "Hamburg"})
        r = self.client.post(f"/accidents/{a.pk}/edit/", data)
        self.assertEqual(r.status_code, 302, r.context and r.context["problems"])
        a.refresh_from_db()
        self.assertEqual(a.town_code, "0199")
        self.assertEqual(a.vehicles.get(vehicle_no=1).licence_place_of_issue, "Hamburg")

    def test_pedestrian_code_needs_hit_pedestrian(self):
        data = self.payload(collision_code="11", collision_type="1")
        del data["confirm_warnings"]
        r = self.client.post("/accidents/new/", data)
        self.assertContains(r, "28 Collision code 11 is a pedestrian accident")

    # ---- Site location: the pin on the map -------------------------------------------
    def test_pin_is_saved_and_shown(self):
        self.client.post("/accidents/new/", self.payload(site_location_text="Tech Roundabout",
                                                         latitude="6.674512", longitude="-1.571634"))
        a = Accident.objects.get()
        self.assertEqual((str(a.latitude), str(a.longitude)), ("6.674512", "-1.571634"))
        page = self.client.get(f"/accidents/{a.pk}/")
        self.assertContains(page, 'id="report-map"')
        self.assertContains(page, 'data-lat="6.674512"')
        self.assertEqual(len(self.client.get("/").context["map_points"]), 1)
        # The same place is offered in the map search on the next report.
        pins = self.client.get("/api/pins.json?q=tech round").json()["pins"]
        self.assertEqual(pins, [{"name": "Tech Roundabout", "lat": 6.674512, "lng": -1.571634,
                                 "report": "123/2026"}])
        self.assertEqual(self.client.get("/api/pins.json?q=te").json()["pins"], [])

    def test_pin_must_be_complete_and_in_ghana(self):
        r = self.client.post("/accidents/new/", self.payload(longitude=""))
        self.assertIn("both latitude and longitude", str(r.context["form"].errors["longitude"]))
        r = self.client.post("/accidents/new/", self.payload(latitude="51.500000", longitude="-0.120000"))
        self.assertIn("outside Ghana", str(r.context["form"].errors["latitude"]))
        self.assertEqual(Accident.objects.count(), 0)

    def test_no_pin_is_a_reminder_not_a_block(self):
        data = self.payload(latitude="", longitude="")
        del data["confirm_warnings"]
        r = self.client.post("/accidents/new/", data)
        self.assertContains(r, "no pin is placed on the map")
        self.assertContains(r, "Save anyway")
        self.assertEqual(Accident.objects.count(), 0)
        self.client.post("/accidents/new/", {**data, "confirm_warnings": "1"})
        a = Accident.objects.get()
        self.assertIsNone(a.latitude)
        self.assertContains(self.client.get(f"/accidents/{a.pk}/"), "No pin on the map for this report")

    def test_locations_api_etag_and_invalidation(self):
        r = self.client.get("/api/locations.json")
        data = r.json()
        self.assertEqual(len(data["regions"]), 16)
        self.assertTrue(any(t[2] == self.town.name for t in data["towns"]))
        etag = r["ETag"]
        self.assertEqual(self.client.get("/api/locations.json", HTTP_IF_NONE_MATCH=etag).status_code, 304)
        Town.objects.create(district=self.district, name="Brand New Village")
        r2 = self.client.get("/api/locations.json", HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(r2.status_code, 200)
        self.assertIn("Brand New Village", r2.content.decode())

    def test_form_renders_only_selected_town(self):
        for i in range(30):
            Town.objects.create(district=self.district, name=f"Village {i}")
        r = self.client.get("/accidents/new/")
        self.assertNotContains(r, "Village 7")

    def test_create_with_children(self):
        r = self.client.post("/accidents/new/", self.payload())
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        a = Accident.objects.get()
        self.assertEqual(a.vehicles.count(), 2)
        self.assertEqual(a.passengers.count(), 1)
        self.assertEqual(a.day_of_week, 1)  # 2 Nov 2026 is a Monday
        self.assertEqual(a.created_by, self.user)
        self.assertEqual(a.audit.count(), 1)

    def test_validation_errors(self):
        other = PoliceStation.objects.create(
            region=Region.objects.exclude(pk=self.region.pk).first(), name="Far Police Station")
        r = self.client.post("/accidents/new/", self.payload(police_station=other.pk))
        self.assertEqual(r.status_code, 200)  # form re-shown with errors
        self.assertIn("police_station", r.context["form"].errors)
        self.assertEqual(Accident.objects.count(), 0)

    def test_dashboard_list_detail_exports(self):
        self.client.post("/accidents/new/", self.payload())
        self.client.post("/accidents/new/", self.payload(report_number="124"))
        a = Accident.objects.first()
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["totals"]["n"], 2)
        self.assertEqual(len(r.context["blackspots"]), 1)
        self.assertContains(self.client.get("/accidents/?region=%d" % self.region.pk), "Kumasi-Accra Rd")
        self.assertContains(self.client.get(f"/accidents/{a.pk}/"), "Possible duplicates")
        x = self.client.get("/export/xlsx/")
        self.assertEqual(x.status_code, 200)
        self.assertTrue(x.content[:2] == b"PK")
        c = self.client.get("/export/csv/")
        self.assertIn("1 Report number", c.content.decode("utf-8-sig"))

    def test_dashboard_has_only_four_charts(self):
        self.client.post("/accidents/new/", self.payload())
        r = self.client.get("/")
        self.assertEqual(set(r.context["charts"]), {"month", "region", "severity", "road_users"})
        html = r.content.decode()
        for title in ("Accidents per month", "Accidents by region", "Accidents by severity",
                      "Casualties by road user"):
            self.assertIn(title, html)
        for gone in ("Time of day", "Day of week", "Collision type", "Vehicles involved, by type",
                     "Driver error", "Region summary"):
            self.assertNotIn(gone, html)

    def test_review(self):
        self.client.post("/accidents/new/", self.payload())
        a = Accident.objects.get()
        self.client.post(f"/accidents/{a.pk}/review/", {"status": "reviewed", "analyst_notes": "ok"})
        a.refresh_from_db()
        self.assertEqual(a.status, "reviewed")
        self.assertEqual(a.reviewed_by, self.user)

    def test_sample_data_consistent_and_removable(self):
        import os
        self.client.post("/accidents/new/", self.payload(report_number="REAL-1"))
        call_command("load_sample_data", count=60, stdout=open(os.devnull, "w"))
        samples = Accident.objects.filter(is_sample=True)
        self.assertEqual(samples.count(), 60)
        for a in samples.prefetch_related("vehicles", "passengers", "pedestrians"):
            sevs = [v.driver_injury for v in a.vehicles.all() if v.driver_injury in (1, 2, 3)]
            sevs += [p.severity for p in a.passengers.all()] + [p.severity for p in a.pedestrians.all()]
            self.assertEqual((a.killed, a.injured), (sevs.count(1), len(sevs) - sevs.count(1)))
            self.assertEqual(a.severity, min(sevs) if sevs else 4)
            self.assertEqual(a.num_vehicles, a.vehicles.count())
            self.assertEqual(a.district.region_id, a.region_id)
            self.assertTrue(a.report_number.startswith("SAMPLE-"))
        self.assertContains(self.client.get("/"), "Sample data:")
        call_command("load_sample_data", delete=True, stdout=open(os.devnull, "w"))
        self.assertEqual(list(Accident.objects.values_list("report_number", flat=True)), ["REAL-1"])
        self.assertNotContains(self.client.get("/"), "Sample data:")

    def test_approved_report_stays_editable_and_edit_is_logged(self):
        self.client.post("/accidents/new/", self.payload())
        a = Accident.objects.get()
        self.client.post(f"/accidents/{a.pk}/review/", {"status": "reviewed", "analyst_notes": ""})
        detail = self.client.get(f"/accidents/{a.pk}/")
        self.assertContains(detail, "Approved by analyst")
        self.assertContains(detail, f'href="/accidents/{a.pk}/edit/"')
        self.assertContains(self.client.get("/accidents/"), f'href="/accidents/{a.pk}/edit/"')
        page = self.client.get(f"/accidents/{a.pk}/edit/")
        self.assertContains(page, "This report was approved")
        # Re-post the saved values with one change.
        r = self.client.post(f"/accidents/{a.pk}/edit/", self.edit_payload(a, road_name="Corrected Road"))
        self.assertEqual(r.status_code, 302, r.context and r.context["problems"])
        a.refresh_from_db()
        self.assertEqual(a.road_name, "Corrected Road")
        self.assertEqual(a.status, "reviewed")          # still approved
        self.assertEqual(a.audit.first().action, "edited after approval")

    def test_edit_keeps_children(self):
        self.client.post("/accidents/new/", self.payload())
        a = Accident.objects.get()
        r = self.client.get(f"/accidents/{a.pk}/edit/")
        self.assertEqual(r.status_code, 200)

    # ---- Consistency checks when saving (checks.py) ------------------------------------
    def _problems(self, r):
        return " | ".join(p["msg"] for p in r.context["problems"])

    def test_fatal_casualty_but_severity_hospitalised_is_blocked(self):
        r = self.client.post("/accidents/new/", self.payload(severity="2"))
        self.assertEqual(Accident.objects.count(), 0)
        self.assertIn("12 Accident severity is 2 - Hospitalised, but it should be 1 - Fatal", self._problems(r))
        self.assertContains(r, 'data-goto="id_severity"')

    def test_severity_fatal_but_no_one_killed_is_blocked(self):
        p = self.payload(killed="0", injured="2", **{"passengers-0-severity": "2"})
        r = self.client.post("/accidents/new/", p)               # severity still 1 - Fatal
        self.assertIn("should be 2 - Hospitalised", self._problems(r))

    def test_killed_and_injured_counts_must_match_people(self):
        r = self.client.post("/accidents/new/", self.payload(killed="2", injured="3"))
        msgs = self._problems(r)
        self.assertIn("10 No. killed is 2, but 1 person(s) are marked Fatal", msgs)
        self.assertIn("11 No. injured is 3, but 1 person(s)", msgs)

    def test_damage_only_with_casualties_is_blocked(self):
        r = self.client.post("/accidents/new/", self.payload(severity="4"))
        self.assertIn("should be 1 - Fatal", self._problems(r))

    def test_vehicle_section_without_type_is_blocked(self):
        p = self.payload()
        p["vehicles-1-vehicle_type"] = ""          # 2 sections, only one filled in
        r = self.client.post("/accidents/new/", p)
        self.assertIn("Vehicle 2: 29 Vehicle type is missing", self._problems(r))
        self.assertEqual(Accident.objects.count(), 0)

    def test_casualty_on_missing_vehicle_is_blocked(self):
        r = self.client.post("/accidents/new/", self.payload(**{"passengers-0-vehicle_no": "5"}))
        self.assertIn("46 Veh no. is 5, but there are only 2 vehicle(s)", self._problems(r))

    def test_reminders_shown_then_save_anyway(self):
        p = self.payload(accident_time="", collision_type="9", light_conditions="1")
        del p["confirm_warnings"]
        r = self.client.post("/accidents/new/", p)
        self.assertEqual(Accident.objects.count(), 0)            # held back for the reminders
        warns = " | ".join(w["msg"] for w in r.context["warnings"])
        self.assertIn("9 Time is not filled in", warns)
        self.assertIn("Hit Pedestrian\" but no pedestrian casualty", warns)
        self.assertIn("3 Police station is not filled in", warns)
        self.assertContains(r, "Save anyway")
        self.assertEqual(r.context["problems"], [])
        r = self.client.post("/accidents/new/", {**p, "confirm_warnings": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Accident.objects.count(), 1)

    def test_day_light_at_night_and_young_full_licence_warn(self):
        p = self.payload(accident_time="22:30", light_conditions="1",
                         **{"vehicles-0-driver_age": "16", "vehicles-0-licence_status": "1"})
        del p["confirm_warnings"]
        warns = " | ".join(w["msg"] for w in self.client.post("/accidents/new/", p).context["warnings"])
        self.assertIn("\"Day\" but 9 Time is 22:30", warns)
        self.assertIn("driver aged 16 with a Full licence", warns)

    def test_clean_report_saves_without_prompts(self):
        st = PoliceStation.objects.create(region=self.region, name="Ejisu Police Station")
        p = self.payload(police_station=st.pk, **{"vehicles-1-driver_injury": "4"})
        del p["confirm_warnings"]
        r = self.client.post("/accidents/new/", p)
        self.assertEqual(r.status_code, 302, r.context and (r.context["problems"], r.context["warnings"]))

    # ---- Records search by district and police station ---------------------------------
    def test_records_filter_by_district_and_station(self):
        st_a = PoliceStation.objects.create(region=self.region, district=self.district, name="Alpha Police Station")
        st_b = PoliceStation.objects.create(region=self.region, name="Bravo Police Station")
        other_d = District.objects.exclude(pk=self.district.pk).filter(region=self.region).first() \
            or District.objects.create(region=self.region, name="Other District")
        self.client.post("/accidents/new/", self.payload(report_number="A1", police_station=st_a.pk))
        self.client.post("/accidents/new/", self.payload(report_number="B2", police_station=st_b.pk))
        # District is no longer entered on the form; older records have it.
        Accident.objects.filter(report_number="A1").update(district=self.district)
        Accident.objects.filter(report_number="B2").update(district=other_d)
        refs = lambda url: sorted(a.report_number for a in self.client.get(url).context["page"])
        self.assertEqual(refs("/accidents/"), ["A1", "B2"])
        self.assertEqual(refs(f"/accidents/?district={self.district.pk}"), ["A1"])
        self.assertEqual(refs(f"/accidents/?district={other_d.pk}"), ["B2"])
        self.assertEqual(refs(f"/accidents/?police_station={st_b.pk}"), ["B2"])
        self.assertEqual(refs("/accidents/?q=alpha"), ["A1"])                # search box matches station
        self.assertEqual(refs(f"/accidents/?q={other_d.name[:6]}"), ["B2"])   # ...and district
        page = self.client.get(f"/accidents/?police_station={st_a.pk}")
        self.assertContains(page, f'value="{st_a.pk}" data-r="{self.region.pk}"')
        # Exports and dashboard use the same filters.
        self.assertEqual(self.client.get(f"/?police_station={st_a.pk}").context["totals"]["n"], 1)
        csv_rows = self.client.get(f"/export/csv/?district={other_d.pk}").content.decode("utf-8-sig").splitlines()
        self.assertEqual(len(csv_rows), 2)  # header + B2

    # ---- Form follows the paper: every number 1-69, in order -------------------------
    def test_form_shows_every_field_number_in_paper_order(self):
        import re as _re
        html = self.client.get("/accidents/new/").content.decode()
        # Field numbers in labels / headings, in page order (first occurrence each).
        nums = []
        for m in _re.finditer(r"(?:<label[^>]*>|<th>|<h2>)\s*(\d{1,2})(?:[-\s])", html):
            # "5-7 Date" counts as 5, 6 and 7.
            hi = _re.match(r"\d+-(\d+)", html[m.start(1):])
            for n in range(int(m.group(1)), int(hi.group(1)) + 1 if hi else int(m.group(1)) + 1):
                if n not in nums:
                    nums.append(n)
        self.assertEqual(sorted(nums), list(range(1, 70)), "a field number is missing")
        self.assertEqual(nums, sorted(nums), f"field numbers out of paper order: {nums}")

    def test_day_month_year_combine_and_day_of_week(self):
        self.client.post("/accidents/new/", self.payload(accident_date="2026-11-07"))
        a = Accident.objects.get()
        self.assertEqual(str(a.accident_date), "2026-11-07")
        self.assertEqual(a.get_day_of_week_display(), "6 - Saturday")
        page = self.client.get(f"/accidents/{a.pk}/edit/")
        f = page.context["form"]
        self.assertIn('value="2026-11-07"', str(f["accident_date"]))
        self.assertEqual(f["day_of_week_display"].value(), "6 - Saturday")
        self.assertContains(self.client.get(f"/accidents/{a.pk}/"), "6 - Saturday")

    def test_impossible_or_future_date_rejected(self):
        r = self.client.post("/accidents/new/", self.payload(accident_date="2026-04-31"))
        self.assertIn("accident_date", r.context["form"].errors)
        r = self.client.post("/accidents/new/", self.payload(accident_date="2099-01-01"))
        self.assertIn("future", str(r.context["form"].errors["accident_date"]))
        self.assertEqual(Accident.objects.count(), 0)

    # ---- Number of vehicles must match the vehicle sections ---------------------------
    def test_num_vehicles_matches_sections(self):
        r = self.client.post("/accidents/new/", self.payload(num_vehicles="2"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(list(Accident.objects.get().vehicles.values_list("vehicle_no", flat=True)), [1, 2])

    def test_num_vehicles_mismatch_rejected(self):
        r = self.client.post("/accidents/new/", self.payload(num_vehicles="3"))  # only 2 sections
        self.assertEqual(r.status_code, 200)
        self.assertIn("2 vehicle section(s)", self._problems(r))
        self.assertEqual(Accident.objects.count(), 0)

    def test_empty_vehicle_section_is_blocked_unknown_type_allowed(self):
        # "3 vehicles" but the 3rd section is empty -> not saved, the person is told.
        p = self.payload(num_vehicles="3", **{"vehicles-TOTAL_FORMS": "3", "vehicles-2-vehicle_no": "3"})
        r = self.client.post("/accidents/new/", p)
        self.assertIn("Vehicle 3: 29 Vehicle type is missing", self._problems(r))
        # An unknown (hit-and-run) vehicle is recorded as type 10 - Unknown.
        p["vehicles-2-vehicle_type"] = "10"
        self.assertEqual(self.client.post("/accidents/new/", p).status_code, 302)
        self.assertEqual(Accident.objects.get().vehicles.count(), 3)

    def test_edit_deleting_vehicle_must_update_count(self):
        self.client.post("/accidents/new/", self.payload(num_vehicles="2"))
        a = Accident.objects.get()
        base = self.edit_payload(a, **{"vehicles-1-DELETE": "on"})
        r = self.client.post(f"/accidents/{a.pk}/edit/", {**base, "num_vehicles": "2"})
        self.assertIn("4 No. of vehicles says 2, but 1 vehicle section(s)", self._problems(r))
        r = self.client.post(f"/accidents/{a.pk}/edit/", {**base, "num_vehicles": "1"})
        self.assertEqual(r.status_code, 302, r.context and r.context["problems"])
        self.assertEqual(a.vehicles.count(), 1)

    # ---- Police stations ----------------------------------------------------------
    def test_choose_existing_station(self):
        st = PoliceStation.objects.create(region=self.region, district=self.district,
                                          name="Ejisu Police Station")
        self.client.post("/accidents/new/", self.payload(police_station=st.pk))
        self.assertEqual(Accident.objects.get().police_station, st)

    def test_new_station_typed_on_form_is_created_unverified(self):
        r = self.client.post("/accidents/new/", self.payload(new_police_station="  Fumesua  "))
        self.assertEqual(r.status_code, 302)
        st = Accident.objects.get().police_station
        self.assertEqual(st.name, "Fumesua Police Station")   # suffix added
        self.assertEqual((st.region, st.district, st.source, st.verified, st.added_by),
                         (self.region, None, "user", False, self.user))
        # Typing the same name again re-uses it instead of duplicating.
        self.client.post("/accidents/new/", self.payload(report_number="200",
                                                         new_police_station="fumesua police station"))
        self.assertEqual(PoliceStation.objects.filter(name__iexact="Fumesua Police Station").count(), 1)
        self.assertContains(self.client.get(f"/accidents/{st.accident_set.first().pk}/"), "not yet checked")

    def test_station_choice_and_new_name_conflict(self):
        st = PoliceStation.objects.create(region=self.region, name="Ejisu Police Station")
        r = self.client.post("/accidents/new/", self.payload(police_station=st.pk,
                                                             new_police_station="Another"))
        self.assertIn("new_police_station", r.context["form"].errors)

    def test_station_must_be_in_region(self):
        other = Region.objects.exclude(pk=self.region.pk).first()
        st = PoliceStation.objects.create(region=other, name="Far Away Police Station")
        r = self.client.post("/accidents/new/", self.payload(police_station=st.pk))
        self.assertIn("police_station", r.context["form"].errors)

    def test_locations_api_station_format_and_dashboard_layer(self):
        PoliceStation.objects.create(region=self.region, district=self.district, name="X Police Station",
                                     kind="mttd", latitude=6.7, longitude=-1.6)
        s = self.client.get("/api/locations.json").json()["stations"][0]
        self.assertEqual(s, [s[0], self.region.pk, self.district.pk, "X Police Station", "mttd", 6.7, -1.6])
        self.assertEqual(len(self.client.get("/").context["stations"]), 1)

    def test_import_stations_csv(self):
        import os
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as fh:
            fh.write("region,district,station,kind,latitude,longitude\n")
            fh.write(f"Ashanti,{self.district.name},Official Station,district_hq,6.70,-1.60\n")
            fh.write("Ashanti,,Second Station,,,\n")
        try:
            call_command("import_locations", fh.name, stations=True, stdout=open(os.devnull, "w"))
        finally:
            os.unlink(fh.name)
        st = PoliceStation.objects.get(name="Official Station")
        self.assertEqual((st.kind, st.district, st.verified, st.source), ("district_hq", self.district, True, "csv"))
        self.assertTrue(PoliceStation.objects.filter(name="Second Station", region=self.region).exists())

    def test_osm_name_cleaning(self):
        from accidents.management.commands.load_police_stations import EXCLUDE, classify, clean_name
        self.assertEqual(clean_name("Ghana Police Service-Enchi"), ("Enchi Police Station", False))
        self.assertEqual(clean_name("Sefwi Bekwai Police Sation"), ("Sefwi Bekwai Police Station", False))
        self.assertEqual(clean_name("Offinso police"), ("Offinso Police Station", False))
        self.assertEqual(clean_name("Kotobabi M.T.T.U"), ("Kotobabi MTTU", False))
        self.assertEqual(clean_name("Dixcove"), ("Dixcove Police Station", False))
        self.assertTrue(clean_name("District Police Headquarters")[1])      # generic
        self.assertTrue(EXCLUDE.search("Inchaban Police Barrier"))
        self.assertFalse(EXCLUDE.search("Walewale District Police Headquarters"))
        self.assertEqual(classify("Navrongo Divisional Police Headquarters"), "divisional_hq")
        self.assertEqual(classify("Volta Regional Police Headquarters"), "regional_hq")
        self.assertEqual(classify("Agbogba Police Post"), "post")

    def test_online_only(self):
        # Old offline installs get a worker that removes itself and its caches.
        r = self.client.get("/sw.js")
        self.assertEqual(r["Content-Type"], "application/javascript")
        self.assertContains(r, "unregister")
        self.assertNotContains(r, "addEventListener(\"fetch\"")
        self.assertEqual(self.client.get("/manifest.json").status_code, 404)
        page = self.client.get("/accidents/new/").content.decode()
        self.assertNotIn("offline.js", page)
        self.assertIn("csir-emblem.png", page)


class AdminAreaTests(TestCase):
    """The administrator area: accounts, read-only reports and history."""

    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_superuser("boss", password="pw-12345-test")
        cls.analyst = User.objects.create_user("kofi", password="pw-12345-test")
        cls.region = Region.objects.create(name="Ashanti")
        cls.acc = Accident.objects.create(report_number="9", report_year=2026, region=cls.region,
                                          accident_date=__import__("datetime").date(2026, 1, 5),
                                          created_by=cls.analyst)
        cls.acc.audit.create(user=cls.analyst, action="created")

    def setUp(self):
        self.client.login(username="boss", password="pw-12345-test")

    def test_only_administrators_get_in_and_one_login_page(self):
        self.assertContains(self.client.get("/admin/"), "Analyst accounts")
        self.client.logout()
        self.assertRedirects(self.client.get("/admin/login/"), "/login/?next=/admin/")
        self.client.login(username="kofi", password="pw-12345-test")
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        self.assertNotContains(self.client.get("/"), "/admin/")

    def test_add_analyst_and_administrator(self):
        new = {"username": "ama", "password1": "Zx9-kumasi-road", "password2": "Zx9-kumasi-road",
               "first_name": "Ama", "last_name": "Owusu", "email": ""}
        r = self.client.post("/admin/auth/user/add/", new)
        self.assertEqual(r.status_code, 302, r.context and r.context["adminform"].form.errors)
        ama = User.objects.get(username="ama")
        self.assertEqual((ama.is_staff, ama.is_superuser, ama.get_full_name()), (False, False, "Ama Owusu"))
        self.assertTrue(self.client.login(username="ama", password="Zx9-kumasi-road"))
        self.client.login(username="boss", password="pw-12345-test")
        self.client.post("/admin/auth/user/add/", {**new, "username": "yaw", "is_superuser": "on"})
        yaw = User.objects.get(username="yaw")
        self.assertEqual((yaw.is_staff, yaw.is_superuser), (True, True))

    def test_cannot_lock_yourself_out(self):
        page = self.client.get(f"/admin/auth/user/{self.boss.pk}/change/")
        data = {"username": "boss", "first_name": "", "last_name": "", "email": ""}   # both boxes unticked
        r = self.client.post(f"/admin/auth/user/{self.boss.pk}/change/", data)
        self.assertEqual(r.status_code, 302, page.status_code)
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.is_superuser and self.boss.is_staff and self.boss.is_active)
        self.assertEqual(self.client.get(f"/admin/auth/user/{self.boss.pk}/delete/").status_code, 403)

    def test_reports_are_view_and_delete_only(self):
        url = f"/admin/accidents/accident/{self.acc.pk}/"
        self.assertContains(self.client.get(url + "change/"), "Open report")
        self.assertEqual(self.client.post(url + "change/", {"report_number": "X"}).status_code, 403)
        self.assertEqual(self.client.get("/admin/accidents/accident/add/").status_code, 403)
        # History cannot be added, edited or deleted on its own ...
        log = self.acc.audit.get()
        self.assertEqual(self.client.get("/admin/accidents/auditlog/add/").status_code, 403)
        self.assertEqual(self.client.post(f"/admin/accidents/auditlog/{log.pk}/delete/", {"post": "yes"}).status_code, 403)
        # ... but goes with its report when the report is deleted.
        self.assertNotContains(self.client.get(url + "delete/"), "your account doesn't have permission")
        self.client.post(url + "delete/", {"post": "yes"})
        self.assertEqual(Accident.objects.count(), 0)


class FirstAdminTests(TestCase):
    good = {"first_name": "Ama", "last_name": "Mensah", "email": "a@example.com", "username": "ama",
            "password1": "Road-safety-2026", "password2": "Road-safety-2026"}

    def test_login_sends_to_setup_when_no_accounts(self):
        self.assertRedirects(self.client.get("/login/"), "/setup/")

    def test_creates_administrator_and_opens_add_user(self):
        r = self.client.post("/setup/", self.good)
        self.assertRedirects(r, "/admin/auth/user/add/")
        u = User.objects.get(username="ama")
        self.assertTrue(u.is_superuser and u.is_staff and u.is_active)

    def test_closed_once_an_account_exists(self):
        User.objects.create_user("analyst", password="pw-12345-test")
        self.assertRedirects(self.client.get("/setup/"), "/login/")
        self.client.post("/setup/", self.good)
        self.assertFalse(User.objects.filter(username="ama").exists())
        self.assertEqual(self.client.get("/login/").status_code, 200)

    def test_weak_password_rejected(self):
        r = self.client.post("/setup/", {**self.good, "password1": "123", "password2": "123"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.exists())

    @override_settings(FIRST_ADMIN_CODE="open-sesame")
    def test_setup_code_required_when_set(self):
        self.client.post("/setup/", {**self.good, "setup_code": "wrong"})
        self.assertFalse(User.objects.exists())
        self.client.post("/setup/", {**self.good, "setup_code": "open-sesame"})
        self.assertTrue(User.objects.filter(username="ama", is_superuser=True).exists())

    def test_database_problem_page_instead_of_login(self):
        from unittest import mock
        from django.db import DatabaseError
        with mock.patch("accidents.views.User.objects.exists",
                        side_effect=DatabaseError('relation "auth_user" does not exist')):
            for url in ("/login/", "/setup/"):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 503)
                self.assertContains(r, "setup-online.bat", status_code=503)
