


import re
import json
import math
import urllib.request
import urllib.parse
from decimal import Decimal
from datetime import timedelta

from django.db.models import Q
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from .models import UserProfile, OTPVerification, ServiceCity, ServiceZone, UserAddress
from .authentication import BearerTokenAuthentication

COOKIE_MAX_AGE = 315360000  # 10 years (non-expiring token cookie)


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

    # Check if user already exists
    profile = UserProfile.objects.filter(phone=phone).first()

    if profile:
        if profile.account_status in ('Blocked', 'Suspended'):
            return Response({
                'success': False,
                'message': 'Your account has been deactivated by administrator. Please contact support.'
            }, status=status.HTTP_403_FORBIDDEN)

        otp_rec = OTPVerification.generate_otp_for_phone(phone, purpose='LOGIN')
        return Response({
            'success': True,
            'message': f"OTP sent for login to {phone}",
            'mobile_number': phone,
            'phone': phone,
            'is_registered': True,
            'action': 'LOGIN',
            'otp_debug': otp_rec.otp
        }, status=status.HTTP_200_OK)
    else:
        otp_rec = OTPVerification.generate_otp_for_phone(phone, purpose='REGISTER')
        return Response({
            'success': True,
            'message': f"Mobile number not registered. OTP sent for registration to {phone}",
            'mobile_number': phone,
            'phone': phone,
            'is_registered': False,
            'action': 'REGISTER',
            'otp_debug': otp_rec.otp
        }, status=status.HTTP_200_OK)


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
    otp_rec = OTPVerification.objects.filter(phone=phone, is_verified=False).order_by('-created_at').first()

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

    if otp_rec.otp != otp_code:
        otp_rec.attempts += 1
        otp_rec.save(update_fields=['attempts'])
        return Response({
            'success': False,
            'message': 'Invalid OTP. Please check the code and try again.'
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
    otp_rec = OTPVerification.objects.filter(phone=phone, is_verified=False).order_by('-created_at').first()

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

    if otp_rec.otp != otp_code:
        otp_rec.attempts += 1
        otp_rec.save(update_fields=['attempts'])
        return Response({
            'success': False,
            'message': 'Invalid OTP code. Please check and try again.'
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
        account_status='Active'
    )

    # Mark OTP as verified
    otp_rec.is_verified = True
    otp_rec.save(update_fields=['is_verified'])

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
    if 'full_name' in data and data['full_name'].strip():
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

    if not pincode:
        return Response({
            'success': False,
            'message': 'Pincode is required to confirm address.'
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
            pass

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

    # Check is_default status
    is_default = bool(data.get('is_default', False))
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
        address_obj.pincode = str(data['pincode']).strip()
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

