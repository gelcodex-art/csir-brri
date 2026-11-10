"""Codes from the BRRI coding manual.

- 28 Collision code: a list of the manual's codes (stored text unchanged).
- 30 Registration code: new.
- 39 / pedestrian Nationality: typed text -> manual code (Ghanaian = 1).
- 43 Place of issue: office codes written in capitals ("As1" -> "AS1").
"""
from django.db import migrations, models

import accidents.codebook as cb

NAT = {"ghanaian": 1, "ghana": 1}
AFRICAN = ("nigeria", "togo", "burkin", "ivor", "benin", "niger", "mali", "liberia", "sierra",
           "senegal", "gambia", "guinea", "cameroon", "south africa", "kenya")


def to_code(text):
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in NAT:
        return 1
    if any(a in t for a in AFRICAN):
        return 2
    return 5                                            # Other


def forwards(apps, schema_editor):
    Vehicle = apps.get_model("accidents", "Vehicle")
    Ped = apps.get_model("accidents", "PedestrianCasualty")
    for v in Vehicle.objects.all():
        v.nat_code = to_code(v.driver_nationality)
        place = (v.licence_place_of_issue or "").strip()
        if place.upper() in cb.LICENCE_PLACE:
            place = place.upper()
        v.licence_place_of_issue = place
        v.save(update_fields=["nat_code", "licence_place_of_issue"])
    for p in Ped.objects.all():
        p.nat_code = to_code(p.nationality)
        p.save(update_fields=["nat_code"])


def backwards(apps, schema_editor):
    Vehicle = apps.get_model("accidents", "Vehicle")
    Ped = apps.get_model("accidents", "PedestrianCasualty")
    for model, field in ((Vehicle, "driver_nationality"), (Ped, "nationality")):
        for o in model.objects.all():
            setattr(o, field, cb.NATIONALITY.get(o.nat_code, ""))
            o.save(update_fields=[field])


coded = dict(blank=True, null=True)

class Migration(migrations.Migration):

    dependencies = [("accidents", "0008_admin_names")]

    operations = [
        migrations.AlterField(
            model_name="accident", name="collision_code",
            field=models.CharField(blank=True, choices=cb.collision_code_choices(), max_length=4,
                                   verbose_name="28 Collision code")),
        migrations.AddField(
            model_name="vehicle", name="registration_code",
            field=models.PositiveSmallIntegerField(choices=cb.choices(cb.VEHICLE_REG_CODE),
                                                   verbose_name="30 Registration code", **coded)),
        migrations.AddField(model_name="vehicle", name="nat_code",
                            field=models.PositiveSmallIntegerField(**coded)),
        migrations.AddField(model_name="pedestriancasualty", name="nat_code",
                            field=models.PositiveSmallIntegerField(**coded)),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="vehicle", name="driver_nationality"),
        migrations.RemoveField(model_name="pedestriancasualty", name="nationality"),
        migrations.RenameField(model_name="vehicle", old_name="nat_code", new_name="driver_nationality"),
        migrations.RenameField(model_name="pedestriancasualty", old_name="nat_code", new_name="nationality"),
        migrations.AlterField(
            model_name="vehicle", name="driver_nationality",
            field=models.PositiveSmallIntegerField(choices=cb.choices(cb.NATIONALITY),
                                                   verbose_name="39 Nationality", **coded)),
        migrations.AlterField(
            model_name="pedestriancasualty", name="nationality",
            field=models.PositiveSmallIntegerField(choices=cb.choices(cb.NATIONALITY),
                                                   verbose_name="Nationality", **coded)),
    ]
