import os
import sys
import time
import json
import socket
import urllib.request
import urllib.error
import urllib.parse
from decimal import Decimal
import subprocess

# Set environment for audit
os.environ['DJANGO_SETTINGS_MODULE'] = 'myproject.settings'
os.environ['DJANGO_DB_NAME'] = 'audit_http_test.sqlite3'
os.environ['AADHAAR_PROVIDER_MODE'] = 'local-test'
os.environ['PAYMENT_REFUND_MODE'] = 'local-test'

import django
django.setup()

from django.core.management import call_command
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from nainjyoti.models import (
    UserProfile, UserAddress, ScrapCategory, ScrapSubCategory, PickupOrder,
    OrderInvoice, OrderReview, PickupImage, UserBankDetail, LegalDocument,
    UserConsent, PaymentTransaction, UserNotification, OTPVerification,
    ServiceCity, ServiceZone, VendorProfile, VendorBillingSetting,
    VendorOfferRejection, RefundRequest
)
from nainjyoti.api_views import payment_signature, webhook_signature

PORT = 8768
BASE_URL = f"http://127.0.0.1:{PORT}"

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def http_req(method, path, data=None, token=None, content_type='application/json', headers=None):
    url = f"{BASE_URL}{path}"
    req_headers = dict(headers or {})
    if token:
        req_headers['Authorization'] = f"Bearer {token}"
    
    body = None
    if data is not None:
        if isinstance(data, (bytes, bytearray)):
            body = data
        elif content_type == 'application/json':
            req_headers['Content-Type'] = 'application/json'
            body = json.dumps(data).encode('utf-8')
        elif isinstance(data, dict):
            req_headers['Content-Type'] = 'application/x-www-form-urlencoded'
            body = urllib.parse.urlencode(data).encode('utf-8')

    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            resp_body = resp.read().decode('utf-8')
            try:
                parsed = json.loads(resp_body)
            except Exception:
                parsed = resp_body
            return resp.status, parsed, dict(resp.headers)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8')
        try:
            parsed = json.loads(err_body)
        except Exception:
            parsed = err_body
        return e.code, parsed, dict(e.headers)

def multipart_encode(fields, files):
    boundary = '----WebKitFormBoundaryAuditTest7MA4YWxkTrZu0gW'
    body = bytearray()
    for name, value in fields.items():
        body.extend(f'--{boundary}\r\n'.encode('utf-8'))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode('utf-8'))
        body.extend(f'{value}\r\n'.encode('utf-8'))
    for name, (filename, content, content_type) in files.items():
        body.extend(f'--{boundary}\r\n'.encode('utf-8'))
        body.extend(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode('utf-8'))
        body.extend(f'Content-Type: {content_type}\r\n\r\n'.encode('utf-8'))
        body.extend(content)
        body.extend(b'\r\n')
    body.extend(f'--{boundary}--\r\n'.encode('utf-8'))
    return bytes(body), f'multipart/form-data; boundary={boundary}'


def kill_port(port):
    try:
        subprocess.run(
            ['powershell', '-Command', f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue; if ($c) {{ Stop-Process -Id $c.OwningProcess -Force }}"],
            capture_output=True, timeout=5
        )
    except Exception:
        pass


def setup_database():
    kill_port(PORT)
    from django.db import connection
    connection.close()
    if os.path.exists('audit_http_test.sqlite3'):
        try:
            os.remove('audit_http_test.sqlite3')
        except Exception:
            pass
    print("Running migrations on audit_http_test.sqlite3...")
    call_command('migrate', interactive=False)

    # Seed base data
    city, _ = ServiceCity.objects.get_or_create(name='Bengaluru', defaults={'state': 'Karnataka', 'is_active': True})
    zone1, _ = ServiceZone.objects.get_or_create(
        city=city, name='Indiranagar Zone',
        defaults={'code': 'ZN-BLR-01', 'pincodes': '560038, 560008', 'center_latitude': '12.9784', 'center_longitude': '77.6408', 'radius_km': '10.00', 'is_active': True}
    )
    zone2, _ = ServiceZone.objects.get_or_create(
        city=city, name='Koramangala Zone',
        defaults={'code': 'ZN-BLR-02', 'pincodes': '560034', 'center_latitude': '12.9352', 'center_longitude': '77.6245', 'radius_km': '10.00', 'is_active': True}
    )

    cat, _ = ScrapCategory.objects.get_or_create(name='Metal', defaults={'icon': 'recycle', 'is_active': True})
    subcat, _ = ScrapSubCategory.objects.get_or_create(
        category=cat, name='Iron Scrap',
        defaults={'rate_per_kg': '40.00', 'gst_percent': '18.00', 'min_weight_kg': '5.00', 'is_active': True}
    )

    # Legal documents
    LegalDocument.objects.get_or_create(document_type=LegalDocument.DocumentType.TERMS, defaults={'version': '2026.1', 'title': 'Terms of Service', 'content': 'Terms content...', 'is_active': True})
    LegalDocument.objects.get_or_create(document_type=LegalDocument.DocumentType.PRIVACY, defaults={'version': '2026.1', 'title': 'Privacy Policy', 'content': 'Privacy content...', 'is_active': True})

    # Approved billing setting
    VendorBillingSetting.objects.get_or_create(
        is_active=True, defaults={
            'commission_percent': Decimal('2.00'),
            'commission_tax_percent': Decimal('18.00'),
            'fixed_platform_fee': Decimal('50.00'),
            'is_approved': True,
            'note': 'Audit verification approved policy'
        }
    )

    # Superuser admin
    admin, _ = User.objects.get_or_create(username='audit_admin', defaults={'email': 'admin@bazaarpe.com', 'is_staff': True, 'is_superuser': True})
    admin.set_password('AdminSecret123!')
    admin.save()
    admin_token, _ = Token.objects.get_or_create(user=admin)
    return admin, admin_token, subcat, zone1


def run_audit():
    admin, admin_token, subcat, zone1 = setup_database()
    from django.db import connection
    connection.close()

    # Start live server
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, 'manage.py', 'runserver', f'127.0.0.1:{PORT}', '--noreload'],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    
    print(f"Waiting for live server on {BASE_URL}...")
    for _ in range(30):
        if is_port_in_use(PORT):
            break
        time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError("Server failed to start on port 8768.")

    print(f"Server is LIVE on {BASE_URL}. Executing full test suite...\n")

    results = []
    def record(name, route, method, status_code, passed, details=""):
        results.append({
            'name': name, 'route': route, 'method': method,
            'status': status_code, 'passed': passed, 'details': details
        })
        icon = "[PASS]" if passed else "[FAIL]"
        print(f"  {icon} {method} {route} -> HTTP {status_code}: {name} {details}")

    try:
        # 1. SEND OTP - Validation & Cooldown
        s, r, _ = http_req('POST', '/api/user/send-otp/', {'phone': 'invalid'})
        record('OTP invalid phone rejected', '/api/user/send-otp/', 'POST', s, s == 400)

        s, r, _ = http_req('POST', '/api/user/send-otp/', {'phone': '9800000001'})
        otp_a = r.get('otp_debug') if isinstance(r, dict) else None
        record('User A send OTP', '/api/user/send-otp/', 'POST', s, s == 200 and otp_a is not None, f"action={r.get('action')}")

        s, r, _ = http_req('POST', '/api/user/send-otp/', {'phone': '9800000001'})
        record('OTP cooldown 429', '/api/user/send-otp/', 'POST', s, s == 429)

        # 2. LOGIN OTP - Attempt limits & unverified user
        s, r, _ = http_req('POST', '/api/user/login-otp/', {'phone': '9800000001', 'otp': '000000'})
        record('Wrong OTP rejected', '/api/user/login-otp/', 'POST', s, s == 400)

        s, r, _ = http_req('POST', '/api/user/login-otp/', {'phone': '9800000001', 'otp': otp_a})
        record('Unregistered user login rejected', '/api/user/login-otp/', 'POST', s, s == 404)

        # 3. REGISTER USER A
        # Missing consent rejected
        s, r, _ = http_req('POST', '/api/user/register/', {
            'full_name': 'Ramesh Kumar', 'mobile_number': '9800000001', 'address': '12th Main Road',
            'pincode': '560038', 'city': 'Bengaluru', 'otp': otp_a
        })
        record('Register without consent rejected', '/api/user/register/', 'POST', s, s == 400)

        # Register User A with consent
        s, r, h = http_req('POST', '/api/user/register/', {
            'full_name': 'Ramesh Kumar', 'mobile_number': '9800000001', 'email': 'ramesh@example.com',
            'address': '12th Main Road, Indiranagar', 'pincode': '560038', 'city': 'Bengaluru',
            'otp': otp_a, 'accept_privacy': True, 'privacy_version': '2026.1',
            'accept_terms': True, 'terms_version': '2026.1'
        })
        user_a_token = r.get('token') if isinstance(r, dict) else None
        record('Register User A succeeded', '/api/user/register/', 'POST', s, s == 201 and bool(user_a_token))

        # OTP reuse rejected
        s, r, _ = http_req('POST', '/api/user/register/', {
            'full_name': 'Ramesh Kumar', 'mobile_number': '9800000001', 'email': 'ramesh@example.com',
            'address': '12th Main Road, Indiranagar', 'pincode': '560038', 'city': 'Bengaluru',
            'otp': otp_a, 'accept_privacy': True, 'privacy_version': '2026.1', 'accept_terms': True, 'terms_version': '2026.1'
        })
        record('Reusing OTP rejected', '/api/user/register/', 'POST', s, s == 400)

        # 4. REGISTER USER B
        OTPVerification.objects.filter(phone='9800000002').delete()
        s, r, _ = http_req('POST', '/api/user/send-otp/', {'phone': '9800000002'})
        otp_b = r.get('otp_debug')
        s, r, _ = http_req('POST', '/api/user/register/', {
            'full_name': 'Suresh Sharma', 'mobile_number': '9800000002', 'address': 'Koramangala 4th Block',
            'pincode': '560034', 'city': 'Bengaluru', 'otp': otp_b,
            'accept_privacy': True, 'privacy_version': '2026.1', 'accept_terms': True, 'terms_version': '2026.1'
        })
        user_b_token = r.get('token')
        record('Register User B succeeded', '/api/user/register/', 'POST', s, s == 201 and bool(user_b_token))

        # 5. USER PROFILE & IMMUTABLE PHONE & MULTIPART PHOTO
        s, r, _ = http_req('GET', '/api/user/profile/', token=user_a_token)
        record('Get User A Profile', '/api/user/profile/', 'GET', s, s == 200 and r.get('user', {}).get('full_name') == 'Ramesh Kumar')

        # Edit phone directly -> 400
        s, r, _ = http_req('PATCH', '/api/user/profile/', {'phone': '9999999999'}, token=user_a_token)
        record('Direct phone edit rejected', '/api/user/profile/', 'PATCH', s, s == 400)

        # Multipart photo upload
        photo_bytes = b'GIF89a\x01\x00\x01\x00\x00\x00\x00\x00\x00;'
        mp_data, mp_ct = multipart_encode({'full_name': 'Ramesh Kumar Updated'}, {'profile_photo': ('avatar.gif', photo_bytes, 'image/gif')})
        s, r, _ = http_req('PATCH', '/api/user/profile/', data=mp_data, token=user_a_token, headers={'Content-Type': mp_ct})
        record('Multipart profile photo update', '/api/user/profile/', 'PATCH', s, s == 200)

        # 6. PHONE NUMBER CHANGE
        s, r, _ = http_req('POST', '/api/user/change-phone/request/', {'new_phone': '9800000099'}, token=user_a_token)
        ch_otp = r.get('otp_debug')
        record('Request phone change', '/api/user/change-phone/request/', 'POST', s, s == 200 and bool(ch_otp))

        s, r, _ = http_req('POST', '/api/user/change-phone/confirm/', {'new_phone': '9800000099', 'otp': '000000'}, token=user_a_token)
        record('Wrong phone change OTP rejected', '/api/user/change-phone/confirm/', 'POST', s, s == 400)

        s, r, _ = http_req('POST', '/api/user/change-phone/confirm/', {'new_phone': '9800000099', 'otp': ch_otp}, token=user_a_token)
        record('Confirm phone change succeeded', '/api/user/change-phone/confirm/', 'POST', s, s == 200)

        # Change it back to 9800000001 for clean testing
        s, r, _ = http_req('POST', '/api/user/change-phone/request/', {'new_phone': '9800000001'}, token=user_a_token)
        ch_otp2 = r.get('otp_debug')
        http_req('POST', '/api/user/change-phone/confirm/', {'new_phone': '9800000001', 'otp': ch_otp2}, token=user_a_token)

        # 7. LOCATION & ADDRESSES
        s, r, _ = http_req('POST', '/api/user/location/detect/', {'latitude': 12.9784, 'longitude': 77.6408})
        record('Auto-detect GPS location', '/api/user/location/detect/', 'POST', s, s == 200 and r.get('is_serviceable') is True)

        s, r, _ = http_req('GET', '/api/user/service-zones/')
        record('Get service zones', '/api/user/service-zones/', 'GET', s, s == 200 and len(r.get('cities', [])) > 0)

        # Save address User A
        s, r, _ = http_req('POST', '/api/user/address/save/', {
            'house_no': 'Flat 101', 'street_address': '12th Main Road', 'landmark': 'Near Park',
            'city': 'Bengaluru', 'state': 'Karnataka', 'pincode': '560038',
            'latitude': 12.9784, 'longitude': 77.6408, 'address_type': 'Home', 'is_default': True
        }, token=user_a_token)
        addr_a_id = r.get('address', {}).get('id')
        record('Save serviceable address User A', '/api/user/address/save/', 'POST', s, s == 201 and addr_a_id is not None)

        # Save address User B
        s, r, _ = http_req('POST', '/api/user/address/save/', {
            'house_no': 'House 202', 'street_address': 'Koramangala 4th Block',
            'city': 'Bengaluru', 'state': 'Karnataka', 'pincode': '560034',
            'latitude': 12.9352, 'longitude': 77.6245, 'address_type': 'Home', 'is_default': True
        }, token=user_b_token)
        addr_b_id = r.get('address', {}).get('id')
        record('Save address User B', '/api/user/address/save/', 'POST', s, s == 201 and addr_b_id is not None)

        # Cross-user address access rejected
        s, r, _ = http_req('GET', f'/api/user/addresses/{addr_a_id}/', token=user_b_token)
        record('Cross-user address access rejected', f'/api/user/addresses/{addr_a_id}/', 'GET', s, s == 404)

        # List addresses
        s, r, _ = http_req('GET', '/api/user/addresses/', token=user_a_token)
        record('List saved addresses', '/api/user/addresses/', 'GET', s, s == 200 and r.get('count') == 1)

        # Set default address
        s, r, _ = http_req('POST', f'/api/user/addresses/{addr_a_id}/set-default/', token=user_a_token)
        record('Set default address', f'/api/user/addresses/{addr_a_id}/set-default/', 'POST', s, s == 200)

        # 8. VENDOR ONBOARDING & KYC (Vendor A, Vendor B, Vendor C)
        def register_vendor(phone, name, shop_name):
            OTPVerification.objects.filter(phone=phone).delete()
            http_req('POST', '/api/vendor/auth/send-otp/', {'phone': phone})
            otp = OTPVerification.objects.filter(phone=phone).order_by('-created_at').first().otp
            s, r, _ = http_req('POST', '/api/vendor/auth/register/', {
                'full_name': name, 'mobile_number': phone, 'address': 'Indiranagar',
                'pincode': '560038', 'city': 'Bengaluru', 'otp': otp,
                'accept_privacy': True, 'privacy_version': '2026.1', 'accept_terms': True, 'terms_version': '2026.1'
            })
            token = r.get('token')
            # Profile
            s, r, _ = http_req('POST', '/api/vendor/profile/', {
                'shop_name': shop_name, 'owner_name': name, 'full_address': 'Shop 12, Indiranagar',
                'city': 'Bengaluru', 'state': 'Karnataka', 'pincode': '560038',
                'latitude': 12.9784, 'longitude': 77.6408
            }, token=token)
            return token

        vendor_a_token = register_vendor('9870000001', 'Anand Kumar', 'GreenLoop Traders')
        record('Vendor A registered & profile created', '/api/vendor/profile/', 'POST', 201, bool(vendor_a_token))

        vendor_b_token = register_vendor('9870000002', 'Bipin Verma', 'EcoRecycle Hub')
        record('Vendor B registered & profile created', '/api/vendor/profile/', 'POST', 201, bool(vendor_b_token))

        vendor_c_token = register_vendor('9870000003', 'Chirag Patel', 'Unapproved Scrap')
        record('Vendor C (Unapproved) registered', '/api/vendor/profile/', 'POST', 201, bool(vendor_c_token))

        # Vendor zones
        s, r, _ = http_req('PUT', '/api/vendor/operating-zones/', {'zone_ids': [zone1.id]}, token=vendor_a_token)
        record('Vendor A update operating zones', '/api/vendor/operating-zones/', 'PUT', s, s == 200)

        s, r, _ = http_req('PUT', '/api/vendor/operating-zones/', {'zone_ids': [zone1.id]}, token=vendor_b_token)
        record('Vendor B update operating zones', '/api/vendor/operating-zones/', 'PUT', s, s == 200)

        # Online toggle before KYC approval -> 403
        s, r, _ = http_req('POST', '/api/vendor/availability/', {'is_online': True}, token=vendor_a_token)
        record('Online toggle before KYC rejected', '/api/vendor/availability/', 'POST', s, s == 403)

        # Vendor A Aadhaar verification
        s, r, _ = http_req('POST', '/api/vendor/kyc/aadhaar/initiate/', {'aadhaar_last4': '1234'}, token=vendor_a_token)
        ref = r.get('reference')
        record('Vendor A initiate Aadhaar', '/api/vendor/kyc/aadhaar/initiate/', 'POST', s, s == 200 and bool(ref))

        s, r, _ = http_req('POST', '/api/vendor/kyc/aadhaar/confirm/', {'reference': ref, 'otp': '123456'}, token=vendor_a_token)
        record('Vendor A confirm Aadhaar', '/api/vendor/kyc/aadhaar/confirm/', 'POST', s, s == 200 and r.get('status') == 'VERIFIED')

        # Vendor A KYC multipart submission
        dummy_file = b'%PDF-1.4 dummy pdf content'
        mp_data, mp_ct = multipart_encode(
            {'pan_last4': 'ABCD'},
            {'aadhaar_document': ('aadhaar.pdf', dummy_file, 'application/pdf'), 'pan_document': ('pan.pdf', dummy_file, 'application/pdf')}
        )
        s, r, _ = http_req('POST', '/api/vendor/kyc/', data=mp_data, token=vendor_a_token, headers={'Content-Type': mp_ct})
        record('Vendor A KYC submitted', '/api/vendor/kyc/', 'POST', s, s == 201 and r.get('status') == 'UNDER_REVIEW')

        # Vendor A KYC masked retrieval
        s, r, _ = http_req('GET', '/api/vendor/kyc/', token=vendor_a_token)
        record('Vendor A KYC status masked', '/api/vendor/kyc/', 'GET', s, s == 200 and r.get('kyc', {}).get('pan_masked') == 'XXXXXXABCD')

        # Admin approves Vendor A KYC
        v_a_prof = VendorProfile.objects.get(user__username='9870000001')
        s, r, _ = http_req('POST', f'/admin/vendors/{v_a_prof.id}/kyc/approve', headers={'Authorization': f"Bearer {admin_token.key}", 'X-Requested-With': 'XMLHttpRequest'})
        record('Admin approve Vendor A KYC', f'/admin/vendors/{v_a_prof.id}/kyc/approve', 'POST', s, s == 200)

        # Vendor B Aadhaar & KYC approval
        v_b_prof = VendorProfile.objects.get(user__username='9870000002')
        v_b_prof.aadhaar_status = VendorProfile.AadhaarStatus.VERIFIED
        v_b_prof.kyc_status = VendorProfile.KYCStatus.APPROVED
        v_b_prof.save()

        # Vendor A & B Go Online
        s, r, _ = http_req('POST', '/api/vendor/availability/', {'is_online': True}, token=vendor_a_token)
        record('Vendor A Go Online', '/api/vendor/availability/', 'POST', s, s == 200 and r.get('is_online') is True)

        s, r, _ = http_req('POST', '/api/vendor/availability/', {'is_online': True}, token=vendor_b_token)
        record('Vendor B Go Online', '/api/vendor/availability/', 'POST', s, s == 200 and r.get('is_online') is True)

        # 9. PRICING & ORDER CREATION
        s, r, _ = http_req('POST', '/api/pricing/calculate/', {'subcategory_id': subcat.id, 'approx_weight': 2.0})
        record('Pricing below min weight rejected', '/api/pricing/calculate/', 'POST', s, s == 400)

        s, r, _ = http_req('POST', '/api/pricing/calculate/', {'subcategory_id': subcat.id, 'approx_weight': 25.0})
        record('Pricing calculation succeeded', '/api/pricing/calculate/', 'POST', s, s == 200 and r.get('base_price') == 1000.0)

        # User A creates order
        s, r, _ = http_req('POST', '/api/user/orders/create/', {
            'address_id': addr_a_id, 'subcategory_id': subcat.id, 'approx_weight': 25.0,
            'pickup_date': '2026-11-01', 'time_slot': '10:00 AM - 01:00 PM', 'notes': 'Gate 4 code 1234'
        }, token=user_a_token)
        order_id = r.get('order', {}).get('order_id')
        otp_pickup = r.get('order', {}).get('pickup_otp')
        record('User A create pickup order', '/api/user/orders/create/', 'POST', s, s == 201 and bool(order_id) and bool(otp_pickup), f"status={r.get('order', {}).get('status')}")

        # 10. NEGOTIATION & PUBLICATION
        # Vendor attempts to access unpublished order -> 403
        s, r, _ = http_req('GET', f'/api/vendor/orders/{order_id}/', token=vendor_a_token)
        record('Vendor accessing unpublished order rejected', f'/api/vendor/orders/{order_id}/', 'GET', s, s == 403)

        # Admin proposes price
        s, r, _ = http_req('POST', f'/admin/orders/{order_id}/negotiate', {'final_agreed_price': '1150.00'}, headers={'Authorization': f"Bearer {admin_token.key}", 'X-Requested-With': 'XMLHttpRequest'})
        record('Admin proposes price', f'/admin/orders/{order_id}/negotiate', 'POST', s, s == 200)

        # Admin tries to publish before user accepts -> 409
        s, r, _ = http_req('POST', f'/admin/orders/{order_id}/publish', headers={'Authorization': f"Bearer {admin_token.key}", 'X-Requested-With': 'XMLHttpRequest'})
        record('Publishing before user acceptance rejected', f'/admin/orders/{order_id}/publish', 'POST', s, s == 409)

        # User A views proposals
        s, r, _ = http_req('GET', f'/api/user/orders/{order_id}/negotiations/', token=user_a_token)
        record('User A views negotiations', f'/api/user/orders/{order_id}/negotiations/', 'GET', s, s == 200 and len(r.get('proposals', [])) == 1)

        # User A confirms price
        s, r, _ = http_req('POST', f'/api/user/orders/{order_id}/confirm-price/', token=user_a_token)
        record('User A confirms price', f'/api/user/orders/{order_id}/confirm-price/', 'POST', s, s == 200 and r.get('awaiting_admin_publication') is True)

        # Admin publishes order
        s, r, _ = http_req('POST', f'/admin/orders/{order_id}/publish', headers={'Authorization': f"Bearer {admin_token.key}", 'X-Requested-With': 'XMLHttpRequest'})
        record('Admin publishes order to vendors', f'/admin/orders/{order_id}/publish', 'POST', s, s == 200)

        # 11. MARKETPLACE DISCOVERY & CONCURRENCY
        # Unapproved vendor querying available -> 403
        s, r, _ = http_req('GET', '/api/vendor/orders/available/', token=vendor_c_token)
        record('Unapproved vendor marketplace access rejected', '/api/vendor/orders/available/', 'GET', s, s == 403)

        # Vendor A sees available order (redacted customer details, NO pickup OTP)
        s, r, _ = http_req('GET', '/api/vendor/orders/available/', token=vendor_a_token)
        orders_list = r.get('orders', [])
        found = any(o.get('order_id') == order_id for o in orders_list)
        has_otp = any('pickup_otp' in o for o in orders_list)
        has_full_addr = any('pickup_address' in o for o in orders_list)
        record('Vendor A discovers available order (redacted)', '/api/vendor/orders/available/', 'GET', s, s == 200 and found and not has_otp and not has_full_addr)

        # Vendor B rejects order
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/reject/', {'reason': 'Truck maintenance'}, token=vendor_b_token)
        record('Vendor B rejects order for self', f'/api/vendor/orders/{order_id}/reject/', 'POST', s, s == 200)

        # Vendor B no longer sees it
        s, r, _ = http_req('GET', '/api/vendor/orders/available/', token=vendor_b_token)
        record('Vendor B does not see rejected order', '/api/vendor/orders/available/', 'GET', s, s == 200 and r.get('count') == 0)

        # Vendor A still sees it
        s, r, _ = http_req('GET', '/api/vendor/orders/available/', token=vendor_a_token)
        record('Vendor A still sees available order', '/api/vendor/orders/available/', 'GET', s, s == 200 and r.get('count') == 1)

        # Vendor A accepts order
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/accept/', token=vendor_a_token)
        record('Vendor A accepts order', f'/api/vendor/orders/{order_id}/accept/', 'POST', s, s == 200 and r.get('order', {}).get('status') == 'VENDOR_ASSIGNED')

        # Vendor B attempts concurrent acceptance -> 409
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/accept/', token=vendor_b_token)
        record('Vendor B concurrent acceptance rejected', f'/api/vendor/orders/{order_id}/accept/', 'POST', s, s in (403, 409))

        # Cross-user tracking rejected (User B cannot track User A's order)
        s, r, _ = http_req('GET', f'/api/user/orders/{order_id}/tracking/', token=user_b_token)
        record('Cross-user order tracking rejected', f'/api/user/orders/{order_id}/tracking/', 'GET', s, s == 404)

        # 12. TRACKING & LIVE STEPPER
        # Out-of-order transition rejected (Vendor jumps to REACHED_LOCATION)
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/status/', {'status': 'REACHED_LOCATION'}, token=vendor_a_token)
        record('Out-of-order transition rejected', f'/api/vendor/orders/{order_id}/status/', 'POST', s, s == 409)

        # Move to VENDOR_ON_THE_WAY
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/status/', {'status': 'VENDOR_ON_THE_WAY'}, token=vendor_a_token)
        record('Advance status to VENDOR_ON_THE_WAY', f'/api/vendor/orders/{order_id}/status/', 'POST', s, s == 200)

        # Update live location
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/update-location/', {'latitude': 12.9790, 'longitude': 77.6410}, token=vendor_a_token)
        record('Update vendor live location', f'/api/vendor/orders/{order_id}/update-location/', 'POST', s, s == 200)

        # User A tracking shows status, live coordinates, and pickup OTP
        s, r, _ = http_req('GET', f'/api/user/orders/{order_id}/tracking/', token=user_a_token)
        record('User A tracks live status & location', f'/api/user/orders/{order_id}/tracking/', 'GET', s, s == 200 and r.get('status') == 'VENDOR_ON_THE_WAY' and r.get('pickup_otp') == otp_pickup)

        # Move to REACHED_LOCATION
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/status/', {'status': 'REACHED_LOCATION'}, token=vendor_a_token)
        record('Advance status to REACHED_LOCATION', f'/api/vendor/orders/{order_id}/status/', 'POST', s, s == 200)

        # 13. PICKUP OTP VERIFICATION
        # Wrong OTP rejected
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/verify-otp/', {'otp': '000000'}, token=vendor_a_token)
        record('Wrong pickup OTP rejected', f'/api/vendor/orders/{order_id}/verify-otp/', 'POST', s, s == 400)

        # Correct OTP verified
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/verify-otp/', {'otp': otp_pickup}, token=vendor_a_token)
        record('Correct pickup OTP verified', f'/api/vendor/orders/{order_id}/verify-otp/', 'POST', s, s == 200 and r.get('order', {}).get('status') == 'PICKUP_IN_PROGRESS')

        # Reusing OTP rejected
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/verify-otp/', {'otp': otp_pickup}, token=vendor_a_token)
        record('Reusing pickup OTP rejected', f'/api/vendor/orders/{order_id}/verify-otp/', 'POST', s, s == 409)

        # 14. BILLING, PAYMENT & INVOICING
        # Billing with negative weight rejected
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/billing/', {'final_weight': -5.0}, token=vendor_a_token)
        record('Negative final weight rejected', f'/api/vendor/orders/{order_id}/billing/', 'POST', s, s == 400)

        # Valid billing (30 kg)
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/billing/', {'final_weight': 30.0}, token=vendor_a_token)
        payment_id = r.get('payment', {}).get('payment_id')
        payment_obj = PaymentTransaction.objects.get(payment_id=payment_id)
        valid_sig = payment_signature(payment_obj)
        record('Create vendor billing & sandbox payment', f'/api/vendor/orders/{order_id}/billing/', 'POST', s, s == 201 and bool(payment_id))

        # User invoice unavailable before payment verification -> 404
        s, r, _ = http_req('GET', f'/api/user/orders/{order_id}/invoice/', token=user_a_token)
        record('Invoice unavailable before payment verified', f'/api/user/orders/{order_id}/invoice/', 'GET', s, s == 404)

        # Forged payment signature rejected
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/payment/verify/', {'payment_id': payment_id, 'signature': 'forged_signature_123'}, token=vendor_a_token)
        record('Forged payment signature rejected', f'/api/vendor/orders/{order_id}/payment/verify/', 'POST', s, s == 400)

        # Valid payment verification
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/payment/verify/', {'payment_id': payment_id, 'signature': valid_sig}, token=vendor_a_token)
        inv_num = r.get('invoice', {}).get('invoice_number')
        record('Verify vendor payment & generate invoice', f'/api/vendor/orders/{order_id}/payment/verify/', 'POST', s, s == 200 and bool(inv_num))

        # Idempotent re-verification
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/payment/verify/', {'payment_id': payment_id, 'signature': valid_sig}, token=vendor_a_token)
        record('Idempotent payment re-verification', f'/api/vendor/orders/{order_id}/payment/verify/', 'POST', s, s == 200 and r.get('invoice', {}).get('invoice_number') == inv_num)

        # Webhook replay test
        wh_sig = webhook_signature('evt_test_1001', payment_id, 'PAID')
        s, r, _ = http_req('POST', '/api/payments/webhook/', {'event_id': 'evt_test_1001', 'payment_id': payment_id, 'status': 'PAID'}, headers={'X-Payment-Signature': wh_sig})
        record('Payment webhook processed', '/api/payments/webhook/', 'POST', s, s == 200)

        s, r, _ = http_req('POST', '/api/payments/webhook/', {'event_id': 'evt_test_1001', 'payment_id': payment_id, 'status': 'PAID'}, headers={'X-Payment-Signature': wh_sig})
        record('Payment webhook idempotent replay', '/api/payments/webhook/', 'POST', s, s == 200 and r.get('idempotent_replay') is True)

        # Retrieve invoice (User A and Vendor A)
        s, r, _ = http_req('GET', f'/api/user/orders/{order_id}/invoice/', token=user_a_token)
        record('User A retrieves paid invoice', f'/api/user/orders/{order_id}/invoice/', 'GET', s, s == 200 and r.get('invoice', {}).get('payment_status') == 'PAID')

        s, r, _ = http_req('GET', f'/api/vendor/orders/{order_id}/invoice/', token=vendor_a_token)
        record('Vendor A retrieves paid invoice', f'/api/vendor/orders/{order_id}/invoice/', 'GET', s, s == 200 and r.get('invoice', {}).get('invoice_number') == inv_num)

        # 15. COMPLETION & PROOF IMAGES
        # Completion with mismatched weight rejected
        mp_data, mp_ct = multipart_encode({'final_weight': '99.0'}, {'item_images': ('scale.png', photo_bytes, 'image/png')})
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/complete/', data=mp_data, token=vendor_a_token, headers={'Content-Type': mp_ct})
        record('Mismatched final weight completion rejected', f'/api/vendor/orders/{order_id}/complete/', 'POST', s, s == 409)

        # Valid completion with multipart image
        mp_data, mp_ct = multipart_encode({'final_weight': '30.0'}, {'item_images': ('scale.png', photo_bytes, 'image/png')})
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/complete/', data=mp_data, token=vendor_a_token, headers={'Content-Type': mp_ct})
        record('Vendor completes pickup with photo proof', f'/api/vendor/orders/{order_id}/complete/', 'POST', s, s == 200 and r.get('order', {}).get('status') == 'COMPLETED')

        # User A tracking now shows pickup summary and proof images
        s, r, _ = http_req('GET', f'/api/user/orders/{order_id}/tracking/', token=user_a_token)
        summary = r.get('pickup_summary', {})
        record('User A sees authorized pickup summary & proofs', f'/api/user/orders/{order_id}/tracking/', 'GET', s, s == 200 and summary.get('final_weight') == 30.0 and len(summary.get('item_images', [])) == 1)

        # Duplicate completion rejected
        s, r, _ = http_req('POST', f'/api/vendor/orders/{order_id}/complete/', data=mp_data, token=vendor_a_token, headers={'Content-Type': mp_ct})
        record('Duplicate pickup completion rejected', f'/api/vendor/orders/{order_id}/complete/', 'POST', s, s == 409)

        # 16. REVIEWS & MODERATION
        # User A submits review
        s, r, _ = http_req('POST', f'/api/user/orders/{order_id}/review/', {'rating': 5, 'comments': 'Prompt and accurate digital weighing!'}, token=user_a_token)
        review_id = r.get('review', {}).get('id')
        record('User A submits rating and review', f'/api/user/orders/{order_id}/review/', 'POST', s, s == 201 and bool(review_id))

        # Duplicate review rejected
        s, r, _ = http_req('POST', f'/api/user/orders/{order_id}/review/', {'rating': 4}, token=user_a_token)
        record('Duplicate review rejected', f'/api/user/orders/{order_id}/review/', 'POST', s, s == 409)

        # Vendor views reviews before admin approval -> comments are hidden
        s, r, _ = http_req('GET', '/api/vendor/reviews/', token=vendor_a_token)
        rev = r.get('reviews', [{}])[0]
        record('Vendor views unapproved review (comment hidden)', '/api/vendor/reviews/', 'GET', s, s == 200 and rev.get('comment_visible') is False and rev.get('comments') == '')

        # Public reviews does NOT show unapproved review
        s, r, _ = http_req('GET', '/api/reviews/')
        record('Public reviews exclude unapproved review', '/api/reviews/', 'GET', s, s == 200 and len(r.get('reviews', [])) == 0)

        # Admin approves review
        s, r, _ = http_req('POST', f'/admin/ratings/{review_id}/approve', headers={'Authorization': f"Bearer {admin_token.key}", 'X-Requested-With': 'XMLHttpRequest'})
        record('Admin approves review', f'/admin/ratings/{review_id}/approve', 'POST', s, s == 200)

        # Vendor views review -> comment now visible
        s, r, _ = http_req('GET', '/api/vendor/reviews/', token=vendor_a_token)
        rev = r.get('reviews', [{}])[0]
        record('Vendor views approved review (comment visible)', '/api/vendor/reviews/', 'GET', s, s == 200 and rev.get('comment_visible') is True and 'Prompt' in rev.get('comments'))

        # User reviews endpoint
        s, r, _ = http_req('GET', '/api/user/reviews/', token=user_a_token)
        record('User views submitted reviews', '/api/user/reviews/', 'GET', s, s == 200 and r.get('count') == 1)

        # 17. USER BANK DETAILS & ADMIN PAYOUT
        # Add bank details
        s, r, _ = http_req('POST', '/api/user/bank-details/', {
            'account_holder_name': 'Ramesh Kumar', 'bank_name': 'State Bank of India',
            'account_number': '123456789012', 'ifsc_code': 'SBIN0001234', 'upi_id': 'ramesh@sbi'
        }, token=user_a_token)
        record('User A adds bank details', '/api/user/bank-details/', 'POST', s, s == 201 and r.get('bank_details', {}).get('account_number') == 'XXXXXXXX9012')

        # Get bank details (masked)
        s, r, _ = http_req('GET', '/api/user/bank-details/', token=user_a_token)
        record('Get bank details (masked account number)', '/api/user/bank-details/', 'GET', s, s == 200 and r.get('bank_details', {}).get('account_number') == 'XXXXXXXX9012')

        # Admin disburses user payout (matching negotiated amount 1150.00)
        s, r, _ = http_req('POST', f'/admin/settlements/{order_id}/disburse', {
            'amount': '1150.00', 'method': 'IMPS', 'reference': 'UTR123456789'
        }, headers={'Authorization': f"Bearer {admin_token.key}", 'X-Requested-With': 'XMLHttpRequest'})
        record('Admin records user payout', f'/admin/settlements/{order_id}/disburse', 'POST', s, s == 200)

        # Duplicate disbursement rejected
        s, r, _ = http_req('POST', f'/admin/settlements/{order_id}/disburse', {
            'amount': '1150.00', 'method': 'IMPS', 'reference': 'UTR123456789'
        }, headers={'Authorization': f"Bearer {admin_token.key}", 'X-Requested-With': 'XMLHttpRequest'})
        record('Duplicate payout disbursement rejected', f'/admin/settlements/{order_id}/disburse', 'POST', s, s == 409)

        # 18. REFUND WORKFLOW
        # Request refund exceeding paid amount -> 400
        s, r, _ = http_req('POST', '/api/vendor/refunds/', {'order_id': order_id, 'amount': '999999.00', 'reason': 'Error'}, token=vendor_a_token)
        record('Excessive refund request rejected', '/api/vendor/refunds/', 'POST', s, s == 400)

        # Request valid refund
        s, r, _ = http_req('POST', '/api/vendor/refunds/', {'order_id': order_id, 'amount': '100.00', 'reason': 'Partial scrap grade dispute'}, token=vendor_a_token)
        ref_id = r.get('refund', {}).get('id')
        record('Vendor A requests partial refund', '/api/vendor/refunds/', 'POST', s, s == 201 and bool(ref_id))

        # Duplicate refund request rejected
        s, r, _ = http_req('POST', '/api/vendor/refunds/', {'order_id': order_id, 'amount': '50.00', 'reason': 'Again'}, token=vendor_a_token)
        record('Duplicate refund request rejected', '/api/vendor/refunds/', 'POST', s, s == 409)

        # Admin approves refund
        s, r, _ = http_req('POST', f'/admin/refunds/{ref_id}/approve', headers={'Authorization': f"Bearer {admin_token.key}", 'X-Requested-With': 'XMLHttpRequest'})
        record('Admin approves refund', f'/admin/refunds/{ref_id}/approve', 'POST', s, s == 200 and r.get('status') == 'APPROVED')

        # Admin processes refund in local-test sandbox
        s, r, _ = http_req('POST', f'/admin/refunds/{ref_id}/process', headers={'Authorization': f"Bearer {admin_token.key}", 'X-Requested-With': 'XMLHttpRequest'})
        record('Admin processes sandbox refund', f'/admin/refunds/{ref_id}/process', 'POST', s, s == 200 and r.get('status') == 'SUCCEEDED')

        # List & get refund details
        s, r, _ = http_req('GET', '/api/vendor/refunds/', token=vendor_a_token)
        record('List vendor refunds', '/api/vendor/refunds/', 'GET', s, s == 200 and r.get('count') == 1)

        s, r, _ = http_req('GET', f'/api/vendor/refunds/{ref_id}/', token=vendor_a_token)
        record('Get vendor refund detail', f'/api/vendor/refunds/{ref_id}/', 'GET', s, s == 200 and r.get('refund', {}).get('status') == 'SUCCEEDED')

        # 19. HOME, NOTIFICATIONS & HISTORY
        s, r, _ = http_req('GET', '/api/user/home/', token=user_a_token)
        record('Get User Home Dashboard', '/api/user/home/', 'GET', s, s == 200 and r.get('current_address') is not None)

        s, r, _ = http_req('GET', '/api/vendor/dashboard/', token=vendor_a_token)
        record('Get Vendor Dashboard Summary', '/api/vendor/dashboard/', 'GET', s, s == 200 and r.get('summary', {}).get('is_online') is True)

        s, r, _ = http_req('GET', '/api/user/orders/history/?type=completed', token=user_a_token)
        record('Get User Completed Orders History', '/api/user/orders/history/', 'GET', s, s == 200 and r.get('count') == 1)

        s, r, _ = http_req('GET', '/api/vendor/orders/history/', token=vendor_a_token)
        record('Get Vendor Orders History', '/api/vendor/orders/history/', 'GET', s, s == 200 and r.get('count') == 1)

        s, r, _ = http_req('GET', '/api/user/notifications/', token=user_a_token)
        notifs = r.get('notifications', [])
        notif_id = notifs[0].get('id') if notifs else None
        record('List User Notifications', '/api/user/notifications/', 'GET', s, s == 200 and len(notifs) > 0)

        if notif_id:
            s, r, _ = http_req('POST', f'/api/user/notifications/{notif_id}/read/', token=user_a_token)
            record('Mark Single Notification Read', f'/api/user/notifications/{notif_id}/read/', 'POST', s, s == 200)

        s, r, _ = http_req('POST', '/api/user/notifications/read-all/', token=user_a_token)
        record('Mark All Notifications Read', '/api/user/notifications/read-all/', 'POST', s, s == 200)

        # 20. SUPPORT CONFIG & LOGOUT
        s, r, _ = http_req('GET', '/api/support/')
        record('Get Support Details', '/api/support/', 'GET', s, s == 200 and bool(r.get('support', {}).get('phone')))

        s, r, _ = http_req('POST', '/api/user/logout/', token=user_a_token)
        record('User Logout', '/api/user/logout/', 'POST', s, s == 200)

        # Subsequent call with logged-out token -> 401
        s, r, _ = http_req('GET', '/api/user/profile/', token=user_a_token)
        record('Logged-out token rejected', '/api/user/profile/', 'GET', s, s == 401)

        s, r, _ = http_req('POST', '/api/vendor/auth/logout/', token=vendor_a_token)
        record('Vendor Logout', '/api/vendor/auth/logout/', 'POST', s, s == 200)

    finally:
        print("\nTerminating test server...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    failed = total - passed
    print(f"\nAudit complete: Total {total} HTTP test scenarios, {passed} PASSED, {failed} FAILED.")
    if failed > 0:
        print("\nFailed Scenarios:")
        for r in results:
            if not r['passed']:
                print(f"  FAILED: {r['method']} {r['route']} -> HTTP {r['status']}: {r['name']} ({r['details']})")
    return results

if __name__ == '__main__':
    run_audit()
