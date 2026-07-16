"""Small request-inspection helpers shared between chat/signals.py (login
tracking) and chat/admin_views.py (audit log) - kept in one place so both
agree on the same X-Forwarded-For handling rather than each reimplementing
it slightly differently.
"""


def client_ip(request):
    if not request:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def raw_user_agent(request):
    if not request:
        return ''
    return request.META.get('HTTP_USER_AGENT', '')[:500]
