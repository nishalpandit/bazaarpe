import random
import math
from datetime import timedelta
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class ServiceCity(models.Model):
    name = models.CharField(max_length=100, unique=True, help_text="City name e.g. Bengaluru, Mumbai")
    state = models.CharField(max_length=100, default='Karnataka', help_text="State name")
    is_active = models.BooleanField(default=True, help_text="Whether delivery/pickup service is live")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Service City'
        verbose_name_plural = 'Service Cities'

    def __str__(self):
        return f"{self.name}, {self.state}"

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'state': self.state,
            'is_active': self.is_active,
            'zones_count': self.zones.filter(is_active=True).count(),
        }


class ServiceZone(models.Model):
    city = models.ForeignKey(ServiceCity, on_delete=models.CASCADE, related_name='zones')
    name = models.CharField(max_length=150, help_text="Zone name e.g. Zone 1 – Indiranagar")
    code = models.CharField(max_length=50, blank=True, null=True, help_text="Zone code e.g. ZN-BLR-01")
    pincodes = models.TextField(blank=True, default='', help_text="Comma-separated pincodes covered")
    center_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, help_text="Latitude for map center / distance matching")
    center_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, help_text="Longitude for map center / distance matching")
    radius_km = models.DecimalField(max_digits=6, decimal_places=2, default=8.00, help_text="Service radius in km")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['city__name', 'name']
        verbose_name = 'Service Zone'
        verbose_name_plural = 'Service Zones'

    def __str__(self):
        return f"{self.name} ({self.city.name})"

    @property
    def pincode_list(self):
        if not self.pincodes:
            return []
        raw = self.pincodes.replace('\n', ',').replace(';', ',')
        return [p.strip() for p in raw.split(',') if p.strip()]

    def distance_to(self, lat, lon):
        """Calculates distance in kilometers from GPS point to zone center."""
        if self.center_latitude is None or self.center_longitude is None:
            return None
        try:
            lat1 = math.radians(float(lat))
            lon1 = math.radians(float(lon))
            lat2 = math.radians(float(self.center_latitude))
            lon2 = math.radians(float(self.center_longitude))
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return round(6371.0 * c, 2)
        except Exception:
            return None

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code or f"ZN-{self.id:02d}",
            'city': self.city.name,
            'city_id': self.city_id,
            'state': self.city.state,
            'pincodes': self.pincode_list,
            'center_latitude': float(self.center_latitude) if self.center_latitude is not None else None,
            'center_longitude': float(self.center_longitude) if self.center_longitude is not None else None,
            'radius_km': float(self.radius_km),
            'is_active': self.is_active,
        }


class UserProfile(models.Model):
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Blocked', 'Blocked'),
        ('Suspended', 'Suspended'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField(max_length=150, help_text="Full Name of the customer")
    phone = models.CharField(max_length=15, unique=True, db_index=True, help_text="10-digit mobile number")
    email = models.EmailField(blank=True, null=True, help_text="Email address")
    address = models.TextField(blank=True, null=True, help_text="Primary pickup address")
    pincode = models.CharField(max_length=10, blank=True, null=True, help_text="Postal Pincode (6 digits)")
    city = models.CharField(max_length=100, blank=True, null=True, default="Bengaluru")
    
    # Location coordinates & zone
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    service_zone = models.ForeignKey(ServiceZone, on_delete=models.SET_NULL, null=True, blank=True, related_name='user_profiles')

    account_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    
    # Financial and marketplace summary fields
    orders_count = models.PositiveIntegerField(default=0)
    settlement_due = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    settlement_status = models.CharField(max_length=30, default='Not due')
    bank_name = models.CharField(max_length=100, blank=True, default='HDFC Bank')
    account_number_masked = models.CharField(max_length=50, blank=True, default='XXXXXXXX4471')
    ifsc_code = models.CharField(max_length=20, blank=True, default='HDFC0001234')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f"{self.full_name} ({self.phone})"

    @property
    def display_user_id(self):
        return f"USR-{1000 + self.id}"

    @property
    def masked_phone(self):
        clean = ''.join(c for c in str(self.phone) if c.isdigit())
        if len(clean) >= 10:
            last4 = clean[-4:]
            first2 = clean[:2]
            return f"+91 {first2}•••• {last4}"
        return self.phone

    @property
    def initials(self):
        parts = self.full_name.strip().split()
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}".upper()
        elif parts and parts[0]:
            return parts[0][:2].upper()
        return "BP"

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.display_user_id,
            'full_name': self.full_name,
            'mobile_number': self.phone,
            'phone': self.phone,
            'email': self.email or '',
            'address': self.address or '',
            'pincode': self.pincode or '',
            'city': self.city or '',
            'latitude': float(self.latitude) if self.latitude is not None else None,
            'longitude': float(self.longitude) if self.longitude is not None else None,
            'service_zone': self.service_zone.name if self.service_zone else None,
            'service_zone_id': self.service_zone_id if self.service_zone else None,
            'account_status': self.account_status,
            'is_active': self.account_status == 'Active',
            'orders_count': self.orders_count,
            'settlement_due': float(self.settlement_due),
            'settlement_status': self.settlement_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class UserAddress(models.Model):
    ADDRESS_TYPES = [
        ('Home', 'Home'),
        ('Work', 'Work'),
        ('Other', 'Other'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='saved_addresses')
    address_type = models.CharField(max_length=20, choices=ADDRESS_TYPES, default='Home')
    
    # Granular address lines for user editing
    house_no = models.CharField(max_length=150, blank=True, default='', help_text="Flat, House, Building name")
    street_address = models.CharField(max_length=255, blank=True, default='', help_text="Street, Road, Colony / Area")
    landmark = models.CharField(max_length=150, blank=True, default='', help_text="Nearby landmark")
    formatted_address = models.TextField(help_text="Full formatted address string")
    
    city = models.CharField(max_length=100, default='Bengaluru')
    state = models.CharField(max_length=100, default='Karnataka')
    pincode = models.CharField(max_length=10)
    
    service_zone = models.ForeignKey(ServiceZone, on_delete=models.SET_NULL, null=True, blank=True, related_name='user_addresses')
    zone_name = models.CharField(max_length=150, blank=True, default='')

    # GPS coordinates (fetched via GPS / Maps)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', '-created_at']
        verbose_name = 'User Address'
        verbose_name_plural = 'User Addresses'

    def __str__(self):
        return f"{self.user.username} - {self.address_type}: {self.formatted_address[:30]}"

    def to_dict(self):
        return {
            'id': self.id,
            'address_type': self.address_type,
            'house_no': self.house_no,
            'street_address': self.street_address,
            'landmark': self.landmark,
            'formatted_address': self.formatted_address,
            'city': self.city,
            'state': self.state,
            'pincode': self.pincode,
            'service_zone': self.service_zone.name if self.service_zone else (self.zone_name or None),
            'service_zone_id': self.service_zone_id if self.service_zone else None,
            'latitude': float(self.latitude) if self.latitude is not None else None,
            'longitude': float(self.longitude) if self.longitude is not None else None,
            'is_default': self.is_default,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class OTPVerification(models.Model):
    PURPOSE_CHOICES = [
        ('LOGIN', 'Login'),
        ('REGISTER', 'Registration'),
        ('AUTH', 'Authentication'),
    ]

    phone = models.CharField(max_length=15, db_index=True)
    otp = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default='AUTH')
    is_verified = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.phone} - OTP {self.otp} ({self.purpose})"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @classmethod
    def generate_otp_for_phone(cls, phone, purpose='AUTH', validity_minutes=10):
        otp_code = f"{random.randint(100000, 999999)}"
        cls.objects.filter(phone=phone, is_verified=False).delete()
        record = cls.objects.create(
            phone=phone,
            otp=otp_code,
            purpose=purpose,
            is_verified=False,
            expires_at=timezone.now() + timedelta(minutes=validity_minutes)
        )
        return record
