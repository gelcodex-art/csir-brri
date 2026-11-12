# CSIR-BRRI Road Accident Data System (MVP)

A web app for entering, checking and analysing road accident reports from all
regions of Ghana. It is based on the Ghana Police Service / BRRI Road Accident
Report form, and the field numbers match the paper form.

## Run it
Double-click `start.bat`, then open http://127.0.0.1:8000

## Main parts
| Path | What it is |
|---|---|
| `accidents/codebook.py` | Every coded field on the form (the single source of truth) |
| `accidents/models.py` | Database tables: Accident, Vehicle, PassengerCasualty, PedestrianCasualty, Region/District/Town, PoliceStation, AuditLog |
| `accidents/views.py` | Dashboard, data entry, review, Excel/CSV export, location list API |
| `accidents/analysis.py` | Analysis page: frequency tables, cross-tables with a chi-square test, two periods compared, and averages by group |
| `accidents/stats.py` | Probabilities for those tests (chi-square, F, normal); no extra package needed |
| `accidents/static/accidents/app.js` | Report form: location dropdowns, town search, GPS map |
| `accidents/static/accidents/maps.js` | Shared map setup: background tiles with fallback, region/district boundaries |
| `accidents/static/accidents/csir-emblem.png` | CSIR seal used in the header (also `favicon.png`) |

The system is **online-only**: an internet connection is needed to enter and view data.

### Background maps
The maps use Esri's public World Street Map and World Imagery (satellite) tiles.
OpenStreetMap's own tile server (`tile.openstreetmap.org`) and CARTO basemaps
are deliberately **not** used. They show "Access blocked" / "API KEY REQUIRED"
pictures for this kind of app.
For a production deployment with many users, get a free API key from a tile
provider (ArcGIS Location Platform, MapTiler or Stadia Maps) and set the URL in
`accidents/static/accidents/maps.js` (`BASEMAPS`).
| `accidents/management/commands/` | `seed_locations` (16 regions) and `import_locations` (CSV import) |

## Location data (all of Ghana)
The system includes all **16 regions**, all **261 MMDAs** (6 Metropolitan,
102 Municipal and 153 District assemblies) and **22,982 named towns, villages,
suburbs and hamlets**. Each town is placed in its district by its coordinates.

Rebuild or refresh the data (safe to re-run; towns used in reports are never deleted):

    .venv\Scripts\python.exe manage.py load_ghana_locations

Sources, stored in `data/sources/`:
| File | Source | Licence |
|---|---|---|
| `gha_ADM1.geojson` | geoBoundaries, regions (from OpenStreetMap, 2021) | ODbL |
| `gha_ADM2.geojson` | geoBoundaries, 260 MMDAs (USAID / Ghana Statistical Service, 2019) | open |
| `osm_places_ghana.json` | OpenStreetMap places, via the Overpass API | ODbL, credit "© OpenStreetMap contributors" |
| `geonames/GH.txt` | GeoNames populated places | CC BY 4.0 |

Known gaps:
- Guan District (created in 2022) has no published boundary yet. Its towns
  (Santrokofi, Akpafu, Lolobi, Likpe) are assigned to it by name.
- Assembly types (Metropolitan / Municipal / District) come from the source
  names plus a list of corrections in `load_ghana_locations.py` (`MUNICIPAL`).
  Check them against the current Ministry of Local Government list.
- Open data does not include every hamlet. Analysts can add missing towns in
  Admin → Towns, or in bulk with a CSV (below).

## Sample (demo) data
2,000 generated reports are loaded for demonstrations and training. They are
numbered `SAMPLE-00001`…, flagged as sample data, and the dashboard and
Records pages show a notice while any are present. The names, registration
numbers and licence numbers in them are invented.

    .venv\Scripts\python.exe manage.py load_sample_data --delete      # remove all sample reports
    .venv\Scripts\python.exe manage.py load_sample_data                # add 2000 again
    .venv\Scripts\python.exe manage.py load_sample_data --count 500    # a different amount

`--delete` only removes sample reports; real reports are never touched.
**Delete the sample data before real data entry starts.**

## Police stations
No official open list of Ghana Police Service stations exists, so the list is
built from three sources:

1. **OpenStreetMap**: 362 stations, district/divisional/regional HQs, police posts
   and MTTU offices, cleaned and placed in their region and district:

       .venv\Scripts\python.exe manage.py load_police_stations

   Checkpoints, barriers, barracks, training schools, customs and non-traffic
   units are left out. Vague names ("District Police Headquarters") are named
   after the nearest town. To refresh from OpenStreetMap, save the result of this
   Overpass query (https://overpass-api.de/api/interpreter) as
   `data/sources/osm_police_ghana.json`, then re-run the command:

       [out:json][timeout:300];area["ISO3166-1"="GH"][admin_level=2]->.gh;
       (nwr["amenity"="police"](area.gh);nwr["police"](area.gh););out center tags qt;
2. **Analysts**: on the report form, "Station not in the list? Type its name"
   adds a station for that region. It is marked unverified.
3. **Official list (CSV)**: if the Ghana Police Service / MTTD provides a list,
   import it. Stations imported this way are marked verified:

       .venv\Scripts\python.exe manage.py import_locations data\stations.csv --stations

   Columns: `region,district,station,kind,latitude,longitude` (see
   `data/stations_template.csv`). `kind` is one of national_hq, regional_hq,
   divisional_hq, district_hq, station, post, mttd.

4. **Kumasi supplement**: OpenStreetMap misses many Kumasi stations (Suntreso,
   Bantama, Asawase, Kwadaso, Santasi, Tafo...). `data/kumasi_stations_unverified.csv`
   adds 14 of them, placed at the centre of their suburb (approximate), marked
   unverified until checked against the official list:

       .venv\Scripts\python.exe manage.py import_locations data\kumasi_stations_unverified.csv --stations --unverified

Admins check stations in **Admin → Police stations**. Filter by
*source = Added by analysts* or *verified = No*, correct the name or district,
then use the action "Mark selected stations as verified".

## Adding BRRI town codes, extra towns and police stations
    .venv\Scripts\python.exe manage.py import_locations data\towns.csv
    .venv\Scripts\python.exe manage.py import_locations data\stations.csv --stations
See `data/towns_template.csv` for the columns. Towns that already exist are
matched by name within their district and given the BRRI code (field 60).

## The admin area (administrators only)
http://127.0.0.1:8000/admin/ - the **Admin** tab, shown only to administrators. It is for:

- **Analyst accounts** - add an analyst (Users → Add user), reset a password, or untick
  *Can log in* when someone leaves. Tick *Administrator* to let the person use the admin area.
- **Police stations** - check and verify the stations analysts typed in (see above).
- **Regions, districts, towns** - correct the lists the report form uses.
- **Accident reports** - look up any report, or delete one entered by mistake. Reports are
  never edited here: editing in the main app runs the checks and records the change history.
- **Change history** - read-only record of who created, edited or approved each report.

## Tests
    .venv\Scripts\python.exe manage.py test accidents

## Before going live on a BRRI server
- Set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0` and `DJANGO_ALLOWED_HOSTS`.
- Switch to PostgreSQL (and PostGIS for spatial analysis).
- Serve the site over HTTPS. Phones only allow the "Use my GPS location" button on HTTPS sites.
- Set up regular database backups.
