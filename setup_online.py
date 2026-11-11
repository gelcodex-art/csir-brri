"""Fill the online (Supabase) database. Run by setup-online.bat.

Asks for the Supabase connection string, tests it, then creates the tables and
loads the Ghana regions, districts, towns and police stations. Safe to run again.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = [
    ("Creating the tables", ["migrate", "--noinput"]),
    ("Creating the shared cache", ["createcachetable"]),
    ("Loading regions, districts and towns (several minutes)", ["load_ghana_locations"]),
    ("Loading police stations", ["load_police_stations"]),
    ("Adding the extra Kumasi stations",
     ["import_locations", str(HERE / "data" / "kumasi_stations_unverified.csv"), "--stations", "--unverified"]),
    ("Loading the police station codes", ["load_station_codes"]),
]
# "update": for a site that is already set up - only what a new version needs.
UPDATE_STEPS = [
    ("Updating the tables", ["migrate", "--noinput"]),
    ("Loading the police station codes", ["load_station_codes"]),
]


def main():
    print("Paste the Supabase 'Transaction pooler' line (starts with postgresql://)")
    print("then press Enter. Right-click pastes in this window.\n")
    url = input("> ").strip().strip('"').strip("'")
    if not url.startswith(("postgresql://", "postgres://")):
        return "That does not start with postgresql:// - copy the whole line from Supabase."
    if "[" in url or "]" in url:
        return ("The line still has [YOUR-PASSWORD] in it. Replace that whole part, "
                "including the [ ] brackets, with your database password.")
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("PGCONNECT_TIMEOUT", "20")      # give up instead of hanging
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "brri.settings")

    print("\nTesting the connection...")
    try:
        import django
        django.setup()
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("select 1")
    except Exception as exc:                      # show the real reason, in plain words
        text = str(exc).strip().splitlines()[-1] if str(exc).strip() else type(exc).__name__
        hint = ""
        low = str(exc).lower()
        if "password" in low or "authentication" in low:
            hint = ("\nThe password is wrong. If it has symbols like @ # / : ? % in it, reset it in "
                    "Supabase (Project Settings > Database) to letters and numbers only, then try again.")
        elif "timeout" in low or "timed out" in low:
            hint = "\nNo answer from the database. Check your internet, and that the line is the Transaction pooler one."
        elif "tenant" in low or "not found" in low or "resolve" in low or "getaddrinfo" in low:
            hint = "\nThe address looks wrong. Copy the Transaction pooler line again from Supabase > Connect."
        return f"Could not connect: {text}{hint}"
    print("Connected.\n")

    update = "update" in sys.argv[1:]
    for label, args in (UPDATE_STEPS if update else STEPS):
        print(f"--- {label} ...")
        if subprocess.run([sys.executable, str(HERE / "manage.py"), *args], cwd=HERE).returncode:
            return f"'{label}' failed. Copy the lines above and send them to get help."
    if update:
        print("\nALL DONE. The online database is up to date.")
        return None
    print("\nALL DONE. Now open https://csir-brri.vercel.app/setup/ and create your administrator.")
    print("If that page sends you to the login page, the DATABASE_URL saved in Vercel is not")
    print("the same line you pasted here: fix it in Vercel, then Redeploy.")
    return None


if __name__ == "__main__":
    problem = main()
    if problem:
        print("\nPROBLEM: " + problem)
    input("\nPress Enter to close this window.")
