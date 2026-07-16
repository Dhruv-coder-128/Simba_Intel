"""SIMBA_INTEL's role-based access control.

Single source of truth for every privileged decision in the app - nothing
outside this module should ever compare `request.user.is_staff`/
`is_superuser` to decide what a user may do. Those two Django flags exist
purely for framework/django.contrib.admin compatibility (see UserProfile.role's
docstring in chat/models.py); they're kept in sync as a side effect of role
changes (chat/admin_views.py's change_role action) but are never themselves
a permission source here.

Adding a future role (e.g. a "Support" tier) means adding one line to
Role (chat/models.py) and one line to ROLE_LEVEL below - no other file in
this module, or any view using these decorators, needs to change.
"""
import functools

from django.core.exceptions import PermissionDenied

from chat.models import Role

# Higher number = more privilege. Deliberately spaced out (not 5,4,3,2,1,0)
# so a future role can be inserted between two existing ones without
# renumbering everything else.
ROLE_LEVEL = {
    Role.OWNER: 100,
    Role.SUPER_ADMIN: 80,
    Role.ADMIN: 60,
    Role.MODERATOR: 40,
    Role.VERIFIED: 20,
    Role.USER: 0,
}


def user_role(user) -> str:
    """Always returns a real Role value, never raises, and never writes to
    the database (a permission check must be a pure read) - an anonymous
    user always resolves to Role.USER. A user with NO profile row yet
    (profiles are created lazily, on first real use - see UserProfile.
    get_or_create_for's docstring) falls back to deriving a role from
    is_superuser/is_staff instead of blindly defaulting to Role.USER,
    mirroring get_or_create_for's own bootstrap logic exactly - otherwise a
    freshly created superuser (createsuperuser, or any pre-RBAC test
    fixture) would fail every permission check until something happened to
    trigger their first profile write, a chicken-and-egg gap that would
    otherwise lock them out of the very console they'd use to fix it."""
    if not getattr(user, "is_authenticated", False):
        return Role.USER
    profile = getattr(user, "profile", None)
    if profile is not None:
        return profile.role
    if user.is_superuser:
        return Role.SUPER_ADMIN
    if user.is_staff:
        return Role.ADMIN
    return Role.USER


def role_level(role: str) -> int:
    return ROLE_LEVEL.get(role, ROLE_LEVEL[Role.USER])


def has_role_at_least(user, minimum_role: str) -> bool:
    """True if user's role outranks or equals minimum_role in the
    hierarchy - e.g. has_role_at_least(user, Role.ADMIN) is True for an
    Admin, Super Admin, or Owner, False for a Moderator or below."""
    return role_level(user_role(user)) >= role_level(minimum_role)


def is_owner(user) -> bool:
    return user_role(user) == Role.OWNER


def can_access_admin_console(user) -> bool:
    """Owner, Super Admin, and Admin only - explicitly excludes Moderator,
    matching the console visibility rule (Moderator's own, narrower
    permissions - view users, suspend, ban, delete chats, view reports -
    are enforced independently via has_permission() below, not by letting
    Moderators into this console)."""
    return has_role_at_least(user, Role.ADMIN)


# Fine-grained capability map, independent of console access - lets a
# permission be checked correctly even for a role that has the capability
# but not general console access (e.g. Moderator can ban/suspend/view users/
# delete chats/view reports without being able to reach feature flags,
# broadcasts, or security settings). Every action gated anywhere in the app
# should have exactly one entry here rather than an inline role comparison,
# so the full permission matrix is readable in one place.
PERMISSIONS = {
    "manage_users": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN},
    "ban_user": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN, Role.MODERATOR},
    "suspend_user": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN, Role.MODERATOR},
    "force_logout": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN},
    "delete_chats": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN, Role.MODERATOR},
    "view_users": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN, Role.MODERATOR},
    "view_reports": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN, Role.MODERATOR},
    "view_analytics": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN},
    "manage_broadcasts": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN},
    "view_audit_log": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN},
    "manage_feature_flags": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN},
    "manage_security": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN},
    "manage_roles": {Role.OWNER, Role.SUPER_ADMIN},
    "delete_account": {Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN},
    "transfer_ownership": {Role.OWNER},
    "emergency_kill_switch": {Role.OWNER},
}


def has_permission(user, action: str) -> bool:
    allowed_roles = PERMISSIONS.get(action)
    if allowed_roles is None:
        # An unregistered action name is a bug in the calling code, not a
        # permission decision - fail closed rather than silently allowing
        # something nobody explicitly granted.
        return False
    return user_role(user) in allowed_roles


def can_act_on_target(actor, target_user) -> bool:
    """The Owner-protection rule: nobody except the Owner may ban, suspend,
    delete, demote, or otherwise mutate the Owner's own account - not even
    another Super Admin or a second person who also happens to hold
    Role.OWNER (which shouldn't normally exist, since ownership transfer
    is atomic, but this stays safe even if it ever did). An Owner acting on
    themselves (e.g. stepping down via transfer_ownership) is allowed."""
    target_profile = getattr(target_user, "profile", None)
    if target_profile is not None and target_profile.role == Role.OWNER:
        return actor.id == target_user.id and is_owner(actor)
    return True


def sync_django_flags(user, role: str) -> None:
    """Keeps is_staff/is_superuser in step with role changes, purely so
    django.contrib.admin (still reachable at /admin/) and any other code
    that only understands Django's own permission flags keeps behaving
    sensibly - SIMBA_INTEL's own views never read these two flags for a
    permission decision."""
    is_staff = role_level(role) >= ROLE_LEVEL[Role.MODERATOR]
    is_superuser = role_level(role) >= ROLE_LEVEL[Role.SUPER_ADMIN]
    if user.is_staff != is_staff or user.is_superuser != is_superuser:
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.save(update_fields=["is_staff", "is_superuser"])


def require_role(minimum_role: str):
    """View decorator: 403s (raises PermissionDenied, rendered by Django via
    templates/403.html) unless the requesting user's role outranks or
    equals minimum_role. Stacks under @login_required - an anonymous user
    resolves to Role.USER and is rejected the same as any other
    under-privileged user, but @login_required should still run first so
    they're sent to the login page instead of a bare 403."""
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not has_role_at_least(request.user, minimum_role):
                raise PermissionDenied("Your role does not have access to this page.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_roles(*roles):
    """View decorator: like require_role, but for an exact set of roles
    rather than "at least this rank" - e.g. a page meant for Admins and
    Moderators specifically, skipping Super Admin/Owner would be wrong for
    require_role but is exactly what require_roles(Role.ADMIN,
    Role.MODERATOR) expresses. Not currently used by any URL-level view in
    this app (every existing admin-console page is a single "at least
    Admin" tier), but provided as the documented, tested extension point for
    the next one that isn't."""
    allowed = set(roles)

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if user_role(request.user) not in allowed:
                raise PermissionDenied("Your role does not have access to this page.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_permission(action: str):
    """View/action decorator keyed to the PERMISSIONS capability map rather
    than a hierarchy rank - use this (not require_role) wherever the spec
    grants a capability to a role that sits below the console's own
    require_role(Role.ADMIN) gate, so the same action function stays correct
    if that role ever gets a direct entry point later."""
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not has_permission(request.user, action):
                raise PermissionDenied("Your role does not have permission to do this.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
