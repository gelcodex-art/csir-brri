"""Police station codes, as BRRI writes them on reports: region number + station
number, five digits ("04086" = Eastern, Nsawam).

Two lists were supplied by BRRI:
  * "Police Station Codes" - the printed list for the ten old regions;
  * "NEW POLICE STATION CODES" - the regions created in 2018/19 (Ahafo, Bono East,
    North East, Oti, Savannah, Western North) and newer lists for Central, Upper
    East and Upper West.

Names are as on the lists (a few plain misprints corrected). Where a station of an
old region is now listed under a new region, both codes lead to the same station
(ALIASES): "02041" and "12001" are both Techiman.

`manage.py load_station_codes` puts the list in the database (StationCode).
"""
import re

from django.db import DatabaseError, transaction

# Region number -> station names in code order (None = the list has no such number).
_OLD = {
    1: [  # ASHANTI
        "Kumasi Central", "Manhyia", "Asawasi", "Asokwa", "Suame", "Old Tafo", "Suntreso", "KNUST",
        "Ejisu", "Kwaso", "Boankra", "Juaben", "Effiduase", "Asokore", "Oyoko", "Banko", "Kumawu",
        "Bodomasi", "Juaso", "Obogu", "Banso", "Amantia", "Bompata", "Kantanso", "Pra River",
        "Konongo", "Odumasi", "Peminase", "Kwease", "Agogo", "Juansa", "Akutuase", "Krofa",
        "Mamponteng", "Antoa",
        "Sakora Wonoo", "Asonomaso", "Agona", "Jamasi", "Wiamoase", "Kona", "Mampong", "Nsuta",
        "Kofiase", "Kwamang", "Beposo", "Ejura", "Sekodumase", "Akomadan", "Afrancho", "Nkenkasu",
        "Abofour", "Offinso", "Kodie", "Boamang", "Tetrem", "Nyinahin", "Adiembra", "Sreso Timpom",
        "Tepa", "Pokukrom", "Wioso", "Abonsuaso", "Mabae", "Manfo", "Asuafua", "Adankwame",
        "Barekese", "Abuakwa", "Nkawie",
        "Mankranso", "Ahwerewa", "Akropong", "Jachie", "Trede", "Pakyi No.2", "Twedie",
        "Brofoyedru", "Kuntenase", "Sewua", "Hwidiem", "Bekwai", "Kokofu", "Jacobu", "Abodom",
        "Esiwa", "Semfi", "Essumeja", "Anhyiankwanta", "Manso Nkwanta", "Antoakrom", "Manso Abobe",
        "Manso Edubia", "Domi Keniago", "Obuasi", "Akrofuom", "Ampunyasi", "Akrokerri", "Fomena",
        "Bodwesango", "Anwhiaso", "New Edubiase", "Antobiase", "Fumso", "Oforikrom",
        None, None, None,
        "Asokore Mampong", "Domeabra",          # 109, 110: written by hand on the list
    ],
    2: [  # BRONG AHAFO
        "Sunyani", "Nsuatre", "Duayaw Nkwanta", "Bechem", "Berekum", "Jinijini", "Seikwa", "Drobo",
        "Japekrom", "Dodosua", "Atuna", "Sampa", "Suma Ahenkro", "Goka", "Adanasu",
        "Dormaa Ahenkro", "Wamfie", "Amaso", "Nkrankwanta", "Nsesreso", "Goaso", "Mim", "Kwapong",
        "Kasapin", "Sankore", "Gambia No.1", "Kukuom", "Nkoranza", "Yefri", "Busunya", "Akuma",
        "Donkokrom", "Atebubu", "Yeji", "Kwajokrom", "Kwame Danso",
        "Amantin", "Sawaba No.2", "Prang", "Abease", "Techiman", "Tanoso", "Tuobodom", "Nsuta",
        "Aworowa", "Akrofrom", "Kintampo", "Kadelso", "New Longoro", "Kenyase", None, "Hwidiem",
        "Acherensua", "Ntotroso", "Wenchi", "Badu", "Nsawkaw", "Subinso", "Banda-Gbao", "Offuman",
        "Yamfo", "Bomaah", "Bosamkro", "Techimantia", "Dermah", "Atronie", "Chiraa", "Gambia No.2",
        "Bassa", "Terchire", "Jema",
    ],
    4: [  # EASTERN
        "Koforidua", "Jumapo", "Kurankam", "Effiduase", "Akwadum", "Railways", "Tafo", "Begoro",
        "Kukurantumi", "Osiem", "Mpaem", "Abuaso", "Asirebuso", "Mayiwa Brosankro",
        "Ehiamankyene", "Bepoase", "Asesewa", "Oterkporlu", "Oprokper", "Sekesua", "Udawale",
        "Akim Oda", "Akroso", "Akim Adjobue", "Akim Manso", "Akropong Akwapim", "Adukrom",
        "Mangoase", "Adawso", "Lartey", "Manfe", "Okrakwadwo", "Amanfro", "Akim Ofoase", "Ntroman",
        "Adubease",
        "Ayirebi", "Afosu", "Asamankese", "Asikasu", "Mepom", "Nyano", "Kade", "Asuom", "Prankese",
        "Akwatia", "Osenase", "Akim Takyiman", "Takorase", "Akim Swedru", "Akim Achiase",
        "Akim Achiase Railways", "Aperade", "Kibi", "Asiakwa", "Bunso", "Akim Akropong", "Akosombo",
        "Adomi Senchi", "Frankadua", "Anum", "Boso", "Adjena", "Akuse", "Somanya", "Odumasi",
        "Kpong", "Nuaso", "Asutsase", "Mampong Akwapim", "Aburi", "Ayinensa",
        "Berekuso", "Nkawkaw", "Nkawkaw Railways", "Kwahu Praso", "Asuboni", "Suan Nakese",
        "Akoase", "Amuana Praso", "Asuboni No.3", "Donkorkrom", "Tease", "Abonsarfo", "Amankwa",
        "Nsawam", "Adeiso", "Coaltar", "Obodan", "Parko", "Suhum", "Apedwa", "Akim Asafo",
        "Mankese", "Anyinam", "Kwabeng", "Abonosu", "Osino", "New Jejeti", "Mpraeso", "Nkwatia",
        "Abetifi", "New Owurobong", "Hweehwee", "Kwahu Tafo", "Ofranase", "Oyoko",
    ],
    5: [  # GREATER ACCRA
        "Accra Central MTU", "Korle-Bu", "Jamestown", "Nima", "Kaneshie Odorkor", "Tesano",
        "Kotobabi", "Labadi", "Cantonment", "Osu", "Teshie", "Nungua/Kpeshie", "Airport", "Legon",
        "Kwabenya", "Madina", "Dodowa", "Doryumu", "Afienya", "Tema C.1", "Tema C.2", "Harbour",
        "Ashaiman", "Prampram", "Kpone", "Old Ningo", "Adafoa", "Kasseh", "Dawa", "Big Ada",
        "Ayimensah", "Dansoman", "New Ningo", "Amasaman", "Kaneshie",
        "Mamprobi", "New Weija", "Adenta", "Sakumono", "Mile 7", "Toll Booth", "Anyaa",
        "Tema New Town", "Sowutuom", "Adjen-Kotoku", "Amanfrom", "Oyibi", "Gbawe Lafa", "Baatsona",
        "Ministries", "Darkuman",
    ],
    6: [  # NORTHERN
        "Tamale", "Nyankpala", "Savelugu", "Yendi", "Gushegu", "Karaga", "Zabzugu", "Tatale",
        "Salaga", "Gambaga", "Nalerigu", "Walewale", "Nakpanduri", "Bunkpurugu", "Bimbilla",
        "Wulensi", "Kpandai", "Bole", "Sawla", "Bamboi", "Kalba", "Tuna", "Damongo", "Fufulso",
        "Mpaha", "Buipe", "Daboya", "Nasia", "Yapei",
    ],
    9: [  # VOLTA
        "Ho", "Kpando", "Anfoega", "Wurupong", "Nkonya Ahenkro", "Alavanyo", "Vakpo", "Abor",
        "Afife", "Akatsi", "Anyiwase", "Hlefi", "Dzolufoeta", "Kpedze", "Abutia", "Peki",
        "Kpalwe Duga", "Kpeve", "Have", "Juapong", "Dzodze", "Penyi", "Ehi", "Tadzewu", "Ave Dakpa",
        "Kpetue", "Ziope", "Dzalele", "Aflao", "Agzozume", "Denu", "Sogakope",
        "Dabala", "Agbakope", "Aveyime", "Keta", "Anloga", "Hohoe", "Gologwati", "Tetle", "Anyanii",
        "Jasikan", "Kadjebi", "Ahamansu", "Dodo Amanfrom", "Dodi Papase", "Pampiwie", "Dambai",
        "Tokurano", "Katanga", "Nkwanta", "Brewaniase", "Kpasa", "Kete Krachi", "Chinderi", "Banda",
        "Worawora", "Abotoase", "Kwamekrom", "New Ayoma", "Wute", "Adidome", "Borae", "Damanko",
    ],
    10: [  # WESTERN
        "Takoradi", "Railways & Airport", "Effiakuma", "Sekondi", "Kojokrom", "Kwesimintsim",
        "Shama", "Inchaban", "Beposo", "Agona Junction", "Abura", "Dixcove", "Mpohor", "Tarkwa",
        "Bonsaso", "Aboso", "Nsuta Wassaw", "Prestea", "Bogoso", "Wasa Akropong", "Manso Amanfi",
        "Enchi", "Samreboi", "Asankragua", "Dadieso", "Sefwi Asawinso", "Boinzan", "Amoanya",
        "Adabokrom", "Dadiso", "Juaboso", "Asempaneye", "Benchema", "Sefwi Wiawso",
        "Sefwi Bodi", "Juabo", "Akontombra", "Anyinabrem", None, "Dompim", "Adum Banso", "Nsueam",
        None, "Half Assini", "Atuabo", "Tikobo No.1", "Mpataba", "Axim", "Nkroful", "Anyinase",
        "Asiama", "Subiri", "Sefwi Anhwiaso", "Awaso", "Sefwi Bekwai", "Bibiani", "Sefwi Boako",
        None, "Sefwi Asafo", "Bonsu Nkwanta", "Elubo", "Osei Kojo", None, "Aboazede",
    ],
}

_NEW = {
    3: [  # CENTRAL
        "Cape Coast", "Elmina", "Komenda", "Apam", "Winneba", "Awutu Bereku", "Gomoa Dawurampong",
        "Agona", "Agona Swedru", "Agona Nyakrom", "Agona Nsabaa", "Agona Duakwa", "Assin Manso",
        "Assin Nyanabrim", "Assin Fosu", "Assin Akropong", "Assin Praso", "Assin Danmang",
        "Abura Dunkwa", "Fanti Nyankomase", "Assin Bereku", "Saltpond", "Anomabo", "Essaerkyir",
        "Mankesim", "Otuam", "Twifu Praso", "Twifu Hemang", "Twifu Wawase", "Twifu Mokwa",
        "Dunkwa-on-Offin", "Diaso", "Ayanfuri", "Chechewere", "Subin Hill", "Ajumako",
        "Enyan Abaasa", "Nkwantanum", "Ochiso", "Besease", "Breman Asikuma", "Brakwa", "Odoben",
        "Amanfopong", "Akonfudi", "Agona Bobikuma", "Abodom", "Tarkwa", "Eshiem", "Ngyiresi",
        "Kasoa", "Fette", "Bawjiase", "Ayeldu", "Dominase", "Abakrampa", "Jukwa", "Gomoa Obuase",
        "Awisem", None, None, None, "Mankrong", "Denkyira Dominase", "Yamoransa", "Ojobi", "Ofaakor",
    ],
    7: ["Bolgatanga", "Navrongo", "Paga", "Sandema", "Chiana", "Bawku", "Garu", "Zebilla", "Pusiga",
        "Binaba", "Bongo"],
    8: ["Wa", "Dorimon", "Nadowli", "Tumu", "Lawra", "Babile", "Lambussie", "Hamile", "Nandom",
        "Jirapa", "Wellembelle", "Gwollu", "Kaleo", "Hain"],
    11: ["Goaso", "Mim", "Bechem", "Duayaw Nkwanta", "Kenyase", "Yamso", "Acherensua", "Kukuom",
         "Ntotroso", "Sankore", "Gambia No.1", "Terchire", "Yamfo", "Kwapong", "Kasapin",
         "Techimantia", "Hwidiem"],
    12: ["Techiman", "Wenchi", "Nkoranza", "Kintampo", "Yeji", "Atebubu", "Tuobodom", "Kwame Danso",
         "Prang", "Amantin", "Jema", "New Longoro", "Kadelso", "Sawaba", "Kajeji"],
    13: ["Nalerigu", "Walewale", "Gambaga", "Nakpanduri", "Chereponi", "Bunkpurugu"],
    14: ["Dambai", "Kpasa", "Kadjebi", "Kete Krachi", "Jasikan", "Kwamekrom", "Worawora", "Nkwanta",
         "Nkonya Ahenkro", "Alavanyo", "Ahamansu", "Dodo Amanfrom", "Dodi Papase", "Tokurano",
         "Katanga", "Brewaniase", "Chinderi", "Abotoase", "Damanko", "Borae", "Wurawura", "Banda"],
    15: ["Damongo", "Salaga", "Bole", "Buipe", "Sawla", "Bamboi", "Tuna", "Fufulso", "Yapei", "Kalba"],
    16: ["Sefwi Wiawso", "Bibiani", "Juaboso", "Sefwi Asawinso", "Sefwi Bekwai", "Enchi",
         "Benchema Junction", "Asempaneye", "Adjoafua", "Debiso", "Adabokrom", "Oseikojo", "Kaase",
         "Sefwi Boako", "Sefwi Asafo", "Asafo", "Sefwi Anhwiaso", "Akontombra", "Sefwi Bodi", None,
         "Amoanya", "Boinzan", "Dadieso", "Afere", "Bonso Nkwanta"],
}

# Old code -> the code of the same station on the list of its new region.
ALIASES = {
    # Brong Ahafo -> Ahafo
    "02003": "11004", "02004": "11003", "02021": "11001", "02022": "11002", "02023": "11014",
    "02024": "11015", "02025": "11010", "02026": "11011", "02027": "11008", "02050": "11005",
    "02052": "11017", "02053": "11007", "02054": "11009", "02061": "11013", "02064": "11016",
    "02070": "11012",
    # Brong Ahafo -> Bono East
    "02028": "12003", "02033": "12006", "02034": "12005", "02036": "12008", "02037": "12010",
    "02038": "12014", "02039": "12009", "02041": "12001", "02043": "12007", "02047": "12004",
    "02048": "12013", "02049": "12012", "02071": "12011",
    # Northern -> North East, Savannah
    "06010": "13003", "06011": "13001", "06012": "13002", "06013": "13004", "06014": "13006",
    "06009": "15002", "06018": "15003", "06019": "15005", "06020": "15006", "06021": "15010",
    "06022": "15007", "06023": "15001", "06024": "15008", "06026": "15004", "06029": "15009",
    # Volta -> Oti
    "09005": "14009", "09006": "14010", "09042": "14005", "09043": "14003", "09044": "14011",
    "09045": "14012", "09046": "14013", "09048": "14001", "09049": "14014", "09050": "14015",
    "09051": "14008", "09052": "14016", "09053": "14002", "09054": "14004", "09055": "14017",
    "09056": "14022", "09057": "14007", "09058": "14018", "09059": "14006", "09063": "14020",
    "09064": "14019",
    # Western -> Western North
    "10022": "16006", "10025": "16023", "10026": "16004", "10027": "16022", "10028": "16021",
    "10029": "16011", "10031": "16003", "10032": "16008", "10033": "16007", "10034": "16001",
    "10035": "16019", "10037": "16018", "10053": "16017", "10055": "16005", "10056": "16002",
    "10057": "16014", "10059": "16015", "10060": "16025", "10062": "16012",
}


def all_codes():
    """{"04086": "Nsawam", ...} - every code on the two lists."""
    out = {}
    for lists in (_OLD, _NEW):
        for region, names in lists.items():
            for i, name in enumerate(names, start=1):
                if name:
                    out[f"{region:02d}{i:03d}"] = name
    return out


def clean_code(text):
    """'4086', '04086' or 4086.0 -> '04086'; '' when it is not a station code."""
    text = re.sub(r"\.0+$", "", str(text if text is not None else "").strip())
    return text.zfill(5) if text.isdigit() and 3 <= len(text) <= 5 else ""


def codes_by_station():
    """{station id: ["04086", ...]}; {} while the code table has not been created yet."""
    from .models import StationCode
    out = {}
    try:
        with transaction.atomic():
            for code, sid in StationCode.objects.order_by("code").values_list("code", "station_id"):
                out.setdefault(sid, []).append(code)
    except DatabaseError:
        return {}
    return out


def stations_by_code():
    """{"04086": PoliceStation}; {} while the code table has not been created yet."""
    from .models import StationCode
    try:
        with transaction.atomic():
            return {c.code: c.station for c in StationCode.objects.select_related("station")}
    except DatabaseError:
        return {}
