"""
Codebook for the Ghana Police Service / BRRI ROAD ACCIDENT REPORT form.

Transcribed from the paper form (page 1: fields 1-45, page 2: fields 46-69).
Field numbers match the form so data entry and analysis can refer to them directly.
Items marked  # VERIFY  were hard to read on the photo and need confirming.
"""

# ---------------------------------------------------------------------------
# PAGE 1 - ACCIDENT DETAILS
# ---------------------------------------------------------------------------
# 1  Report Number / Year          (text / year)
# 2  Region, Road Name             (lookup / text)
# 3  Police Station                (lookup)
# 4  No. of Vehicles Involved      (2 digits)
# 5  Day, 6 Month, 7 Year          (date)
# 9  Time (24 hrs)                 (hour : minutes)
# 10 No. Casualties KILLED         (2 digits)
# 11 No. Casualties INJURED        (2 digits)
# 20 Road Width (m)                (number)
# 28 Collision Code                (2 digits)                       # VERIFY meaning
#    Speed Limit                   (number, km/h)

DAY_OF_WEEK = {  # 8
    1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
    5: "Friday", 6: "Saturday", 7: "Sunday",
}

ACCIDENT_SEVERITY = {  # 12
    1: "Fatal", 2: "Hospitalised", 3: "Injured Not-Hospitalised", 4: "Damage Only",
}

WEATHER = {  # 13
    1: "Clear", 2: "Fog/Mist", 3: "Rain", 4: "Dust/Smoke", 5: "Dazzle", 6: "Other",
}

LIGHT_CONDITIONS = {  # 14
    1: "Day", 2: "Night - No Lights", 3: "Night - Lights OFF", 4: "Night - Lights ON",
}

ROAD_DESCRIPTION = {  # 15
    1: "Straight and Flat", 2: "Curve Only", 3: "Incline Only",
    4: "Curve & Incline", 5: "Bridge (name river)", 6: "Crest",
}

ROAD_SURFACE_TYPE = {  # 16
    1: "Tar Good", 2: "Tar Few Potholes", 3: "Tar Many Potholes",
    4: "Gravel", 5: "Earth Few Potholes", 6: "Earth Many Potholes",
}

SHOULDER_TYPE = {  # 17
    1: "Tarred", 2: "Untarred", 3: "No Shoulder",
}

SHOULDER_CONDITION = {  # 18
    1: "Good", 2: "Poor", 3: "Overgrown", 4: "No Shoulder",
}

ROAD_SEPARATION = {  # 19
    1: "Median", 2: "No Median",
}

ROAD_TYPE = {  # (unnumbered, below field 20)
    1: "Motorway", 2: "Highway", 3: "Urban Road", 4: "Feeder Road", 5: "Other Roads",
}

SURFACE_CONDITION = {  # 21
    1: "Dry", 2: "Wet", 3: "Muddy",
}

SURFACE_REPAIR = {  # 22
    1: "Good", 2: "Potholes", 3: "Rough",
}

LOCATION_TYPE = {  # 23  (junction diagrams on the form)
    1: "Not at Junction", 2: "Crossroads (+)", 3: "T-Junction",
    4: "Staggered Junction", 5: "Y-Junction", 6: "Roundabout",
    7: "Railway Crossing", 8: "Other",
}  # VERIFY 2-5 against the diagrams

TRAFFIC_CONTROL = {  # 24
    1: "None", 2: "Pedestrian Crossing", 3: "Signals",
    4: "Stop Sign", 5: "Give Way", 6: "Other",
}

COLLISION_TYPE = {  # 25
    1: "Head On", 2: "Rear End", 3: "Right Angle", 4: "Side Swipe",
    5: "Ran Off Road (Overturn)", 6: "Hit Object on Road", 7: "Hit Object off Road",
    8: "Hit Parked Vehicle", 9: "Hit Pedestrian", 10: "Hit Animal", 11: "Other",
}

HIT_AND_RUN = {  # 26
    1: "Not Hit & Run", 2: "Hit & Run",
}

ROADWORKS = {  # 27
    1: "Not at Roadworks", 2: "At Roadworks",
}

# ---------------------------------------------------------------------------
# PAGE 1 - VEHICLES & DRIVERS (one block per vehicle; form shows Vehicle 1 & 2)
# ---------------------------------------------------------------------------
# 30 Registration No.      (text)
# 36 Driver Name           (text)
# 37 Sex, 38 Age, 39 Nationality
# 41 Licence No., Driver's Education                                # VERIFY "Driver's Edu."
# 43 Place of Issue, Issue Date, Expiry Date

VEHICLE_TYPE = {  # 29
    1: "Car", 2: "HGV", 3: "Tractor", 4: "Bus", 5: "Minibus", 6: "Motor Cycle",
    7: "Pickup", 8: "Bicycle", 9: "Other", 10: "Unknown", 11: "Tricycle", 12: "Rickshaw",
}

OWNERSHIP_USAGE = {  # 31
    1: "Govt", 2: "Company", 3: "Private", 4: "Taxi", 5: "Bus",
    6: "Police/Military", 7: "Emergency", 8: "Other",
}

VEHICLE_MANOEUVRE = {  # 32
    1: "Right Turn", 2: "Left Turn", 3: "U Turn", 4: "Cross Traffic", 5: "Merging",
    6: "Diverging", 7: "Overtaking", 8: "Going Ahead", 9: "Reversing",
    10: "Sudden Start", 11: "Sudden Stop", 12: "Parked Off Road",
    13: "Stopped On Road", 14: "Other",
}

VEHICLE_DAMAGE = {  # 33
    1: "None", 2: "Minor", 3: "Extensive",
}

VEHICLE_DEFECTS = {  # 34
    1: "None", 2: "Brakes", 3: "Steering", 4: "Tyres", 5: "Suspension",
    6: "Lights", 7: "Multiple", 8: "Other",
}

VEHICLE_DIRECTION = {  # 35 (also used for 68 Direction)
    1: "North", 2: "East", 3: "South", 4: "West",
}

SEX = {1: "Male", 2: "Female"}  # 37 / 47 / 53                       # VERIFY coding

DRIVER_INJURY = {  # 40
    1: "Fatal", 2: "Hospitalised", 3: "Not-Hospitalised", 4: "Uninjured",
}

LICENCE_STATUS = {  # 42
    1: "Full", 2: "Provisional", 3: "Learner", 4: "Unlicensed",
}

DRINK_DRUGGED_DRIVING = {  # 44
    1: "Not Suspected", 2: "Suspected", 3: "Tested and Positive",
    4: "Tested and Negative", 5: "Unknown",
}

DRIVER_ERROR = {  # 45
    1: "None", 2: "Inexperience", 3: "Inattentive", 4: "Too Fast", 5: "Too Close",
    6: "No Signal", 7: "Improper Overtaking", 8: "Improper Turning",
    9: "Fatigued/Asleep", 10: "Other",
}

# ---------------------------------------------------------------------------
# PAGE 2 - PASSENGER CASUALTIES (46-51 + seatbelt), paper form has 10 rows
# ---------------------------------------------------------------------------
# 46 Veh No, 47 Sex, 48 Age, 49 Severity, 50 Position, 51 Action, Helmet/Belt Y/N

INJURY_SEVERITY = {  # 49 & 55
    1: "Fatal", 2: "Hospitalised", 3: "Injured Not-Hospitalised",
}

PASSENGER_POSITION = {  # 50
    1: "Front Seat", 2: "Rear Seat", 3: "Motorcycle Passenger", 4: "Bus Passenger",
    5: "Inside", 6: "Outside Sitting", 7: "Outside Standing",
}

PASSENGER_ACTION = {  # 51
    1: "Boarding", 2: "Alighting/Jumping", 3: "Falling from Vehicle", 4: "Other",
}

# ---------------------------------------------------------------------------
# PAGE 2 - PEDESTRIAN CASUALTIES (52-58 + STD, Nation), paper form has 4 rows
# ---------------------------------------------------------------------------
# 52 Veh No, 53 Sex, 54 Age, 55 Severity, 56 Action, 57 Location, 58 Drink,
# STD Y/N (# VERIFY meaning - student?), Nationality

PEDESTRIAN_ACTION = {  # 56
    1: "No Action", 2: "Crossing Road", 3: "Walking Along Road",
    4: "Walking Along Edge", 5: "Playing On Road", 6: "On Footpath", 7: "Other",
}

PEDESTRIAN_LOCATION = {  # 57
    1: "Pedestrian Crossing", 2: "Within 50m of Crossing", 3: "On Central Refuge",
    4: "In Road Centre", 5: "On Footpath/Verge", 6: "Unknown", 7: "Other",
}

PEDESTRIAN_DRINK_DRUGS = {  # 58
    1: "Not Suspected", 2: "Suspected", 3: "Unknown",
}

# ---------------------------------------------------------------------------
# PAGE 2 - LOCATION CODING (filled by BRRI / MTTD)
# ---------------------------------------------------------------------------
# 59 Type                 (1 digit)                                  # VERIFY meaning
# 60 Town/Village Code    (3 digits)                                 # need BRRI code list
# 61 Km                   (3 digits)
# 62 100m                 (1 digit)
# 63 Route Number         (3 chars)
# 64 X Co-ordinate        (6 digits)
# 65 Y Co-ordinate        (6 digits)
# 66 Node 1, 67 Node 2    (3 digits each)
# 68 Direction            (1 digit, see VEHICLE_DIRECTION)
# 69 Police Description of Accident (free text)
#    Sketch of the Accident Scene / Site Location Sketch (image upload)

LANDMARK = {
    1: "Near School", 2: "Near/Inside Village", 3: "Near Factory",
    4: "Near Religious", 5: "Recreation/Cinema", 6: "Shopping Area",
    7: "Residential Area", 8: "Near Hospital", 9: "Open Area", 10: "Near Bus Stop",
    11: "Near Fuel Station", 12: "Pedestrian Crossing", 13: "Bridge",
    14: "Near Office Block",
}

DRIVER_EDUCATION = {  # "Driver's Edu." (unnumbered)                # VERIFY options
    1: "None", 2: "Primary", 3: "JHS/Middle", 4: "SHS/Secondary", 5: "Tertiary", 6: "Unknown",
}


def choices(codes):
    """Django choices list with the code shown, e.g. (3, '3 - Rain')."""
    return [(k, f"{k} - {v}") for k, v in codes.items()]


# ---------------------------------------------------------------------------
# Ghana's 16 administrative regions (districts/towns loaded from data files)
# ---------------------------------------------------------------------------
REGIONS = [
    "Ahafo", "Ashanti", "Bono", "Bono East", "Central", "Eastern",
    "Greater Accra", "North East", "Northern", "Oti", "Savannah",
    "Upper East", "Upper West", "Volta", "Western", "Western North",
]


# ===========================================================================
# CODING MANUAL (BRRI "Accident codes" document, pages 3-14)
# ===========================================================================

# ---------------------------------------------------------------------------
# 28 COLLISION CODE - grouped as in the manual's diagrams. First digit = group.
# Stored as text ("51"), so old reports keep exactly what was typed.
# ---------------------------------------------------------------------------
COLLISION_CODE_GROUPS = [
    ("1 - Pedestrian accidents", {
        11: "Vehicle hit a pedestrian crossing from left to right",
        12: "Vehicle hit a pedestrian crossing from right to left",
        13: "Vehicle hit a pedestrian walking along the road",
        14: "Vehicle hit a pedestrian walking on the pavement / footway",
        15: "Vehicle hit a person playing, working, lying or standing in the road",
        16: "Vehicle hit a person getting on or off a bus, or selling to bus passengers",
    }),
    ("2 - Single vehicle", {
        21: "Vehicle goes off the road to the left",
        22: "Vehicle goes off the road to the right",
        23: "Vehicle goes out of control but stays on the road",
        24: "Vehicle goes out of control while turning at a junction",
    }),
    ("3 - Single vehicle hit a fixed / stationary object", {
        31: "Hit parked or stopped vehicle on left or right side of the road",
        32: "Vehicle hit another vehicle while parking",
        33: "Vehicle hit roadside obstruction (sign, bridge, tree)",
        34: "Vehicle hit object in or above the road (traffic island, etc.)",
        35: "Vehicle hit road works (signs, material, etc.)",
    }),
    ("4 - Opposite directions (head on)", {
        41: "Vehicle hit oncoming vehicle while overtaking",
        42: "Vehicle hit oncoming vehicle, not overtaking",
        43: "Vehicle hit another vehicle while turning left",
        44: "Both vehicles turning left",
        45: "Vehicle turning left hit another vehicle turning right",
        46: "Vehicle turning right hit another vehicle turning right or going straight",
        47: "Vehicle hit oncoming vehicle while making a U-turn",           # VERIFY - cut off in the copy
    }),
    ("5 - Same direction (rear end)", {
        51: "Vehicle moves into vehicle ahead",
        52: "Vehicle hit another when changing lane to the right",
        53: "Vehicle hit another when changing lane to the left",
        54: "Vehicle hit another travelling in the same lane (side swipe)",
        55: "Vehicle hit another while making a U-turn",
        56: "Vehicle hit another while overtaking on the left",
        57: "Vehicle hit another while overtaking on the right",
    }),
    ("6 - Same direction, one or both turning (side swipe)", {
        61: "Side swipe between vehicle turning right and one going ahead",
        62: "Side swipe between vehicle turning left and one going ahead",
        63: "Vehicle runs into the back of another vehicle turning right",
        64: "Vehicle runs into the back of another vehicle turning left",
        65: "Both vehicles turning right",
        66: "Vehicle turning right hit another vehicle turning right or going straight",
    }),
    ("7 - At right angles", {
        71: "Hits vehicle coming from the left",
        72: "Hits vehicle coming from the right",
        73: "Hits vehicle coming from the left while turning right",
        74: "Hits vehicle coming from the right while turning right",
        75: "Hits vehicle coming from the left while turning left",
        76: "Hits vehicle coming from the right while turning left",
        77: "Both vehicles turning",
    }),
    ("8 - Other accidents", {
        81: "Hit by train",
        82: "Passenger fell from vehicle",
        83: "Hit animal",
        84: "Hit temporary object on road (load falling from vehicle)",
        85: "Hit object while reversing (not parked)",
        86: "Parked vehicle rolled over",
        87: "Object falling from vehicle",
        88: "Vehicle caught fire",                                          # VERIFY - cut off in the copy
    }),
]
COLLISION_CODE = {str(k): v for _, codes in COLLISION_CODE_GROUPS for k, v in codes.items()}


def collision_code_choices():
    """Grouped choices for 28 Collision code: [(group, [("51", "51 - ..."), ...]), ...]."""
    return [(group, [(str(k), f"{k} - {v}") for k, v in codes.items()])
            for group, codes in COLLISION_CODE_GROUPS]


# ---------------------------------------------------------------------------
# 30 VEHICLE REGISTRATION CODE (region letters at the start of the number plate)
# ---------------------------------------------------------------------------
VEHICLE_REG_CODE = {
    1: "AS - Ashanti", 2: "BA - Brong Ahafo", 3: "CR - Central", 4: "ER - Eastern",
    5: "GR - Greater Accra", 6: "NR - Northern", 7: "UE - Upper East", 8: "UW - Upper West",
    9: "VR - Volta", 10: "WR - Western", 11: "GA, GP - Army", 12: "Foreign",
    13: "Temporary", 14: "Unregistered / Unlicensed",
}

# ---------------------------------------------------------------------------
# 39 / pedestrian NATIONALITY
# ---------------------------------------------------------------------------
NATIONALITY = {1: "Ghanaian", 2: "Other African", 3: "Asian", 4: "Europe/North America", 5: "Other"}

# ---------------------------------------------------------------------------
# 43 DRIVER LICENCE PLACE OF ISSUE - stored as the office code ("AS1").
# Manual numbers in comments; the manual gives 23 twice and has no 25.
# ---------------------------------------------------------------------------
LICENCE_PLACE = {
    "AS1": "Kumasi",            # 1
    "CR4": "Dunkwa",            # 2
    "AS3": "Ashanti Mampong",   # 3
    "BA1": "Sunyani",           # 4
    "CR1": "Cape Coast",        # 5
    "CR2": "Winneba",           # 6
    "ER3": "Akim Oda",          # 7
    "ER1": "Koforidua",         # 8
    "GR1": "Accra",             # 9
    "GR2": "Tema",              # 10
    "NR1": "Tamale",            # 11
    "UE1": "Bolgatanga",        # 12
    "UW1": "Wa",                # 13
    "VR1": "Denu",              # 14
    "VR2": "Hohoe",             # 15
    "VR3": "Ho",                # 16
    "WR1": "Takoradi",          # 17
    "WR2": "Tarkwa",            # 18
    "VR4": "Keta",              # 19
    "ER2": "Nkawkaw",           # 20
    "AS4": "Agona",             # 21
    "AS2": "Obuasi",            # 22
    "VR5": "Agbozome",          # 23
    "CR3": "Swedru",            # 24
    "BA2": "Techiman",          # 26
    "GR3": "Weija",             # 27
    "ER4": "Asamankese",        # 28
    "WR3": "Sekondi",           # 23 (sic)
    "AS5": "Bekwai",            # 29
}

# ---------------------------------------------------------------------------
# 60 TOWN / VILLAGE CODE: region number + town number, written as 4 digits
# ("0101" = Ashanti, Kumasi), as in the reports already entered.
# A few misprints in the manual are corrected (e.g. Damango -> Damongo).
# ---------------------------------------------------------------------------
TOWN_CODES = {
    "Ashanti": (1, ["Kumasi", "Obuasi", "Mampong", "Agogo", "Ejura", "Konongo/Odumase", "Bekwai",
                    "Akomadan", "Wiamoase", "Juaben", "Effiduase", "Kumawu", "Tepa", "Jamasi",
                    "Sekodumase", "Nkenkasu", "Abofour", "Kwaman", "New Edubiase", "Agona", "Juaso",
                    "Jacobu", "Obogu", "Ejisu", "Offinso", "Asokore Mampong", "Kuntenase"]),
    "Bono": (2, ["Sunyani", "Berekum", "Dormaa Ahenkro", "Chiraa", "Techimantia", "Nsuatre", "Wamfie",
                 "Jinijini", "Odumase", "Sampa", "Fiapre", "Abesim", "Drobo", "Badu", "Banda Ahenkro",
                 "Nkrankwanta", "Wenchi", "Nsawkaw"]),
    "Central": (3, ["Cape Coast", "Agona Swedru", "Winneba", "Dunkwa-on-Offin", "Elmina", "Apam", "Moree",
                    "Saltpond", "Senya Beraku", "Agona Nyakrom", "Assin Fosu", "Bawjiase", "Besease",
                    "Mumford", "Mankessim", "Breman Asikuma", "Agona Kwanyarko", "Anomabu", "Brakwa",
                    "Tantum (Otuam)", "Komenda", "Abura Dunkwa", "Agona Bobikuma", "Agona Nsaba",
                    "Abodom", "Kasoa"]),
    "Eastern": (4, ["Koforidua", "Nkawkaw", "Nsawam", "Akim Oda", "Asamankese", "Suhum", "Begoro",
                    "Akwatia", "New Tafo", "Somanya", "Akropong", "Akyease", "Akosombo", "Odumase Krobo",
                    "Agomanya", "Kade", "Asuom", "Kukurantumi", "Kpong", "Nkwatia", "Supong", "Effiduase",
                    "Aburi", "Akroso", "Kibi", "Mpreeso", "Akim Swedru", "Lartey", "Asesewa", "Asokore",
                    "Adieso", "Mampong", "Asene", "Anyinam", "Obo", "Oyoko", "Akoase", "Apedwa",
                    "Osenase", "Adukrom"]),
    "Greater Accra": (5, ["Accra", "Tema", "Madina", "Old Ningo", "Kpone", "Prampram", "Ada-Foah",
                          "Ashaiman", "Amasaman", "Pokuase", "Dawhenya", "Adenta", "Baatsona", "Sowutuom",
                          "Weija", "Sakumono", "La", "Dodowa", "Abokobi", "Sege"]),
    "Northern": (6, ["Tamale", "Yendi", "Savelugu", "Bimbilla", "Gushegu", "Zabzugu", "Karaga", "Kpandai",
                     "Nyankpala", "Kumbungu", "Tatale", "Saboba", "Sagnarigu", "Wulensi", "Nanton", "Sang",
                     "Tolon"]),
    "Upper East": (7, ["Bolgatanga", "Bawku", "Zebilla", "Navrongo", "Sandema", "Paga", "Bongo", "Gawu",
                       "Binduri", "Fumbisi", "Garu", "Nangodi", "Pusiga", "Tongo", "Zuarungu", "Tempane"]),
    "Upper West": (8, ["Wa", "Jirapa", "Tumu", "Nandom", "Hawa", "Nadowli", "Issa", "Lambussie",
                       "Lawra", "Gwollu", "Funsi", "Wechiau"]),
    "Volta": (9, ["Ho", "Hohoe", "Aflao", "Anloga", "Kpando", "Dzodze", "Kete", "Peki", "Tegbi", "Akatsi",
                  "Juapong", "Tsito", "Sogakope", "Kpetoe", "Woe", "Kpedze", "Dzelukope", "Penyi",
                  "Wusuta", "Adaklu Waya", "Ve Golokwati", "Ave-Dakpa", "Adidome", "Anfoega",
                  "Battor Dugame", "Kpeve New Town", "Denu"]),
    "Western": (10, ["Sekondi/Takoradi", "Tarkwa", "Prestea", "Axim", "Shama", "Half Assini", "Asankragwa",
                     "Enchi", "Samreboi", "Bogoso", "Wassa Akropong", "Kwesimintim", "Daboase", "Mpohor",
                     "Nkroful"]),
    "Ahafo": (11, ["Goaso", "Mim", "Bechem", "Duayaw Nkwanta", "Kenyase", "Yamfo", "Acherensua",
                   "Kukuom", "Hwidiem",
                   "Techimantia"]),           # 10 added by hand in the manual
    "Bono East": (12, ["Techiman", "Wenchi", "Nkoranza", "Kintampo", "Yeji", "Atebubu", "Tuobodom",
                       "Kwame Danso", "Prang", "Amantin", "Jema", "Busunya", "Kajaji", "Pru"]),
    "North East": (13, ["Nalerigu", "Walewale", "Gambaga", "Chereponi", "Yunyoo", "Yagaba", "Bunkpurugu"]),
    "Oti": (14, ["Dambai", "Kpassa", "Kadjebi", "Kete Krachi", "Jasikan", "Kwamekrom", "Wurawura",
                 "Nkwanta", "Nkonya Ahenkro",
                 "Chinderi"]),               # 10 corrected by hand; the manual also prints "Dambai 10"
    "Savannah": (15, ["Damongo", "Salaga", "Bole", "Buipe", "Sawla", "Daboya", "Kpalbe"]),
    "Western North": (16, ["Sefwi Wiawso", "Bibiani", "Sefwi Asawinso", "Juaboso", "Sefwi Bekwai",
                           "Enchi", "Adabokrom", "Essam", "Bodi", "Sefwi Akontombra", "Dadieso",
                           "Dadiaso"]),          # 12 added by hand in the manual   # VERIFY name
}


def town_code_choices(region_name):
    """[("0101", "0101 - Kumasi"), ...] for one region, or [] if the region is not listed."""
    if region_name not in TOWN_CODES:
        return []
    rnum, towns = TOWN_CODES[region_name]
    return [(f"{rnum:02d}{i:02d}", f"{rnum:02d}{i:02d} - {t}") for i, t in enumerate(towns, start=1)]


def town_code_name(code):
    """'0101' -> 'Kumasi' ('' if the code is not in the manual)."""
    if not (code and len(code) == 4 and code.isdigit()):
        return ""
    for rnum, towns in TOWN_CODES.values():
        if int(code[:2]) == rnum:
            i = int(code[2:])
            return towns[i - 1] if 1 <= i <= len(towns) else ""
    return ""
