"""
Generate realistic SAMPLE accident reports for demonstrations and testing.

    python manage.py load_sample_data              # 2000 reports
    python manage.py load_sample_data --count 500
    python manage.py load_sample_data --delete     # remove ALL sample reports

Every generated report has is_sample=True and a report number starting with
"SAMPLE-"; real reports are never touched. People's names, registration and
licence numbers are invented.

What makes the data realistic:
  * regions weighted toward Greater Accra and Ashanti; ~25% of crashes at
    highway hotspot towns (so blackspots appear), the rest at random towns
  * dates over the last 2 years, more at weekends and in December,
    times peaking 06-09h and 16-21h
  * casualties (drivers, passengers, pedestrians) are generated first; killed,
    injured and accident severity are derived from them, so they always agree
  * pedestrian casualties only in "hit pedestrian" collisions; light condition
    follows the time of day; police station = nearest station in the region
"""
import random
import uuid
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accidents.geo import km
from accidents.models import (Accident, AuditLog, PassengerCasualty, PedestrianCasualty,
                              PoliceStation, Region, Town, Vehicle)

REGION_WEIGHT = {
    "Greater Accra": 24, "Ashanti": 20, "Eastern": 10, "Central": 9, "Western": 6, "Volta": 5,
    "Bono East": 4, "Northern": 4, "Bono": 3, "Western North": 3, "Upper East": 3, "Ahafo": 2,
    "Oti": 2, "Savannah": 2, "Upper West": 2, "North East": 1,
}
# Towns on the busiest highways (N1, N6, N8, N10...). Matched by name in the region.
HOTSPOTS = [
    ("Central", "Kasoa"), ("Central", "Winneba"), ("Central", "Mankessim"), ("Central", "Apam Junction"),
    ("Ashanti", "Ejisu"), ("Ashanti", "Konongo"), ("Ashanti", "Offinso"), ("Ashanti", "Suame"),
    ("Ashanti", "Kumasi"), ("Greater Accra", "Madina"), ("Greater Accra", "Tema"),
    ("Greater Accra", "Kaneshie"), ("Greater Accra", "Ashaiman"), ("Greater Accra", "Amasaman"),
    ("Eastern", "Nsawam"), ("Eastern", "Nkawkaw"), ("Eastern", "Bunso"), ("Bono East", "Techiman"),
    ("Bono East", "Kintampo"), ("Northern", "Tamale"), ("Volta", "Sogakope"), ("Western", "Tarkwa"),
    ("Western", "Takoradi"), ("Upper East", "Bolgatanga"), ("Bono", "Sunyani"),
]

FIRST = ["Kwame", "Kofi", "Kwabena", "Yaw", "Kwaku", "Kojo", "Kwesi", "Ama", "Akosua", "Abena",
         "Afia", "Adwoa", "Yaa", "Esi", "Efua", "Mensah", "Ibrahim", "Abdul", "Fatima", "Mohammed",
         "Selorm", "Elikem", "Dela", "Nii", "Naa", "Emmanuel", "Daniel", "Samuel", "Grace", "Joseph",
         "Michael", "Isaac", "Prince", "Richard", "Gifty", "Mercy", "Seidu", "Alhassan", "Issah"]
LAST = ["Mensah", "Owusu", "Boateng", "Asante", "Osei", "Agyeman", "Appiah", "Amoah", "Ofori",
        "Addo", "Quaye", "Tetteh", "Lamptey", "Annan", "Danso", "Darko", "Opoku", "Sarpong",
        "Acheampong", "Adjei", "Nkrumah", "Abubakar", "Iddrisu", "Yakubu", "Mahama", "Fuseini",
        "Agbeko", "Kpodo", "Amenyo", "Dzidzornu", "Gyamfi", "Antwi", "Badu", "Bonsu", "Frimpong"]
REG_PREFIX = {"Greater Accra": ["GR", "GT", "GE", "GW", "GN", "GC"], "Ashanti": ["AS", "AW", "AE"],
              "Eastern": ["ER"], "Central": ["CR"], "Western": ["WR"], "Volta": ["VR"],
              "Northern": ["NR"], "Upper East": ["UE"], "Upper West": ["UW"], "Bono": ["BA"],
              "Bono East": ["BT"], "Ahafo": ["AH"], "Oti": ["OT"], "Savannah": ["SV"],
              "North East": ["NE"], "Western North": ["WN"]}


def pick(weights):
    """weights: {value: weight}"""
    keys = list(weights)
    return random.choices(keys, weights=[weights[k] for k in keys])[0]


VEHICLE_TYPE = {1: 30, 6: 24, 5: 15, 2: 8, 7: 6, 4: 5, 11: 5, 8: 2, 3: 1, 9: 1, 10: 3}
OWNERSHIP_FOR = {1: {3: 6, 4: 4, 2: 1}, 6: {3: 8, 2: 1}, 5: {5: 8, 3: 2}, 2: {2: 8, 3: 2},
                 7: {3: 5, 2: 4, 1: 1}, 4: {5: 8, 2: 2}, 11: {3: 9, 2: 1}, 8: {3: 1}, 3: {3: 1, 2: 1},
                 9: {3: 1, 8: 1}, 10: {8: 1}}
COLLISION = {1: 12, 2: 18, 3: 12, 4: 10, 5: 14, 6: 3, 7: 4, 8: 4, 9: 20, 10: 1, 11: 2}
DRIVER_ERROR = {1: 18, 2: 8, 3: 22, 4: 25, 5: 9, 6: 2, 7: 9, 8: 4, 9: 3, 10: 2}
MANOEUVRE = {8: 45, 7: 14, 1: 5, 2: 5, 3: 3, 4: 5, 5: 3, 6: 2, 9: 3, 10: 2, 11: 6, 13: 4, 12: 1, 14: 2}
DESCRIPTIONS = {
    1: "{v1} travelling {d} collided head-on with {v2} while overtaking on a curve.",
    2: "{v1} ran into the rear of {v2} which had stopped suddenly in traffic.",
    3: "{v1} failed to give way at the junction and collided with {v2} at right angles.",
    4: "{v1} side-swiped {v2} while changing lanes.",
    5: "Driver of {v1} lost control, ran off the road and the vehicle overturned.",
    6: "{v1} hit an object on the carriageway.",
    7: "{v1} veered off the road and hit a roadside object.",
    8: "{v1} crashed into a parked {v2}.",
    9: "{v1} knocked down a pedestrian crossing the road.",
    10: "{v1} hit an animal on the road and the driver lost control.",
    11: "Accident involving {v1}; details under investigation.",
}
VNAME = {1: "a saloon car", 2: "a heavy goods vehicle", 3: "a tractor", 4: "a bus", 5: "a trotro (minibus)",
         6: "a motorbike", 7: "a pickup", 8: "a bicycle", 9: "a vehicle", 10: "an unknown vehicle",
         11: "a tricycle (aboboyaa)", 12: "a rickshaw"}


def random_datetime(start, end):
    while True:
        d = start + timedelta(days=random.randrange((end - start).days + 1))
        w = 1.0 + (0.35 if d.isoweekday() >= 5 else 0) + (0.6 if d.month == 12 else 0)
        if random.random() < w / 1.95:
            break
    hour = random.choices(range(24), weights=[2, 1.5, 1.5, 1.5, 2, 4, 7, 8, 7, 5, 4, 4, 4, 4, 5,
                                               6, 7, 8, 8, 8, 7, 5, 4, 3])[0]
    return d, time(hour, random.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]))


class Command(BaseCommand):
    help = "Generate realistic SAMPLE accident reports (flagged is_sample)."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=2000)
        parser.add_argument("--seed", type=int, default=2026, help="Same seed = same data")
        parser.add_argument("--delete", action="store_true", help="Delete all sample reports")

    def handle(self, count, seed, delete, **opts):
        if delete:
            n = Accident.objects.filter(is_sample=True).count()
            Accident.objects.filter(is_sample=True).delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {n} sample reports."))
            return
        random.seed(seed)
        with transaction.atomic():
            made = self.generate(count)
        self.stdout.write(self.style.SUCCESS(
            f"Created {made} sample reports. Total reports: {Accident.objects.count()} "
            f"({Accident.objects.filter(is_sample=True).count()} sample). "
            "Remove them with: manage.py load_sample_data --delete"))

    # -------------------------------------------------------------------------------
    def generate(self, count):
        user = get_user_model().objects.filter(is_superuser=True).first()
        regions = {r.name: r for r in Region.objects.all()}
        towns_by_region = {}
        for t in (Town.objects.exclude(latitude=None).select_related("district")
                  .only("id", "name", "kind", "code", "latitude", "longitude",
                        "district__id", "district__region_id")):
            towns_by_region.setdefault(t.district.region_id, []).append(t)
        stations_by_region = {}
        for s in PoliceStation.objects.all():
            stations_by_region.setdefault(s.region_id, []).append(s)
        hotspots = []
        for rname, tname in HOTSPOTS:
            r = regions.get(rname)
            cands = [t for t in towns_by_region.get(r.id, []) if t.name.lower() == tname.lower()] if r else []
            cands.sort(key=lambda t: {"city": 0, "town": 1, "suburb": 2}.get(t.kind, 3))
            if cands:
                hotspots.append((r, cands[0]))

        start = date.today() - timedelta(days=730)
        end = date.today() - timedelta(days=1)
        next_no = Accident.objects.filter(is_sample=True).count() + 1
        accidents, children = [], []

        for i in range(count):
            # --- where -------------------------------------------------------------
            if hotspots and random.random() < 0.25:
                region, town = random.choice(hotspots)
                spread = 0.006                                   # ~0.6 km: forms blackspots
            else:
                region = regions[pick(REGION_WEIGHT)]
                pool = towns_by_region[region.id]
                big = [t for t in pool if t.kind in ("city", "town", "suburb")]
                town = random.choice(big if big and random.random() < 0.6 else pool)
                spread = 0.012
            lat = float(town.latitude) + random.gauss(0, spread)
            lng = float(town.longitude) + random.gauss(0, spread)
            stations = stations_by_region.get(region.id, [])
            located = [s for s in stations if s.latitude is not None]
            station = (min(located, key=lambda s: km(lat, lng, float(s.latitude), float(s.longitude)))
                       if located else (random.choice(stations) if stations else None))
            neighbours = [t for t in towns_by_region[region.id]
                          if t.id != town.id and t.kind in ("city", "town")
                          and abs(float(t.latitude) - lat) < 0.5 and abs(float(t.longitude) - lng) < 0.5]
            road = (f"{town.name} - {random.choice(neighbours).name} Road" if neighbours and random.random() < 0.7
                    else f"{town.name} Main Road")

            # --- when --------------------------------------------------------------
            d, t = random_datetime(start, end)
            night = t.hour >= 19 or t.hour < 6
            light = (pick({2: 5, 3: 1, 4: 4}) if night else 1)

            # --- vehicles ------------------------------------------------------------
            collision = pick(COLLISION)
            single = collision in (5, 6, 7, 9, 10)
            n_veh = 1 if single else pick({2: 85, 3: 12, 4: 3})
            vehicles = []
            for v in range(1, n_veh + 1):
                vt = pick(VEHICLE_TYPE)
                hit_run_unknown = (v == n_veh and n_veh > 1 and random.random() < 0.04)
                if hit_run_unknown:
                    vt = 10
                vehicles.append({"no": v, "type": vt, "unknown": hit_run_unknown})

            # --- casualties (decide first, derive totals) -----------------------------
            outcome = pick({1: 14, 2: 30, 3: 26, 4: 30})        # worst outcome of the crash
            veh_rows, pax_rows, ped_rows = [], [], []

            # Injury of one casualty, given the crash outcome (1 fatal ... 4 damage only).
            sev_weights = {1: [4, 3, 2], 2: [0, 3, 4], 3: [0, 0, 1]}

            def person_sev():
                if outcome == 4:
                    return None
                return random.choices([1, 2, 3], weights=sev_weights[outcome])[0]

            for v in vehicles:
                sev = person_sev() if random.random() < (0.85 if v["type"] in (6, 8, 11) else 0.45) else None
                v["driver_sev"] = None if v["unknown"] else sev   # hit-and-run: driver unknown
            if collision == 9:
                for _ in range(pick({1: 85, 2: 12, 3: 3})):
                    ped_rows.append({"sev": person_sev() or 3, "veh": 1})
            for v in vehicles:
                cap = {4: 6, 5: 5, 1: 3, 7: 2, 11: 2, 6: 1, 2: 1}.get(v["type"], 1)
                for _ in range(random.choices(range(cap + 1), weights=[6] + [max(1, 6 - k) for k in range(cap)])[0]):
                    s = person_sev()
                    if s:
                        pax_rows.append({"sev": s, "veh": v["no"], "vt": v["type"]})
            def all_sevs():
                return ([v["driver_sev"] for v in vehicles if v["driver_sev"]]
                        + [p["sev"] for p in pax_rows] + [p["sev"] for p in ped_rows])

            if outcome == 1 and 1 not in all_sevs():      # make sure a fatal crash has a death
                if ped_rows:
                    ped_rows[0]["sev"] = 1
                elif pax_rows:
                    pax_rows[0]["sev"] = 1
                else:
                    vehicles[0]["driver_sev"] = 1
            sevs = all_sevs()                             # counted after any change above
            killed = sevs.count(1)
            injured = len(sevs) - killed
            severity = min(sevs) if sevs else 4

            weather = pick({1: 78, 3: 14, 2: 3, 4: 3, 5: 1, 6: 1})
            surface = pick({1: 85, 2: 12, 3: 3}) if weather != 3 else pick({2: 80, 3: 20})
            surface_type = pick({1: 45, 2: 25, 3: 10, 4: 10, 5: 6, 6: 4})
            junction = pick({1: 62, 3: 15, 2: 8, 4: 3, 5: 4, 6: 5, 7: 1, 8: 2})
            status = pick({"reviewed": 60, "submitted": 30, "query": 10})
            v1, v2 = VNAME[vehicles[0]["type"]], VNAME[vehicles[1]["type"]] if n_veh > 1 else "another vehicle"
            desc = DESCRIPTIONS[collision].format(v1=v1.capitalize(), v2=v2,
                                                   d=random.choice(["north", "south", "east", "west"]))
            desc += f" {killed} killed, {injured} injured." if sevs else " No injuries; damage only."

            a = Accident(
                client_uuid=uuid.uuid4(), is_sample=True,
                report_number=f"SAMPLE-{next_no + i:05d}", report_year=d.year,
                region=region, district_id=town.district.id, town=town, town_code=town.code,
                road_name=road, police_station=station, num_vehicles=n_veh,
                accident_date=d, day_of_week=d.isoweekday(), accident_time=t,
                killed=killed, injured=injured, severity=severity,
                weather=weather, light_conditions=light,
                road_description=pick({1: 55, 2: 15, 3: 10, 4: 12, 5: 3, 6: 5}),
                road_surface_type=surface_type, shoulder_type=pick({1: 25, 2: 50, 3: 25}),
                shoulder_condition=pick({1: 35, 2: 35, 3: 15, 4: 15}),
                road_separation=pick({1: 15, 2: 85}), road_width_m=random.choice([6.0, 7.0, 7.3, 7.5, 9.0, 11.0, 14.6]),
                road_type=pick({2: 45, 3: 35, 4: 15, 1: 2, 5: 3}),
                surface_condition=surface, surface_repair=pick({1: 55, 2: 35, 3: 10}),
                location_type=junction,
                traffic_control=(pick({1: 60, 3: 15, 2: 10, 4: 5, 5: 8, 6: 2}) if junction != 1
                                 else pick({1: 92, 2: 8})),
                collision_type=collision,
                hit_and_run=2 if any(v["unknown"] for v in vehicles) or (collision == 9 and random.random() < 0.08) else 1,
                roadworks=pick({1: 96, 2: 4}),
                speed_limit=random.choice([30, 50, 50, 50, 80, 80, 100]),
                direction=random.randint(1, 4), landmark=pick({k: 1 for k in range(1, 15)}),
                latitude=round(lat, 6), longitude=round(lng, 6),
                police_description=desc, status=status, created_by=user,
                reviewed_by=user if status == "reviewed" else None,
                analyst_notes="Sample data" if status != "query" else "Sample data - please confirm time of accident.",
            )
            accidents.append(a)
            children.append((vehicles, pax_rows, ped_rows, region.name))

        Accident.objects.bulk_create(accidents, batch_size=500)

        veh_objs, pax_objs, ped_objs, logs = [], [], [], []
        for a, (vehicles, pax_rows, ped_rows, rname) in zip(accidents, children):
            for v in vehicles:
                unknown = v["unknown"]
                sex = 1 if random.random() < 0.9 else 2
                age = max(18, min(75, int(random.gauss(36, 10))))
                issue = a.accident_date - timedelta(days=random.randint(200, 3000))
                veh_objs.append(Vehicle(
                    accident=a, vehicle_no=v["no"], vehicle_type=v["type"],
                    registration_no="" if unknown else
                    f"{random.choice(REG_PREFIX.get(rname, ['GR']))} {random.randint(100, 9999)}-{random.randint(10, 25)}",
                    ownership=None if unknown else pick(OWNERSHIP_FOR[v["type"]]),
                    manoeuvre=pick(MANOEUVRE), damage=pick({1: 10, 2: 50, 3: 40}),
                    defects=pick({1: 80, 2: 7, 4: 7, 6: 2, 3: 1, 5: 1, 7: 1, 8: 1}),
                    direction=random.randint(1, 4),
                    driver_name="" if unknown else f"{random.choice(FIRST)} {random.choice(LAST)}",
                    driver_sex=None if unknown else sex, driver_age=None if unknown else age,
                    driver_nationality=None if unknown else (1 if random.random() < 0.96 else 2),
                    driver_injury={1: 1, 2: 2, 3: 3, None: 4}[v["driver_sev"]] if not unknown else None,
                    licence_no="" if unknown or v["type"] in (8,) else f"{random.choice('ABCDEFGH')}{random.randint(1000000, 9999999)}",
                    driver_education=None if unknown else pick({1: 6, 2: 12, 3: 30, 4: 32, 5: 15, 6: 5}),
                    licence_status=None if unknown else (pick({4: 70, 3: 20, 1: 10}) if v["type"] in (6, 11, 8)
                                                         else pick({1: 82, 2: 6, 3: 4, 4: 8})),
                    licence_place_of_issue="" if unknown else random.choice(["GR1", "AS1", "GR2", "WR1", "NR1", "ER1", "CR1", "VR3", "BA1"]),
                    licence_issue_date=None if unknown else issue,
                    licence_expiry_date=None if unknown else issue + timedelta(days=365 * 4),
                    drink_drugs=None if unknown else pick({1: 82, 2: 8, 3: 3, 4: 2, 5: 5}),
                    driver_error=None if unknown else pick(DRIVER_ERROR),
                ))
            for p in pax_rows:
                pos = {6: 3, 4: 4, 5: 4, 11: 6}.get(p["vt"]) or pick({1: 45, 2: 55})
                pax_objs.append(PassengerCasualty(
                    accident=a, vehicle_no=p["veh"], sex=random.choice([1, 2]),
                    age=max(1, min(85, int(random.gauss(30, 14)))), severity=p["sev"], position=pos,
                    action=pick({4: 70, 1: 8, 2: 12, 3: 10}),
                    helmet_belt=random.random() < (0.35 if pos == 3 else 0.25)))
            for p in ped_rows:
                ped_objs.append(PedestrianCasualty(
                    accident=a, vehicle_no=p["veh"], sex=random.choice([1, 1, 2]),
                    age=max(3, min(90, int(random.gauss(32, 18)))), severity=p["sev"],
                    action=pick({2: 55, 3: 15, 4: 12, 5: 5, 6: 5, 1: 5, 7: 3}),
                    location=pick({4: 30, 5: 20, 2: 15, 1: 10, 6: 15, 7: 5, 3: 5}),
                    drink_drugs=pick({1: 80, 2: 8, 3: 12}),
                    std=random.random() < 0.12, nationality=1))
            logs.append(AuditLog(accident=a, user=a.created_by, action="created (sample data)"))
            if a.status == "reviewed":
                logs.append(AuditLog(accident=a, user=a.created_by, action="status: Approved"))

        Vehicle.objects.bulk_create(veh_objs, batch_size=1000)
        PassengerCasualty.objects.bulk_create(pax_objs, batch_size=1000)
        PedestrianCasualty.objects.bulk_create(ped_objs, batch_size=1000)
        AuditLog.objects.bulk_create(logs, batch_size=1000)
        self.stdout.write(f"  vehicles {len(veh_objs)}, passenger casualties {len(pax_objs)}, "
                          f"pedestrian casualties {len(ped_objs)}, hotspot towns {len(hotspots)}")
        return len(accidents)
