from django.db import migrations

# All default to enabled=True: every one of these is a feature that's
# already live today, so seeding them enabled preserves current behavior
# exactly - an admin has to deliberately flip one off, nothing changes on
# deploy.
DEFAULT_FLAGS = [
    ("image_generation", "Image Studio (AI image generation)"),
    ("vision", "Vision (image understanding in chat)"),
    ("ai_chat", "AI Chat (text conversation)"),
    ("analytics", "Personal analytics dashboard"),
    ("registration", "New account registration"),
    ("google_login", "Continue with Google"),
    ("email_verification", "Email verification enforcement"),
    ("maintenance_mode", "Site-wide maintenance mode"),
]


def seed_flags(apps, schema_editor):
    FeatureFlag = apps.get_model("chat", "FeatureFlag")
    for key, description in DEFAULT_FLAGS:
        FeatureFlag.objects.get_or_create(
            key=key,
            defaults={"description": description, "enabled": key != "maintenance_mode"},
        )


def noop_reverse(apps, schema_editor):
    # Deliberately a no-op, not a delete: if an admin has since toggled any
    # of these (which is the entire point of a feature flag), reversing this
    # migration should not silently destroy that state.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0019_adminauditlog_browser_adminauditlog_ip_address_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_flags, noop_reverse),
    ]
