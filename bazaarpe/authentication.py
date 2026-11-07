from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication


def is_vendor_account(user):
    """Business profiles are authoritative for legacy accounts with a stale flag."""
    return bool(getattr(getattr(user, 'profile', None), 'is_vendor', False) or hasattr(user, 'vendor_profile'))


def request_is_vendor(request):
    return request.path.startswith('/api/vendor/')


class BearerTokenAuthentication(TokenAuthentication):
    """Accept only Authorization: Bearer <token>, enforcing the app account role."""
    keyword = 'Bearer'

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        profile = getattr(user, 'profile', None)
        if profile and profile.account_status in ('Blocked', 'Suspended'):
            raise exceptions.AuthenticationFailed('User account has been deactivated by administrator.')
        if request.path.startswith(('/api/vendor/', '/api/user/')):
            if is_vendor_account(user) != request_is_vendor(request):
                raise exceptions.PermissionDenied('This account cannot access this app. Use the vendor app.' if is_vendor_account(user) else 'This account cannot access this app. Use the customer app.')
        return user, token
