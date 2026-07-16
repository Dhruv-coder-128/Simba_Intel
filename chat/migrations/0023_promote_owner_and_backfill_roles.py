"""One-time backfill for the RBAC rollout: gives every existing account a
sensible role based on its current is_staff/is_superuser flags, and
promotes exactly one account to Role.OWNER so "only one Owner exists" holds
from the very first migrate.

Owner selection (in order):
  1. settings.OWNER_EMAIL, if set (see simba_web/settings.py) - matched
     case-insensitively.
  2. Otherwise, the existing Django superuser with the earliest
     date_joined - the common case for an app that's already deployed:
     that's the account created via createsuperuser before this migration
     ever ran.
  3. If neither exists (e.g. a brand new install where createsuperuser
     hasn't run yet), nobody is promoted here - the promote_owner
     management command (chat/management/commands/promote_owner.py) covers
     that afterwards, since a migration can't wait for a command that
     hasn't been run yet.

Every other existing superuser becomes Role.SUPER_ADMIN; is_staff-only
accounts become Role.ADMIN; everyone else stays Role.USER (the field's own
default, so no explicit write is needed for them).
"""
from django.conf import settings
from django.db import migrations


def promote_owner_and_backfill_roles(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    UserProfile = apps.get_model("chat", "UserProfile")

    owner_email = (settings.OWNER_EMAIL or "").strip().lower()
    owner_user = None
    if owner_email:
        owner_user = User.objects.filter(email__iexact=owner_email).first()
    if owner_user is None:
        owner_user = User.objects.filter(is_superuser=True).order_by("date_joined", "id").first()

    for user in User.objects.all():
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if owner_user is not None and user.id == owner_user.id:
            role = "owner"
        elif user.is_superuser:
            role = "super_admin"
        elif user.is_staff:
            role = "admin"
        else:
            role = "user"
        if profile.role != role:
            profile.role = role
            profile.save(update_fields=["role"])


def noop_reverse(apps, schema_editor):
    # Deliberately a no-op: reversing this migration should not silently
    # demote every admin/owner back to a role that no longer reflects
    # decisions made through the app since this ran.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0022_add_role_field"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(promote_owner_and_backfill_roles, noop_reverse),
    ]
