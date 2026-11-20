from django.db import migrations

RIGHTS = [
    ("submit_report", "Can submit reports"),
    ("approve_report", "Can approve reports"),
    ("do_analysis", "Can do analysis"),
]


def give_existing_accounts_all_rights(apps, schema_editor):
    """Accounts made before the rights existed could do all three: they keep that."""
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("auth", "User")
    ct, _ = ContentType.objects.get_or_create(app_label="accidents", model="accident")
    perms = [Permission.objects.get_or_create(content_type=ct, codename=code,
                                              defaults={"name": name})[0]
             for code, name in RIGHTS]
    for user in User.objects.filter(is_superuser=False):
        user.user_permissions.add(*perms)


class Migration(migrations.Migration):

    dependencies = [
        ("accidents", "0012_injury_not_known_if_hospitalised"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="accident",
            options={
                "ordering": ["-accident_date", "-accident_time"],
                "permissions": RIGHTS,
                "verbose_name": "accident report",
            },
        ),
        migrations.RunPython(give_existing_accounts_all_rights, migrations.RunPython.noop),
    ]
