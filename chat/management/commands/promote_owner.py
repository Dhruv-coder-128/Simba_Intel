"""Manually designates the Owner - the fallback path for when chat/migrations/
0023_promote_owner_and_backfill_roles.py had no superuser/OWNER_EMAIL match to
promote at migrate time (e.g. a brand new install where `createsuperuser`
only runs after `migrate`). Also the correct tool for fixing ownership by
hand outside of the app's own transfer_ownership admin-console action
(which requires being logged in as the current Owner already).

Usage:
    python manage.py promote_owner someone@example.com
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from chat.models import Role, UserProfile

User = get_user_model()


class Command(BaseCommand):
    help = "Promote a user to Role.OWNER, demoting any existing Owner to Super Admin first."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address of the account to make Owner.")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise CommandError(f"No user found with email '{email}'.")
        except User.MultipleObjectsReturned:
            raise CommandError(f"Multiple users share the email '{email}' - resolve that first.")

        with transaction.atomic():
            UserProfile.objects.filter(role=Role.OWNER).exclude(user=user).update(role=Role.SUPER_ADMIN)
            profile = UserProfile.get_or_create_for(user)
            profile.role = Role.OWNER
            profile.save(update_fields=["role"])
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=["is_staff", "is_superuser"])

        self.stdout.write(self.style.SUCCESS(f"{user.username} ({email}) is now Owner."))
