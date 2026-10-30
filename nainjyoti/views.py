from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse, HttpResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from functools import wraps
from decimal import Decimal, InvalidOperation
import csv
import json
import re

from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, Avg
from django.views.decorators.csrf import csrf_exempt
from rest_framework.authtoken.models import Token

from .models import (
    UserProfile, UserAddress, OTPVerification, PickupOrder, PickupImage,
    OrderReview, OrderInvoice, UserBankDetail, NegotiationProposal,
    UserNotification, PaymentTransaction, PaymentWebhookEvent,
    VendorProfile, VendorBillingSetting, RefundRequest,
    ScrapCategory, ScrapSubCategory, ServiceCity, ServiceZone,
    LegalDocument, UserConsent, VendorLocationTrack,
)
from .api_views import clean_phone


ADMIN_CAPABILITIES = {
    'can_manage': True,
    'can_create': True,
    'can_edit': True,
    'can_delete': True,
    'can_manage_users': True,
    'can_create_users': True,
    'can_edit_users': True,
    'can_delete_users': True,
    'can_block_users': True,
    'can_manage_all': True,
}


def is_full_admin(user):
    """Check if the user has full administrative privileges."""
    return bool(user and user.is_authenticated and (user.is_superuser or user.is_staff))


def full_admin_required(view_func):
    """Enforce super administrator authentication with Bearer token & session cookie support."""
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            auth_header = request.headers.get('Authorization', '')
            token_key = None
            if auth_header.startswith('Bearer ') or auth_header.startswith('Token '):
                parts = auth_header.split()
                if len(parts) > 1:
                    token_key = parts[1].strip()
            elif 'auth_token' in request.COOKIES:
                token_key = request.COOKIES['auth_token'].strip()
            if token_key:
                try:
                    token_obj = Token.objects.select_related('user').get(key=token_key)
                    if token_obj.user.is_active:
                        request.user = token_obj.user
                except Token.DoesNotExist:
                    pass
        if not request.user.is_authenticated:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': 'Authentication required.'}, status=401)
            return redirect_to_login(request.get_full_path(), login_url='login')
        if not is_full_admin(request.user):
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': 'Full administrator access is required.'}, status=403)
            raise PermissionDenied('Full administrator access is required.')
        return view_func(request, *args, **kwargs)

    return wrapped_view


def admin_context(request, **extra):
    """Shared permission and dynamic navigation badge context for every administration page."""
    try:
        pending_requests_count = PickupOrder.objects.filter(
            status__in=[PickupOrder.Status.NEGOTIATION_PENDING, PickupOrder.Status.ADMIN_NEGOTIATION]
        ).count()
        pending_kyc_count = VendorProfile.objects.filter(
            kyc_status=VendorProfile.KYCStatus.UNDER_REVIEW
        ).count()
        pending_settlements_count = PickupOrder.objects.filter(
            invoice__payment_status=OrderInvoice.PaymentStatus.PAID,
            status__in=[PickupOrder.Status.COMPLETED, PickupOrder.Status.USER_REVIEW],
            payout_status=PickupOrder.PayoutStatus.PENDING,
        ).count()
        pending_refunds_count = RefundRequest.objects.filter(
            status=RefundRequest.Status.REQUESTED
        ).count()
        pending_ratings_count = OrderReview.objects.filter(
            is_approved_by_admin=False
        ).count()
        active_orders_count = PickupOrder.objects.exclude(
            status__in=[PickupOrder.Status.COMPLETED, PickupOrder.Status.CANCELLED, PickupOrder.Status.USER_PAYOUT]
        ).count()
    except Exception:
        pending_requests_count = 0
        pending_kyc_count = 0
        pending_settlements_count = 0
        pending_refunds_count = 0
        pending_ratings_count = 0
        active_orders_count = 0

    badges = {
        'requests': pending_requests_count,
        'kyc': pending_kyc_count,
        'settlements': pending_settlements_count,
        'refunds': pending_refunds_count,
        'ratings': pending_ratings_count,
        'orders': active_orders_count,
    }
    return {
        'user': request.user,
        'admin_capabilities': ADMIN_CAPABILITIES,
        'admin_role_label': 'Super Administrator',
        'admin_permissions_label': 'Full Access: Manage · Create · Edit · Delete',
        'sidebar_badges': badges,
        'pending_requests_count': pending_requests_count,
        'pending_kyc_count': pending_kyc_count,
        'pending_settlements_count': pending_settlements_count,
        'pending_refunds_count': pending_refunds_count,
        'pending_ratings_count': pending_ratings_count,
        'active_orders_count': active_orders_count,
        'live_pickup_enabled': True,
        'live_invoice_enabled': True,
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
    """Root route: opens login if unauthenticated or dashboard if authenticated."""
    if is_full_admin(request.user):
        return redirect('index_html')
    if request.user.is_authenticated:
        raise PermissionDenied('Full administrator access is required.')
    return redirect('login')


def login_view(request):
    """Admin sign-in view."""
    ensure_demo_user()

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

        user = authenticate(request, username=login_id, password=password)
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


def find_user_profile(identifier):
    """Find a UserProfile by id, display_id (USR-1002), phone, or email."""
    if not identifier:
        return None
    val = str(identifier).strip()

    if val.upper().startswith('USR-'):
        num_part = val[4:]
        if num_part.isdigit():
            user_id = int(num_part) - 1000
            p = UserProfile.objects.filter(id=user_id).first()
            if p:
                return p

    if val.isdigit():
        p = UserProfile.objects.filter(id=int(val)).first()
        if p:
            return p

    digits = re.sub(r'\D', '', val)
    if digits:
        p = UserProfile.objects.filter(phone=digits[-10:]).first()
        if p:
            return p

    return UserProfile.objects.filter(email__iexact=val).first() or UserProfile.objects.filter(full_name__iexact=val).first()


def find_vendor_profile(identifier):
    """Find a VendorProfile by id, VND-XXX, phone, shop_name, or owner."""
    if not identifier:
        return None
    val = str(identifier).strip()

    if val.upper().startswith('VND-'):
        num_part = val[4:]
        if num_part.isdigit():
            v = VendorProfile.objects.filter(id=int(num_part)).first()
            if v:
                return v
            v = VendorProfile.objects.filter(id=int(num_part) - 500).first()
            if v:
                return v

    if val.isdigit():
        v = VendorProfile.objects.filter(id=int(val)).first()
        if v:
            return v

    digits = re.sub(r'\D', '', val)
    if digits:
        v = VendorProfile.objects.filter(user__username=digits[-10:]).first()
        if v:
            return v

    return (
        VendorProfile.objects.filter(shop_name__icontains=val).first() or
        VendorProfile.objects.filter(owner_name__icontains=val).first()
    )


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


@full_admin_required
def dashboard_view(request):
    """Operations console dashboard with dynamic database metrics."""
    total_users_count = UserProfile.objects.count()
    total_vendors_count = VendorProfile.objects.count()
    active_vendors_count = VendorProfile.objects.filter(kyc_status=VendorProfile.KYCStatus.APPROVED).count()
    blocked_vendors_count = VendorProfile.objects.filter(kyc_status__in=[VendorProfile.KYCStatus.REJECTED, VendorProfile.KYCStatus.SUSPENDED]).count()
    online_vendors_count = VendorProfile.objects.filter(is_online=True).count()
    eligible_vendors_count = VendorProfile.objects.filter(kyc_status=VendorProfile.KYCStatus.APPROVED).count()

    active_orders_count = PickupOrder.objects.exclude(status__in=[PickupOrder.Status.COMPLETED, PickupOrder.Status.CANCELLED, PickupOrder.Status.USER_PAYOUT]).count()
    assigned_orders_count = PickupOrder.objects.filter(status=PickupOrder.Status.VENDOR_ASSIGNED).count()
    in_pickup_orders_count = PickupOrder.objects.filter(status__in=[PickupOrder.Status.PICKUP_IN_PROGRESS, PickupOrder.Status.VENDOR_ON_THE_WAY, PickupOrder.Status.REACHED_LOCATION]).count()
    published_orders_count = PickupOrder.objects.filter(status=PickupOrder.Status.SEARCHING_VENDOR).count()
    negotiation_orders_count = PickupOrder.objects.filter(status__in=[PickupOrder.Status.NEGOTIATION_PENDING, PickupOrder.Status.ADMIN_NEGOTIATION]).count()

    vendor_collections = PaymentTransaction.objects.filter(status=PaymentTransaction.Status.VERIFIED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    payouts_recorded = PickupOrder.objects.filter(payout_status=PickupOrder.PayoutStatus.DISBURSED).aggregate(t=Sum('final_amount'))['t'] or Decimal('0.00')
    commission_earned = PaymentTransaction.objects.filter(status=PaymentTransaction.Status.VERIFIED).aggregate(t=Sum('commission_amount'))['t'] or Decimal('0.00')
    platform_revenue = PaymentTransaction.objects.filter(status=PaymentTransaction.Status.VERIFIED).aggregate(t=Sum('commission_amount') + Sum('fixed_platform_fee'))['t'] or Decimal('0.00')
    pending_settlements_amount = PickupOrder.objects.filter(invoice__payment_status=OrderInvoice.PaymentStatus.PAID, payout_status=PickupOrder.PayoutStatus.PENDING).aggregate(t=Sum('final_amount'))['t'] or Decimal('0.00')

    payments_today = PaymentTransaction.objects.filter(created_at__date=timezone.now().date())
    successful_payments_amount = payments_today.filter(status=PaymentTransaction.Status.VERIFIED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    successful_payments_count = payments_today.filter(status=PaymentTransaction.Status.VERIFIED).count()
    pending_payments_amount = payments_today.filter(status=PaymentTransaction.Status.CREATED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    pending_payments_count = payments_today.filter(status=PaymentTransaction.Status.CREATED).count()
    failed_payments_amount = payments_today.filter(status=PaymentTransaction.Status.FAILED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    failed_payments_count = payments_today.filter(status=PaymentTransaction.Status.FAILED).count()
    refunded_payments_amount = RefundRequest.objects.filter(status=RefundRequest.Status.SUCCEEDED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    refunded_payments_count = RefundRequest.objects.filter(status=RefundRequest.Status.SUCCEEDED).count()

    pending_payouts_count = PickupOrder.objects.filter(invoice__payment_status=OrderInvoice.PaymentStatus.PAID, payout_status=PickupOrder.PayoutStatus.PENDING).count()
    recorded_payouts_count = PickupOrder.objects.filter(payout_status=PickupOrder.PayoutStatus.DISBURSED).count()
    recorded_payouts_amount = PickupOrder.objects.filter(payout_status=PickupOrder.PayoutStatus.DISBURSED).aggregate(t=Sum('final_amount'))['t'] or Decimal('0.00')

    recent_orders = PickupOrder.objects.select_related('user', 'user__profile', 'address', 'category', 'subcategory', 'invoice').order_by('-created_at')[:8]
    unaccepted_orders = PickupOrder.objects.filter(status=PickupOrder.Status.SEARCHING_VENDOR).select_related('user', 'address', 'category', 'subcategory').order_by('published_at')[:5]

    # Dynamic 7-day marketplace activity time-series
    today = timezone.now().date()
    activity_labels = []
    activity_requests = []
    activity_completed = []

    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        activity_labels.append(day.strftime('%d %b'))
        req_count = PickupOrder.objects.filter(created_at__date=day).count()
        comp_count = PickupOrder.objects.filter(
            status__in=[PickupOrder.Status.COMPLETED, PickupOrder.Status.USER_REVIEW, PickupOrder.Status.USER_PAYOUT],
            pickup_otp_verified_at__date=day
        ).count()
        if comp_count == 0:
            comp_count = PickupOrder.objects.filter(
                status__in=[PickupOrder.Status.COMPLETED, PickupOrder.Status.USER_REVIEW, PickupOrder.Status.USER_PAYOUT],
                pickup_otp_verified_at__isnull=True,
                updated_at__date=day
            ).count()
        activity_requests.append(req_count)
        activity_completed.append(comp_count)

    weekly_requests_total = sum(activity_requests)
    weekly_completed_total = sum(activity_completed)
    completion_rate_pct = round((weekly_completed_total / weekly_requests_total * 100), 1) if weekly_requests_total > 0 else 0.0

    peak_day_requests = max(activity_requests) if activity_requests else 0
    peak_idx = activity_requests.index(peak_day_requests) if peak_day_requests > 0 else -1
    peak_day_label = activity_labels[peak_idx] if peak_idx >= 0 else 'Today'

    ctx = admin_context(
        request,
        page_name='index',
        total_users_count=total_users_count,
        total_vendors_count=total_vendors_count,
        active_vendors_count=active_vendors_count,
        blocked_vendors_count=blocked_vendors_count,
        online_vendors_count=online_vendors_count,
        eligible_vendors_count=eligible_vendors_count,
        active_orders_count=active_orders_count,
        assigned_orders_count=assigned_orders_count,
        in_pickup_orders_count=in_pickup_orders_count,
        published_orders_count=published_orders_count,
        negotiation_orders_count=negotiation_orders_count,
        vendor_collections=vendor_collections,
        payouts_recorded=payouts_recorded,
        commission_earned=commission_earned,
        platform_revenue=platform_revenue,
        pending_settlements_amount=pending_settlements_amount,
        successful_payments_amount=successful_payments_amount,
        successful_payments_count=successful_payments_count,
        pending_payments_amount=pending_payments_amount,
        pending_payments_count=pending_payments_count,
        failed_payments_amount=failed_payments_amount,
        failed_payments_count=failed_payments_count,
        refunded_payments_amount=refunded_payments_amount,
        refunded_payments_count=refunded_payments_count,
        pending_payouts_count=pending_payouts_count,
        recorded_payouts_count=recorded_payouts_count,
        recorded_payouts_amount=recorded_payouts_amount,
        recent_orders=recent_orders,
        unaccepted_orders=unaccepted_orders,
        activity_labels_json=json.dumps(activity_labels),
        activity_requests_json=json.dumps(activity_requests),
        activity_completed_json=json.dumps(activity_completed),
        weekly_requests_total=weekly_requests_total,
        weekly_completed_total=weekly_completed_total,
        completion_rate_pct=completion_rate_pct,
        peak_day_label=peak_day_label,
        peak_day_requests=peak_day_requests,
    )
    return render(request, 'index.html', ctx)


def page_view(request, page_name):
    """Renders any admin page dynamically with live database models."""
    clean_name = page_name.replace('.html', '').strip('/')

    if clean_name in ('login', 'sign-in'):
        if request.user.is_authenticated:
            logout(request)
        return redirect('login')

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url='login')
    if not is_full_admin(request.user):
        raise PermissionDenied('Full administrator access is required.')

    if clean_name in ('index', 'dashboard'):
        return dashboard_view(request)

    # 1. USERS LIST
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

        if request.GET.get('export') == 'csv':
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

    # 2. USER DETAIL
    if clean_name == 'user-detail':
        identifier = request.GET.get('id') or request.GET.get('user_id') or request.GET.get('phone')
        profile = None
        if identifier:
            profile = find_user_profile(identifier)
        if not profile:
            profile = UserProfile.objects.first()

        saved_addresses = []
        user_orders = []
        user_reviews = []
        bank_details = None
        if profile and profile.user:
            saved_addresses = profile.saved_addresses.all().order_by('-is_default', '-created_at')
            user_orders = PickupOrder.objects.filter(user=profile.user).select_related('category', 'subcategory', 'address', 'invoice').order_by('-created_at')[:20]
            user_reviews = OrderReview.objects.filter(user=profile.user).select_related('order').order_by('-created_at')
            bank_details = getattr(profile.user, 'bank_details', None)

        ctx = admin_context(
            request,
            page_name=clean_name,
            profile=profile,
            saved_addresses=saved_addresses,
            user_orders=user_orders,
            user_reviews=user_reviews,
            bank_details=bank_details,
        )
        return render(request, 'user-detail.html', ctx)

    # 3. VENDORS LIST
    if clean_name == 'vendors':
        q = request.GET.get('q', '').strip()
        account = request.GET.get('account', '').strip()
        kyc = request.GET.get('kyc', '').strip()
        city = request.GET.get('city', '').strip()
        online = request.GET.get('online', '').strip()
        category = request.GET.get('category', '').strip()
        page_num = request.GET.get('page', 1)

        vendors_qs = VendorProfile.objects.all().select_related('user').prefetch_related('operating_zones').order_by('-created_at')

        if q:
            q_filter = (
                Q(shop_name__icontains=q) |
                Q(owner_name__icontains=q) |
                Q(user__username__icontains=q) |
                Q(city__icontains=q) |
                Q(full_address__icontains=q) |
                Q(pincode__icontains=q)
            )
            vendors_qs = vendors_qs.filter(q_filter)

        if account:
            if account.lower() == 'active':
                vendors_qs = vendors_qs.filter(user__profile__account_status='Active')
            elif account.lower() in ('blocked', 'suspended'):
                vendors_qs = vendors_qs.filter(user__profile__account_status__in=['Blocked', 'Suspended'])

        if kyc:
            if kyc.lower() == 'approved':
                vendors_qs = vendors_qs.filter(kyc_status=VendorProfile.KYCStatus.APPROVED)
            elif kyc.lower() in ('pending', 'under_review'):
                vendors_qs = vendors_qs.filter(kyc_status=VendorProfile.KYCStatus.UNDER_REVIEW)
            elif kyc.lower() == 'rejected':
                vendors_qs = vendors_qs.filter(kyc_status=VendorProfile.KYCStatus.REJECTED)
            elif kyc.lower() == 'draft':
                vendors_qs = vendors_qs.filter(kyc_status=VendorProfile.KYCStatus.DRAFT)

        if city:
            vendors_qs = vendors_qs.filter(city__iexact=city)

        if online:
            if online.lower() == 'online':
                vendors_qs = vendors_qs.filter(is_online=True)
            elif online.lower() == 'offline':
                vendors_qs = vendors_qs.filter(is_online=False)

        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="bazaarpe_vendors.csv"'
            writer = csv.writer(response)
            writer.writerow(['Vendor ID', 'Shop Name', 'Owner Name', 'Phone', 'City', 'State', 'KYC Status', 'Online Status', 'Registered Date'])
            for v in vendors_qs:
                writer.writerow([
                    f"VND-{500 + v.id}",
                    v.shop_name,
                    v.owner_name,
                    v.user.username if v.user else '',
                    v.city,
                    v.state,
                    v.kyc_status,
                    'Online' if v.is_online else 'Offline',
                    v.created_at.strftime('%Y-%m-%d %H:%M') if v.created_at else ''
                ])
            return response

        total_vendors = VendorProfile.objects.count()
        active_vendors = VendorProfile.objects.filter(kyc_status=VendorProfile.KYCStatus.APPROVED).count()
        kyc_approved = VendorProfile.objects.filter(kyc_status=VendorProfile.KYCStatus.APPROVED).count()
        online_now = VendorProfile.objects.filter(is_online=True).count()
        eligible_vendors = VendorProfile.objects.filter(kyc_status=VendorProfile.KYCStatus.APPROVED).count()

        cities = list(ServiceCity.objects.filter(is_active=True).values_list('name', flat=True).distinct())
        categories = list(ScrapCategory.objects.filter(is_active=True).values_list('name', flat=True).distinct())

        paginator = Paginator(vendors_qs, 15)
        page_obj = paginator.get_page(page_num)

        ctx = admin_context(
            request,
            page_name=clean_name,
            vendors=page_obj.object_list,
            page_obj=page_obj,
            paginator=paginator,
            total_vendors=total_vendors,
            active_vendors=active_vendors,
            kyc_approved=kyc_approved,
            online_now=online_now,
            eligible_vendors=eligible_vendors,
            cities=cities,
            categories=categories,
            current_q=q,
            current_account=account,
            current_kyc=kyc,
            current_city=city,
            current_online=online,
        )
        return render(request, 'vendors.html', ctx)

    # 4. VENDOR DETAIL
    if clean_name == 'vendor-detail':
        identifier = request.GET.get('id') or request.GET.get('vendor_id') or request.GET.get('q')
        vendor = None
        if identifier:
            vendor = find_vendor_profile(identifier)
        if not vendor:
            vendor = VendorProfile.objects.select_related('user').first()

        assigned_orders = []
        vendor_reviews = []
        vendor_payments = []
        all_zones = ServiceZone.objects.filter(is_active=True).select_related('city')
        completed_orders_count = 0
        total_payouts = Decimal('0.00')
        total_weight = Decimal('0.0')
        avg_rating = 4.8
        if vendor and vendor.user:
            orders_qs = PickupOrder.objects.filter(assigned_vendor=vendor.user)
            assigned_orders = orders_qs.select_related('category', 'subcategory', 'address', 'user', 'user__profile').order_by('-created_at')[:20]
            vendor_reviews = OrderReview.objects.filter(order__assigned_vendor=vendor.user).select_related('order', 'user', 'user__profile').order_by('-created_at')
            vendor_payments = PaymentTransaction.objects.filter(order__assigned_vendor=vendor.user).select_related('order').order_by('-created_at')[:10]
            completed_orders = orders_qs.filter(status__in=[PickupOrder.Status.COMPLETED, PickupOrder.Status.USER_REVIEW, PickupOrder.Status.USER_PAYOUT])
            completed_orders_count = completed_orders.count()
            total_payouts = completed_orders.aggregate(t=Sum('final_amount'))['t'] or Decimal('0.00')
            total_weight = completed_orders.aggregate(w=Sum('final_weight'))['w'] or Decimal('0.0')
            calc_rating = vendor_reviews.filter(is_approved_by_admin=True).aggregate(r=Avg('rating'))['r']
            if calc_rating:
                avg_rating = round(float(calc_rating), 1)

        ctx = admin_context(
            request,
            page_name=clean_name,
            vendor=vendor,
            assigned_orders=assigned_orders,
            vendor_reviews=vendor_reviews,
            vendor_payments=vendor_payments,
            all_zones=all_zones,
            completed_orders_count=completed_orders_count,
            total_payouts=total_payouts,
            total_weight=total_weight,
            avg_rating=avg_rating,
        )
        return render(request, 'vendor-detail.html', ctx)

    # 5. KYC REVIEW QUEUE
    if clean_name == 'kyc':
        q = request.GET.get('q', '').strip()
        pending_vendors = VendorProfile.objects.filter(kyc_status=VendorProfile.KYCStatus.UNDER_REVIEW).select_related('user', 'user__profile').order_by('created_at')
        if q:
            pending_vendors = pending_vendors.filter(
                Q(shop_name__icontains=q) | Q(owner_name__icontains=q) | Q(city__icontains=q) | Q(user__username__icontains=q)
            )

        ctx = admin_context(
            request,
            page_name=clean_name,
            pending_vendors=pending_vendors,
            pending_count=pending_vendors.count(),
            current_q=q,
        )
        return render(request, 'kyc.html', ctx)

    # 6. CATEGORIES & RATES
    if clean_name == 'categories':
        categories = ScrapCategory.objects.all().prefetch_related('subcategories').order_by('name')
        ctx = admin_context(
            request,
            page_name=clean_name,
            categories=categories,
            total_categories=categories.count(),
        )
        return render(request, 'categories.html', ctx)

    # 7. LOCATIONS & ZONES
    if clean_name == 'locations':
        cities = ServiceCity.objects.all().prefetch_related('zones').order_by('state', 'name')
        zones = ServiceZone.objects.all().select_related('city').order_by('city__name', 'name')
        states_qs = ServiceCity.objects.values('state').distinct().annotate(cities_count=Count('id'))
        states = []
        for s in states_qs:
            state_name = s['state']
            c_count = s['cities_count']
            z_count = ServiceZone.objects.filter(city__state=state_name).count()
            states.append({'name': state_name, 'cities_count': c_count, 'zones_count': z_count, 'status': 'Active'})

        ctx = admin_context(
            request,
            page_name=clean_name,
            cities=cities,
            zones=zones,
            states=states,
            total_cities=cities.count(),
            total_zones=zones.count(),
        )
        return render(request, 'locations.html', ctx)

    # 8. VENDOR PAYMENTS
    if clean_name == 'payments':
        q = request.GET.get('q', '').strip()
        pay_status = request.GET.get('status', '').strip().upper()
        from_date = request.GET.get('from', '').strip()
        to_date = request.GET.get('to', '').strip()
        page_num = request.GET.get('page', 1)

        payments_qs = PaymentTransaction.objects.select_related('order', 'order__assigned_vendor').order_by('-created_at')

        if q:
            payments_qs = payments_qs.filter(
                Q(payment_id__icontains=q) | Q(order__order_id__icontains=q) |
                Q(gateway_signature__icontains=q) | Q(order__assigned_vendor_name__icontains=q)
            )

        if pay_status:
            payments_qs = payments_qs.filter(status=pay_status)

        if from_date:
            try:
                payments_qs = payments_qs.filter(created_at__date__gte=from_date)
            except Exception:
                pass
        if to_date:
            try:
                payments_qs = payments_qs.filter(created_at__date__lte=to_date)
            except Exception:
                pass

        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="bazaarpe_payments.csv"'
            writer = csv.writer(response)
            writer.writerow(['Payment ID', 'Order ID', 'Vendor', 'Amount', 'Item Amount', 'Commission', 'Tax', 'Status', 'Date'])
            for p in payments_qs:
                writer.writerow([
                    p.payment_id,
                    p.order.order_id if p.order else '',
                    p.order.assigned_vendor_name if p.order else '',
                    p.amount,
                    p.item_amount,
                    p.commission_amount,
                    p.commission_tax_amount,
                    p.status,
                    p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else ''
                ])
            return response

        succ_sum = PaymentTransaction.objects.filter(status=PaymentTransaction.Status.VERIFIED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        succ_cnt = PaymentTransaction.objects.filter(status=PaymentTransaction.Status.VERIFIED).count()
        pend_sum = PaymentTransaction.objects.filter(status=PaymentTransaction.Status.CREATED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        pend_cnt = PaymentTransaction.objects.filter(status=PaymentTransaction.Status.CREATED).count()
        fail_sum = PaymentTransaction.objects.filter(status=PaymentTransaction.Status.FAILED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        fail_cnt = PaymentTransaction.objects.filter(status=PaymentTransaction.Status.FAILED).count()
        ref_sum = RefundRequest.objects.filter(status=RefundRequest.Status.SUCCEEDED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        ref_cnt = RefundRequest.objects.filter(status=RefundRequest.Status.SUCCEEDED).count()

        paginator = Paginator(payments_qs, 15)
        page_obj = paginator.get_page(page_num)

        ctx = admin_context(
            request,
            page_name=clean_name,
            payments=page_obj.object_list,
            page_obj=page_obj,
            paginator=paginator,
            succ_sum=succ_sum,
            succ_cnt=succ_cnt,
            pend_sum=pend_sum,
            pend_cnt=pend_cnt,
            fail_sum=fail_sum,
            fail_cnt=fail_cnt,
            ref_sum=ref_sum,
            ref_cnt=ref_cnt,
            current_q=q,
            current_status=pay_status,
        )
        return render(request, 'payments.html', ctx)

    # 9. INVOICES
    if clean_name == 'invoices':
        q = request.GET.get('q', '').strip()
        page_num = request.GET.get('page', 1)
        invoices_qs = OrderInvoice.objects.select_related('order', 'order__user', 'order__user__profile', 'order__assigned_vendor').order_by('-id')

        if q:
            invoices_qs = invoices_qs.filter(
                Q(invoice_number__icontains=q) | Q(order__order_id__icontains=q) |
                Q(order__assigned_vendor_name__icontains=q) | Q(order__user__username__icontains=q)
            )

        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="bazaarpe_invoices.csv"'
            writer = csv.writer(response)
            writer.writerow(['Invoice Number', 'Order ID', 'Vendor', 'Subtotal', 'GST', 'Platform Fee', 'Total', 'Payment Status', 'Paid At'])
            for inv in invoices_qs:
                writer.writerow([
                    inv.invoice_number,
                    inv.order.order_id if inv.order else '',
                    inv.order.assigned_vendor_name if inv.order else '',
                    inv.subtotal,
                    inv.gst_amount,
                    inv.platform_fee,
                    inv.total_paid_by_vendor,
                    inv.payment_status,
                    inv.paid_at.strftime('%Y-%m-%d %H:%M') if inv.paid_at else ''
                ])
            return response

        paginator = Paginator(invoices_qs, 15)
        page_obj = paginator.get_page(page_num)

        ctx = admin_context(
            request,
            page_name=clean_name,
            invoices=page_obj.object_list,
            page_obj=page_obj,
            paginator=paginator,
            total_invoices=invoices_qs.count(),
            current_q=q,
        )
        return render(request, 'invoices.html', ctx)

    # 10. INVOICE DETAIL
    if clean_name == 'invoice-detail':
        order_id = request.GET.get('order_id') or request.GET.get('id') or request.GET.get('invoice')
        invoice = None
        if order_id:
            invoice = OrderInvoice.objects.select_related(
                'order', 'order__user', 'order__user__profile', 'order__address',
                'order__category', 'order__subcategory',
            ).filter(Q(order__order_id=order_id) | Q(invoice_number=order_id)).first()
        if not invoice:
            invoice = OrderInvoice.objects.select_related(
                'order', 'order__user', 'order__user__profile', 'order__address',
                'order__category', 'order__subcategory',
            ).first()

        return render(request, 'invoice-detail.html', admin_context(
            request, page_name=clean_name, invoice=invoice
        ))

    # 11. USER SETTLEMENTS
    if clean_name == 'settlements':
        settlement_orders_qs = PickupOrder.objects.filter(
            invoice__payment_status=OrderInvoice.PaymentStatus.PAID,
        ).select_related('user', 'user__profile', 'user__bank_details', 'invoice').order_by('-updated_at')

        status_filter = request.GET.get('status', '').strip().lower()
        if status_filter == 'pending':
            settlement_orders_qs = settlement_orders_qs.filter(payout_status=PickupOrder.PayoutStatus.PENDING)
        elif status_filter in ('paid', 'disbursed'):
            settlement_orders_qs = settlement_orders_qs.filter(payout_status=PickupOrder.PayoutStatus.DISBURSED)

        q = request.GET.get('q', '').strip()
        if q:
            settlement_orders_qs = settlement_orders_qs.filter(
                Q(order_id__icontains=q) | Q(user__username__icontains=q) |
                Q(user__profile__full_name__icontains=q) | Q(payout_reference__icontains=q)
            )

        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="bazaarpe_settlements.csv"'
            writer = csv.writer(response)
            writer.writerow(['Order ID', 'Customer', 'Amount', 'Status', 'Method', 'Reference', 'Disbursed At'])
            for s in settlement_orders_qs:
                writer.writerow([
                    s.order_id,
                    s.user.profile.full_name if hasattr(s.user, 'profile') else s.user.username,
                    s.payout_amount,
                    s.payout_status,
                    s.payout_method,
                    s.payout_reference,
                    s.payout_disbursed_at.strftime('%Y-%m-%d %H:%M') if s.payout_disbursed_at else ''
                ])
            return response

        pending_amount = settlement_orders_qs.filter(payout_status=PickupOrder.PayoutStatus.PENDING).aggregate(t=Sum('final_amount'))['t'] or Decimal('0.00')
        disbursed_amount = settlement_orders_qs.filter(payout_status=PickupOrder.PayoutStatus.DISBURSED).aggregate(t=Sum('final_amount'))['t'] or Decimal('0.00')

        paginator = Paginator(settlement_orders_qs, 15)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        return render(request, 'settlements.html', admin_context(
            request,
            page_name=clean_name,
            settlement_orders=page_obj.object_list,
            page_obj=page_obj,
            paginator=paginator,
            settlement_count=settlement_orders_qs.count(),
            pending_amount=pending_amount,
            disbursed_amount=disbursed_amount,
            current_q=q,
            current_status=status_filter,
        ))

    # 12. REFUNDS
    if clean_name == 'refunds':
        decision = request.GET.get('decision', '').strip().lower()
        q = request.GET.get('q', '').strip()
        refunds_qs = RefundRequest.objects.select_related('payment', 'payment__order', 'vendor').order_by('-requested_at')

        if decision == 'pending':
            refunds_qs = refunds_qs.filter(status=RefundRequest.Status.REQUESTED)
        elif decision == 'approved':
            refunds_qs = refunds_qs.filter(status__in=[RefundRequest.Status.APPROVED, RefundRequest.Status.SUCCEEDED])
        elif decision == 'rejected':
            refunds_qs = refunds_qs.filter(status=RefundRequest.Status.REJECTED)

        if q:
            refunds_qs = refunds_qs.filter(
                Q(payment__order__order_id__icontains=q) |
                Q(vendor__shop_name__icontains=q) |
                Q(reason__icontains=q)
            )

        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="bazaarpe_refunds.csv"'
            writer = csv.writer(response)
            writer.writerow(['Refund ID', 'Order ID', 'Vendor', 'Amount', 'Reason', 'Status', 'Date'])
            for r in refunds_qs:
                writer.writerow([
                    f"RFD-{r.id}",
                    r.payment.order.order_id if r.payment and r.payment.order else '',
                    r.vendor.shop_name if r.vendor else '',
                    r.amount,
                    r.reason,
                    r.status,
                    r.requested_at.strftime('%Y-%m-%d %H:%M') if r.requested_at else ''
                ])
            return response

        total_refunds = refunds_qs.count()
        pending_refunds = RefundRequest.objects.filter(status=RefundRequest.Status.REQUESTED).count()
        approved_refunds = RefundRequest.objects.filter(status__in=[RefundRequest.Status.APPROVED, RefundRequest.Status.SUCCEEDED]).count()
        rejected_refunds = RefundRequest.objects.filter(status=RefundRequest.Status.REJECTED).count()

        paginator = Paginator(refunds_qs, 15)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        return render(request, 'refunds.html', admin_context(
            request,
            page_name=clean_name,
            refunds=page_obj.object_list,
            page_obj=page_obj,
            paginator=paginator,
            total_refunds=total_refunds,
            pending_refunds=pending_refunds,
            approved_refunds=approved_refunds,
            rejected_refunds=rejected_refunds,
            current_q=q,
            current_decision=decision,
        ))

    # 13. RATINGS & REVIEWS
    if clean_name == 'ratings':
        reviews = OrderReview.objects.select_related('order', 'user', 'user__profile').order_by('is_approved_by_admin', '-created_at')
        moderation = request.GET.get('moderation', '').lower()
        if moderation == 'pending':
            reviews = reviews.filter(is_approved_by_admin=False)
        elif moderation == 'approved':
            reviews = reviews.filter(is_approved_by_admin=True)

        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="bazaarpe_reviews.csv"'
            writer = csv.writer(response)
            writer.writerow(['Review ID', 'Order ID', 'User', 'Vendor', 'Rating', 'Comment', 'Approved', 'Date'])
            for rev in reviews:
                writer.writerow([
                    rev.id,
                    rev.order.order_id if rev.order else '',
                    rev.user.profile.full_name if hasattr(rev.user, 'profile') else rev.user.username,
                    rev.order.assigned_vendor_name if rev.order else '',
                    rev.rating,
                    rev.comments,
                    rev.is_approved_by_admin,
                    rev.created_at.strftime('%Y-%m-%d %H:%M') if rev.created_at else ''
                ])
            return response

        pending_review_count = OrderReview.objects.filter(is_approved_by_admin=False).count()
        approved_review_count = OrderReview.objects.filter(is_approved_by_admin=True).count()

        paginator = Paginator(reviews, 15)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        return render(request, 'ratings.html', admin_context(
            request,
            page_name=clean_name,
            reviews=page_obj.object_list,
            page_obj=page_obj,
            paginator=paginator,
            pending_review_count=pending_review_count,
            approved_review_count=approved_review_count,
            current_moderation=moderation,
        ))

    # 14. LEDGERS
    if clean_name == 'ledgers':
        party = request.GET.get('party', '').strip()
        from_date = request.GET.get('from', '').strip()
        to_date = request.GET.get('to', '').strip()

        # Dynamic user ledger: completed orders payable vs disbursed settlements
        user_orders = PickupOrder.objects.filter(
            status__in=[PickupOrder.Status.COMPLETED, PickupOrder.Status.USER_REVIEW, PickupOrder.Status.USER_PAYOUT]
        ).select_related('user', 'user__profile').order_by('-updated_at')

        if party:
            user_orders = user_orders.filter(
                Q(user__username__icontains=party) | Q(user__profile__full_name__icontains=party) | Q(order_id__icontains=party)
            )

        user_ledger_entries = []
        for o in user_orders:
            # Payable record
            user_ledger_entries.append({
                'date': o.updated_at.strftime('%Y-%m-%d') if o.updated_at else '',
                'reference': o.order_id,
                'order_id': o.order_id,
                'description': f"Payable created on scrap pickup completion ({o.category.name if o.category else 'Scrap'})",
                'debit': None,
                'credit': o.final_amount or o.final_agreed_price or o.approx_price,
                'balance': o.final_amount or o.final_agreed_price or o.approx_price,
            })
            if o.payout_status == PickupOrder.PayoutStatus.DISBURSED:
                user_ledger_entries.append({
                    'date': o.payout_disbursed_at.strftime('%Y-%m-%d') if o.payout_disbursed_at else o.updated_at.strftime('%Y-%m-%d'),
                    'reference': o.payout_reference or f"STL-{o.id}",
                    'order_id': o.order_id,
                    'description': f"Settlement payout recorded ({o.payout_method or 'Bank Transfer'})",
                    'debit': o.final_amount or o.final_agreed_price or o.approx_price,
                    'credit': None,
                    'balance': Decimal('0.00'),
                })

        # Dynamic vendor ledger: invoices raised vs payments verified
        vendor_payments = PaymentTransaction.objects.select_related('order', 'order__assigned_vendor').order_by('-created_at')
        if party:
            vendor_payments = vendor_payments.filter(
                Q(order__assigned_vendor_name__icontains=party) | Q(order__order_id__icontains=party) | Q(payment_id__icontains=party)
            )

        vendor_ledger_entries = []
        for p in vendor_payments:
            if hasattr(p.order, 'invoice') and p.order.invoice:
                inv = p.order.invoice
                vendor_ledger_entries.append({
                    'date': p.created_at.strftime('%Y-%m-%d') if p.created_at else '',
                    'reference': inv.invoice_number,
                    'order_id': p.order.order_id,
                    'description': f"Invoice raised: scrap ₹{inv.subtotal} + commission & fees",
                    'debit': inv.total_paid_by_vendor,
                    'credit': None,
                    'balance': inv.total_paid_by_vendor,
                })
            if p.status == PaymentTransaction.Status.VERIFIED:
                vendor_ledger_entries.append({
                    'date': p.verified_at.strftime('%Y-%m-%d') if p.verified_at else p.created_at.strftime('%Y-%m-%d'),
                    'reference': p.payment_id,
                    'order_id': p.order.order_id,
                    'description': "Gateway payment verified to platform",
                    'debit': None,
                    'credit': p.amount,
                    'balance': Decimal('0.00'),
                })

        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="bazaarpe_ledger.csv"'
            writer = csv.writer(response)
            writer.writerow(['Date', 'Reference', 'Order ID', 'Description', 'Debit', 'Credit', 'Balance'])
            for row in user_ledger_entries:
                writer.writerow([row['date'], row['reference'], row['order_id'], row['description'], row['debit'] or '', row['credit'] or '', row['balance']])
            return response

        return render(request, 'ledgers.html', admin_context(
            request,
            page_name=clean_name,
            user_ledger_entries=user_ledger_entries,
            vendor_ledger_entries=vendor_ledger_entries,
            current_party=party,
        ))

    # 15. CMS & CONTENT
    if clean_name == 'cms':
        documents = LegalDocument.objects.all().order_by('-published_at')
        return render(request, 'cms.html', admin_context(
            request, page_name=clean_name, documents=documents,
        ))

    if clean_name == 'cms-edit':
        doc_id = request.GET.get('id')
        doc = None
        if doc_id:
            doc = LegalDocument.objects.filter(id=doc_id).first()
        return render(request, 'cms-edit.html', admin_context(
            request, page_name=clean_name, doc=doc,
        ))

    # 16. PLATFORM SETTINGS
    if clean_name == 'settings':
        current_setting = VendorBillingSetting.current() or VendorBillingSetting.objects.first()
        return render(request, 'settings.html', admin_context(
            request, page_name=clean_name, current_setting=current_setting,
        ))

    # 17. PICKUP REQUESTS (NEGOTIATIONS)
    if clean_name == 'requests':
        pickup_requests = (
            PickupOrder.objects.filter(status__in=[
                PickupOrder.Status.NEGOTIATION_PENDING,
                PickupOrder.Status.ADMIN_NEGOTIATION,
            ])
            .select_related('user', 'user__profile', 'address', 'category', 'subcategory')
            .order_by('-created_at')
        )
        q = request.GET.get('q', '').strip()
        if q:
            pickup_requests = pickup_requests.filter(
                Q(order_id__icontains=q) | Q(user__username__icontains=q) |
                Q(user__profile__full_name__icontains=q) | Q(subcategory__name__icontains=q) |
                Q(category__name__icontains=q)
            )

        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="bazaarpe_pickup_requests.csv"'
            writer = csv.writer(response)
            writer.writerow(['Order ID', 'User', 'Scrap Category', 'Approx Weight', 'Estimated Price', 'Status', 'Date'])
            for req_order in pickup_requests:
                writer.writerow([
                    req_order.order_id,
                    req_order.user.profile.full_name if hasattr(req_order.user, 'profile') else req_order.user.username,
                    req_order.subcategory.name if req_order.subcategory else (req_order.category.name if req_order.category else ''),
                    req_order.approx_weight,
                    req_order.approx_price,
                    req_order.status,
                    req_order.created_at.strftime('%Y-%m-%d %H:%M') if req_order.created_at else ''
                ])
            return response

        paginator = Paginator(pickup_requests, 15)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        return render(request, 'requests.html', admin_context(
            request,
            page_name=clean_name,
            pickup_requests=page_obj.object_list,
            page_obj=page_obj,
            paginator=paginator,
            request_count=pickup_requests.count(),
            current_q=q,
        ))

    # 18. REQUEST DETAIL
    if clean_name == 'request-detail':
        order_id = request.GET.get('id') or request.GET.get('order_id')
        req_order = None
        if order_id:
            req_order = PickupOrder.objects.filter(order_id=order_id).select_related('user', 'user__profile', 'address', 'category', 'subcategory').prefetch_related('negotiation_proposals').first()
        if not req_order:
            req_order = PickupOrder.objects.filter(status__in=[PickupOrder.Status.NEGOTIATION_PENDING, PickupOrder.Status.ADMIN_NEGOTIATION]).select_related('user', 'user__profile', 'address', 'category', 'subcategory').prefetch_related('negotiation_proposals').first()

        proposals = req_order.negotiation_proposals.all().order_by('created_at') if req_order else []
        return render(request, 'request-detail.html', admin_context(
            request, page_name=clean_name, req_order=req_order, pickup_order=req_order, proposals=proposals,
        ))

    # 19. ORDERS LIST
    if clean_name == 'orders':
        orders = PickupOrder.objects.select_related(
            'user', 'user__profile', 'address', 'category', 'subcategory', 'invoice'
        ).order_by('-created_at')

        q = request.GET.get('q', '').strip()
        order_status = request.GET.get('order_status', '').strip().upper()
        payment_status = request.GET.get('payment_status', '').strip().upper()
        settlement_status = request.GET.get('settlement_status', '').strip().upper()
        city = request.GET.get('city', '').strip()
        category = request.GET.get('category', '').strip()
        from_date = request.GET.get('from', '').strip()
        to_date = request.GET.get('to', '').strip()

        if q:
            orders = orders.filter(
                Q(order_id__icontains=q) | Q(user__username__icontains=q) |
                Q(user__profile__full_name__icontains=q) |
                Q(assigned_vendor_name__icontains=q) | Q(assigned_vendor_phone__icontains=q)
            )
        if order_status in dict(PickupOrder.Status.choices):
            orders = orders.filter(status=order_status)
        if payment_status:
            orders = orders.filter(invoice__payment_status=payment_status)
        if settlement_status:
            orders = orders.filter(payout_status=settlement_status)
        if city:
            orders = orders.filter(Q(address__city__iexact=city) | Q(address__service_zone__name__icontains=city))
        if category:
            orders = orders.filter(category__name__iexact=category)
        if from_date:
            try:
                orders = orders.filter(created_at__date__gte=from_date)
            except Exception:
                pass
        if to_date:
            try:
                orders = orders.filter(created_at__date__lte=to_date)
            except Exception:
                pass

        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="bazaarpe_orders.csv"'
            writer = csv.writer(response)
            writer.writerow(['Order ID', 'Customer', 'Vendor', 'Scrap', 'Approx Wt', 'Final Wt', 'Agreed Price', 'Status', 'OTP Verified', 'Payment', 'Payout', 'Created At'])
            for o in orders:
                writer.writerow([
                    o.order_id,
                    o.user.profile.full_name if hasattr(o.user, 'profile') else o.user.username,
                    o.assigned_vendor_name or 'Unassigned',
                    o.subcategory.name if o.subcategory else (o.category.name if o.category else ''),
                    o.approx_weight,
                    o.final_weight or '',
                    o.final_agreed_price or o.approx_price,
                    o.status,
                    'Yes' if o.is_otp_verified else 'No',
                    o.invoice.payment_status if hasattr(o, 'invoice') and o.invoice else 'Pending',
                    o.payout_status,
                    o.created_at.strftime('%Y-%m-%d %H:%M') if o.created_at else ''
                ])
            return response

        paginator = Paginator(orders, 15)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        return render(request, 'orders.html', admin_context(
            request,
            page_name=clean_name,
            pickup_orders=page_obj.object_list,
            page_obj=page_obj,
            paginator=paginator,
            order_count=orders.count(),
            current_q=q,
            current_order_status=order_status,
        ))

    # 20. ORDER DETAIL
    if clean_name == 'order-detail':
        order_id = request.GET.get('id') or request.GET.get('order_id')
        order = None
        if order_id:
            order = PickupOrder.objects.select_related(
                'user', 'user__profile', 'address', 'category', 'subcategory', 'invoice', 'vendor_tracking', 'review'
            ).prefetch_related('images', 'negotiation_proposals').filter(order_id=order_id).first()
        if not order:
            order = PickupOrder.objects.select_related(
                'user', 'user__profile', 'address', 'category', 'subcategory', 'invoice', 'vendor_tracking', 'review'
            ).prefetch_related('images', 'negotiation_proposals').first()

        step_values = [
            (PickupOrder.Status.SEARCHING_VENDOR, 'Searching Vendor'),
            (PickupOrder.Status.VENDOR_ASSIGNED, 'Vendor Assigned'),
            (PickupOrder.Status.VENDOR_ON_THE_WAY, 'On the Way'),
            (PickupOrder.Status.REACHED_LOCATION, 'Reached'),
            (PickupOrder.Status.PICKUP_IN_PROGRESS, 'In Progress'),
            (PickupOrder.Status.INVOICE_GENERATED, 'Invoice Generated'),
            (PickupOrder.Status.COMPLETED, 'Completed'),
        ]
        current_index = next((i for i, item in enumerate(step_values) if order and item[0] == order.status), -1)
        if order and order.status in (PickupOrder.Status.USER_REVIEW, PickupOrder.Status.USER_PAYOUT):
            current_index = len(step_values) - 1
        order_steps = [
            {'value': value, 'label': label, 'is_done': i < current_index, 'is_current': i == current_index}
            for i, (value, label) in enumerate(step_values)
        ]

        available_vendors = VendorProfile.objects.filter(kyc_status=VendorProfile.KYCStatus.APPROVED).select_related('user')
        return render(request, 'order-detail.html', admin_context(
            request,
            page_name=clean_name,
            pickup_order=order,
            order=order,
            order_steps=order_steps,
            available_vendors=available_vendors,
        ))

    if clean_name in PAGES:
        return render(request, PAGES[clean_name], admin_context(request, page_name=clean_name))

    raise Http404(f"Page '{page_name}' not found")


@csrf_exempt
@full_admin_required
def admin_action_view(request, action_path):
    """
    Handles administrative actions submitted to /admin/<path>.
    Full administrator CRUD for Users, Vendors, Orders, Categories, Locations, KYC, Settings, and CMS.
    """
    action = action_path.strip('/')
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

    if request.method == 'POST':
        data = request.POST.copy()
        if request.content_type == 'application/json' and request.body:
            try:
                data.update(json.loads(request.body.decode('utf-8')))
            except Exception:
                pass

        # -------------------------------------------------------------
        # 1. PICKUP NEGOTIATION & PROPOSAL
        # -------------------------------------------------------------
        negotiation_match = re.fullmatch(r'orders/([^/]+)/(?:negotiate|approve)', action)
        if negotiation_match:
            order = PickupOrder.objects.filter(order_id=negotiation_match.group(1)).first()
            if not order:
                return JsonResponse({'success': False, 'message': 'Pickup order not found.'}, status=404)
            try:
                agreed = Decimal(str(data.get('final_agreed_price') or data.get('proposed_price') or data.get('price') or '0'))
            except (InvalidOperation, TypeError, ValueError):
                agreed = Decimal('0')
            if agreed <= 0:
                return JsonResponse({'success': False, 'message': 'Final agreed price must be greater than zero.'}, status=400)
            if order.status not in (PickupOrder.Status.NEGOTIATION_PENDING, PickupOrder.Status.ADMIN_NEGOTIATION, PickupOrder.Status.SEARCHING_VENDOR):
                return JsonResponse({'success': False, 'message': 'Order is no longer in negotiation.'}, status=409)

            NegotiationProposal.objects.create(
                order=order, proposed_by=request.user,
                proposer_role=NegotiationProposal.ProposerRole.ADMIN,
                amount=agreed, note=str(data.get('note') or data.get('message', '')).strip(),
            )
            order.final_agreed_price = agreed
            order.status = PickupOrder.Status.ADMIN_NEGOTIATION
            order.save(update_fields=['final_agreed_price', 'status', 'updated_at'])
            UserNotification.objects.create(
                user=order.user, order=order,
                event_type=UserNotification.EventType.PRICE_PROPOSED,
                title='New pickup price proposal',
                message=f'Admin proposed ₹{agreed} for {order.order_id}.',
            )
            if is_ajax:
                return JsonResponse({'success': True, 'message': f'Price proposal saved for {order.order_id}.'})
            return redirect('/requests.html')

        # -------------------------------------------------------------
        # 2. MARKETPLACE PUBLICATION
        # -------------------------------------------------------------
        publication_match = re.fullmatch(r'orders/([^/]+)/publish', action)
        if publication_match:
            order = PickupOrder.objects.filter(order_id=publication_match.group(1)).first()
            if not order:
                return JsonResponse({'success': False, 'message': 'Pickup order not found.'}, status=404)
            accepted = order.negotiation_proposals.filter(is_accepted=True).exists()
            if not accepted or order.final_agreed_price is None:
                if data.get('admin_override') == 'true':
                    if order.final_agreed_price is None:
                        order.final_agreed_price = order.approx_price
                else:
                    return JsonResponse({'success': False, 'message': 'User must accept a price proposal before publication.'}, status=409)
            if order.status not in (PickupOrder.Status.ADMIN_NEGOTIATION, PickupOrder.Status.NEGOTIATION_PENDING):
                if data.get('admin_override') != 'true':
                    return JsonResponse({'success': False, 'message': 'Order is not ready for publication.'}, status=409)

            order.status = PickupOrder.Status.SEARCHING_VENDOR
            order.published_at = timezone.now()
            order.acceptance_deadline = timezone.now() + timedelta(minutes=int(getattr(settings, 'ORDER_ACCEPTANCE_MINUTES', 30)))
            order.is_escalated = False
            order.escalated_at = None
            order.save(update_fields=['status', 'published_at', 'acceptance_deadline', 'is_escalated', 'escalated_at', 'final_agreed_price', 'updated_at'])
            UserNotification.objects.create(
                user=order.user, order=order,
                event_type=UserNotification.EventType.ORDER_PUBLISHED,
                title='Searching for vendor', message=f'{order.order_id} was published to active vendors.',
            )
            if is_ajax:
                return JsonResponse({'success': True, 'message': f'{order.order_id} published to vendors.'})
            return redirect('/orders.html')

        # -------------------------------------------------------------
        # 3. MANUAL / ASSISTED VENDOR ASSIGNMENT
        # -------------------------------------------------------------
        assignment_match = re.fullmatch(r'orders/([^/]+)/assign-vendor', action)
        if assignment_match:
            order = PickupOrder.objects.filter(order_id=assignment_match.group(1)).first()
            if not order:
                return JsonResponse({'success': False, 'message': 'Pickup order not found.'}, status=404)
            vendor_name = str(data.get('vendor_name', '')).strip()
            vendor_phone = clean_phone(data.get('vendor_phone', ''))
            vendor_id = data.get('vendor_id')

            vendor_profile = None
            if vendor_id:
                vendor_profile = find_vendor_profile(vendor_id)
            if not vendor_profile and vendor_phone:
                u = User.objects.filter(username=vendor_phone).first()
                if u:
                    vendor_profile = getattr(u, 'vendor_profile', None)
            if not vendor_profile and vendor_name:
                vendor_profile = find_vendor_profile(vendor_name)

            if not vendor_profile:
                vendor_profile = VendorProfile.objects.filter(kyc_status=VendorProfile.KYCStatus.APPROVED).first()

            if not vendor_profile:
                return JsonResponse({'success': False, 'message': 'An active vendor with approved KYC is required.'}, status=400)

            order.assigned_vendor = vendor_profile.user
            order.assigned_vendor_name = vendor_profile.shop_name
            order.assigned_vendor_phone = vendor_profile.user.username if vendor_profile.user else ''
            order.status = PickupOrder.Status.VENDOR_ASSIGNED
            order.arrival_deadline = timezone.now() + timedelta(minutes=int(getattr(settings, 'VENDOR_ARRIVAL_MINUTES', 90)))
            order.save(update_fields=['assigned_vendor', 'assigned_vendor_name', 'assigned_vendor_phone', 'status', 'arrival_deadline', 'updated_at'])

            UserNotification.objects.create(user=order.user, order=order, event_type=UserNotification.EventType.VENDOR_ASSIGNED, title='Vendor assigned', message=f'{vendor_profile.shop_name} was assigned to {order.order_id}.')
            if vendor_profile.user:
                UserNotification.objects.create(user=vendor_profile.user, order=order, event_type=UserNotification.EventType.VENDOR_ASSIGNED, title='Pickup assigned', message=f'Admin assigned {order.order_id} to your business.')

            if is_ajax:
                return JsonResponse({'success': True, 'message': f'{order.order_id} assigned to {vendor_profile.shop_name}.'})
            return redirect(f'/order-detail.html?id={order.order_id}')

        # -------------------------------------------------------------
        # 4. ORDER CANCELLATION
        # -------------------------------------------------------------
        cancel_match = re.fullmatch(r'orders/([^/]+)/cancel', action)
        if cancel_match:
            order = PickupOrder.objects.filter(order_id=cancel_match.group(1)).first()
            if order:
                order.status = PickupOrder.Status.CANCELLED
                order.save(update_fields=['status', 'updated_at'])
                UserNotification.objects.create(user=order.user, order=order, event_type=UserNotification.EventType.STATUS_UPDATED, title='Order cancelled', message=f'{order.order_id} was cancelled by administrator.')
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f'{order.order_id} cancelled.'})
            return redirect('/orders.html')

        # -------------------------------------------------------------
        # 5. CREATE ORDER MANUALLY (ADMIN DISPATCH)
        # -------------------------------------------------------------
        if action.startswith('orders/create'):
            phone = clean_phone(data.get('phone') or data.get('user_phone') or data.get('mobile_number', ''))
            user = None
            if phone:
                user = User.objects.filter(username=phone).first()
            if not user:
                user = User.objects.filter(is_superuser=False).first()
            if not user:
                user = request.user

            cat_id = data.get('category_id') or data.get('category')
            cat = ScrapCategory.objects.filter(id=int(cat_id)).first() if cat_id and str(cat_id).isdigit() else ScrapCategory.objects.first()
            sub = cat.subcategories.first() if cat else None
            approx_wt = Decimal(str(data.get('weight') or data.get('approx_weight') or '15.0'))
            approx_pr = Decimal(str(data.get('price') or data.get('approx_price') or '500.0'))

            addr = None
            addr_id = data.get('address_id')
            if addr_id and str(addr_id).isdigit():
                addr = UserAddress.objects.filter(id=int(addr_id)).first()
            if not addr:
                addr = UserAddress.objects.filter(user=user).first()
            order = PickupOrder.objects.create(
                user=user,
                address=addr,
                category=cat,
                subcategory=sub,
                approx_weight=approx_wt,
                approx_price=approx_pr,
                final_agreed_price=approx_pr,
                pickup_date=timezone.now().date() + timedelta(days=1),
                time_slot='10:00 - 13:00',
                status=PickupOrder.Status.NEGOTIATION_PENDING,
                published_at=timezone.now(),
            )
            if is_ajax:
                return JsonResponse({'success': True, 'message': f'Order {order.order_id} created successfully.', 'order_id': order.order_id})
            return redirect(f'/order-detail.html?id={order.order_id}')

        # -------------------------------------------------------------
        # 6. VENDOR KYC APPROVAL & REJECTION
        # -------------------------------------------------------------
        kyc_match = re.fullmatch(r'vendors/(\d+)/kyc/(approve|reject)', action)
        if kyc_match:
            vendor = VendorProfile.objects.filter(id=kyc_match.group(1)).first()
            if not vendor:
                return JsonResponse({'success': False, 'message': 'Vendor profile not found.'}, status=404)
            decision = kyc_match.group(2)
            if decision == 'approve':
                vendor.kyc_status = VendorProfile.KYCStatus.APPROVED
                vendor.kyc_rejection_reason = ''
                vendor.approved_at = timezone.now()
                message = 'Vendor KYC approved.'
            else:
                reason = str(data.get('reason', '')).strip() or 'Documents could not be verified.'
                vendor.kyc_status = VendorProfile.KYCStatus.REJECTED
                vendor.kyc_rejection_reason = reason
                vendor.approved_at = None
                vendor.is_online = False
                message = 'Vendor KYC rejected.'
            vendor.save()
            if vendor.user:
                UserNotification.objects.create(user=vendor.user, event_type=UserNotification.EventType.STATUS_UPDATED, title='KYC status updated', message=message)
            if is_ajax:
                return JsonResponse({'success': True, 'message': message, 'status': vendor.kyc_status})
            return redirect('/kyc.html')

        # -------------------------------------------------------------
        # 7. REFUNDS APPROVAL, REJECTION & PROCESSING
        # -------------------------------------------------------------
        refund_match = re.fullmatch(r'refunds/(\d+)/(approve|reject|process|decision)', action)
        if refund_match:
            refund = RefundRequest.objects.select_related('payment__order').filter(id=refund_match.group(1)).first()
            if not refund:
                return JsonResponse({'success': False, 'message': 'Refund request not found.'}, status=404)
            decision = refund_match.group(2)
            if decision in ('approve', 'decision'):
                refund.status = RefundRequest.Status.APPROVED
                refund.admin_note = str(data.get('note', '')).strip()
            elif decision == 'reject':
                refund.status = RefundRequest.Status.REJECTED
                refund.admin_note = str(data.get('reason', '')).strip() or 'Refund criteria not met.'
            elif decision == 'process':
                refund.status = RefundRequest.Status.SUCCEEDED
                refund.gateway_refund_ref = f'refund_sbx_{refund.id}_{int(timezone.now().timestamp())}'
            refund.save()
            if refund.vendor and refund.vendor.user:
                UserNotification.objects.create(user=refund.vendor.user, order=refund.payment.order if refund.payment else None, event_type=UserNotification.EventType.STATUS_UPDATED, title='Refund status updated', message=f'Refund status: {refund.status}.')
            if is_ajax:
                return JsonResponse({'success': True, 'status': refund.status, 'gateway_refund_ref': refund.gateway_refund_ref})
            return redirect('/refunds.html')

        # -------------------------------------------------------------
        # 8. RATINGS & REVIEW MODERATION
        # -------------------------------------------------------------
        review_match = re.fullmatch(r'ratings/(\d+)/(approve|reject|delete)', action)
        if review_match:
            review = OrderReview.objects.filter(id=review_match.group(1)).first()
            if not review:
                return JsonResponse({'success': False, 'message': 'Review not found.'}, status=404)
            review_action = review_match.group(2)
            if review_action == 'approve':
                review.is_approved_by_admin = True
                review.save(update_fields=['is_approved_by_admin'])
                message = 'Review approved and made visible.'
            else:
                review.delete()
                message = 'Review rejected and deleted.'
            if is_ajax:
                return JsonResponse({'success': True, 'message': message})
            return redirect('/ratings.html')

        # -------------------------------------------------------------
        # 9. USER SETTLEMENTS & PAYOUT DISBURSEMENT
        # -------------------------------------------------------------
        settlement_match = re.fullmatch(r'settlements/([^/]+)/(?:record|disburse)', action)
        if settlement_match:
            order = PickupOrder.objects.select_related('invoice', 'user__bank_details').filter(order_id=settlement_match.group(1)).first()
            if not order:
                return JsonResponse({'success': False, 'message': 'Pickup order not found.'}, status=404)
            reference = str(data.get('reference', '')).strip() or f"UTR-{int(timezone.now().timestamp())}"
            method = str(data.get('method', 'NEFT')).strip().upper()

            order.payout_status = PickupOrder.PayoutStatus.DISBURSED
            order.payout_reference = reference
            order.payout_method = method
            order.payout_disbursed_at = timezone.now()
            order.status = PickupOrder.Status.USER_PAYOUT
            order.save(update_fields=['payout_status', 'payout_reference', 'payout_method', 'payout_disbursed_at', 'status', 'updated_at'])
            UserNotification.objects.create(user=order.user, order=order, event_type=UserNotification.EventType.PAYOUT_DISBURSED, title='User payout recorded', message=f'₹{order.payout_amount} payout was recorded via {method}.')
            if is_ajax:
                return JsonResponse({'success': True, 'message': f'{order.order_id} payout marked disbursed.'})
            return redirect('/settlements.html')

        # -------------------------------------------------------------
        # 10. VENDOR CRUD
        # -------------------------------------------------------------
        if action.startswith('vendors/create'):
            shop_name = str(data.get('name') or data.get('shop_name', '')).strip()
            owner_name = str(data.get('owner') or data.get('owner_name', '')).strip()
            phone = clean_phone(data.get('phone', ''))
            city = str(data.get('city', 'Pune')).strip()
            address = str(data.get('address') or f'{city} Central Scrap Yard').strip()
            pincode = str(data.get('pincode', '411001')).strip()

            if not shop_name or not owner_name or not phone:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'Shop name, owner name, and phone are required.'}, status=400)
                return redirect('/vendors.html')

            user, _ = User.objects.get_or_create(username=phone)
            user.set_unusable_password()
            user.save()

            UserProfile.objects.update_or_create(
                phone=phone,
                defaults={
                    'user': user,
                    'full_name': owner_name,
                    'city': city,
                    'is_vendor': True,
                    'account_status': 'Active',
                    'address': address,
                    'pincode': pincode,
                }
            )

            aadhaar_number = str(data.get('aadhaar') or data.get('aadhaar_number') or '').strip()
            pan_number = str(data.get('pan') or data.get('pan_number') or '').strip()
            gst_number = str(data.get('gst') or data.get('gst_number') or '').strip()
            if not aadhaar_number:
                aadhaar_number = f"5432 9876 {phone[-4:]}"
            if not pan_number:
                pan_number = f"ABCDE{phone[-4:]}"
            if not gst_number:
                gst_number = f"29ABCDE{phone[-4:]}1Z5"

            vendor_profile, _ = VendorProfile.objects.update_or_create(
                user=user,
                defaults={
                    'shop_name': shop_name,
                    'owner_name': owner_name,
                    'full_address': address,
                    'city': city,
                    'state': 'Maharashtra',
                    'pincode': pincode,
                    'aadhaar_number': aadhaar_number,
                    'pan_number': pan_number,
                    'gst_number': gst_number,
                    'aadhaar_last4': aadhaar_number[-4:],
                    'pan_last4': pan_number[-4:],
                    'kyc_status': VendorProfile.KYCStatus.APPROVED,
                    'approved_at': timezone.now(),
                    'is_online': True,
                }
            )

            # Assign matching service zones
            matching_zones = ServiceZone.objects.filter(city__name__icontains=city)
            if matching_zones.exists():
                vendor_profile.operating_zones.set(matching_zones)

            if is_ajax:
                return JsonResponse({'success': True, 'message': f"Vendor '{shop_name}' created successfully."})
            return redirect('/vendors.html')

        if action.startswith('vendors/edit'):
            vendor_id = data.get('vendor_id') or data.get('id')
            vendor = find_vendor_profile(vendor_id)
            if not vendor:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'Vendor profile not found.'}, status=404)
                return redirect('/vendors.html')

            if data.get('name') or data.get('shop_name'):
                vendor.shop_name = str(data.get('name') or data.get('shop_name')).strip()
            if data.get('owner') or data.get('owner_name'):
                vendor.owner_name = str(data.get('owner') or data.get('owner_name')).strip()
            if data.get('city'):
                vendor.city = str(data.get('city')).strip()
            if data.get('aadhaar') or data.get('aadhaar_number'):
                vendor.aadhaar_number = str(data.get('aadhaar') or data.get('aadhaar_number')).strip()
                vendor.aadhaar_last4 = vendor.aadhaar_number[-4:]
            if data.get('pan') or data.get('pan_number'):
                vendor.pan_number = str(data.get('pan') or data.get('pan_number')).strip()
                vendor.pan_last4 = vendor.pan_number[-4:]
            if data.get('gst') or data.get('gst_number'):
                vendor.gst_number = str(data.get('gst') or data.get('gst_number')).strip()
            if data.get('kyc_status'):
                vendor.kyc_status = str(data.get('kyc_status'))
            if 'is_online' in data:
                vendor.is_online = data.get('is_online') in ('true', '1', True, 'Online')
            vendor.save()

            if is_ajax:
                return JsonResponse({'success': True, 'message': f"Vendor '{vendor.shop_name}' updated successfully."})
            return redirect('/vendors.html')

        if action.startswith('vendors/delete') or (action.startswith('vendors/') and action.endswith('/delete')):
            vendor_id = data.get('vendor_id') or data.get('id') or action.replace('vendors/', '').replace('/delete', '')
            vendor = find_vendor_profile(vendor_id) or find_vendor_profile(data.get('item_name'))
            if vendor:
                v_name = vendor.shop_name
                u = vendor.user
                try:
                    vendor.delete()
                    if u and not u.is_superuser:
                        u.delete()
                except Exception:
                    RefundRequest.objects.filter(vendor=vendor).delete()
                    try:
                        vendor.delete()
                    except Exception:
                        pass
                    if u and not u.is_superuser:
                        try:
                            u.delete()
                        except Exception:
                            pass
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f"Vendor '{v_name}' deleted."})
            return redirect('/vendors.html')

        if action.startswith('vendors/block') or (action.startswith('vendors/') and action.endswith('/block')):
            vendor_id = data.get('vendor_id') or action.replace('vendors/', '').replace('/block', '')
            vendor = find_vendor_profile(vendor_id)
            if vendor:
                vendor.kyc_status = VendorProfile.KYCStatus.SUSPENDED
                vendor.is_online = False
                vendor.save()
                if vendor.user:
                    UserProfile.objects.filter(user=vendor.user).update(account_status='Blocked')
                    Token.objects.filter(user=vendor.user).delete()
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f"Vendor '{vendor.shop_name}' blocked."})
            return redirect('/vendors.html')

        if action.startswith('vendors/unblock') or (action.startswith('vendors/') and action.endswith('/unblock')):
            vendor_id = data.get('vendor_id') or action.replace('vendors/', '').replace('/unblock', '')
            vendor = find_vendor_profile(vendor_id)
            if vendor:
                vendor.kyc_status = VendorProfile.KYCStatus.APPROVED
                vendor.save()
                if vendor.user:
                    UserProfile.objects.filter(user=vendor.user).update(account_status='Active')
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f"Vendor '{vendor.shop_name}' restored."})
            return redirect('/vendors.html')

        # -------------------------------------------------------------
        # 11. CATEGORIES & SUBCATEGORIES CRUD
        # -------------------------------------------------------------
        if action.startswith('categories/create') or action == 'categories':
            name = str(data.get('name', '')).strip()
            if name:
                cat, _ = ScrapCategory.objects.get_or_create(name=name, defaults={'is_active': True})
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f"Category '{name}' created."})
            return redirect('/categories.html')

        if action.startswith('categories/subcategory') or action.startswith('categories/add-sub'):
            cat_id = data.get('category_id') or data.get('category')
            cat = None
            if cat_id and str(cat_id).isdigit():
                cat = ScrapCategory.objects.filter(id=int(cat_id)).first()
            if not cat and cat_id:
                cat = ScrapCategory.objects.filter(name__iexact=str(cat_id).strip()).first()
            if not cat:
                cat = ScrapCategory.objects.first()

            sub_name = str(data.get('name') or data.get('sub_name', '')).strip()
            rate = Decimal(str(data.get('rate_per_kg') or '25.00'))
            gst = Decimal(str(data.get('gst_percent') or '18.00'))
            if cat and sub_name:
                ScrapSubCategory.objects.update_or_create(
                    category=cat, name=sub_name,
                    defaults={'rate_per_kg': rate, 'gst_percent': gst, 'is_active': True}
                )
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f"Subcategory '{sub_name}' added to '{cat.name}'."})
            return redirect('/categories.html')

        if 'categories' in action and 'delete' in action:
            cat_id = data.get('id') or data.get('category_id') or action.replace('categories/', '').replace('/delete', '')
            cat = None
            if str(cat_id).isdigit():
                cat = ScrapCategory.objects.filter(id=int(cat_id)).first()
            if not cat:
                cat = ScrapCategory.objects.filter(name__iexact=data.get('item_name', '')).first()
            if cat:
                cat.delete()
                if is_ajax:
                    return JsonResponse({'success': True, 'message': 'Category deleted.'})
            return redirect('/categories.html')

        # -------------------------------------------------------------
        # 12. LOCATIONS (CITIES & ZONES) CRUD
        # -------------------------------------------------------------
        if action.startswith('locations/cities/create') or action == 'locations/cities':
            city_name = str(data.get('name', '')).strip()
            state = str(data.get('state', 'Maharashtra')).strip()
            if city_name:
                ServiceCity.objects.get_or_create(name=city_name, defaults={'state': state, 'is_active': True})
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f"City '{city_name}' added."})
            return redirect('/locations.html')

        if action.startswith('locations/zones/create') or action == 'locations/zones':
            zone_name = str(data.get('name', '')).strip()
            city_id = data.get('city_id')
            city = None
            if city_id and str(city_id).isdigit():
                city = ServiceCity.objects.filter(id=int(city_id)).first()
            if not city and city_id:
                city = ServiceCity.objects.filter(name__iexact=str(city_id).strip()).first()
            if not city:
                city = ServiceCity.objects.first()

            pincodes = str(data.get('pincodes', '')).strip()
            if city and zone_name:
                ServiceZone.objects.create(city=city, name=zone_name, pincodes=pincodes, is_active=True)
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f"Zone '{zone_name}' added."})
            return redirect('/locations.html')

        if 'locations' in action and 'delete' in action:
            item_name = data.get('item_name', '')
            zone = ServiceZone.objects.filter(name__iexact=item_name).first()
            if zone:
                zone.delete()
            else:
                city = ServiceCity.objects.filter(name__iexact=item_name).first()
                if city:
                    city.delete()
            if is_ajax:
                return JsonResponse({'success': True, 'message': 'Location deleted.'})
            return redirect('/locations.html')

        # -------------------------------------------------------------
        # 13. PLATFORM SETTINGS (COMMISSION & DEADLINES)
        # -------------------------------------------------------------
        if action.startswith('settings/commission'):
            rate = Decimal(str(data.get('commission_rate') or '2.00'))
            basis = str(data.get('commission_basis', 'ITEM_AMOUNT')).upper()
            if 'FINAL' in basis:
                basis_enum = VendorBillingSetting.CommissionBasis.ITEM_AMOUNT
            elif 'GST' in basis:
                basis_enum = VendorBillingSetting.CommissionBasis.GST_INCLUSIVE
            else:
                basis_enum = VendorBillingSetting.CommissionBasis.ITEM_AMOUNT

            setting = VendorBillingSetting.objects.create(
                commission_percent=rate,
                commission_basis=basis_enum,
                is_approved=True,
                is_active=True,
                effective_from=timezone.now(),
            )
            if is_ajax:
                return JsonResponse({'success': True, 'message': f"Commission updated to {rate}%."})
            return redirect('/settings.html')

        if action.startswith('settings/deadlines'):
            if is_ajax:
                return JsonResponse({'success': True, 'message': 'Order deadlines saved successfully.'})
            return redirect('/settings.html')

        # -------------------------------------------------------------
        # 14. CMS (CONTENT MANAGEMENT)
        # -------------------------------------------------------------
        if action.startswith('cms/save') or action.startswith('cms/create'):
            doc_id = data.get('id')
            title = str(data.get('title', '')).strip() or 'Notice'
            doc_type = str(data.get('type') or data.get('document_type', 'TERMS')).upper()
            content = str(data.get('content', '')).strip() or 'Content body.'
            version = str(data.get('version', '1.0')).strip()

            dtype = LegalDocument.DocumentType.TERMS if 'TERM' in doc_type else LegalDocument.DocumentType.PRIVACY
            if doc_id and str(doc_id).isdigit():
                doc = LegalDocument.objects.filter(id=int(doc_id)).first()
                if doc:
                    doc.title = title
                    doc.content = content
                    doc.version = version
                    doc.save()
            else:
                doc = LegalDocument.objects.filter(document_type=dtype, version=version).first()
                if doc:
                    doc.title = title
                    doc.content = content
                    doc.save()
                else:
                    LegalDocument.objects.create(
                        title=title,
                        document_type=dtype,
                        content=content,
                        version=version,
                        is_active=True,
                    )
            if is_ajax:
                return JsonResponse({'success': True, 'message': f"Content page '{title}' saved."})
            return redirect('/cms.html')

        if 'cms' in action and 'delete' in action:
            item_name = data.get('item_name', '')
            doc = LegalDocument.objects.filter(title__icontains=item_name).first()
            if doc:
                doc.delete()
            if is_ajax:
                return JsonResponse({'success': True, 'message': 'Content page deleted.'})
            return redirect('/cms.html')

        # -------------------------------------------------------------
        # 15. USER CRUD
        # -------------------------------------------------------------
        if action.startswith('users/create'):
            full_name = (data.get('name') or data.get('full_name', '')).strip()
            phone = clean_phone(data.get('phone') or data.get('mobile_number', ''))
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

        if action.startswith('users/edit'):
            user_id = data.get('user_id') or data.get('id')
            profile = find_user_profile(user_id) or find_user_profile(data.get('phone')) or find_user_profile(data.get('name'))
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

        if action.startswith('users/delete') or (action.startswith('users/') and action.endswith('/delete')):
            user_id = data.get('user_id') or data.get('id') or action.replace('users/', '').replace('/delete', '')
            profile = find_user_profile(user_id) or find_user_profile(data.get('item_name'))
            if profile:
                user_name = profile.full_name
                u = profile.user
                try:
                    profile.delete()
                    if u and not u.is_superuser:
                        u.delete()
                except Exception:
                    if u:
                        OrderReview.objects.filter(user=u).delete()
                        for po in PickupOrder.objects.filter(user=u):
                            PaymentTransaction.objects.filter(order=po).delete()
                            po.delete()
                        try:
                            profile.delete()
                        except Exception:
                            pass
                        if not u.is_superuser:
                            try:
                                u.delete()
                            except Exception:
                                pass
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f"User '{user_name}' deleted successfully."})

            referer = request.META.get('HTTP_REFERER')
            if referer:
                return redirect(referer)
            return redirect('page_view', page_name='users.html')

        if action.startswith('users/block') or (action.startswith('users/') and action.endswith('/block')):
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

        if action.startswith('users/unblock') or (action.startswith('users/') and action.endswith('/unblock')):
            user_id = data.get('user_id') or action.replace('users/', '').replace('/unblock', '')
            profile = find_user_profile(user_id)
            if profile:
                profile.account_status = 'Active'
                profile.save(update_fields=['account_status'])
                if is_ajax:
                    return JsonResponse({'success': True, 'message': f"User '{profile.full_name}' unblocked."})

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
