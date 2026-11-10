"""
Load Ghana's 16 regions with their capitals (and capital-city districts) so the
system is usable immediately. Load BRRI's full district/town/code list with:

    python manage.py import_locations data/towns.csv
"""
from django.core.management.base import BaseCommand

from accidents.models import District, Region, Town

# region: (capital town, district/assembly of the capital, approx lat, lng)
SEED = {
    "Ahafo": ("Goaso", "Asunafo North Municipal", 6.8036, -2.5172),
    "Ashanti": ("Kumasi", "Asokore Mampong Municipal", 6.6885, -1.6244),
    "Bono": ("Sunyani", "Sunyani Municipal", 7.3349, -2.3123),
    "Bono East": ("Techiman", "Techiman Municipal", 7.5909, -1.9344),
    "Central": ("Cape Coast", "Cape Coast Metropolitan", 5.1053, -1.2466),
    "Eastern": ("Koforidua", "New Juaben South Municipal", 6.0940, -0.2591),
    "Greater Accra": ("Accra", "Accra Metropolitan", 5.5600, -0.2057),
    "North East": ("Nalerigu", "East Mamprusi Municipal", 10.5273, -0.3698),
    "Northern": ("Tamale", "Tamale Metropolitan", 9.4008, -0.8393),
    "Oti": ("Dambai", "Krachi East Municipal", 8.0700, 0.1800),
    "Savannah": ("Damongo", "West Gonja Municipal", 9.0833, -1.8167),
    "Upper East": ("Bolgatanga", "Bolgatanga Municipal", 10.7856, -0.8514),
    "Upper West": ("Wa", "Wa Municipal", 10.0601, -2.5099),
    "Volta": ("Ho", "Ho Municipal", 6.6008, 0.4713),
    "Western": ("Sekondi-Takoradi", "Sekondi-Takoradi Metropolitan", 4.9340, -1.7137),
    "Western North": ("Sefwi Wiawso", "Sefwi Wiawso Municipal", 6.2058, -2.4859),
}


class Command(BaseCommand):
    help = "Create the 16 regions of Ghana with their capital towns."

    def handle(self, *args, **opts):
        for name, (capital, district, lat, lng) in SEED.items():
            region, _ = Region.objects.update_or_create(name=name, defaults={"capital": capital})
            d, _ = District.objects.get_or_create(region=region, name=district)
            Town.objects.get_or_create(district=d, name=capital,
                                       defaults={"latitude": lat, "longitude": lng})
        self.stdout.write(self.style.SUCCESS(
            f"Regions: {Region.objects.count()}, districts: {District.objects.count()}, "
            f"towns: {Town.objects.count()}"))
