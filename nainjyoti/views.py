from functools import wraps

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils.http import url_has_allowed_host_and_scheme


ADMIN_CAPABILITIES = {
    'can_manage': True,
    'can_create': True,
    'can_edit': True,
    'can_delete': True,
}


def is_full_admin(user):
    """Only active Django superusers may use the administration console."""
    return user.is_authenticated and user.is_active and user.is_staff and user.is_superuser


def full_admin_required(view_func):
    """Require authentication and the full administrator role for a view."""
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url='login')
        if not is_full_admin(request.user):
            raise PermissionDenied('Full administrator access is required.')
        return view_func(request, *args, **kwargs)

    return wrapped_view


def admin_context(request, **extra):
    """Shared permission context for every administration page."""
    return {
        'user': request.user,
        'admin_capabilities': ADMIN_CAPABILITIES,
        'admin_role_label': 'Super Administrator',
        'admin_permissions_label': 'Full Access: Manage · Create · Edit · Delete',
        **extra,
    }


def ensure_demo_user():
    """Ensure the superuser exists with the requested credentials."""
    try:
        user, created = User.objects.get_or_create(username='admin')
        email_changed = user.email != 'admin@gmail.com'
        changed_fields = []

        if email_changed:
            user.email = 'admin@gmail.com'
            changed_fields.append('email')
        if created or email_changed:
            user.set_password('12345')
            changed_fields.append('password')

        required_values = {
            'is_superuser': True,
            'is_staff': True,
            'is_active': True,
            'first_name': 'Admin',
        }
        for field, value in required_values.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                changed_fields.append(field)

        if changed_fields:
            user.save(update_fields=changed_fields)
    except Exception:
        pass


def home_view(request):
    """
    Root route:
    When running the server, opens the login template first if unauthenticated,
    or directs to the dashboard if already signed in.
    """
    if is_full_admin(request.user):
        return redirect('index_html')
    if request.user.is_authenticated:
        raise PermissionDenied('Full administrator access is required.')
    return redirect('login')


def login_view(request):
    """Admin sign-in view."""
    ensure_demo_user()

    # If user arrives via Sign Out button (login.html?logout=true or direct sign out link)
    if request.GET.get('logout') == 'true':
        logout(request)
        return redirect('login')

    error = None
    if request.user.is_authenticated:
        if is_full_admin(request.user):
            return redirect('index_html')
        logout(request)
        error = 'This account does not have full administrator access.'

    if request.method == 'POST':
        login_id = request.POST.get('email', '').strip() or request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        # 1. Try standard username auth
        user = authenticate(request, username=login_id, password=password)

        # 2. Try email match if username failed
        if user is None and login_id:
            try:
                matched_user = User.objects.filter(email__iexact=login_id).first()
                if matched_user:
                    user = authenticate(request, username=matched_user.username, password=password)
            except Exception:
                pass

        if user is not None and is_full_admin(user):
            login(request, user)
            next_url = request.GET.get('next') or request.POST.get('next')
            if (
                next_url
                and not next_url.startswith('/login')
                and url_has_allowed_host_and_scheme(
                    next_url,
                    allowed_hosts={request.get_host()},
                    require_https=request.is_secure(),
                )
            ):
                return redirect(next_url)
            return redirect('index_html')
        elif user is not None:
            error = 'This account does not have full administrator access.'
        else:
            error = 'Invalid email or password. Please try again.'

    return render(request, 'login.html', {'error': error})


def logout_view(request):
    """Logs the user out and redirects to the login screen."""
    logout(request)
    return redirect('login')


@full_admin_required
def dashboard_view(request):
    """Operations console dashboard."""
    return render(request, 'index.html', admin_context(request))


import re
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.authtoken.models import Token

from .models import UserProfile, OTPVerification
from .api_views import clean_phone


def find_user_profile(identifier):
    """Find a UserProfile by id, display_id (USR-1002), phone, or email."""
    if not identifier:
        return None
    val = str(identifier).strip()

    # 1. Try USR-XXXX pattern
    if val.upper().startswith('USR-'):
        num_part = val[4:]
        if num_part.isdigit():
            user_id = int(num_part) - 1000
            p = UserProfile.objects.filter(id=user_id).first()
            if p:
                return p

    # 2. Try integer ID
    if val.isdigit():
        p = UserProfile.objects.filter(id=int(val)).first()
        if p:
            return p

    # 3. Try clean phone
    digits = re.sub(r'\D', '', val)
    if digits:
        p = UserProfile.objects.filter(phone=digits[-10:]).first()
        if p:
            return p

    # 4. Try email or full_name
    return UserProfile.objects.filter(email__iexact=val).first() or UserProfile.objects.filter(full_name__iexact=val).first()


PAGES = {
    'index': 'index.html',
    'dashboard': 'index.html',
    'categories': 'categories.html',
    'cms': 'cms.html',
    'cms-edit': 'cms-edit.html',
    'invoice-detail': 'invoice-detail.html',
    'invoices': 'invoices.html',
    'kyc': 'kyc.html',
    'ledgers': 'ledgers.html',
    'locations': 'locations.html',
    'order-detail': 'order-detail.html',
    'orders': 'orders.html',
    'payments': 'payments.html',
    'ratings': 'ratings.html',
    'refunds': 'refunds.html',
    'request-detail': 'request-detail.html',
    'requests': 'requests.html',
    'settings': 'settings.html',
    'settlements': 'settlements.html',
    'user-detail': 'user-detail.html',
    'users': 'users.html',
    'vendor-detail': 'vendor-detail.html',
    'vendors': 'vendors.html',
}


def page_view(request, page_name):
    """
    Renders any template by route or static .html link, enforcing authentication.
    Dynamically loads database models for users and user-detail.
    """
    clean_name = page_name.replace('.html', '').strip('/')

    if clean_name in ('login', 'sign-in'):
        if request.user.is_authenticated:
            # Clicking 'Sign out' which links to login.html will log out the user
            logout(request)
        return redirect('login')

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url='login')
    if not is_full_admin(request.user):
        raise PermissionDenied('Full administrator access is required.')

    # Dynamic Users list page
    if clean_name == 'users':
        q = request.GET.get('q', '').strip()
        account = request.GET.get('account', '').strip()
        city = request.GET.get('city', '').strip()
        from_date = request.GET.get('from', '').strip()
        page_num = request.GET.get('page', 1)

        users_qs = UserProfile.objects.all().select_related('service_zone', 'service_zone__city', 'user').prefetch_related('saved_addresses').order_by('-created_at')

        if q:
            id_match = None
            if q.upper().startswith('USR-'):
                sub = q[4:]
                if sub.isdigit():
                    id_match = int(sub) - 1000
            elif q.isdigit():
                id_match = int(q)

            q_filter = (
                Q(full_name__icontains=q) |
                Q(phone__icontains=q) |
                Q(email__icontains=q) |
                Q(address__icontains=q) |
                Q(pincode__icontains=q) |
                Q(city__icontains=q)
            )
            if id_match is not None:
                q_filter |= Q(id=id_match)
            users_qs = users_qs.filter(q_filter)

        if account:
            if account.lower() == 'active':
                users_qs = users_qs.filter(account_status='Active')
            elif account.lower() == 'blocked':
                users_qs = users_qs.filter(account_status='Blocked')
            else:
                users_qs = users_qs.filter(account_status__iexact=account)

        if city:
            users_qs = users_qs.filter(city__iexact=city)

        if from_date:
            try:
                users_qs = users_qs.filter(created_at__date__gte=from_date)
            except Exception:
                pass

        # CSV Export for user data
        if request.GET.get('export') == 'csv':
            import csv
            from django.http import HttpResponse
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="bazaarpe_users.csv"'
            writer = csv.writer(response)
            writer.writerow(['User ID', 'Full Name', 'Mobile Number', 'Email', 'Primary Address', 'Pincode', 'City', 'Service Zone', 'Status', 'Registered Date'])
            for u in users_qs:
                zone_str = u.service_zone.name if u.service_zone else ''
                writer.writerow([
                    u.display_user_id,
                    u.full_name,
                    u.phone,
                    u.email or '',
                    u.address or '',
                    u.pincode or '',
                    u.city or '',
                    zone_str,
                    u.account_status,
                    u.created_at.strftime('%Y-%m-%d %H:%M') if u.created_at else ''
                ])
            return response

        total_count = UserProfile.objects.count()
        active_count = UserProfile.objects.filter(account_status='Active').count()
        blocked_count = UserProfile.objects.filter(account_status='Blocked').count()

        cities = list(UserProfile.objects.exclude(city__isnull=True).exclude(city='').values_list('city', flat=True).distinct())

        paginator = Paginator(users_qs, 15)
        page_obj = paginator.get_page(page_num)

        ctx = admin_context(
            request,
            page_name=clean_name,
            users=page_obj.object_list,
            page_obj=page_obj,
            paginator=paginator,
            total_count=total_count,
            active_count=active_count,
            blocked_count=blocked_count,
            cities=cities,
            current_q=q,
            current_account=account,
            current_city=city,
            current_from=from_date,
        )
        return render(request, 'users.html', ctx)

    # Dynamic User Detail view
    if clean_name == 'user-detail':
        identifier = request.GET.get('id') or request.GET.get('user_id') or request.GET.get('phone')
        profile = None
        if identifier:
            profile = find_user_profile(identifier)
        if not profile:
            profile = UserProfile.objects.first()

        saved_addresses = []
        if profile:
            saved_addresses = profile.saved_addresses.all().order_by('-is_default', '-created_at')

        ctx = admin_context(
            request,
            page_name=clean_name,
            profile=profile,
            saved_addresses=saved_addresses,
        )
        return render(request, 'user-detail.html', ctx)

    if clean_name in PAGES:
        return render(request, PAGES[clean_name], admin_context(request, page_name=clean_name))

    raise Http404(f"Page '{page_name}' not found")


@csrf_exempt
@full_admin_required
def admin_action_view(request, action_path):
    """
    Handles administrative actions (manage, create, edit, delete, block) submitted to /admin/<path>.
    Super administrator has full permission to apply changes directly to the database.
    Supports both HTML form redirects and JSON fetch responses.
    """
    action = action_path.strip('/')
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

    if request.method == 'POST':
        import json
        data = request.POST.copy()
        if request.content_type == 'application/json' and request.body:
            try:
                data.update(json.loads(request.body.decode('utf-8')))
            except Exception:
                pass

        # 1. CREATE USER
        if action.startswith('users/create'):
            full_name = data.get('name') or data.get('full_name', '')
            full_name = full_name.strip()
            phone_raw = data.get('phone') or data.get('mobile_number', '')
            phone = clean_phone(phone_raw)
            email = data.get('email', '').strip() or None
            city = data.get('city', '').strip() or 'Bengaluru'
            account_status = data.get('status') or data.get('account_status', 'Active')
            address = data.get('address', '').strip()
            pincode = data.get('pincode', '').strip() or '560001'

            if not full_name or not phone or len(phone) != 10:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'Please provide full name and a valid 10-digit mobile number.'}, status=400)
                return redirect('page_view', page_name='users.html')

            user, _ = User.objects.get_or_create(username=phone)
            parts = full_name.split()
            user.first_name = parts[0]
            user.last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''
            if email:
                user.email = email
            user.set_unusable_password()
            user.save()

            profile, _ = UserProfile.objects.update_or_create(
                phone=phone,
                defaults={
                    'user': user,
                    'full_name': full_name,
                    'email': email,
                    'city': city,
                    'account_status': account_status,
                    'address': address,
                    'pincode': pincode,
                }
            )
            Token.objects.get_or_create(user=user)

            if is_ajax:
                return JsonResponse({'success': True, 'message': f"User '{full_name}' created successfully.", 'user': profile.to_dict()})
            return redirect('page_view', page_name='users.html')

        # 2. EDIT USER
        if action.startswith('users/edit'):
            user_id = data.get('user_id') or data.get('id')
            profile = find_user_profile(user_id)
            if not profile:
                profile = find_user_profile(data.get('phone')) or find_user_profile(data.get('name'))

            if not profile:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'User profile not found.'}, status=404)
                return redirect('page_view', page_name='users.html')

            full_name = data.get('name') or data.get('full_name')
            if full_name:
                profile.full_name = full_name.strip()
                parts = profile.full_name.split()
                profile.user.first_name = parts[0]
                profile.user.last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''

            if 'email' in data:
                profile.email = data['email'].strip() or None
                profile.user.email = profile.email or ''

            if 'city' in data and data['city']:
                profile.city = data['city'].strip()

            if 'status' in data or 'account_status' in data:
                profile.account_status = data.get('status') or data.get('account_status')
                if profile.account_status in ('Blocked', 'Suspended'):
                    Token.objects.filter(user=profile.user).delete()

            if 'address' in data:
                profile.address = data['address'].strip()

            if 'pincode' in data:
                profile.pincode = data['pincode'].strip()

            profile.user.save()
            profile.save()

            if is_ajax:
                return JsonResponse({'success': True, 'message': f"User '{profile.full_name}' updated successfully.", 'user': profile.to_dict()})

            referer = request.META.get('HTTP_REFERER')
            if referer:
                return redirect(referer)
            return redirect('page_view', page_name='users.html')

        # 3. DELETE USER
        if action.startswith('users/delete') or action.endswith('/delete'):
            user_id = data.get('user_id') or data.get('id') or action.replace('users/', '').replace('/delete', '')
            profile = find_user_profile(user_id) or find_user_profile(data.get('item_name'))
            if profile:
                user_name = profile.full_name
                u = profile.user
                profile.delete()
                if u and not u.is_superuser:
                    u.delete()
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f"User '{user_name}' deleted successfully."})
            else:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'User record not found.'}, status=404)

            referer = request.META.get('HTTP_REFERER')
            if referer:
                return redirect(referer)
            return redirect('page_view', page_name='users.html')

        # 4. BLOCK USER
        if action.endswith('/block') or action.startswith('users/block'):
            user_id = data.get('user_id') or action.replace('users/', '').replace('/block', '')
            profile = find_user_profile(user_id)
            if profile:
                profile.account_status = 'Blocked'
                profile.save(update_fields=['account_status'])
                Token.objects.filter(user=profile.user).delete()
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f"User '{profile.full_name}' blocked."})

            referer = request.META.get('HTTP_REFERER')
            if referer:
                return redirect(referer)
            return redirect('page_view', page_name='users.html')

        # Fallback redirect to referer
        referer = request.META.get('HTTP_REFERER')
        if referer and url_has_allowed_host_and_scheme(
            referer,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(referer)
        return redirect('index_html')

    return redirect('index_html')


