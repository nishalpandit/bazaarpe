


import re
import json
import math
import hashlib
import hmac
import secrets
import urllib.request
import urllib.parse
from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.core.paginator import Paginator
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.dateparse import parse_date
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.decorators import parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from .models import (
    UserProfile, OTPVerification, ServiceCity, ServiceZone, UserAddress,
    ScrapCategory, ScrapSubCategory, PickupOrder, PickupImage,
    VendorLocationTrack, OrderInvoice, OrderReview, UserBankDetail, money,
    LegalDocument, UserConsent, NegotiationProposal, UserNotification,
    PaymentTransaction, PaymentWebhookEvent,
    VendorProfile, VendorOfferRejection, VendorBillingSetting, RefundRequest,
)
from .authentication import BearerTokenAuthentication

COOKIE_MAX_AGE = 315360000  # 10 years (non-expiring token cookie)
OTP_COOLDOWN_SECONDS = 60
OTP_MAX_ATTEMPTS = 5
ALLOWED_PICKUP_SLOTS = {
    '09:00 AM - 12:00 PM', '10:00 AM - 01:00 PM',
    '12:00 PM - 03:00 PM', '03:00 PM - 06:00 PM',
}


def set_auth_cookies(response, token_key):
    """
    Sets persistent, non-expiring authentication cookies for app and web clients.
    Stores 'auth_token', 'token', and 'bearer_token' with 10-year lifetime.
    """
    for cookie_name in ('auth_token', 'token', 'bearer_token'):
        response.set_cookie(
            key=cookie_name,
            value=token_key,
            max_age=COOKIE_MAX_AGE,
            path='/',
            httponly=False,  # Accessible to client apps if needed
            samesite='Lax',
            secure=False
        )
    return response


def clear_auth_cookies(response):
    """Clears all auth cookies upon logout."""
    for cookie_name in ('auth_token', 'token', 'bearer_token'):
        response.delete_cookie(key=cookie_name, path='/')
    return response


def clean_phone(phone_input):
    """Normalize phone to a clean 10-digit number."""
    if not phone_input:
        return ''
    digits = re.sub(r'\D', '', str(phone_input))
    if len(digits) > 10 and digits.startswith('91'):
        digits = digits[2:]
    return digits[-10:] if len(digits) >= 10 else digits


def truthy(value):
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def active_legal_documents():
    documents = {}
    for doc_type in (LegalDocument.DocumentType.PRIVACY, LegalDocument.DocumentType.TERMS):
        documents[doc_type] = LegalDocument.objects.filter(document_type=doc_type, is_active=True).order_by('-published_at').first()
    return documents


def missing_required_consents(user):
    docs = active_legal_documents()
    accepted_ids = set(UserConsent.objects.filter(user=user).values_list('document_id', flat=True))
    return [doc for doc in docs.values() if doc and doc.id not in accepted_ids]


def consent_required_response(user):
    missing = missing_required_consents(user)
    if not missing:
        return None
    return Response({
        'success': False,
        'message': 'Current Privacy Policy and Terms must be accepted before continuing.',
        'consent_required': True,
        'missing': [{'document_type': doc.document_type, 'version': doc.version} for doc in missing],
    }, status=status.HTTP_428_PRECONDITION_REQUIRED)


def create_notification(user, event_type, title, message, order=None):
    return UserNotification.objects.create(
        user=user, order=order, event_type=event_type, title=title, message=message,
    )



@api_view(['POST'])
@permission_classes([AllowAny])
def send_otp_view(request):
    """
    POST /api/user/send-otp/
    Sends OTP for user registration or login.
    Params:
      - mobile_number or phone (required, 10 digits)
      - purpose (optional: 'LOGIN', 'REGISTER', 'AUTH')
    """
    phone_raw = request.data.get('mobile_number') or request.data.get('phone') or request.POST.get('mobile_number') or request.POST.get('phone')
    phone = clean_phone(phone_raw)

    if not phone or len(phone) != 10:
        return Response({
            'success': False,
            'message': 'Please provide a valid 10-digit mobile number.'
        }, status=status.HTTP_400_BAD_REQUEST)

    latest = OTPVerification.objects.filter(phone=phone, is_verified=False).order_by('-created_at').first()
    if latest:
        elapsed = (timezone.now() - latest.created_at).total_seconds()
        if elapsed < OTP_COOLDOWN_SECONDS:
            retry_after = max(1, int(OTP_COOLDOWN_SECONDS - elapsed))
            return Response({
                'success': False,
                'message': 'Please wait before requesting another OTP.',
                'retry_after_seconds': retry_after,
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

    # Check if user already exists
    profile = UserProfile.objects.filter(phone=phone).first()

    if profile:
        if profile.account_status in ('Blocked', 'Suspended'):
            return Response({
                'success': False,
                'message': 'Your account has been deactivated by administrator. Please contact support.'
            }, status=status.HTTP_403_FORBIDDEN)

        otp_rec = OTPVerification.generate_otp_for_phone(phone, purpose='LOGIN')
        payload = {
            'success': True,
            'message': f"OTP sent for login to {phone}",
            'mobile_number': phone,
            'phone': phone,
            'is_registered': True,
            'action': 'LOGIN',
            'expires_in_seconds': 600,
            'resend_after_seconds': OTP_COOLDOWN_SECONDS,
        }
        if settings.DEBUG:
            payload['otp_debug'] = otp_rec.otp
        return Response(payload, status=status.HTTP_200_OK)
    else:
        otp_rec = OTPVerification.generate_otp_for_phone(phone, purpose='REGISTER')
        payload = {
            'success': True,
            'message': f"Mobile number not registered. OTP sent for registration to {phone}",
            'mobile_number': phone,
            'phone': phone,
            'is_registered': False,
            'action': 'REGISTER',
            'expires_in_seconds': 600,
            'resend_after_seconds': OTP_COOLDOWN_SECONDS,
        }
        if settings.DEBUG:
            payload['otp_debug'] = otp_rec.otp
        return Response(payload, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp_login_view(request):
    """
    POST /api/user/verify-otp-login/ or /api/user/login-otp/
    Verifies OTP and signs in an existing user.
    Params:
      - mobile_number or phone (required)
      - otp (required, 6 digits)
    """
    phone_raw = request.data.get('mobile_number') or request.data.get('phone')
    phone = clean_phone(phone_raw)
    otp_code = str(request.data.get('otp', '')).strip()

    if not phone or len(phone) != 10:
        return Response({
            'success': False,
            'message': 'Please provide a valid 10-digit mobile number.'
        }, status=status.HTTP_400_BAD_REQUEST)

    if not otp_code or len(otp_code) != 6:
        return Response({
            'success': False,
            'message': 'Please provide a valid 6-digit OTP.'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Verify OTP
    otp_rec = OTPVerification.objects.filter(phone=phone, is_verified=False).exclude(purpose='CHANGE_PHONE').order_by('-created_at').first()

    if not otp_rec:
        return Response({
            'success': False,
            'message': 'No pending OTP found. Please request a new OTP.'
        }, status=status.HTTP_400_BAD_REQUEST)

    if otp_rec.is_expired:
        return Response({
            'success': False,
            'message': 'OTP has expired. Please request a new OTP.'
        }, status=status.HTTP_400_BAD_REQUEST)

    if otp_rec.attempts >= OTP_MAX_ATTEMPTS:
        return Response({
            'success': False,
            'message': 'OTP attempt limit reached. Request a new OTP after the cooldown.',
        }, status=status.HTTP_429_TOO_MANY_REQUESTS)

    if otp_rec.otp != otp_code:
        otp_rec.attempts += 1
        otp_rec.save(update_fields=['attempts'])
        return Response({
            'success': False,
            'message': 'Invalid OTP. Please check the code and try again.',
            'attempts_remaining': max(0, OTP_MAX_ATTEMPTS - otp_rec.attempts),
        }, status=status.HTTP_400_BAD_REQUEST)

    # Check user registration status
    profile = UserProfile.objects.filter(phone=phone).first()
    if not profile:
        return Response({
            'success': False,
            'message': 'Mobile number is not registered. Please complete registration.',
            'is_registered': False,
            'action': 'REGISTER'
        }, status=status.HTTP_404_NOT_FOUND)

    if profile.account_status in ('Blocked', 'Suspended'):
        return Response({
            'success': False,
            'message': 'Your account has been deactivated by administrator. Please contact support.'
        }, status=status.HTTP_403_FORBIDDEN)

    # Success
    otp_rec.is_verified = True
    otp_rec.save(update_fields=['is_verified'])

    token, _ = Token.objects.get_or_create(user=profile.user)

    response = Response({
        'success': True,
        'message': 'Login successful',
        'is_registered': True,
        'token': token.key,
        'user': profile.to_dict()
    }, status=status.HTTP_200_OK)

    # Store token in non-expiring cookies for app & web clients
    set_auth_cookies(response, token.key)
    return response


@api_view(['POST'])
@permission_classes([AllowAny])
def register_user_view(request):
    """
    POST /api/user/register/
    Registers a new user with OTP verification.
    Required credentials:
      - full_name (required)
      - mobile_number or phone (required, 10 digits)
      - email (optional / recommended)
      - address (required)
      - pincode (required, 6 digits)
      - otp (required, 6 digits)
      - city (optional)
    """
    data = request.data
    full_name = str(data.get('full_name', '')).strip()
    phone_raw = data.get('mobile_number') or data.get('phone')
    phone = clean_phone(phone_raw)
    email = str(data.get('email', '')).strip() or None
    address = str(data.get('address', '')).strip()
    pincode = str(data.get('pincode', '')).strip()
    city = str(data.get('city', '')).strip() or 'Bengaluru'
    otp_code = str(data.get('otp', '')).strip()
    legal_docs = active_legal_documents()

    # Validation
    errors = {}
    if not full_name:
        errors['full_name'] = 'Full name is required.'
    if not phone or len(phone) != 10:
        errors['mobile_number'] = 'A valid 10-digit mobile number is required.'
    if not address:
        errors['address'] = 'Address is required.'
    if not pincode or len(pincode) < 5:
        errors['pincode'] = 'A valid postal pincode is required.'
    if not otp_code or len(otp_code) != 6:
        errors['otp'] = 'A valid 6-digit OTP is required.'
    if not truthy(data.get('accept_privacy')):
        errors['accept_privacy'] = 'Privacy Policy acceptance is required.'
    if not truthy(data.get('accept_terms')):
        errors['accept_terms'] = 'Terms acceptance is required.'
    for doc_type, field_name in (
        (LegalDocument.DocumentType.PRIVACY, 'privacy_version'),
        (LegalDocument.DocumentType.TERMS, 'terms_version'),
    ):
        document = legal_docs.get(doc_type)
        if document and str(data.get(field_name, '')).strip() != document.version:
            errors[field_name] = f'Current version {document.version} must be accepted.'

    if errors:
        return Response({
            'success': False,
            'message': 'Validation failed. Please correct the fields.',
            'errors': errors
        }, status=status.HTTP_400_BAD_REQUEST)

    # Check if phone already registered
    if UserProfile.objects.filter(phone=phone).exists():
        return Response({
            'success': False,
            'message': 'A user with this mobile number already exists. Please login using OTP.',
            'is_registered': True,
            'action': 'LOGIN'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Verify OTP
    otp_rec = OTPVerification.objects.filter(phone=phone, purpose='REGISTER', is_verified=False).order_by('-created_at').first()

    if not otp_rec:
        return Response({
            'success': False,
            'message': 'No OTP requested for this mobile number. Please send OTP first.'
        }, status=status.HTTP_400_BAD_REQUEST)

    if otp_rec.is_expired:
        return Response({
            'success': False,
            'message': 'OTP has expired. Please request a new OTP.'
        }, status=status.HTTP_400_BAD_REQUEST)

    if otp_rec.attempts >= OTP_MAX_ATTEMPTS:
        return Response({
            'success': False,
            'message': 'OTP attempt limit reached. Request a new OTP after the cooldown.',
        }, status=status.HTTP_429_TOO_MANY_REQUESTS)

    if otp_rec.otp != otp_code:
        otp_rec.attempts += 1
        otp_rec.save(update_fields=['attempts'])
        return Response({
            'success': False,
            'message': 'Invalid OTP code. Please check and try again.',
            'attempts_remaining': max(0, OTP_MAX_ATTEMPTS - otp_rec.attempts),
        }, status=status.HTTP_400_BAD_REQUEST)

    # Create Django User
    user, created = User.objects.get_or_create(username=phone)
    name_parts = full_name.split()
    user.first_name = name_parts[0]
    user.last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
    if email:
        user.email = email
    user.set_unusable_password()
    user.save()

    # Create UserProfile
    profile = UserProfile.objects.create(
        user=user,
        full_name=full_name,
        phone=phone,
        email=email,
        address=address,
        pincode=pincode,
        city=city,
        account_status='Active',
        onboarding_step=2,
        onboarding_completed=bool(address and pincode),
    )

    # Mark OTP as verified
    otp_rec.is_verified = True
    otp_rec.save(update_fields=['is_verified'])

    UserConsent.objects.bulk_create([
        UserConsent(user=user, document=document)
        for document in legal_docs.values() if document
    ], ignore_conflicts=True)

    # Issue auth token
    token, _ = Token.objects.get_or_create(user=user)

    response = Response({
        'success': True,
        'message': 'User registered successfully',
        'is_registered': True,
        'token': token.key,
        'user': profile.to_dict()
    }, status=status.HTTP_201_CREATED)

    # Store token in non-expiring cookies for app & web clients
    set_auth_cookies(response, token.key)
    return response


@api_view(['GET', 'PUT', 'PATCH'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def user_profile_view(request):
    """
    GET /api/user/profile/
    PUT/PATCH /api/user/profile/
    Inspect or update the authenticated user's profile.
    Requires: Authorization: Bearer <token> or auth cookies
    """
    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist:
        return Response({
            'success': False,
            'message': 'User profile not found.'
        }, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response({
            'success': True,
            'user': profile.to_dict()
        }, status=status.HTTP_200_OK)

    # Update profile
    data = request.data
    if 'phone' in data or 'mobile_number' in data:
        submitted = clean_phone(data.get('phone') or data.get('mobile_number'))
        if submitted != clean_phone(profile.phone):
            return Response({
                'success': False,
                'message': 'Registered mobile number cannot be changed through profile editing. Verify the new number first.',
            }, status=status.HTTP_400_BAD_REQUEST)
    if 'full_name' in data and not str(data['full_name']).strip():
        return Response({'success': False, 'message': 'full_name cannot be blank.'}, status=status.HTTP_400_BAD_REQUEST)
    if 'pincode' in data and not re.fullmatch(r'\d{6}', str(data['pincode']).strip()):
        return Response({'success': False, 'message': 'pincode must be exactly 6 digits.'}, status=status.HTTP_400_BAD_REQUEST)
    if 'full_name' in data and str(data['full_name']).strip():
        profile.full_name = data['full_name'].strip()
        parts = profile.full_name.split()
        request.user.first_name = parts[0]
        request.user.last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''
    if 'email' in data:
        profile.email = data['email'].strip() or None
        request.user.email = profile.email or ''
    if 'address' in data:
        profile.address = data['address'].strip()
    if 'pincode' in data:
        profile.pincode = data['pincode'].strip()
    if 'city' in data:
        profile.city = data['city'].strip()
    if request.FILES.get('profile_photo'):
        uploaded = request.FILES['profile_photo']
        if not str(uploaded.content_type).startswith('image/'):
            return Response({'success': False, 'message': 'profile_photo must be an image file.'}, status=status.HTTP_400_BAD_REQUEST)
        if uploaded.size > 5 * 1024 * 1024:
            return Response({'success': False, 'message': 'profile_photo must not exceed 5 MB.'}, status=status.HTTP_400_BAD_REQUEST)
        profile.profile_photo = uploaded

    profile.onboarding_completed = bool(profile.full_name and profile.address and profile.pincode)
    profile.onboarding_step = 3 if profile.onboarding_completed else 2

    request.user.save()
    profile.save()

    return Response({
        'success': True,
        'message': 'Profile updated successfully',
        'user': profile.to_dict()
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def logout_api_view(request):
    """
    POST /api/user/logout/
    Logs out the user, deletes their active auth token, and clears auth cookies.
    Requires: Authorization: Bearer <token> or auth cookies
    """
    try:
        if request.auth:
            request.auth.delete()
        response = Response({
            'success': True,
            'message': 'User successfully logged out'
        }, status=status.HTTP_200_OK)

        # Clear authentication cookies
        clear_auth_cookies(response)
        return response
    except Exception as e:
        return Response({
            'success': False,
            'message': f'Logout error: {str(e)}'
        }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([AllowAny])
def legal_documents_view(request):
    docs = [doc for doc in active_legal_documents().values() if doc]
    return Response({
        'success': True,
        'documents': [{
            'document_type': doc.document_type,
            'version': doc.version,
            'title': doc.title,
            'content': doc.content,
            'published_at': doc.published_at.isoformat(),
        } for doc in docs],
    })


@api_view(['GET', 'POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def user_consents_view(request):
    docs = active_legal_documents()
    if request.method == 'POST':
        errors = {}
        accepted = []
        for doc_type, version_field, accept_field in (
            (LegalDocument.DocumentType.PRIVACY, 'privacy_version', 'accept_privacy'),
            (LegalDocument.DocumentType.TERMS, 'terms_version', 'accept_terms'),
        ):
            doc = docs.get(doc_type)
            if doc and (not truthy(request.data.get(accept_field)) or str(request.data.get(version_field, '')) != doc.version):
                errors[version_field] = f'Accept current version {doc.version}.'
            elif doc:
                consent, _ = UserConsent.objects.get_or_create(user=request.user, document=doc)
                accepted.append(consent)
        if errors:
            return Response({'success': False, 'message': 'Consent validation failed.', 'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
    consents = UserConsent.objects.filter(user=request.user).select_related('document')
    return Response({
        'success': True,
        'consents': [{
            'document_type': item.document.document_type,
            'version': item.document.version,
            'accepted_at': item.accepted_at.isoformat(),
            'is_current': docs.get(item.document.document_type) == item.document,
        } for item in consents],
        'consent_complete': not missing_required_consents(request.user),
    })


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def request_phone_change_view(request):
    new_phone = clean_phone(request.data.get('new_phone') or request.data.get('mobile_number'))
    if len(new_phone) != 10:
        return Response({'success': False, 'message': 'A valid new 10-digit mobile number is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if UserProfile.objects.filter(phone=new_phone).exclude(user=request.user).exists() or User.objects.filter(username=new_phone).exclude(id=request.user.id).exists():
        return Response({'success': False, 'message': 'Mobile number is already registered.'}, status=status.HTTP_409_CONFLICT)
    latest = OTPVerification.objects.filter(phone=new_phone, purpose='CHANGE_PHONE', is_verified=False).order_by('-created_at').first()
    if latest and (timezone.now() - latest.created_at).total_seconds() < OTP_COOLDOWN_SECONDS:
        return Response({'success': False, 'message': 'Please wait before requesting another OTP.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    otp = OTPVerification.generate_otp_for_phone(new_phone, purpose='CHANGE_PHONE')
    payload = {'success': True, 'message': 'OTP sent to the new mobile number.', 'expires_in_seconds': 600}
    if settings.DEBUG:
        payload['otp_debug'] = otp.otp
    return Response(payload)


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def confirm_phone_change_view(request):
    new_phone = clean_phone(request.data.get('new_phone') or request.data.get('mobile_number'))
    code = str(request.data.get('otp', '')).strip()
    otp = OTPVerification.objects.filter(phone=new_phone, purpose='CHANGE_PHONE', is_verified=False).order_by('-created_at').first()
    if not otp or otp.is_expired or otp.attempts >= OTP_MAX_ATTEMPTS:
        return Response({'success': False, 'message': 'No valid phone-change OTP is available.'}, status=status.HTTP_400_BAD_REQUEST)
    if otp.otp != code:
        otp.attempts += 1
        otp.save(update_fields=['attempts'])
        return Response({'success': False, 'message': 'Invalid OTP.', 'attempts_remaining': max(0, OTP_MAX_ATTEMPTS - otp.attempts)}, status=status.HTTP_400_BAD_REQUEST)
    if UserProfile.objects.filter(phone=new_phone).exclude(user=request.user).exists() or User.objects.filter(username=new_phone).exclude(id=request.user.id).exists():
        return Response({'success': False, 'message': 'Mobile number is already registered.'}, status=status.HTTP_409_CONFLICT)
    with transaction.atomic():
        profile = request.user.profile
        profile.phone = new_phone
        profile.save(update_fields=['phone', 'updated_at'])
        request.user.username = new_phone
        request.user.save(update_fields=['username'])
        otp.is_verified = True
        otp.save(update_fields=['is_verified'])
    return Response({'success': True, 'message': 'Registered mobile number updated after verification.', 'mobile_number': new_phone})


# -------------------------------------------------------------------------
# Location & Service Zone Helper Functions
# -------------------------------------------------------------------------

def reverse_geocode_osm(latitude, longitude):
    """
    Reverse geocodes GPS coordinates (latitude, longitude) using OpenStreetMap Nominatim.
    Falls back gracefully if network is slow, unavailable, or rate-limited.
    """
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={latitude}&lon={longitude}&format=json&addressdetails=1"
        headers = {
            'User-Agent': 'BazaarpeApp/1.0 (contact: support@bazaarpe.com)'
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=2.5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                address = data.get('address', {})
                road = address.get('road') or address.get('suburb') or address.get('neighbourhood') or ''
                house_no = address.get('house_number') or address.get('building') or ''
                city = address.get('city') or address.get('town') or address.get('state_district') or address.get('county') or ''
                state = address.get('state') or ''
                postcode = address.get('postcode') or ''
                display_name = data.get('display_name') or ''

                return {
                    'formatted_address': display_name,
                    'house_no': house_no,
                    'street_address': road,
                    'area': address.get('suburb') or address.get('neighbourhood') or road,
                    'city': city,
                    'state': state,
                    'pincode': postcode,
                    'country': address.get('country', 'India')
                }
    except Exception:
        pass
    return None


def match_service_zone(latitude, longitude, detected_city=None, detected_pincode=None):
    """
    Matches coordinates or pincode/city to the nearest active ServiceZone.
    Returns (matched_zone, distance_km, is_serviceable, all_city_zones).
    """
    lat = float(latitude)
    lon = float(longitude)

    # 1. Pincode match priority
    if detected_pincode:
        clean_pin = str(detected_pincode).strip()
        for zone in ServiceZone.objects.filter(is_active=True).select_related('city'):
            if clean_pin in zone.pincode_list:
                dist = zone.distance_to(lat, lon) or 0.0
                city_zones = ServiceZone.objects.filter(city=zone.city, is_active=True)
                return zone, dist, True, list(city_zones)

    # 2. Distance match
    active_zones = ServiceZone.objects.filter(is_active=True).select_related('city')
    if detected_city:
        city_filtered = active_zones.filter(city__name__iexact=detected_city.strip())
        if city_filtered.exists():
            active_zones = city_filtered

    closest_zone = None
    min_dist = float('inf')

    for zone in active_zones:
        dist = zone.distance_to(lat, lon)
        if dist is not None and dist < min_dist:
            min_dist = dist
            closest_zone = zone

    # Fallback to all zones if no match in city_filtered
    if not closest_zone:
        for zone in ServiceZone.objects.filter(is_active=True).select_related('city'):
            dist = zone.distance_to(lat, lon)
            if dist is not None and dist < min_dist:
                min_dist = dist
                closest_zone = zone

    if closest_zone:
        is_serviceable = min_dist <= float(closest_zone.radius_km) or min_dist <= 20.0
        city_zones = ServiceZone.objects.filter(city=closest_zone.city, is_active=True)
        return closest_zone, round(min_dist, 2), is_serviceable, list(city_zones)

    return None, None, False, []


# -------------------------------------------------------------------------
# Location & Service Zone REST API Views
# -------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([AllowAny])
def detect_location_view(request):
    """
    POST /api/user/location/detect/
    Auto-detects user location from GPS coordinates (latitude, longitude).
    Fetches reverse geocoded address, city, pincode, and automatically
    detects the matching Service Zone and serviceable status.
    """
    data = request.data
    lat_raw = data.get('latitude') or data.get('lat')
    lon_raw = data.get('longitude') or data.get('lng') or data.get('lon')

    if lat_raw is None or lon_raw is None:
        return Response({
            'success': False,
            'message': 'Please provide GPS latitude and longitude coordinates.'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        latitude = float(lat_raw)
        longitude = float(lon_raw)
    except (ValueError, TypeError):
        return Response({
            'success': False,
            'message': 'Invalid latitude or longitude values.'
        }, status=status.HTTP_400_BAD_REQUEST)

    # 1. Reverse Geocode via OSM
    geo_data = reverse_geocode_osm(latitude, longitude)

    detected_city = geo_data.get('city') if geo_data else None
    detected_pincode = geo_data.get('pincode') if geo_data else None

    # 2. Match to Bazaarpe Service Zone
    matched_zone, distance_km, is_serviceable, city_zones = match_service_zone(
        latitude, longitude, detected_city, detected_pincode
    )

    # 3. If OSM was offline, use matched zone center to construct clean fallback address
    if not geo_data and matched_zone:
        pin = matched_zone.pincode_list[0] if matched_zone.pincode_list else ''
        geo_data = {
            'formatted_address': f"{matched_zone.name}, {matched_zone.city.name}, {matched_zone.city.state} {pin}".strip(),
            'house_no': '',
            'street_address': matched_zone.name,
            'area': matched_zone.name,
            'city': matched_zone.city.name,
            'state': matched_zone.city.state,
            'pincode': pin,
            'country': 'India'
        }
    elif not geo_data:
        geo_data = {
            'formatted_address': f"Lat: {latitude:.4f}, Long: {longitude:.4f}",
            'house_no': '',
            'street_address': '',
            'area': '',
            'city': 'Bengaluru',
            'state': 'Karnataka',
            'pincode': '',
            'country': 'India'
        }

    # Available zones in this city for manual selection/editing
    available_zones = [
        {
            'id': z.id,
            'name': z.name,
            'code': z.code or f"ZN-{z.id:02d}",
            'city': z.city.name,
            'is_active': z.is_active,
        }
        for z in city_zones
    ]

    response_data = {
        'success': True,
        'message': 'Location and service zone detected successfully',
        'is_serviceable': is_serviceable,
        'location': {
            'latitude': latitude,
            'longitude': longitude,
            'formatted_address': geo_data.get('formatted_address', ''),
            'house_no': geo_data.get('house_no', ''),
            'street_address': geo_data.get('street_address', ''),
            'area': geo_data.get('area', ''),
            'landmark': '',
            'city': matched_zone.city.name if matched_zone else geo_data.get('city', ''),
            'state': matched_zone.city.state if matched_zone else geo_data.get('state', ''),
            'pincode': geo_data.get('pincode', ''),
        },
        'service_zone': {
            'id': matched_zone.id if matched_zone else None,
            'name': matched_zone.name if matched_zone else None,
            'code': matched_zone.code if matched_zone else None,
            'city': matched_zone.city.name if matched_zone else None,
            'distance_km': distance_km,
            'is_serviceable': is_serviceable,
        } if matched_zone else None,
        'available_zones_in_city': available_zones,
    }

    return Response(response_data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def service_zones_view(request):
    """
    GET /api/user/service-zones/ or /api/user/cities/
    Returns list of serviceable cities and active service zones.
    Optional query param: ?city=Bengaluru
    """
    city_filter = request.GET.get('city', '').strip()

    cities_qs = ServiceCity.objects.filter(is_active=True).prefetch_related('zones')
    if city_filter:
        cities_qs = cities_qs.filter(name__iexact=city_filter)

    results = []
    for city in cities_qs:
        zones_data = [
            {
                'id': z.id,
                'name': z.name,
                'code': z.code or f"ZN-{z.id:02d}",
                'pincodes': z.pincode_list,
                'center_latitude': float(z.center_latitude) if z.center_latitude is not None else None,
                'center_longitude': float(z.center_longitude) if z.center_longitude is not None else None,
                'radius_km': float(z.radius_km),
                'is_active': z.is_active,
            }
            for z in city.zones.filter(is_active=True)
        ]
        results.append({
            'id': city.id,
            'city': city.name,
            'state': city.state,
            'is_active': city.is_active,
            'zones': zones_data
        })

    return Response({
        'success': True,
        'cities': results
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def confirm_location_view(request):
    """
    POST /api/user/location/confirm/ or /api/user/address/save/
    Confirms location and saves user address with optional manual edits.
    Params:
      - latitude, longitude (optional / GPS coordinates)
      - house_no (optional: Flat/House/Building)
      - street_address (optional: Street/Road/Area)
      - formatted_address (required or auto-constructed)
      - landmark (optional)
      - city (required, default 'Bengaluru')
      - state (optional, default 'Karnataka')
      - pincode (required)
      - service_zone_id or service_zone (optional)
      - address_type ('Home', 'Work', 'Other', default 'Home')
      - is_default (bool, default true if first address)
    """
    user = request.user
    profile = getattr(user, 'profile', None)
    if not profile:
        profile = UserProfile.objects.create(
            user=user,
            full_name=user.get_full_name() or user.username,
            phone=user.username,
            account_status='Active'
        )

    data = request.data
    house_no = str(data.get('house_no', '')).strip()
    street_address = str(data.get('street_address', '')).strip()
    landmark = str(data.get('landmark', '')).strip()
    city = str(data.get('city', '')).strip() or (profile.city or 'Bengaluru')
    state = str(data.get('state', '')).strip() or 'Karnataka'
    pincode = str(data.get('pincode', '')).strip() or (profile.pincode or '')
    address_type = str(data.get('address_type', 'Home')).strip().title()
    if address_type not in ('Home', 'Work', 'Other'):
        address_type = 'Home'

    formatted_address = str(data.get('formatted_address', '')).strip()
    if not formatted_address:
        parts = [p for p in [house_no, street_address, landmark, city, f"{state} {pincode}".strip()] if p]
        formatted_address = ', '.join(parts)

    if not formatted_address:
        return Response({
            'success': False,
            'message': 'Please provide address details or formatted address.'
        }, status=status.HTTP_400_BAD_REQUEST)

    if not re.fullmatch(r'\d{6}', pincode):
        return Response({
            'success': False,
            'message': 'A valid 6-digit pincode is required to confirm address.'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Parse coordinates
    lat = None
    lon = None
    lat_val = data.get('latitude') or data.get('lat')
    lon_val = data.get('longitude') or data.get('lng') or data.get('lon')
    if lat_val is not None and lon_val is not None:
        try:
            lat = Decimal(str(lat_val))
            lon = Decimal(str(lon_val))
        except Exception:
            return Response({'success': False, 'message': 'Invalid latitude or longitude.'}, status=status.HTTP_400_BAD_REQUEST)
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return Response({'success': False, 'message': 'Latitude or longitude is outside the valid range.'}, status=status.HTTP_400_BAD_REQUEST)

    # Resolve Service Zone
    service_zone = None
    zone_id = data.get('service_zone_id')
    zone_name = str(data.get('service_zone', '')).strip()

    if zone_id:
        service_zone = ServiceZone.objects.filter(id=zone_id, is_active=True).first()
    elif zone_name:
        service_zone = ServiceZone.objects.filter(
            Q(name__iexact=zone_name) | Q(code__iexact=zone_name),
            is_active=True
        ).first()

    # If zone not specified, auto-match from coordinates/pincode
    if not service_zone and (lat is not None and lon is not None or pincode):
        zone_match, _, _, _ = match_service_zone(
            float(lat) if lat else 12.9716,
            float(lon) if lon else 77.5946,
            city,
            pincode
        )
        service_zone = zone_match
    if ServiceZone.objects.filter(is_active=True).exists() and not service_zone:
        return Response({'success': False, 'message': 'This address is outside the configured service area.', 'is_serviceable': False}, status=status.HTTP_400_BAD_REQUEST)

    # Check is_default status
    is_default = truthy(data.get('is_default', False))
    has_existing = UserAddress.objects.filter(user=user).exists()
    if not has_existing or is_default:
        is_default = True
        UserAddress.objects.filter(user=user).update(is_default=False)

    # Save UserAddress
    address_obj = UserAddress.objects.create(
        user=user,
        profile=profile,
        address_type=address_type,
        house_no=house_no,
        street_address=street_address,
        landmark=landmark,
        formatted_address=formatted_address,
        city=city,
        state=state,
        pincode=pincode,
        service_zone=service_zone,
        zone_name=service_zone.name if service_zone else zone_name,
        latitude=lat,
        longitude=lon,
        is_default=is_default
    )

    # If default, sync to UserProfile
    if is_default:
        profile.address = formatted_address
        profile.city = city
        profile.pincode = pincode
        if lat is not None:
            profile.latitude = lat
        if lon is not None:
            profile.longitude = lon
        if service_zone:
            profile.service_zone = service_zone
        profile.save()

    return Response({
        'success': True,
        'message': 'Location and address confirmed successfully',
        'address': address_obj.to_dict(),
        'user_profile': profile.to_dict()
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def user_addresses_view(request):
    """
    GET /api/user/addresses/
    Lists all saved addresses for the authenticated user.
    """
    addresses = UserAddress.objects.filter(user=request.user)
    return Response({
        'success': True,
        'count': addresses.count(),
        'addresses': [addr.to_dict() for addr in addresses]
    }, status=status.HTTP_200_OK)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def user_address_detail_view(request, address_id):
    """
    GET /api/user/addresses/<id>/
    PUT/PATCH /api/user/addresses/<id>/
    DELETE /api/user/addresses/<id>/
    Inspects, updates, or deletes a specific user address.
    """
    address_obj = UserAddress.objects.filter(id=address_id, user=request.user).first()
    if not address_obj:
        return Response({
            'success': False,
            'message': 'Address not found or does not belong to you.'
        }, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response({
            'success': True,
            'address': address_obj.to_dict()
        }, status=status.HTTP_200_OK)

    if request.method == 'DELETE':
        was_default = address_obj.is_default
        address_obj.delete()

        # If deleted address was default, promote latest remaining address
        if was_default:
            next_addr = UserAddress.objects.filter(user=request.user).order_by('-created_at').first()
            if next_addr:
                next_addr.is_default = True
                next_addr.save(update_fields=['is_default'])
                profile = getattr(request.user, 'profile', None)
                if profile:
                    profile.address = next_addr.formatted_address
                    profile.city = next_addr.city
                    profile.pincode = next_addr.pincode
                    profile.latitude = next_addr.latitude
                    profile.longitude = next_addr.longitude
                    profile.service_zone = next_addr.service_zone
                    profile.save()

        return Response({
            'success': True,
            'message': 'Address deleted successfully'
        }, status=status.HTTP_200_OK)

    # PUT / PATCH
    data = request.data
    if 'house_no' in data:
        address_obj.house_no = str(data['house_no']).strip()
    if 'street_address' in data:
        address_obj.street_address = str(data['street_address']).strip()
    if 'landmark' in data:
        address_obj.landmark = str(data['landmark']).strip()
    if 'city' in data:
        address_obj.city = str(data['city']).strip()
    if 'state' in data:
        address_obj.state = str(data['state']).strip()
    if 'pincode' in data:
        candidate_pincode = str(data['pincode']).strip()
        if not re.fullmatch(r'\d{6}', candidate_pincode):
            return Response({'success': False, 'message': 'pincode must be exactly 6 digits.'}, status=status.HTTP_400_BAD_REQUEST)
        address_obj.pincode = candidate_pincode
    if 'address_type' in data:
        t = str(data['address_type']).strip().title()
        if t in ('Home', 'Work', 'Other'):
            address_obj.address_type = t

    if 'formatted_address' in data and data['formatted_address'].strip():
        address_obj.formatted_address = str(data['formatted_address']).strip()
    else:
        parts = [p for p in [address_obj.house_no, address_obj.street_address, address_obj.landmark, address_obj.city, f"{address_obj.state} {address_obj.pincode}".strip()] if p]
        address_obj.formatted_address = ', '.join(parts)

    lat_val = data.get('latitude') or data.get('lat')
    lon_val = data.get('longitude') or data.get('lng') or data.get('lon')
    if lat_val is not None and lon_val is not None:
        try:
            address_obj.latitude = Decimal(str(lat_val))
            address_obj.longitude = Decimal(str(lon_val))
        except Exception:
            pass

    zone_id = data.get('service_zone_id')
    if zone_id:
        sz = ServiceZone.objects.filter(id=zone_id, is_active=True).first()
        if sz:
            address_obj.service_zone = sz
            address_obj.zone_name = sz.name

    if 'is_default' in data and data['is_default']:
        UserAddress.objects.filter(user=request.user).exclude(id=address_obj.id).update(is_default=False)
        address_obj.is_default = True

    address_obj.save()

    # Sync to profile if default
    profile = getattr(request.user, 'profile', None)
    if profile and address_obj.is_default:
        profile.address = address_obj.formatted_address
        profile.city = address_obj.city
        profile.pincode = address_obj.pincode
        profile.latitude = address_obj.latitude
        profile.longitude = address_obj.longitude
        profile.service_zone = address_obj.service_zone
        profile.save()

    return Response({
        'success': True,
        'message': 'Address updated successfully',
        'address': address_obj.to_dict()
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def set_default_address_view(request, address_id):
    """
    POST /api/user/addresses/<id>/set-default/
    Marks the given address as default and syncs it to the user's profile.
    """
    address_obj = UserAddress.objects.filter(id=address_id, user=request.user).first()
    if not address_obj:
        return Response({
            'success': False,
            'message': 'Address not found or does not belong to you.'
        }, status=status.HTTP_404_NOT_FOUND)

    UserAddress.objects.filter(user=request.user).update(is_default=False)
    address_obj.is_default = True
    address_obj.save(update_fields=['is_default'])

    profile = getattr(request.user, 'profile', None)
    if profile:
        profile.address = address_obj.formatted_address
        profile.city = address_obj.city
        profile.pincode = address_obj.pincode
        profile.latitude = address_obj.latitude
        profile.longitude = address_obj.longitude
        profile.service_zone = address_obj.service_zone
        profile.save()

    return Response({
        'success': True,
        'message': 'Default address updated successfully',
        'address': address_obj.to_dict()
    }, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Pickup marketplace, billing, reviews, and payout settings
# ---------------------------------------------------------------------------


def decimal_value(value, field_name, *, positive=False):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{field_name} must be a valid number.')
    if positive and parsed <= 0:
        raise ValueError(f'{field_name} must be greater than zero.')
    return parsed


def order_for_user(order_id, user):
    return (
        PickupOrder.objects.select_related('address', 'category', 'subcategory')
        .filter(order_id=order_id, user=user)
        .first()
    )


def vendor_can_manage(order, user):
    if order.assigned_vendor_id != user.id:
        return False
    vendor = get_vendor_profile(user)
    return vendor_block_reason(vendor) is None


def get_vendor_profile(user):
    return VendorProfile.objects.filter(user=user).select_related('user__profile').prefetch_related('operating_zones').first()


def vendor_block_reason(vendor, *, require_online=False):
    if not vendor or not getattr(vendor.user, 'profile', None) or not vendor.user.profile.is_vendor:
        return 'A vendor business profile is required.'
    if vendor.user.profile.account_status != 'Active':
        return 'Vendor account is not active.'
    if vendor.kyc_status != VendorProfile.KYCStatus.APPROVED:
        return 'Admin-approved KYC is required.'
    if missing_required_consents(vendor.user):
        return 'Current Terms and Privacy Policy acceptance is required.'
    if require_online and not vendor.is_online:
        return 'Vendor must be online to access marketplace orders.'
    return None


def vendor_order_eligibility(order, vendor):
    reason = vendor_block_reason(vendor, require_online=True)
    if reason:
        return False, reason
    if order.status != PickupOrder.Status.SEARCHING_VENDOR or order.assigned_vendor_id:
        return False, 'Order is not available.'
    if order.final_agreed_price is None or order.published_at is None:
        return False, 'Order has not completed price agreement and publication.'
    if order.acceptance_deadline and timezone.now() > order.acceptance_deadline:
        return False, 'Order acceptance deadline has expired.'
    if not order.address_id or not order.address.service_zone_id:
        return False, 'Order does not have a serviceable pickup zone.'
    if order.address.service_zone_id not in set(vendor.operating_zones.values_list('id', flat=True)):
        return False, 'Order is outside the vendor operating zones.'
    if VendorOfferRejection.objects.filter(vendor=vendor, order=order).exists():
        return False, 'Vendor rejected this offer.'
    return True, None


def haversine_km(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    lat1, lon1, lat2, lon2 = map(lambda value: math.radians(float(value)), (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(6371.0 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)), 2)


def serialize_vendor_profile(vendor):
    profile = vendor.user.profile
    return {
        'id': vendor.id,
        'shop_name': vendor.shop_name,
        'owner_name': vendor.owner_name,
        'profile_picture': vendor.profile_picture.url if vendor.profile_picture else None,
        'registered_mobile_number': profile.phone,
        'full_address': vendor.full_address,
        'city': vendor.city,
        'state': vendor.state,
        'pincode': vendor.pincode,
        'latitude': float(vendor.latitude) if vendor.latitude is not None else None,
        'longitude': float(vendor.longitude) if vendor.longitude is not None else None,
        'is_online': vendor.is_online,
        'kyc_status': vendor.kyc_status,
        'kyc_rejection_reason': vendor.kyc_rejection_reason,
        'aadhaar_status': vendor.aadhaar_status,
        'aadhaar_masked': f'XXXXXXXX{vendor.aadhaar_last4}' if vendor.aadhaar_last4 else None,
        'pan_masked': f'XXXXXX{vendor.pan_last4}' if vendor.pan_last4 else None,
        'operating_zones': [zone.to_dict() for zone in vendor.operating_zones.all()],
    }


def serialize_vendor_order(order, vendor, *, assigned=False):
    address = order.address
    distance = haversine_km(vendor.latitude, vendor.longitude, address.latitude if address else None, address.longitude if address else None)
    payload = {
        'order_id': order.order_id,
        'status': order.status,
        'category': order.category.name if order.category else None,
        'subcategory': order.subcategory.name if order.subcategory else None,
        'approx_weight': float(order.approx_weight),
        'pickup_date': order.pickup_date.isoformat(),
        'time_slot': order.time_slot,
        'final_agreed_price': float(order.final_agreed_price) if order.final_agreed_price is not None else None,
        'service_zone': address.service_zone.name if address and address.service_zone else None,
        'coordinates': {
            'latitude': float(address.latitude) if address and address.latitude is not None else None,
            'longitude': float(address.longitude) if address and address.longitude is not None else None,
        },
        'distance_km': distance,
        'distance_method': 'haversine_great_circle' if distance is not None else None,
        'acceptance_deadline': order.acceptance_deadline.isoformat() if order.acceptance_deadline else None,
        'arrival_deadline': order.arrival_deadline.isoformat() if order.arrival_deadline else None,
    }
    if assigned:
        user_profile = getattr(order.user, 'profile', None)
        payload['pickup_address'] = address.formatted_address if address else None
        payload['customer'] = {'name': user_profile.full_name if user_profile else order.user.get_full_name(), 'phone': user_profile.phone if user_profile else None}
        payload['is_otp_verified'] = order.is_otp_verified
        payload['final_weight'] = float(order.final_weight) if order.final_weight is not None else None
    return payload


@api_view(['GET', 'POST', 'PUT', 'PATCH'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def vendor_profile_view(request):
    vendor = get_vendor_profile(request.user)
    if request.method == 'GET':
        if not vendor:
            return Response({'success': False, 'message': 'Vendor profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'vendor': serialize_vendor_profile(vendor)})
    consent = consent_required_response(request.user)
    if consent:
        return consent
    data = request.data
    coordinates = {}
    for field, minimum, maximum in (('latitude', Decimal('-90'), Decimal('90')), ('longitude', Decimal('-180'), Decimal('180'))):
        if field in data and data[field] not in ('', None):
            try:
                coordinates[field] = decimal_value(data[field], field)
            except ValueError as exc:
                return Response({'success': False, 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            if not minimum <= coordinates[field] <= maximum:
                return Response({'success': False, 'message': f'{field} is outside the valid range.'}, status=status.HTTP_400_BAD_REQUEST)
    if 'phone' in data or 'mobile_number' in data:
        submitted = clean_phone(data.get('phone') or data.get('mobile_number'))
        if submitted != clean_phone(request.user.profile.phone):
            return Response({'success': False, 'message': 'Verified mobile number cannot be changed through vendor profile editing.'}, status=status.HTTP_400_BAD_REQUEST)
    required = ('shop_name', 'owner_name', 'full_address', 'city', 'state', 'pincode')
    if not vendor:
        missing = [field for field in required if not str(data.get(field, '')).strip()]
        if missing:
            return Response({'success': False, 'message': f"Missing required fields: {', '.join(missing)}."}, status=status.HTTP_400_BAD_REQUEST)
        if not re.fullmatch(r'\d{6}', str(data.get('pincode', '')).strip()):
            return Response({'success': False, 'message': 'pincode must be exactly 6 digits.'}, status=status.HTTP_400_BAD_REQUEST)
        vendor = VendorProfile.objects.create(
            user=request.user, shop_name=str(data['shop_name']).strip(), owner_name=str(data['owner_name']).strip(),
            full_address=str(data['full_address']).strip(), city=str(data['city']).strip(), state=str(data['state']).strip(),
            pincode=str(data['pincode']).strip(), latitude=coordinates.get('latitude'), longitude=coordinates.get('longitude'),
        )
        request.user.profile.is_vendor = True
        request.user.profile.save(update_fields=['is_vendor', 'updated_at'])
    else:
        for field in required:
            if field in data and str(data[field]).strip():
                setattr(vendor, field, str(data[field]).strip())
        if 'pincode' in data and not re.fullmatch(r'\d{6}', str(data['pincode']).strip()):
            return Response({'success': False, 'message': 'pincode must be exactly 6 digits.'}, status=status.HTTP_400_BAD_REQUEST)
        for field, value in coordinates.items():
            setattr(vendor, field, value)
    picture = request.FILES.get('profile_picture')
    if picture:
        if not str(picture.content_type).startswith('image/') or picture.size > 5 * 1024 * 1024:
            return Response({'success': False, 'message': 'profile_picture must be an image not exceeding 5 MB.'}, status=status.HTTP_400_BAD_REQUEST)
        vendor.profile_picture = picture
    vendor.save()
    return Response({'success': True, 'message': 'Vendor profile saved.', 'vendor': serialize_vendor_profile(vendor)}, status=status.HTTP_201_CREATED if request.method == 'POST' else status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def vendor_states_zones_view(request):
    state_filter = str(request.GET.get('state', '')).strip()
    zones = ServiceZone.objects.filter(is_active=True, city__is_active=True).select_related('city')
    if state_filter:
        zones = zones.filter(city__state__iexact=state_filter)
    states = list(ServiceCity.objects.filter(is_active=True).values_list('state', flat=True).distinct().order_by('state'))
    return Response({'success': True, 'states': states, 'zones': [zone.to_dict() for zone in zones]})


@api_view(['GET', 'PUT'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_operating_zones_view(request):
    vendor = get_vendor_profile(request.user)
    if not vendor:
        return Response({'success': False, 'message': 'Vendor profile not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'PUT':
        zone_ids = request.data.get('zone_ids', [])
        if isinstance(zone_ids, str):
            try: zone_ids = json.loads(zone_ids)
            except json.JSONDecodeError: zone_ids = []
        if not isinstance(zone_ids, list) or not zone_ids:
            return Response({'success': False, 'message': 'zone_ids must be a non-empty list.'}, status=status.HTTP_400_BAD_REQUEST)
        normalized_zone_ids = []
        for zone_id in zone_ids:
            if isinstance(zone_id, bool) or not re.fullmatch(r'\d+', str(zone_id)) or int(zone_id) <= 0:
                return Response({'success': False, 'message': 'Every zone_id must be a positive integer.'}, status=status.HTTP_400_BAD_REQUEST)
            normalized_zone_ids.append(int(zone_id))
        if len(normalized_zone_ids) != len(set(normalized_zone_ids)):
            return Response({'success': False, 'message': 'zone_ids must contain unique positive integers.'}, status=status.HTTP_400_BAD_REQUEST)
        zones = list(ServiceZone.objects.filter(id__in=set(normalized_zone_ids), is_active=True, city__is_active=True))
        if len(zones) != len(set(normalized_zone_ids)):
            return Response({'success': False, 'message': 'One or more zones are invalid or inactive.'}, status=status.HTTP_400_BAD_REQUEST)
        vendor.operating_zones.set(zones)
    return Response({'success': True, 'zones': [zone.to_dict() for zone in vendor.operating_zones.all()]})


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_availability_view(request):
    vendor = get_vendor_profile(request.user)
    if not vendor:
        return Response({'success': False, 'message': 'Vendor profile not found.'}, status=status.HTTP_404_NOT_FOUND)
    if vendor.kyc_status != VendorProfile.KYCStatus.APPROVED and truthy(request.data.get('is_online')):
        return Response({'success': False, 'message': 'Only approved vendors can go online.'}, status=status.HTTP_403_FORBIDDEN)
    vendor.is_online = truthy(request.data.get('is_online'))
    vendor.save(update_fields=['is_online', 'updated_at'])
    return Response({'success': True, 'is_online': vendor.is_online})


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_aadhaar_initiate_view(request):
    vendor = get_vendor_profile(request.user)
    if not vendor:
        return Response({'success': False, 'message': 'Vendor profile not found.'}, status=status.HTTP_404_NOT_FOUND)
    last4 = re.sub(r'\D', '', str(request.data.get('aadhaar_last4', '')))
    if len(last4) != 4:
        return Response({'success': False, 'message': 'Only the final 4 Aadhaar digits are required.'}, status=status.HTTP_400_BAD_REQUEST)
    mode = getattr(settings, 'AADHAAR_PROVIDER_MODE', 'unconfigured')
    if mode != 'local-test':
        return Response({
            'success': False,
            'message': 'Aadhaar provider is not configured; verification cannot be simulated as successful.',
            'provider_configured': False,
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    vendor.aadhaar_last4 = last4
    vendor.aadhaar_status = VendorProfile.AadhaarStatus.PENDING
    vendor.aadhaar_provider_reference = f'aad_sbx_{secrets.token_hex(10)}'
    vendor.save(update_fields=['aadhaar_last4', 'aadhaar_status', 'aadhaar_provider_reference', 'updated_at'])
    payload = {'success': True, 'reference': vendor.aadhaar_provider_reference, 'status': vendor.aadhaar_status}
    if settings.DEBUG:
        payload['sandbox_otp'] = getattr(settings, 'AADHAAR_LOCAL_TEST_OTP', '123456')
    return Response(payload)


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_aadhaar_confirm_view(request):
    vendor = get_vendor_profile(request.user)
    if not vendor or vendor.aadhaar_status != VendorProfile.AadhaarStatus.PENDING:
        return Response({'success': False, 'message': 'No pending Aadhaar verification.'}, status=status.HTTP_409_CONFLICT)
    if getattr(settings, 'AADHAAR_PROVIDER_MODE', 'unconfigured') != 'local-test':
        return Response({'success': False, 'message': 'Aadhaar provider is not configured.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if str(request.data.get('reference', '')) != vendor.aadhaar_provider_reference or str(request.data.get('otp', '')) != str(getattr(settings, 'AADHAAR_LOCAL_TEST_OTP', '123456')):
        vendor.aadhaar_status = VendorProfile.AadhaarStatus.FAILED
        vendor.save(update_fields=['aadhaar_status', 'updated_at'])
        return Response({'success': False, 'message': 'Aadhaar confirmation failed.'}, status=status.HTTP_400_BAD_REQUEST)
    vendor.aadhaar_status = VendorProfile.AadhaarStatus.VERIFIED
    vendor.save(update_fields=['aadhaar_status', 'updated_at'])
    return Response({'success': True, 'status': vendor.aadhaar_status})


@api_view(['GET', 'POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def vendor_kyc_view(request):
    vendor = get_vendor_profile(request.user)
    if not vendor:
        return Response({'success': False, 'message': 'Vendor profile not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response({'success': True, 'kyc': {
            'status': vendor.kyc_status,
            'rejection_reason': vendor.kyc_rejection_reason,
            'aadhaar_status': vendor.aadhaar_status,
            'aadhaar_masked': f'XXXXXXXX{vendor.aadhaar_last4}' if vendor.aadhaar_last4 else None,
            'pan_masked': f'XXXXXX{vendor.pan_last4}' if vendor.pan_last4 else None,
            'aadhaar_document_uploaded': bool(vendor.aadhaar_document),
            'pan_document_uploaded': bool(vendor.pan_document),
            'gst_certificate_uploaded': bool(vendor.gst_certificate),
        }})
    if vendor.kyc_status == VendorProfile.KYCStatus.APPROVED:
        return Response({'success': False, 'message': 'Approved KYC cannot be resubmitted without admin reset.'}, status=status.HTTP_409_CONFLICT)
    if vendor.aadhaar_status != VendorProfile.AadhaarStatus.VERIFIED:
        return Response({'success': False, 'message': 'Aadhaar verification must complete before KYC submission.'}, status=status.HTTP_409_CONFLICT)
    pan_last4 = re.sub(r'[^A-Z0-9]', '', str(request.data.get('pan_last4', '')).upper())
    if len(pan_last4) != 4:
        return Response({'success': False, 'message': 'pan_last4 must contain exactly 4 alphanumeric characters.'}, status=status.HTTP_400_BAD_REQUEST)
    aadhaar_file = request.FILES.get('aadhaar_document')
    pan_file = request.FILES.get('pan_document')
    gst_file = request.FILES.get('gst_certificate')
    if not aadhaar_file or not pan_file:
        return Response({'success': False, 'message': 'aadhaar_document and pan_document are required.'}, status=status.HTTP_400_BAD_REQUEST)
    for name, uploaded in (('aadhaar_document', aadhaar_file), ('pan_document', pan_file), ('gst_certificate', gst_file)):
        if not uploaded:
            continue
        if uploaded.size > 10 * 1024 * 1024 or uploaded.content_type not in ('application/pdf', 'image/jpeg', 'image/png'):
            return Response({'success': False, 'message': f'{name} must be PDF/JPEG/PNG and not exceed 10 MB.'}, status=status.HTTP_400_BAD_REQUEST)
    vendor.pan_last4 = pan_last4
    vendor.aadhaar_document = aadhaar_file
    vendor.pan_document = pan_file
    if gst_file:
        vendor.gst_certificate = gst_file
    vendor.kyc_status = VendorProfile.KYCStatus.UNDER_REVIEW
    vendor.kyc_rejection_reason = ''
    vendor.save()
    return Response({'success': True, 'message': 'KYC submitted for admin review.', 'status': vendor.kyc_status}, status=status.HTTP_201_CREATED)


def serialize_order(order, *, include_otp=False):
    address = order.address.formatted_address if order.address else None
    proof_images = [img.uploaded_file.url if img.uploaded_file else img.image for img in order.images.all()]
    payload = {
        'order_id': order.order_id,
        'status': order.status,
        'status_display': order.get_status_display(),
        'category': order.category.name if order.category else None,
        'subcategory': order.subcategory.name if order.subcategory else None,
        'approx_weight': float(order.approx_weight),
        'approx_price': float(order.approx_price),
        'final_agreed_price': float(order.final_agreed_price) if order.final_agreed_price is not None else None,
        'final_weight': float(order.final_weight) if order.final_weight is not None else None,
        'final_amount': float(order.final_amount) if order.final_amount is not None else None,
        'pickup_date': order.pickup_date.isoformat(),
        'time_slot': order.time_slot,
        'notes': order.notes,
        'pickup_address': address,
        'is_otp_verified': order.is_otp_verified,
        'assigned_vendor': {
            'name': order.assigned_vendor_name,
            'phone': order.assigned_vendor_phone,
        } if order.assigned_vendor_name or order.assigned_vendor_phone else None,
        'payout_status': order.payout_status,
        'created_at': order.created_at.isoformat(),
        'updated_at': order.updated_at.isoformat(),
    }
    if proof_images or order.final_weight is not None:
        payload['pickup_summary'] = {
            'final_weight': float(order.final_weight) if order.final_weight is not None else None,
            'final_amount': float(order.final_amount) if order.final_amount is not None else None,
            'proof_count': len(proof_images),
            'item_images': proof_images,
        }
        if proof_images:
            payload['item_images'] = proof_images
    if include_otp:
        payload['pickup_otp'] = order.pickup_otp
    return payload


@api_view(['GET'])
@permission_classes([AllowAny])
def categories_view(request):
    categories = ScrapCategory.objects.filter(is_active=True).prefetch_related('subcategories')
    data = []
    for category in categories:
        subcategories = category.subcategories.filter(is_active=True)
        data.append({
            'id': category.id,
            'name': category.name,
            'icon': category.icon,
            'subcategories': [
                {
                    'id': item.id,
                    'name': item.name,
                    'rate_per_kg': float(item.rate_per_kg),
                    'gst_percent': float(item.gst_percent),
                    'min_weight_kg': float(item.min_weight_kg),
                }
                for item in subcategories
            ],
        })
    return Response({'success': True, 'count': len(data), 'categories': data})


@api_view(['POST'])
@permission_classes([AllowAny])
def calculate_pricing_view(request):
    subcategory = ScrapSubCategory.objects.filter(
        id=request.data.get('subcategory_id'), is_active=True, category__is_active=True
    ).select_related('category').first()
    if not subcategory:
        return Response({'success': False, 'message': 'Active subcategory not found.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        weight = decimal_value(request.data.get('approx_weight'), 'approx_weight', positive=True)
    except ValueError as exc:
        return Response({'success': False, 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if weight < subcategory.min_weight_kg:
        return Response({
            'success': False,
            'message': f'Minimum pickup weight is {subcategory.min_weight_kg} kg.',
            'min_weight_kg': float(subcategory.min_weight_kg),
        }, status=status.HTTP_400_BAD_REQUEST)
    breakdown = subcategory.price_breakdown(weight)
    return Response({'success': True, **{key: float(value) for key, value in breakdown.items()}})


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def create_pickup_order_view(request):
    consent_response = consent_required_response(request.user)
    if consent_response:
        return consent_response
    address = UserAddress.objects.filter(id=request.data.get('address_id'), user=request.user).first()
    if not address:
        return Response({'success': False, 'message': 'Address not found or does not belong to you.'}, status=status.HTTP_404_NOT_FOUND)
    if ServiceZone.objects.filter(is_active=True).exists() and (not address.service_zone or not address.service_zone.is_active):
        return Response({'success': False, 'message': 'Pickup address is outside the configured service zones.'}, status=status.HTTP_400_BAD_REQUEST)
    subcategory = ScrapSubCategory.objects.filter(
        id=request.data.get('subcategory_id'), is_active=True, category__is_active=True
    ).select_related('category').first()
    if not subcategory:
        return Response({'success': False, 'message': 'Active subcategory not found.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        weight = decimal_value(request.data.get('approx_weight'), 'approx_weight', positive=True)
    except ValueError as exc:
        return Response({'success': False, 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if weight < subcategory.min_weight_kg:
        return Response({'success': False, 'message': f'Minimum pickup weight is {subcategory.min_weight_kg} kg.'}, status=status.HTTP_400_BAD_REQUEST)
    pickup_date = parse_date(str(request.data.get('pickup_date', '')))
    if not pickup_date:
        return Response({'success': False, 'message': 'pickup_date must use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
    if pickup_date < timezone.localdate():
        return Response({'success': False, 'message': 'pickup_date cannot be in the past.'}, status=status.HTTP_400_BAD_REQUEST)
    time_slot = str(request.data.get('time_slot', '')).strip()
    if time_slot not in ALLOWED_PICKUP_SLOTS:
        return Response({'success': False, 'message': 'time_slot is unavailable.', 'available_time_slots': sorted(ALLOWED_PICKUP_SLOTS)}, status=status.HTTP_400_BAD_REQUEST)
    breakdown = subcategory.price_breakdown(weight)
    order = PickupOrder.objects.create(
        user=request.user,
        address=address,
        category=subcategory.category,
        subcategory=subcategory,
        approx_weight=weight,
        pickup_date=pickup_date,
        time_slot=time_slot,
        notes=str(request.data.get('notes', '')).strip(),
        approx_price=breakdown['total_approx_price'],
    )
    create_notification(
        request.user, UserNotification.EventType.ORDER_CREATED,
        'Pickup request created', f'{order.order_id} is awaiting admin negotiation.', order,
    )
    return Response({
        'success': True,
        'message': 'Pickup order created and sent for negotiation.',
        'order': serialize_order(order, include_otp=True),
        'pricing': {key: float(value) for key, value in breakdown.items()},
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def confirm_order_price_view(request, order_id):
    order = order_for_user(order_id, request.user)
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    if order.status not in (PickupOrder.Status.NEGOTIATION_PENDING, PickupOrder.Status.ADMIN_NEGOTIATION):
        return Response({'success': False, 'message': 'This order is not awaiting price confirmation.'}, status=status.HTTP_409_CONFLICT)
    proposal = order.negotiation_proposals.filter(
        proposer_role=NegotiationProposal.ProposerRole.ADMIN,
        is_accepted=False,
    ).order_by('-created_at').first()
    if not proposal:
        return Response({'success': False, 'message': 'The admin has not submitted a price proposal.'}, status=status.HTTP_409_CONFLICT)
    with transaction.atomic():
        proposal.is_accepted = True
        proposal.accepted_at = timezone.now()
        proposal.save(update_fields=['is_accepted', 'accepted_at'])
        order.final_agreed_price = proposal.amount
        order.status = PickupOrder.Status.ADMIN_NEGOTIATION
        order.save(update_fields=['final_agreed_price', 'status', 'updated_at'])
    return Response({
        'success': True,
        'message': 'Price accepted. Awaiting admin publication to vendors.',
        'awaiting_admin_publication': True,
        'order': serialize_order(order),
    })


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def order_negotiations_view(request, order_id):
    order = order_for_user(order_id, request.user)
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    proposals = order.negotiation_proposals.select_related('proposed_by')
    return Response({
        'success': True,
        'order_id': order.order_id,
        'final_agreed_price': float(order.final_agreed_price) if order.final_agreed_price is not None else None,
        'proposals': [{
            'id': proposal.id,
            'proposer_role': proposal.proposer_role,
            'amount': float(proposal.amount),
            'note': proposal.note,
            'is_accepted': proposal.is_accepted,
            'created_at': proposal.created_at.isoformat(),
            'accepted_at': proposal.accepted_at.isoformat() if proposal.accepted_at else None,
        } for proposal in proposals],
    })


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def order_tracking_view(request, order_id):
    order = order_for_user(order_id, request.user)
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    tracking = getattr(order, 'vendor_tracking', None)
    proof_images = [img.uploaded_file.url if img.uploaded_file else img.image for img in order.images.all()]
    response_data = {
        'success': True,
        'order_id': order.order_id,
        'status': order.status,
        'status_display': order.get_status_display(),
        'pickup_otp': order.pickup_otp,
        'is_otp_verified': order.is_otp_verified,
        'final_weight': float(order.final_weight) if order.final_weight is not None else None,
        'final_amount': float(order.final_amount) if order.final_amount is not None else None,
        'assigned_vendor': {
            'name': order.assigned_vendor_name,
            'phone': order.assigned_vendor_phone,
        } if order.assigned_vendor_name or order.assigned_vendor_phone else None,
        'vendor_location': {
            'latitude': float(tracking.latitude),
            'longitude': float(tracking.longitude),
            'updated_at': tracking.updated_at.isoformat(),
        } if tracking else None,
        'pickup_address': order.address.formatted_address if order.address else None,
    }
    if proof_images or order.final_weight is not None:
        response_data['pickup_summary'] = {
            'final_weight': float(order.final_weight) if order.final_weight is not None else None,
            'final_amount': float(order.final_amount) if order.final_amount is not None else None,
            'proof_count': len(proof_images),
            'item_images': proof_images,
        }
        if proof_images:
            response_data['item_images'] = proof_images
    return Response(response_data)


def eligible_vendor_orders(vendor):
    zone_ids = vendor.operating_zones.values_list('id', flat=True)
    rejected_ids = vendor.offer_rejections.values_list('order_id', flat=True)
    return PickupOrder.objects.filter(
        status=PickupOrder.Status.SEARCHING_VENDOR,
        assigned_vendor__isnull=True,
        final_agreed_price__isnull=False,
        published_at__isnull=False,
        address__service_zone_id__in=zone_ids,
    ).exclude(id__in=rejected_ids).select_related('address__service_zone', 'category', 'subcategory')


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_dashboard_view(request):
    vendor = get_vendor_profile(request.user)
    if not vendor:
        return Response({'success': False, 'message': 'Vendor profile not found.'}, status=status.HTTP_404_NOT_FOUND)
    available = eligible_vendor_orders(vendor).filter(Q(acceptance_deadline__isnull=True) | Q(acceptance_deadline__gte=timezone.now())).count() if not vendor_block_reason(vendor, require_online=True) else 0
    assigned = PickupOrder.objects.filter(assigned_vendor=request.user)
    completed_statuses = [PickupOrder.Status.COMPLETED, PickupOrder.Status.USER_REVIEW, PickupOrder.Status.USER_PAYOUT]
    return Response({'success': True, 'summary': {
        'available_orders': available,
        'active_orders': assigned.exclude(status__in=completed_statuses + [PickupOrder.Status.CANCELLED]).count(),
        'completed_orders': assigned.filter(status__in=completed_statuses).count(),
        'unread_notifications': UserNotification.objects.filter(user=request.user, is_read=False).count(),
        'is_online': vendor.is_online,
        'kyc_status': vendor.kyc_status,
    }})


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_available_orders_view(request):
    vendor = get_vendor_profile(request.user)
    reason = vendor_block_reason(vendor, require_online=True)
    if reason:
        return Response({'success': False, 'message': reason}, status=status.HTTP_403_FORBIDDEN)
    orders = eligible_vendor_orders(vendor).filter(Q(acceptance_deadline__isnull=True) | Q(acceptance_deadline__gte=timezone.now()))
    try:
        page_size = min(max(int(request.GET.get('page_size', 20)), 1), 100)
    except (TypeError, ValueError):
        page_size = 20
    paginator = Paginator(orders, page_size)
    page = paginator.get_page(request.GET.get('page', 1))
    return Response({'success': True, 'count': paginator.count, 'page': page.number, 'total_pages': paginator.num_pages, 'orders': [serialize_vendor_order(order, vendor) for order in page.object_list]})


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_order_detail_view(request, order_id):
    vendor = get_vendor_profile(request.user)
    if not vendor:
        return Response({'success': False, 'message': 'Vendor profile not found.'}, status=status.HTTP_404_NOT_FOUND)
    order = PickupOrder.objects.select_related('address__service_zone', 'category', 'subcategory', 'user__profile').filter(order_id=order_id).first()
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    if order.assigned_vendor_id == request.user.id:
        return Response({'success': True, 'order': serialize_vendor_order(order, vendor, assigned=True)})
    eligible, reason = vendor_order_eligibility(order, vendor)
    if not eligible:
        return Response({'success': False, 'message': reason}, status=status.HTTP_403_FORBIDDEN)
    return Response({'success': True, 'order': serialize_vendor_order(order, vendor)})


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_reject_order_view(request, order_id):
    vendor = get_vendor_profile(request.user)
    order = PickupOrder.objects.select_related('address__service_zone').filter(order_id=order_id).first()
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    eligible, reason = vendor_order_eligibility(order, vendor)
    if not eligible:
        return Response({'success': False, 'message': reason}, status=status.HTTP_403_FORBIDDEN)
    rejection, created = VendorOfferRejection.objects.get_or_create(vendor=vendor, order=order, defaults={'reason': str(request.data.get('reason', '')).strip()})
    return Response({'success': True, 'message': 'Offer rejected for this vendor only.', 'already_rejected': not created})


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_order_history_view(request):
    vendor = get_vendor_profile(request.user)
    if not vendor:
        return Response({'success': False, 'message': 'Vendor profile not found.'}, status=status.HTTP_404_NOT_FOUND)
    orders = PickupOrder.objects.filter(assigned_vendor=request.user).select_related('address__service_zone', 'category', 'subcategory')
    status_filter = str(request.GET.get('status', '')).upper()
    if status_filter and status_filter not in dict(PickupOrder.Status.choices):
        return Response({'success': False, 'message': 'status filter is invalid.'}, status=status.HTTP_400_BAD_REQUEST)
    if status_filter:
        orders = orders.filter(status=status_filter)
    from_date, to_date = request.GET.get('from'), request.GET.get('to')
    try:
        parsed_from = parse_date(from_date) if from_date else None
    except ValueError:
        parsed_from = None
    try:
        parsed_to = parse_date(to_date) if to_date else None
    except ValueError:
        parsed_to = None
    if from_date and not parsed_from:
        return Response({'success': False, 'message': 'from must use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
    if to_date and not parsed_to:
        return Response({'success': False, 'message': 'to must use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
    if parsed_from and parsed_to and parsed_from > parsed_to:
        return Response({'success': False, 'message': 'from cannot be later than to.'}, status=status.HTTP_400_BAD_REQUEST)
    if parsed_from: orders = orders.filter(created_at__date__gte=parsed_from)
    if parsed_to: orders = orders.filter(created_at__date__lte=parsed_to)
    try: page_size = min(max(int(request.GET.get('page_size', 20)), 1), 100)
    except (TypeError, ValueError): page_size = 20
    paginator = Paginator(orders, page_size); page = paginator.get_page(request.GET.get('page', 1))
    return Response({'success': True, 'count': paginator.count, 'page': page.number, 'total_pages': paginator.num_pages, 'orders': [serialize_vendor_order(order, vendor, assigned=True) for order in page.object_list]})


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_reviews_view(request):
    vendor = get_vendor_profile(request.user)
    if not vendor:
        return Response({'success': False, 'message': 'Vendor profile not found.'}, status=status.HTTP_404_NOT_FOUND)
    reviews = OrderReview.objects.filter(order__assigned_vendor=request.user).select_related('order', 'user__profile')
    return Response({'success': True, 'count': reviews.count(), 'reviews': [{
        'order_id': review.order.order_id,
        'rating': review.rating,
        'comments': review.comments if review.is_approved_by_admin else '',
        'comment_visible': review.is_approved_by_admin,
        'created_at': review.created_at.isoformat(),
    } for review in reviews]})


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_invoice_view(request, order_id):
    order = PickupOrder.objects.filter(order_id=order_id, assigned_vendor=request.user).first()
    if not order:
        return Response({'success': False, 'message': 'Assigned order not found.'}, status=status.HTTP_404_NOT_FOUND)
    invoice = getattr(order, 'invoice', None)
    if not invoice:
        return Response({'success': False, 'message': 'Invoice has not been generated.'}, status=status.HTTP_404_NOT_FOUND)
    return Response({'success': True, 'invoice': serialize_invoice(invoice)})


def serialize_refund(refund):
    return {
        'id': refund.id,
        'order_id': refund.payment.order.order_id,
        'payment_id': refund.payment.payment_id,
        'amount': float(refund.amount),
        'status': refund.status,
        'reason': refund.reason,
        'admin_note': refund.admin_note,
        'gateway_refund_ref': refund.gateway_refund_ref,
        'requested_at': refund.requested_at.isoformat(),
        'updated_at': refund.updated_at.isoformat(),
    }


@api_view(['GET', 'POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_refunds_view(request):
    vendor = get_vendor_profile(request.user)
    if not vendor:
        return Response({'success': False, 'message': 'Vendor profile not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        refunds = RefundRequest.objects.filter(vendor=vendor).select_related('payment__order')
        return Response({'success': True, 'count': refunds.count(), 'refunds': [serialize_refund(item) for item in refunds]})
    order = PickupOrder.objects.filter(order_id=request.data.get('order_id'), assigned_vendor=request.user).first()
    if not order:
        return Response({'success': False, 'message': 'Assigned order not found.'}, status=status.HTTP_404_NOT_FOUND)
    payment = order.payment_transactions.filter(status=PaymentTransaction.Status.VERIFIED).first()
    if not payment:
        return Response({'success': False, 'message': 'No captured verified payment exists.'}, status=status.HTTP_409_CONFLICT)
    if hasattr(payment, 'refund_request'):
        return Response({'success': False, 'message': 'A refund request already exists for this payment.'}, status=status.HTTP_409_CONFLICT)
    reason = str(request.data.get('reason', '')).strip()
    if not reason:
        return Response({'success': False, 'message': 'reason is required.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        amount = decimal_value(request.data.get('amount', payment.amount), 'amount', positive=True)
    except ValueError as exc:
        return Response({'success': False, 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if amount > payment.amount:
        return Response({'success': False, 'message': 'Refund cannot exceed the captured payment amount.'}, status=status.HTTP_400_BAD_REQUEST)
    refund = RefundRequest.objects.create(payment=payment, vendor=vendor, amount=money(amount), reason=reason)
    return Response({
        'success': True,
        'message': 'Refund requested for admin review; no automatic approval or transfer occurred.',
        'refund': serialize_refund(refund),
        'policy_note': 'Eligibility window, starting event, and commission/tax treatment require an approved business policy.',
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_refund_detail_view(request, refund_id):
    vendor = get_vendor_profile(request.user)
    refund = RefundRequest.objects.select_related('payment__order').filter(id=refund_id, vendor=vendor).first()
    if not refund:
        return Response({'success': False, 'message': 'Refund request not found.'}, status=status.HTTP_404_NOT_FOUND)
    return Response({'success': True, 'refund': serialize_refund(refund)})


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_accept_order_view(request, order_id):
    vendor = get_vendor_profile(request.user)
    block_reason = vendor_block_reason(vendor, require_online=True)
    if block_reason:
        return Response({'success': False, 'message': block_reason}, status=status.HTTP_403_FORBIDDEN)
    profile = request.user.profile
    profile_phone = clean_phone(profile.phone)
    submitted_phone = clean_phone(request.data.get('vendor_phone') or profile_phone)
    if not profile_phone or submitted_phone != profile_phone:
        return Response({'success': False, 'message': 'vendor_phone must match the authenticated profile.'}, status=status.HTTP_400_BAD_REQUEST)
    vendor_name = vendor.shop_name
    vendor_phone = profile_phone
    order = PickupOrder.objects.select_related('address__service_zone').filter(order_id=order_id).first()
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    eligible, reason = vendor_order_eligibility(order, vendor)
    if not eligible:
        response_status = status.HTTP_409_CONFLICT if order.status != PickupOrder.Status.SEARCHING_VENDOR or order.assigned_vendor_id else status.HTTP_403_FORBIDDEN
        return Response({'success': False, 'message': reason}, status=response_status)
    now = timezone.now()
    with transaction.atomic():
        updated = PickupOrder.objects.filter(
            pk=order.pk,
            status=PickupOrder.Status.SEARCHING_VENDOR,
            assigned_vendor__isnull=True,
            final_agreed_price__isnull=False,
            published_at__isnull=False,
        ).filter(Q(acceptance_deadline__isnull=True) | Q(acceptance_deadline__gte=now)).update(
            assigned_vendor=request.user,
            assigned_vendor_name=vendor_name,
            assigned_vendor_phone=vendor_phone,
            status=PickupOrder.Status.VENDOR_ASSIGNED,
            arrival_deadline=now + timedelta(minutes=int(getattr(settings, 'VENDOR_ARRIVAL_MINUTES', 90))),
            updated_at=now,
        )
        if updated != 1:
            return Response({'success': False, 'message': 'Order was already accepted or is no longer available.'}, status=status.HTTP_409_CONFLICT)
        order.refresh_from_db()
        create_notification(order.user, UserNotification.EventType.VENDOR_ASSIGNED, 'Vendor assigned', f'{vendor_name} accepted {order.order_id}.', order)
        create_notification(request.user, UserNotification.EventType.VENDOR_ASSIGNED, 'Pickup assigned', f'You accepted {order.order_id}.', order)
    return Response({'success': True, 'message': 'Order assigned to vendor.', 'order': serialize_vendor_order(order, vendor, assigned=True)})


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_order_status_view(request, order_id):
    order = PickupOrder.objects.filter(order_id=order_id).first()
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    if not vendor_can_manage(order, request.user):
        return Response({'success': False, 'message': 'This order is not assigned to you.'}, status=status.HTTP_403_FORBIDDEN)
    requested = str(request.data.get('status', '')).upper().strip()
    allowed = {
        PickupOrder.Status.VENDOR_ASSIGNED: PickupOrder.Status.VENDOR_ON_THE_WAY,
        PickupOrder.Status.VENDOR_ON_THE_WAY: PickupOrder.Status.REACHED_LOCATION,
    }
    if allowed.get(order.status) != requested:
        return Response({'success': False, 'message': f'Invalid transition from {order.status} to {requested}.'}, status=status.HTTP_409_CONFLICT)
    order.status = requested
    order.save(update_fields=['status', 'updated_at'])
    create_notification(order.user, UserNotification.EventType.STATUS_UPDATED, order.get_status_display(), f'{order.order_id} moved to {order.get_status_display()}.', order)
    create_notification(request.user, UserNotification.EventType.STATUS_UPDATED, order.get_status_display(), f'You updated {order.order_id}.', order)
    return Response({'success': True, 'message': 'Order status updated.', 'order': serialize_order(order)})


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def update_vendor_location_view(request, order_id):
    order = PickupOrder.objects.filter(order_id=order_id).first()
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    if not vendor_can_manage(order, request.user):
        return Response({'success': False, 'message': 'This order is not assigned to you.'}, status=status.HTTP_403_FORBIDDEN)
    try:
        latitude = decimal_value(request.data.get('latitude'), 'latitude')
        longitude = decimal_value(request.data.get('longitude'), 'longitude')
    except ValueError as exc:
        return Response({'success': False, 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        return Response({'success': False, 'message': 'Latitude or longitude is outside the valid range.'}, status=status.HTTP_400_BAD_REQUEST)
    tracking, _ = VendorLocationTrack.objects.update_or_create(
        order=order,
        defaults={'vendor_name': order.assigned_vendor_name or request.user.username, 'latitude': latitude, 'longitude': longitude},
    )
    return Response({
        'success': True,
        'message': 'Vendor location updated.',
        'vendor_location': {'latitude': float(tracking.latitude), 'longitude': float(tracking.longitude), 'updated_at': tracking.updated_at.isoformat()},
    })


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def verify_pickup_otp_view(request, order_id):
    order = PickupOrder.objects.filter(order_id=order_id).first()
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    if not vendor_can_manage(order, request.user):
        return Response({'success': False, 'message': 'This order is not assigned to you.'}, status=status.HTTP_403_FORBIDDEN)
    if order.status not in (PickupOrder.Status.REACHED_LOCATION, PickupOrder.Status.PICKUP_IN_PROGRESS):
        return Response({'success': False, 'message': 'OTP can only be verified at the pickup location.'}, status=status.HTTP_409_CONFLICT)
    if order.is_otp_verified:
        return Response({'success': False, 'message': 'Pickup OTP has already been used.'}, status=status.HTTP_409_CONFLICT)
    if order.pickup_otp_expires_at and timezone.now() > order.pickup_otp_expires_at:
        return Response({'success': False, 'message': 'Pickup OTP has expired.'}, status=status.HTTP_400_BAD_REQUEST)
    if order.pickup_otp_attempts >= OTP_MAX_ATTEMPTS:
        return Response({'success': False, 'message': 'Pickup OTP attempt limit reached.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    if str(request.data.get('otp', '')).strip() != order.pickup_otp:
        order.pickup_otp_attempts += 1
        order.save(update_fields=['pickup_otp_attempts', 'updated_at'])
        return Response({'success': False, 'message': 'Invalid pickup OTP.', 'attempts_remaining': max(0, OTP_MAX_ATTEMPTS - order.pickup_otp_attempts)}, status=status.HTTP_400_BAD_REQUEST)
    order.is_otp_verified = True
    order.pickup_otp_verified_at = timezone.now()
    order.status = PickupOrder.Status.PICKUP_IN_PROGRESS
    order.save(update_fields=['is_otp_verified', 'pickup_otp_verified_at', 'status', 'updated_at'])
    return Response({'success': True, 'message': 'Pickup OTP verified.', 'order': serialize_order(order)})


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def vendor_billing_view(request, order_id):
    order = PickupOrder.objects.select_related('subcategory').filter(order_id=order_id).first()
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    if not vendor_can_manage(order, request.user):
        return Response({'success': False, 'message': 'This order is not assigned to you.'}, status=status.HTTP_403_FORBIDDEN)
    if not order.is_otp_verified or order.status != PickupOrder.Status.PICKUP_IN_PROGRESS:
        return Response({'success': False, 'message': 'Verify the pickup OTP before billing.'}, status=status.HTTP_409_CONFLICT)
    if not order.subcategory:
        return Response({'success': False, 'message': 'Order subcategory is unavailable.'}, status=status.HTTP_409_CONFLICT)
    try:
        final_weight = decimal_value(request.data.get('final_weight'), 'final_weight', positive=True)
    except ValueError as exc:
        return Response({'success': False, 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    billing_policy = VendorBillingSetting.current()
    if not billing_policy:
        return Response({
            'success': False,
            'message': 'No approved vendor commission/tax policy is configured. Production billing is blocked.',
            'billing_policy_required': True,
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    breakdown = order.subcategory.price_breakdown(final_weight)
    commission_basis = breakdown['base_price'] if billing_policy.commission_basis == VendorBillingSetting.CommissionBasis.ITEM_AMOUNT else breakdown['total_approx_price']
    commission_amount = money(commission_basis * billing_policy.commission_percent / Decimal('100'))
    commission_tax = money(commission_amount * billing_policy.commission_tax_percent / Decimal('100'))
    fixed_fee = money(billing_policy.fixed_platform_fee)
    total_paid = money(breakdown['total_approx_price'] + commission_amount + commission_tax + fixed_fee)
    try:
        with transaction.atomic():
            if order.payment_transactions.filter(status=PaymentTransaction.Status.VERIFIED).exists():
                return Response({'success': False, 'message': 'Payment was already verified for this order.'}, status=status.HTTP_409_CONFLICT)
            pending = order.payment_transactions.filter(status=PaymentTransaction.Status.CREATED).first()
            if pending:
                return Response({'success': False, 'message': 'A pending payment already exists.', 'payment_id': pending.payment_id}, status=status.HTTP_409_CONFLICT)
            payment = PaymentTransaction.objects.create(
                order=order,
                payment_id=f"pay_sbx_{secrets.token_hex(12)}",
                amount=total_paid,
                item_amount=breakdown['base_price'],
                gst_amount=breakdown['gst_amount'],
                commission_rate=billing_policy.commission_percent,
                commission_amount=commission_amount,
                commission_tax_amount=commission_tax,
                fixed_platform_fee=fixed_fee,
            )
            order.final_weight = final_weight
            order.final_amount = breakdown['total_approx_price']
            order.save(update_fields=['final_weight', 'final_amount', 'updated_at'])
    except IntegrityError:
        pending = order.payment_transactions.filter(status=PaymentTransaction.Status.CREATED).first()
        return Response({
            'success': False,
            'message': 'A payment already exists for this order.',
            'payment_id': pending.payment_id if pending else None,
        }, status=status.HTTP_409_CONFLICT)
    signature = payment_signature(payment)
    payload = {
        'success': True,
        'message': 'Sandbox payment created. Invoice remains unavailable until signature verification succeeds.',
        'payment': {
            'payment_id': payment.payment_id,
            'order_id': order.order_id,
            'amount': float(payment.amount),
            'currency': 'INR',
            'status': payment.status,
            'item_amount': float(payment.item_amount),
            'gst_amount': float(payment.gst_amount),
            'commission_rate': float(payment.commission_rate),
            'commission_amount': float(payment.commission_amount),
            'commission_tax_amount': float(payment.commission_tax_amount),
            'fixed_platform_fee': float(payment.fixed_platform_fee),
            'final_payable_amount': float(payment.amount),
        },
    }
    if settings.DEBUG:
        payload['sandbox_test_signature'] = signature
    return Response(payload, status=status.HTTP_201_CREATED)


def payment_signature(payment):
    secret = str(getattr(settings, 'PAYMENT_SANDBOX_SECRET', 'local-sandbox-secret')).encode()
    message = f'{payment.payment_id}|{payment.order.order_id}|{payment.amount:.2f}'.encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def webhook_signature(event_id, payment_id, event_status):
    secret = str(getattr(settings, 'PAYMENT_SANDBOX_WEBHOOK_SECRET', 'local-webhook-secret')).encode()
    return hmac.new(secret, f'{event_id}|{payment_id}|{event_status}'.encode(), hashlib.sha256).hexdigest()


def finalize_verified_payment(payment, signature):
    order = payment.order
    if payment.status == PaymentTransaction.Status.VERIFIED:
        return getattr(order, 'invoice', None)
    if not order.subcategory or order.final_weight is None:
        raise ValueError('Final weight and subcategory are required.')
    platform_fee = money(payment.commission_amount + payment.commission_tax_amount + payment.fixed_platform_fee)
    expected_amount = money(payment.item_amount + payment.gst_amount + platform_fee)
    if payment.amount != expected_amount:
        raise ValueError('Stored payment amount does not match server-calculated payable amount.')
    invoice = OrderInvoice.objects.create(
        order=order,
        subtotal=payment.item_amount,
        gst_amount=payment.gst_amount,
        platform_fee=platform_fee,
        total_paid_by_vendor=expected_amount,
        payment_gateway_ref=payment.payment_id,
        payment_status=OrderInvoice.PaymentStatus.PAID,
        paid_at=timezone.now(),
    )
    payment.status = PaymentTransaction.Status.VERIFIED
    payment.gateway_signature = signature
    payment.verified_at = timezone.now()
    payment.save(update_fields=['status', 'gateway_signature', 'verified_at'])
    order.status = PickupOrder.Status.INVOICE_GENERATED
    order.save(update_fields=['status', 'updated_at'])
    create_notification(order.user, UserNotification.EventType.PAYMENT_VERIFIED, 'Vendor payment verified', f'Invoice {invoice.invoice_number} is available.', order)
    if order.assigned_vendor_id:
        create_notification(order.assigned_vendor, UserNotification.EventType.PAYMENT_VERIFIED, 'Platform payment verified', f'Invoice {invoice.invoice_number} is available.', order)
    return invoice


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def verify_vendor_payment_view(request, order_id):
    order = PickupOrder.objects.select_related('subcategory').filter(order_id=order_id).first()
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    if not vendor_can_manage(order, request.user):
        return Response({'success': False, 'message': 'This order is not assigned to you.'}, status=status.HTTP_403_FORBIDDEN)
    payment = order.payment_transactions.filter(payment_id=request.data.get('payment_id')).first()
    if not payment:
        return Response({'success': False, 'message': 'Payment not found for this order.'}, status=status.HTTP_404_NOT_FOUND)
    if payment.status == PaymentTransaction.Status.VERIFIED:
        return Response({'success': True, 'message': 'Payment was already verified.', 'invoice': serialize_invoice(order.invoice)})
    submitted = str(request.data.get('signature', '')).strip()
    if not submitted or not hmac.compare_digest(submitted, payment_signature(payment)):
        return Response({'success': False, 'message': 'Payment signature verification failed.'}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        payment = PaymentTransaction.objects.select_for_update().select_related('order__subcategory').get(pk=payment.pk)
        invoice = finalize_verified_payment(payment, submitted)
    return Response({'success': True, 'message': 'Payment verified and invoice generated.', 'invoice': serialize_invoice(invoice)})


@api_view(['POST'])
@permission_classes([AllowAny])
def payment_webhook_view(request):
    event_id = str(request.data.get('event_id', '')).strip()
    payment_id = str(request.data.get('payment_id', '')).strip()
    event_status = str(request.data.get('status', '')).strip().upper()
    submitted = request.headers.get('X-Payment-Signature') or str(request.data.get('signature', '')).strip()
    if not event_id or not payment_id or event_status not in ('PAID', 'FAILED'):
        return Response({'success': False, 'message': 'event_id, payment_id and valid status are required.'}, status=status.HTTP_400_BAD_REQUEST)
    expected = webhook_signature(event_id, payment_id, event_status)
    if not submitted or not hmac.compare_digest(submitted, expected):
        return Response({'success': False, 'message': 'Webhook signature verification failed.'}, status=status.HTTP_400_BAD_REQUEST)
    payload_hash = hashlib.sha256(json.dumps(request.data, sort_keys=True, default=str).encode()).hexdigest()
    existing = PaymentWebhookEvent.objects.filter(event_id=event_id).first()
    if existing:
        if existing.payload_hash != payload_hash:
            return Response({'success': False, 'message': 'Event id was reused with a different payload.'}, status=status.HTTP_409_CONFLICT)
        return Response({'success': True, 'message': 'Webhook already processed.', 'idempotent_replay': True})
    payment = PaymentTransaction.objects.select_related('order__subcategory').filter(payment_id=payment_id).first()
    if not payment:
        return Response({'success': False, 'message': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)
    with transaction.atomic():
        PaymentWebhookEvent.objects.create(event_id=event_id, payment=payment, payload_hash=payload_hash)
        if event_status == 'PAID':
            invoice = finalize_verified_payment(payment, submitted)
        else:
            payment.status = PaymentTransaction.Status.FAILED
            payment.gateway_signature = submitted
            payment.save(update_fields=['status', 'gateway_signature'])
            invoice = None
    return Response({'success': True, 'message': 'Webhook processed.', 'invoice': serialize_invoice(invoice) if invoice else None})


def serialize_invoice(invoice):
    return {
        'invoice_number': invoice.invoice_number,
        'order_id': invoice.order.order_id,
        'subtotal': float(invoice.subtotal),
        'gst_amount': float(invoice.gst_amount),
        'platform_fee': float(invoice.platform_fee),
        'total_paid_by_vendor': float(invoice.total_paid_by_vendor),
        'payment_gateway_ref': invoice.payment_gateway_ref,
        'payment_status': invoice.payment_status,
        'paid_at': invoice.paid_at.isoformat() if invoice.paid_at else None,
    }


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def order_invoice_view(request, order_id):
    order = order_for_user(order_id, request.user)
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    invoice = getattr(order, 'invoice', None)
    if not invoice:
        return Response({'success': False, 'message': 'Invoice has not been generated.'}, status=status.HTTP_404_NOT_FOUND)
    return Response({'success': True, 'invoice': serialize_invoice(invoice), 'order': serialize_order(order)})


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def complete_pickup_view(request, order_id):
    order = PickupOrder.objects.filter(order_id=order_id).first()
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    if not vendor_can_manage(order, request.user):
        return Response({'success': False, 'message': 'This order is not assigned to you.'}, status=status.HTTP_403_FORBIDDEN)
    invoice = getattr(order, 'invoice', None)
    if order.status != PickupOrder.Status.INVOICE_GENERATED or not invoice or invoice.payment_status != OrderInvoice.PaymentStatus.PAID:
        return Response({'success': False, 'message': 'A paid invoice is required before completion.'}, status=status.HTTP_409_CONFLICT)
    if order.images.exists() or order.status == PickupOrder.Status.COMPLETED:
        return Response({'success': False, 'message': 'Pickup was already completed.'}, status=status.HTTP_409_CONFLICT)
    if order.final_weight is None or order.final_weight <= 0:
        return Response({'success': False, 'message': 'A positive verified final weight is required.'}, status=status.HTTP_409_CONFLICT)
    if request.data.get('final_weight') not in (None, ''):
        try:
            submitted_weight = decimal_value(request.data.get('final_weight'), 'final_weight', positive=True)
        except ValueError as exc:
            return Response({'success': False, 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if submitted_weight != order.final_weight:
            return Response({'success': False, 'message': 'final_weight must match the weight used to create the verified payment.'}, status=status.HTTP_409_CONFLICT)
    uploaded_files = request.FILES.getlist('item_images')
    for uploaded in uploaded_files:
        if not str(uploaded.content_type).startswith('image/'):
            return Response({'success': False, 'message': 'Every item_images upload must be an image.'}, status=status.HTTP_400_BAD_REQUEST)
        if uploaded.size > 8 * 1024 * 1024:
            return Response({'success': False, 'message': 'Each item image must not exceed 8 MB.'}, status=status.HTTP_400_BAD_REQUEST)
    images = request.data.getlist('item_images') if hasattr(request.data, 'getlist') else request.data.get('item_images', [])
    if isinstance(images, str):
        try:
            decoded = json.loads(images)
            images = decoded if isinstance(decoded, list) else [images]
        except (json.JSONDecodeError, TypeError):
            images = [images]
    images = [str(value).strip() for value in images if isinstance(value, str) and str(value).strip()]
    if not uploaded_files and not images:
        return Response({'success': False, 'message': 'At least one item_images file or URL is required.'}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        proofs = [PickupImage.objects.create(order=order, image=value) for value in images]
        proofs.extend(PickupImage.objects.create(order=order, image=uploaded.name, uploaded_file=uploaded) for uploaded in uploaded_files)
        order.status = PickupOrder.Status.COMPLETED
        order.save(update_fields=['status', 'updated_at'])
        create_notification(order.user, UserNotification.EventType.PICKUP_COMPLETED, 'Pickup completed', f'{order.order_id} was completed with {len(proofs)} proof image(s).', order)
        create_notification(request.user, UserNotification.EventType.PICKUP_COMPLETED, 'Pickup completed', f'{order.order_id} was completed successfully.', order)
    return Response({
        'success': True,
        'message': 'Pickup completed with photo proof.',
        'order': serialize_order(order),
        'pickup_summary': {
            'final_weight': float(order.final_weight),
            'final_amount': float(order.final_amount),
            'invoice_number': invoice.invoice_number,
            'proof_count': len(proofs),
        },
        'item_images': [proof.uploaded_file.url if proof.uploaded_file else proof.image for proof in proofs],
    })


@api_view(['GET', 'POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def create_order_review_view(request, order_id):
    order = order_for_user(order_id, request.user)
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        review = getattr(order, 'review', None)
        if not review:
            return Response({'success': False, 'message': 'Review not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'review': serialize_review(review, include_unapproved_comment=True)})
    if order.status not in (PickupOrder.Status.COMPLETED, PickupOrder.Status.USER_REVIEW, PickupOrder.Status.USER_PAYOUT):
        return Response({'success': False, 'message': 'Only completed pickups can be reviewed.'}, status=status.HTTP_409_CONFLICT)
    if hasattr(order, 'review'):
        return Response({'success': False, 'message': 'A review already exists for this order.'}, status=status.HTTP_409_CONFLICT)
    try:
        rating = int(request.data.get('rating'))
    except (TypeError, ValueError):
        rating = 0
    if rating not in range(1, 6):
        return Response({'success': False, 'message': 'rating must be an integer from 1 to 5.'}, status=status.HTTP_400_BAD_REQUEST)
    review = OrderReview.objects.create(order=order, user=request.user, rating=rating, comments=str(request.data.get('comments', '')).strip())
    if order.status == PickupOrder.Status.COMPLETED:
        order.status = PickupOrder.Status.USER_REVIEW
        order.save(update_fields=['status', 'updated_at'])
    return Response({
        'success': True,
        'message': 'Review submitted and awaiting admin approval.',
        'review': {'id': review.id, 'rating': review.rating, 'comments': review.comments, 'is_approved_by_admin': False},
    }, status=status.HTTP_201_CREATED)


def serialize_review(review, *, include_unapproved_comment=False):
    return {
        'id': review.id,
        'order_id': review.order.order_id,
        'rating': review.rating,
        'comments': review.comments if review.is_approved_by_admin or include_unapproved_comment else '',
        'comment_visible': review.is_approved_by_admin,
        'is_approved_by_admin': review.is_approved_by_admin,
        'created_at': review.created_at.isoformat(),
    }


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def user_reviews_view(request):
    reviews = OrderReview.objects.filter(user=request.user).select_related('order')
    return Response({'success': True, 'count': reviews.count(), 'reviews': [serialize_review(item, include_unapproved_comment=True) for item in reviews]})


@api_view(['GET'])
@permission_classes([AllowAny])
def public_reviews_view(request):
    reviews = OrderReview.objects.filter(is_approved_by_admin=True).select_related('order')[:50]
    return Response({'success': True, 'reviews': [serialize_review(item) for item in reviews]})


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def order_history_view(request):
    orders = PickupOrder.objects.filter(user=request.user).select_related('address', 'category', 'subcategory')
    history_type = str(request.GET.get('type', '')).lower()
    past_statuses = [PickupOrder.Status.COMPLETED, PickupOrder.Status.USER_REVIEW, PickupOrder.Status.USER_PAYOUT, PickupOrder.Status.CANCELLED]
    if history_type == 'active':
        orders = orders.exclude(status__in=past_statuses)
    elif history_type in ('past', 'completed'):
        orders = orders.filter(status__in=past_statuses)
    try:
        page_size = min(max(int(request.GET.get('page_size', 10)), 1), 100)
    except (TypeError, ValueError):
        page_size = 10
    paginator = Paginator(orders, page_size)
    page = paginator.get_page(request.GET.get('page', 1))
    return Response({
        'success': True,
        'count': paginator.count,
        'page': page.number,
        'total_pages': paginator.num_pages,
        'next': page.next_page_number() if page.has_next() else None,
        'previous': page.previous_page_number() if page.has_previous() else None,
        'orders': [serialize_order(order) for order in page.object_list],
    })


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def user_home_view(request):
    orders = PickupOrder.objects.filter(user=request.user)
    completed_statuses = [PickupOrder.Status.COMPLETED, PickupOrder.Status.USER_REVIEW, PickupOrder.Status.USER_PAYOUT]
    current = UserAddress.objects.filter(user=request.user, is_default=True).first()
    if not current:
        current = UserAddress.objects.filter(user=request.user).first()
    return Response({
        'success': True,
        'current_address': current.to_dict() if current else None,
        'active_orders': [serialize_order(item) for item in orders.exclude(status__in=completed_statuses + [PickupOrder.Status.CANCELLED])[:10]],
        'completed_orders': [serialize_order(item) for item in orders.filter(status__in=completed_statuses)[:10]],
        'unread_notifications': UserNotification.objects.filter(user=request.user, is_read=False).count(),
    })


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def notifications_view(request):
    notifications = UserNotification.objects.filter(user=request.user).select_related('order')
    return Response({
        'success': True,
        'unread_count': notifications.filter(is_read=False).count(),
        'notifications': [{
            'id': item.id,
            'event_type': item.event_type,
            'title': item.title,
            'message': item.message,
            'order_id': item.order.order_id if item.order else None,
            'is_read': item.is_read,
            'created_at': item.created_at.isoformat(),
        } for item in notifications],
    })


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def mark_notification_read_view(request, notification_id):
    notification = UserNotification.objects.filter(id=notification_id, user=request.user).first()
    if not notification:
        return Response({'success': False, 'message': 'Notification not found.'}, status=status.HTTP_404_NOT_FOUND)
    notification.is_read = True
    notification.save(update_fields=['is_read'])
    return Response({'success': True, 'message': 'Notification marked as read.'})


@api_view(['POST'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def mark_all_notifications_read_view(request):
    updated = UserNotification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({'success': True, 'updated': updated})


@api_view(['GET'])
@permission_classes([AllowAny])
def support_config_view(request):
    return Response({
        'success': True,
        'support': {
            'phone': getattr(settings, 'SUPPORT_PHONE', '+91 80000 00000'),
            'email': getattr(settings, 'SUPPORT_EMAIL', 'support@bazaarpe.local'),
            'whatsapp': getattr(settings, 'SUPPORT_WHATSAPP', '+91 80000 00000'),
            'hours': getattr(settings, 'SUPPORT_HOURS', '09:00 AM - 06:00 PM IST'),
        },
    })


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def authorized_order_tracking_view(request, order_id):
    order = PickupOrder.objects.select_related('address').filter(order_id=order_id).first()
    if not order:
        return Response({'success': False, 'message': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.user != order.user and not vendor_can_manage(order, request.user) and not request.user.is_staff:
        return Response({'success': False, 'message': 'You are not authorized to track this order.'}, status=status.HTTP_403_FORBIDDEN)
    tracking = getattr(order, 'vendor_tracking', None)
    return Response({
        'success': True,
        'order': serialize_order(order, include_otp=request.user == order.user or request.user.is_staff),
        'vendor_location': {
            'latitude': float(tracking.latitude), 'longitude': float(tracking.longitude),
            'updated_at': tracking.updated_at.isoformat(),
        } if tracking else None,
    })


def serialize_bank_detail(bank):
    return {
        'account_holder_name': bank.account_holder_name,
        'bank_name': bank.bank_name,
        'account_number': bank.masked_account_number,
        'ifsc_code': bank.ifsc_code,
        'upi_id': bank.upi_id,
        'is_verified': bank.is_verified,
        'updated_at': bank.updated_at.isoformat(),
    }


@api_view(['GET', 'POST', 'PUT'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def user_bank_details_view(request):
    bank = UserBankDetail.objects.filter(user=request.user).first()
    if request.method == 'GET':
        if not bank:
            return Response({'success': False, 'message': 'Bank details have not been added.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'bank_details': serialize_bank_detail(bank)})
    required = ('account_holder_name', 'bank_name', 'account_number', 'ifsc_code')
    missing = [field for field in required if not str(request.data.get(field, '')).strip()]
    if missing:
        return Response({'success': False, 'message': f"Missing required fields: {', '.join(missing)}."}, status=status.HTTP_400_BAD_REQUEST)
    account_number = re.sub(r'\s+', '', str(request.data['account_number']))
    if not account_number.isdigit() or not 6 <= len(account_number) <= 50:
        return Response({'success': False, 'message': 'account_number must contain 6 to 50 digits.'}, status=status.HTTP_400_BAD_REQUEST)
    ifsc = str(request.data['ifsc_code']).strip().upper()
    if not re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}', ifsc):
        return Response({'success': False, 'message': 'ifsc_code is invalid.'}, status=status.HTTP_400_BAD_REQUEST)
    bank, created = UserBankDetail.objects.update_or_create(
        user=request.user,
        defaults={
            'account_holder_name': str(request.data['account_holder_name']).strip(),
            'bank_name': str(request.data['bank_name']).strip(),
            'account_number': account_number,
            'ifsc_code': ifsc,
            'upi_id': str(request.data.get('upi_id', '')).strip() or None,
            'is_verified': True,
        },
    )
    return Response({
        'success': True,
        'message': 'Bank details saved successfully.',
        'bank_details': serialize_bank_detail(bank),
    }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
