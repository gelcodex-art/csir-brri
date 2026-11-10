"""
Consistency checks run when a report is saved.

Two levels:
  * ERRORS   - the report contradicts itself (e.g. 10 says 1 killed but
               12 Accident severity is "Hospitalised"). It cannot be saved
               until they are fixed.
  * WARNINGS - something important looks forgotten or unusual (e.g. no time,
               no GPS location). The person can fix it or click "Save anyway".

Each problem is a dict: {"msg": text, "anchor": html id of the field to jump to}.
Edit the rules here; the form page lists whatever these functions return.
"""
from . import codebook as cb

SEV_NAME = {1: "1 - Fatal", 2: "2 - Hospitalised", 3: "3 - Injured Not-Hospitalised", 4: "4 - Damage Only"}


def _cd(form):
    return getattr(form, "cleaned_data", None) or {}


def _rows(formset):
    """(index, cleaned_data) of rows that will be saved (filled in, not deleted)."""
    out = []
    for i, f in enumerate(formset.forms):
        cd = _cd(f)
        if not cd or cd.get("DELETE"):
            continue
        if f.instance.pk or f.has_changed():
            out.append((i, cd))
    return out


def check_report(form, vfs, pfs, dfs):
    """Return (errors, warnings) for a submitted report."""
    errors, warnings = [], []
    d = _cd(form)

    def err(msg, anchor):
        errors.append({"msg": msg, "anchor": anchor})

    def warn(msg, anchor):
        warnings.append({"msg": msg, "anchor": anchor})

    vehicles, passengers, pedestrians = _rows(vfs), _rows(pfs), _rows(dfs)
    n_veh = len(vehicles)

    # ---- Vehicles ----------------------------------------------------------------
    declared = d.get("num_vehicles")
    if declared is not None and declared != n_veh:
        err(f"4 No. of vehicles says {declared}, but {n_veh} vehicle section(s) are filled in. "
            "Make them match.", "id_num_vehicles")
    if n_veh == 0:
        err("No vehicle is entered. Every accident involves at least one vehicle "
            "(use 29 Vehicle type \"10 - Unknown\" for a hit-and-run vehicle).", "vehicles-section")
    for pos, (i, v) in enumerate(vehicles, start=1):
        if not v.get("vehicle_type"):
            err(f"Vehicle {pos}: 29 Vehicle type is missing (choose \"10 - Unknown\" if not known).",
                f"id_vehicles-{i}-vehicle_type")
        unknown = v.get("vehicle_type") == 10
        if not unknown and v.get("driver_injury") is None:
            warn(f"Vehicle {pos}: 40 Driver injury is not filled in "
                 "(choose \"4 - Uninjured\" if the driver was not hurt).", f"id_vehicles-{i}-driver_injury")
        age, lic = v.get("driver_age"), v.get("licence_status")
        if age is not None and age < 18 and lic == 1:
            warn(f"Vehicle {pos}: driver aged {age} with a Full licence - please check.",
                 f"id_vehicles-{i}-driver_age")

    # ---- Casualty rows -----------------------------------------------------------
    for i, p in passengers:
        if not p.get("severity"):
            err(f"Passenger row {i + 1}: 49 Severity is missing.", f"id_passengers-{i}-severity")
        vn = p.get("vehicle_no")
        if vn is not None and n_veh and not 1 <= vn <= n_veh:
            err(f"Passenger row {i + 1}: 46 Veh no. is {vn}, but there are only {n_veh} vehicle(s).",
                f"id_passengers-{i}-vehicle_no")
    for i, p in pedestrians:
        if not p.get("severity"):
            err(f"Pedestrian row {i + 1}: 55 Severity is missing.", f"id_pedestrians-{i}-severity")
        vn = p.get("vehicle_no")
        if vn is not None and n_veh and not 1 <= vn <= n_veh:
            err(f"Pedestrian row {i + 1}: 52 Veh no. is {vn}, but there are only {n_veh} vehicle(s).",
                f"id_pedestrians-{i}-vehicle_no")

    # ---- 10 killed / 11 injured / 12 severity vs the people entered --------------------
    sevs = [v.get("driver_injury") for _, v in vehicles if v.get("driver_injury") in (1, 2, 3)]
    sevs += [p.get("severity") for _, p in passengers if p.get("severity")]
    sevs += [p.get("severity") for _, p in pedestrians if p.get("severity")]
    fatal, hurt = sevs.count(1), len(sevs) - sevs.count(1)
    killed, injured, severity = d.get("killed"), d.get("injured"), d.get("severity")
    where = "(40 Driver injury, 49 Passenger severity, 55 Pedestrian severity)"

    if killed is not None and killed != fatal:
        err(f"10 No. killed is {killed}, but {fatal} person(s) are marked Fatal {where}.", "id_killed")
    if injured is not None and injured != hurt:
        err(f"11 No. injured is {injured}, but {hurt} person(s) are marked injured or "
            f"hospitalised {where}.", "id_injured")

    if severity is None:
        err("12 Accident severity is not filled in.", "id_severity")
    else:
        if killed:
            expected = 1
        elif sevs:
            expected = min(sevs)
        elif injured:
            expected = None          # injured count but no casualty rows: counts error covers it
        else:
            expected = 4
        if expected is not None and severity != expected:
            reason = (f"10 says {killed} killed" if expected == 1 and killed else
                      "no one was killed or injured" if expected == 4 else
                      f"the most serious casualty entered is {SEV_NAME[expected][4:]}")
            err(f"12 Accident severity is {SEV_NAME[severity]}, but it should be "
                f"{SEV_NAME[expected]} because {reason}.", "id_severity")

    # ---- Commonly forgotten fields (warnings) ---------------------------------------
    for field, label in [("accident_time", "9 Time"), ("weather", "13 Weather"),
                         ("light_conditions", "14 Light conditions"),
                         ("collision_type", "25 Collision type"), ("road_name", "2 Road name")]:
        if d.get(field) in (None, ""):
            warn(f"{label} is not filled in.", f"id_{field}")
    if not d.get("police_station") and not d.get("new_police_station"):
        warn("3 Police station is not filled in.", "id_police_station")
    if d.get("latitude") is None and d.get("longitude") is None and "latitude" not in form.errors:
        warn("Site location: no pin is placed on the map. Without it the accident cannot be "
             "shown on the crash map or counted in blackspots.", "location-section")

    # ---- Things that do not fit together (warnings) ----------------------------------
    collision = d.get("collision_type")
    if collision == 9 and not pedestrians:
        warn("25 Collision type is \"Hit Pedestrian\" but no pedestrian casualty is entered (52-58).",
             "pedestrians-section")
    if pedestrians and collision not in (None, 9):
        warn(f"Pedestrian casualties are entered but 25 Collision type is "
             f"\"{cb.COLLISION_TYPE.get(collision, '?')}\", not \"Hit Pedestrian\".", "id_collision_type")
    code = d.get("collision_code") or ""
    if code.startswith("1") and len(code) == 2 and collision not in (None, 9):
        warn(f"28 Collision code {code} is a pedestrian accident, but 25 Collision type is "
             f"\"{cb.COLLISION_TYPE.get(collision, '?')}\", not \"Hit Pedestrian\".", "id_collision_type")
    t, light = d.get("accident_time"), d.get("light_conditions")
    if t is not None and light:
        night = t.hour >= 19 or t.hour < 6
        day = 7 <= t.hour < 18
        if light == 1 and night:
            warn(f"14 Light conditions is \"Day\" but 9 Time is {t:%H:%M} (night).", "id_light_conditions")
        if light in (2, 3, 4) and day:
            warn(f"14 Light conditions is \"Night\" but 9 Time is {t:%H:%M} (daytime).",
                 "id_light_conditions")
    return errors, warnings
