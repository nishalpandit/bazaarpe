from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication, get_authorization_header
from rest_framework.authtoken.models import Token


class BearerTokenAuthentication(TokenAuthentication):
    """
    Non-expiring Bearer Token Authentication.
    Accepts tokens via:
      1. HTTP Header: 'Authorization: Bearer <token>' or 'Authorization: Token <token>'
      2. Cookies: 'auth_token', 'token', or 'bearer_token'
      3. Query parameter: ?token=<token>
      4. Request body: token=<token>
    """
    keyword = 'Bearer'

    def authenticate(self, request):
        # 1. Check Authorization header
        auth = get_authorization_header(request).split()
        if auth and auth[0].decode().lower() in ('token', 'bearer'):
            if len(auth) == 1:
                raise exceptions.AuthenticationFailed('Invalid token header. No credentials provided.')
            elif len(auth) > 2:
                raise exceptions.AuthenticationFailed('Invalid token header. Token string should not contain spaces.')

            try:
                token_key = auth[1].decode()
            except UnicodeError:
                raise exceptions.AuthenticationFailed('Invalid token header. Token string should not contain invalid characters.')

            return self.authenticate_credentials(token_key)

        # 2. Check Cookies (auth_token, token, bearer_token)
        cookie_token = (
            request.COOKIES.get('auth_token')
            or request.COOKIES.get('token')
            or request.COOKIES.get('bearer_token')
        )
        if cookie_token:
            return self.authenticate_credentials(cookie_token.strip())

        # 3. Check query param or request body
        token_param = request.GET.get('token') or (
            getattr(request, 'data', {}).get('token') if hasattr(request, 'data') and isinstance(request.data, dict) else None
        )
        if token_param:
            return self.authenticate_credentials(str(token_param).strip())

        return None

    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = model.objects.select_related('user').get(key=key)
        except model.DoesNotExist:
            raise exceptions.AuthenticationFailed('Invalid token.')

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed('User account is inactive.')

        # Check account status if profile exists
        if hasattr(token.user, 'profile'):
            if token.user.profile.account_status in ('Blocked', 'Suspended'):
                raise exceptions.AuthenticationFailed('User account has been deactivated by administrator.')

        # Tokens are non-expiring
        return (token.user, token)

