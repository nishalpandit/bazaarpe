from functools import wraps

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.conf import settings
from datetime import timedelta


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

from .models import (
    UserProfile, OTPVerification, PickupOrder, OrderReview, OrderInvoice,
    UserBankDetail, NegotiationProposal, UserNotification,
    VendorProfile, RefundRequest,
)
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

    if clean_name == 'requests':
        pickup_requests = (
            PickupOrder.objects.filter(status__in=[
                PickupOrder.Status.NEGOTIATION_PENDING,
                PickupOrder.Status.ADMIN_NEGOTIATION,
            ])
            .select_related('user', 'user__profile', 'address', 'category', 'subcategory')
        )
        q = request.GET.get('q', '').strip()
        if q:
            pickup_requests = pickup_requests.filter(
                Q(order_id__icontains=q) | Q(user__username__icontains=q) |
                Q(user__profile__full_name__icontains=q) | Q(subcategory__name__icontains=q)
            )
        return render(request, 'requests.html', admin_context(
            request,
            page_name=clean_name,
            live_pickup_enabled=True,
            pickup_requests=pickup_requests,
            request_count=pickup_requests.count(),
        ))

    if clean_name == 'orders':
        orders = PickupOrder.objects.select_related(
            'user', 'user__profile', 'address', 'category', 'subcategory', 'invoice'
        )
        q = request.GET.get('q', '').strip()
        order_status = request.GET.get('order_status', '').strip().upper()
        if q:
            orders = orders.filter(
                Q(order_id__icontains=q) | Q(user__username__icontains=q) |
                Q(user__profile__full_name__icontains=q) |
                Q(assigned_vendor_name__icontains=q) | Q(assigned_vendor_phone__icontains=q)
            )
        if order_status in dict(PickupOrder.Status.choices):
            orders = orders.filter(status=order_status)
        return render(request, 'orders.html', admin_context(
            request,
            page_name=clean_name,
            live_pickup_enabled=True,
            pickup_orders=orders,
            order_count=orders.count(),
        ))

    if clean_name == 'order-detail':
        order_id = request.GET.get('id') or request.GET.get('order_id')
        order = PickupOrder.objects.select_related(
            'user', 'user__profile', 'address', 'category', 'subcategory', 'invoice', 'vendor_tracking', 'review'
        ).prefetch_related('images').filter(order_id=order_id).first() if order_id else None
        if not order:
            order = PickupOrder.objects.select_related(
                'user', 'user__profile', 'address', 'category', 'subcategory'
            ).prefetch_related('images').first()
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
        return render(request, 'order-detail.html', admin_context(
            request, page_name=clean_name, live_pickup_enabled=True,
            pickup_order=order, order_steps=order_steps,
        ))

    if clean_name == 'invoice-detail':
        order_id = request.GET.get('order_id') or request.GET.get('id')
        invoice = OrderInvoice.objects.select_related(
            'order', 'order__user', 'order__user__profile', 'order__address',
            'order__category', 'order__subcategory',
        ).filter(order__order_id=order_id).first() if order_id else None
        return render(request, 'invoice-detail.html', admin_context(
            request, page_name=clean_name, live_invoice_enabled=True, invoice=invoice
        ))

    if clean_name == 'ratings':
        reviews = OrderReview.objects.select_related(
            'order', 'user', 'user__profile'
        ).order_by('is_approved_by_admin', '-created_at')
        moderation = request.GET.get('moderation', '').lower()
        if moderation == 'pending':
            reviews = reviews.filter(is_approved_by_admin=False)
        elif moderation == 'approved':
            reviews = reviews.filter(is_approved_by_admin=True)
        return render(request, 'ratings.html', admin_context(
            request,
            page_name=clean_name,
            live_pickup_enabled=True,
            reviews=reviews,
            pending_review_count=reviews.filter(is_approved_by_admin=False).count(),
        ))

    if clean_name == 'settlements':
        settlement_orders = PickupOrder.objects.filter(
            invoice__payment_status=OrderInvoice.PaymentStatus.PAID,
            status__in=[
                PickupOrder.Status.COMPLETED,
                PickupOrder.Status.USER_REVIEW,
                PickupOrder.Status.USER_PAYOUT,
            ],
        ).select_related('user', 'user__profile', 'user__bank_details', 'invoice')
        return render(request, 'settlements.html', admin_context(
            request,
            page_name=clean_name,
            live_pickup_enabled=True,
            settlement_orders=settlement_orders,
            settlement_count=settlement_orders.count(),
        ))

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
        from decimal import Decimal, InvalidOperation
        data = request.POST.copy()
        if request.content_type == 'application/json' and request.body:
            try:
                data.update(json.loads(request.body.decode('utf-8')))
            except Exception:
                pass

        # PICKUP NEGOTIATION: create a proposal; publication is a separate action.
        negotiation_match = re.fullmatch(r'orders/([^/]+)/(?:negotiate|approve)', action)
        if negotiation_match:
            order = PickupOrder.objects.filter(order_id=negotiation_match.group(1)).first()
            if not order:
                return JsonResponse({'success': False, 'message': 'Pickup order not found.'}, status=404)
            try:
                agreed = Decimal(str(data.get('final_agreed_price', '')))
            except (InvalidOperation, TypeError, ValueError):
                agreed = Decimal('0')
            if agreed <= 0:
                return JsonResponse({'success': False, 'message': 'Final agreed price must be greater than zero.'}, status=400)
            if order.status not in (PickupOrder.Status.NEGOTIATION_PENDING, PickupOrder.Status.ADMIN_NEGOTIATION):
                return JsonResponse({'success': False, 'message': 'Order is no longer in negotiation.'}, status=409)
            NegotiationProposal.objects.create(
                order=order, proposed_by=request.user,
                proposer_role=NegotiationProposal.ProposerRole.ADMIN,
                amount=agreed, note=str(data.get('note', '')).strip(),
            )
            order.status = PickupOrder.Status.ADMIN_NEGOTIATION
            order.save(update_fields=['status', 'updated_at'])
            UserNotification.objects.create(
                user=order.user, order=order,
                event_type=UserNotification.EventType.PRICE_PROPOSED,
                title='New pickup price proposal',
                message=f'Admin proposed ₹{agreed} for {order.order_id}.',
            )
            if is_ajax:
                return JsonResponse({'success': True, 'message': f'Price proposal saved for {order.order_id}.'})
            return redirect('/requests.html')

        publication_match = re.fullmatch(r'orders/([^/]+)/publish', action)
        if publication_match:
            order = PickupOrder.objects.filter(order_id=publication_match.group(1)).first()
            if not order:
                return JsonResponse({'success': False, 'message': 'Pickup order not found.'}, status=404)
            accepted = order.negotiation_proposals.filter(is_accepted=True).exists()
            if not accepted or order.final_agreed_price is None:
                return JsonResponse({'success': False, 'message': 'User must accept a price proposal before publication.'}, status=409)
            if order.status != PickupOrder.Status.ADMIN_NEGOTIATION:
                return JsonResponse({'success': False, 'message': 'Order is not ready for publication.'}, status=409)
            order.status = PickupOrder.Status.SEARCHING_VENDOR
            order.published_at = timezone.now()
            order.acceptance_deadline = timezone.now() + timedelta(minutes=int(getattr(settings, 'ORDER_ACCEPTANCE_MINUTES', 30)))
            order.is_escalated = False
            order.escalated_at = None
            order.save(update_fields=['status', 'published_at', 'acceptance_deadline', 'is_escalated', 'escalated_at', 'updated_at'])
            UserNotification.objects.create(
                user=order.user, order=order,
                event_type=UserNotification.EventType.ORDER_PUBLISHED,
                title='Searching for vendor', message=f'{order.order_id} was published to active vendors.',
            )
            if is_ajax:
                return JsonResponse({'success': True, 'message': f'{order.order_id} published to vendors.'})
            return redirect('/orders.html')

        # VENDOR ASSIGNMENT: available to admins for assisted/manual dispatch.
        assignment_match = re.fullmatch(r'orders/([^/]+)/assign-vendor', action)
        if assignment_match:
            order = PickupOrder.objects.filter(order_id=assignment_match.group(1)).first()
            if not order:
                return JsonResponse({'success': False, 'message': 'Pickup order not found.'}, status=404)
            vendor_name = str(data.get('vendor_name', '')).strip()
            vendor_phone = clean_phone(data.get('vendor_phone', ''))
            if not vendor_name or not vendor_phone:
                return JsonResponse({'success': False, 'message': 'Vendor name and phone are required.'}, status=400)
            user_profile = UserProfile.objects.filter(phone=vendor_phone, account_status='Active', is_vendor=True).select_related('user').first()
            vendor_profile = VendorProfile.objects.filter(
                user=user_profile.user if user_profile else None,
                kyc_status=VendorProfile.KYCStatus.APPROVED,
            ).first()
            if not vendor_profile:
                return JsonResponse({'success': False, 'message': 'An active vendor with approved KYC is required.'}, status=400)
            if not order.address_id or not order.address.service_zone_id or not vendor_profile.operating_zones.filter(id=order.address.service_zone_id).exists():
                return JsonResponse({'success': False, 'message': 'Vendor does not cover the order service zone.'}, status=400)
            if order.status != PickupOrder.Status.SEARCHING_VENDOR or order.assigned_vendor_id:
                return JsonResponse({'success': False, 'message': 'Order is not available for assignment.'}, status=409)
            order.assigned_vendor = vendor_profile.user
            order.assigned_vendor_name = vendor_profile.shop_name
            order.assigned_vendor_phone = vendor_phone
            order.status = PickupOrder.Status.VENDOR_ASSIGNED
            order.arrival_deadline = timezone.now() + timedelta(minutes=int(getattr(settings, 'VENDOR_ARRIVAL_MINUTES', 90)))
            order.save(update_fields=['assigned_vendor', 'assigned_vendor_name', 'assigned_vendor_phone', 'status', 'arrival_deadline', 'updated_at'])
            UserNotification.objects.create(user=order.user, order=order, event_type=UserNotification.EventType.VENDOR_ASSIGNED, title='Vendor assigned', message=f'{vendor_profile.shop_name} was assigned to {order.order_id}.')
            UserNotification.objects.create(user=vendor_profile.user, order=order, event_type=UserNotification.EventType.VENDOR_ASSIGNED, title='Pickup assigned', message=f'Admin assigned {order.order_id} to your business.')
            if is_ajax:
                return JsonResponse({'success': True, 'message': f'{order.order_id} assigned to {vendor_profile.shop_name}.'})
            return redirect(f'/order-detail.html?id={order.order_id}')

        kyc_match = re.fullmatch(r'vendors/(\d+)/kyc/(approve|reject)', action)
        if kyc_match:
            vendor = VendorProfile.objects.filter(id=kyc_match.group(1)).first()
            if not vendor:
                return JsonResponse({'success': False, 'message': 'Vendor profile not found.'}, status=404)
            decision = kyc_match.group(2)
            if decision == 'approve':
                if vendor.kyc_status != VendorProfile.KYCStatus.UNDER_REVIEW:
                    return JsonResponse({'success': False, 'message': 'Only KYC under review can be approved.'}, status=409)
                vendor.kyc_status = VendorProfile.KYCStatus.APPROVED
                vendor.kyc_rejection_reason = ''
                vendor.approved_at = timezone.now()
                message = 'Vendor KYC approved.'
            else:
                reason = str(data.get('reason', '')).strip()
                if not reason:
                    return JsonResponse({'success': False, 'message': 'Rejection reason is required.'}, status=400)
                vendor.kyc_status = VendorProfile.KYCStatus.REJECTED
                vendor.kyc_rejection_reason = reason
                vendor.approved_at = None
                vendor.is_online = False
                message = 'Vendor KYC rejected.'
            vendor.save()
            UserNotification.objects.create(user=vendor.user, event_type=UserNotification.EventType.STATUS_UPDATED, title='KYC status updated', message=message)
            if is_ajax:
                return JsonResponse({'success': True, 'message': message, 'status': vendor.kyc_status})
            return redirect('/kyc.html')

        refund_match = re.fullmatch(r'refunds/(\d+)/(approve|reject|process)', action)
        if refund_match:
            refund = RefundRequest.objects.select_related('payment__order').filter(id=refund_match.group(1)).first()
            if not refund:
                return JsonResponse({'success': False, 'message': 'Refund request not found.'}, status=404)
            decision = refund_match.group(2)
            if decision == 'approve':
                if refund.status != RefundRequest.Status.REQUESTED:
                    return JsonResponse({'success': False, 'message': 'Refund is not awaiting approval.'}, status=409)
                refund.status = RefundRequest.Status.APPROVED
                refund.admin_note = str(data.get('note', '')).strip()
            elif decision == 'reject':
                if refund.status != RefundRequest.Status.REQUESTED:
                    return JsonResponse({'success': False, 'message': 'Refund is not awaiting approval.'}, status=409)
                reason = str(data.get('reason', '')).strip()
                if not reason:
                    return JsonResponse({'success': False, 'message': 'Rejection reason is required.'}, status=400)
                refund.status = RefundRequest.Status.REJECTED
                refund.admin_note = reason
            else:
                if refund.status != RefundRequest.Status.APPROVED:
                    return JsonResponse({'success': False, 'message': 'Refund must be approved before processing.'}, status=409)
                if getattr(settings, 'PAYMENT_REFUND_MODE', 'unconfigured') != 'local-test':
                    return JsonResponse({'success': False, 'message': 'Refund provider is not configured; no real refund was initiated.'}, status=503)
                refund.status = RefundRequest.Status.SUCCEEDED
                refund.gateway_refund_ref = f'refund_sbx_{refund.id}_{int(timezone.now().timestamp())}'
            refund.save()
            UserNotification.objects.create(user=refund.vendor.user, order=refund.payment.order, event_type=UserNotification.EventType.STATUS_UPDATED, title='Refund status updated', message=f'Refund status: {refund.status}.')
            if is_ajax:
                return JsonResponse({'success': True, 'status': refund.status, 'gateway_refund_ref': refund.gateway_refund_ref})
            return redirect('/refunds.html')

        # REVIEW MODERATION.
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
                review_user = review.user
                review_order = review.order
                review.delete()
                message = 'Review rejected and deleted.'
            UserNotification.objects.create(
                user=review.user if review_action == 'approve' else review_user,
                order=review.order if review_action == 'approve' else review_order,
                event_type=UserNotification.EventType.REVIEW_MODERATED,
                title='Review moderated', message=message,
            )
            if is_ajax:
                return JsonResponse({'success': True, 'message': message})
            return redirect('/ratings.html')

        # USER PAYOUT: invoice must be paid and amount must match the negotiated payout.
        settlement_match = re.fullmatch(r'settlements/([^/]+)/(?:record|disburse)', action)
        if settlement_match:
            order = PickupOrder.objects.select_related('invoice', 'user__bank_details').filter(order_id=settlement_match.group(1)).first()
            if not order:
                return JsonResponse({'success': False, 'message': 'Pickup order not found.'}, status=404)
            invoice = getattr(order, 'invoice', None)
            bank = getattr(order.user, 'bank_details', None)
            if not invoice or invoice.payment_status != OrderInvoice.PaymentStatus.PAID:
                return JsonResponse({'success': False, 'message': 'Vendor payment must be confirmed first.'}, status=409)
            if not bank:
                return JsonResponse({'success': False, 'message': 'The user has not saved bank details.'}, status=409)
            if order.payout_status == PickupOrder.PayoutStatus.DISBURSED:
                return JsonResponse({'success': False, 'message': 'This payout is already marked disbursed.'}, status=409)
            try:
                amount = Decimal(str(data.get('amount', order.payout_amount)))
            except (InvalidOperation, TypeError, ValueError):
                amount = Decimal('-1')
            if amount != order.payout_amount:
                return JsonResponse({'success': False, 'message': f'Amount must equal {order.payout_amount}.'}, status=400)
            reference = str(data.get('reference', '')).strip()
            method = str(data.get('method', '')).strip().upper()
            if not reference or not method:
                return JsonResponse({'success': False, 'message': 'Payment method and reference are required.'}, status=400)
            order.payout_status = PickupOrder.PayoutStatus.DISBURSED
            order.payout_reference = reference
            order.payout_method = method
            order.payout_disbursed_at = timezone.now()
            order.status = PickupOrder.Status.USER_PAYOUT
            order.save(update_fields=[
                'payout_status', 'payout_reference', 'payout_method',
                'payout_disbursed_at', 'status', 'updated_at',
            ])
            UserNotification.objects.create(user=order.user, order=order, event_type=UserNotification.EventType.PAYOUT_DISBURSED, title='User payout recorded', message=f'₹{order.payout_amount} payout was recorded via {method}.')
            if is_ajax:
                return JsonResponse({'success': True, 'message': f'{order.order_id} payout marked disbursed.'})
            return redirect('/settlements.html')

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
