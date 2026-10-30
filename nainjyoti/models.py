import random
import math
import secrets
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


MONEY_PLACES = Decimal('0.01')


def money(value):
    """Return a Decimal rounded to currency precision."""
    return Decimal(str(value)).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def generated_reference(prefix):
    """Create a compact, human-readable reference without relying on row ids."""
    return f"{prefix}-{timezone.now().year}-{secrets.randbelow(900000) + 100000}"


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
    profile_photo = models.FileField(upload_to='profile_photos/%Y/%m/', blank=True, null=True)
    onboarding_step = models.PositiveSmallIntegerField(default=1)
    onboarding_completed = models.BooleanField(default=False)
    is_vendor = models.BooleanField(default=False, db_index=True)

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
            'profile_photo': self.profile_photo.url if self.profile_photo else None,
            'onboarding_step': self.onboarding_step,
            'onboarding_completed': self.onboarding_completed,
            'is_vendor': self.is_vendor,
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
        ('CHANGE_PHONE', 'Change Phone'),
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


class LegalDocument(models.Model):
    class DocumentType(models.TextChoices):
        PRIVACY = 'PRIVACY', 'Privacy Policy'
        TERMS = 'TERMS', 'Terms and Conditions'
        FAQ = 'FAQ', 'Frequently Asked Questions'
        STATIC = 'STATIC', 'Static Page'

    document_type = models.CharField(max_length=20, choices=DocumentType.choices)
    version = models.CharField(max_length=30)
    title = models.CharField(max_length=150)
    content = models.TextField()
    is_active = models.BooleanField(default=True)
    published_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['document_type', '-published_at']
        constraints = [models.UniqueConstraint(fields=['document_type', 'version'], name='unique_legal_document_version')]


class UserConsent(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='consents')
    document = models.ForeignKey(LegalDocument, on_delete=models.PROTECT, related_name='acceptances')
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'document'], name='unique_user_document_consent')]


class ScrapCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    icon = models.CharField(max_length=500, blank=True, default='')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Scrap categories'

    def __str__(self):
        return self.name


class ScrapSubCategory(models.Model):
    category = models.ForeignKey(ScrapCategory, on_delete=models.CASCADE, related_name='subcategories')
    name = models.CharField(max_length=150)
    rate_per_kg = models.DecimalField(max_digits=10, decimal_places=2)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=18.00)
    min_weight_kg = models.DecimalField(max_digits=6, decimal_places=2, default=5.00)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['category__name', 'name']
        constraints = [
            models.UniqueConstraint(fields=['category', 'name'], name='unique_scrap_subcategory_name'),
            models.CheckConstraint(condition=models.Q(rate_per_kg__gte=0), name='subcategory_rate_non_negative'),
            models.CheckConstraint(condition=models.Q(gst_percent__gte=0), name='subcategory_gst_non_negative'),
            models.CheckConstraint(condition=models.Q(min_weight_kg__gt=0), name='subcategory_min_weight_positive'),
        ]

    def __str__(self):
        return f"{self.category.name} - {self.name}"

    def price_breakdown(self, weight):
        weight = Decimal(str(weight))
        base_price = money(weight * self.rate_per_kg)
        gst_amount = money(base_price * self.gst_percent / Decimal('100'))
        return {
            'rate_per_kg': money(self.rate_per_kg),
            'base_price': base_price,
            'gst_percent': money(self.gst_percent),
            'gst_amount': gst_amount,
            'total_approx_price': money(base_price + gst_amount),
        }


class PickupOrder(models.Model):
    class Status(models.TextChoices):
        NEGOTIATION_PENDING = 'NEGOTIATION_PENDING', 'Negotiation Pending'
        ADMIN_NEGOTIATION = 'ADMIN_NEGOTIATION', 'Admin Negotiation'
        SEARCHING_VENDOR = 'SEARCHING_VENDOR', 'Searching for Vendor'
        VENDOR_ASSIGNED = 'VENDOR_ASSIGNED', 'Vendor Assigned'
        VENDOR_ON_THE_WAY = 'VENDOR_ON_THE_WAY', 'Vendor On The Way'
        REACHED_LOCATION = 'REACHED_LOCATION', 'Vendor Reached Location'
        PICKUP_IN_PROGRESS = 'PICKUP_IN_PROGRESS', 'Pickup In Progress'
        OTP_VERIFIED = 'OTP_VERIFIED', 'OTP Verified'
        PAYMENT_COMPLETED = 'PAYMENT_COMPLETED', 'Payment Completed'
        INVOICE_GENERATED = 'INVOICE_GENERATED', 'Invoice Generated'
        COMPLETED = 'COMPLETED', 'Completed'
        USER_REVIEW = 'USER_REVIEW', 'User Review Submitted'
        USER_PAYOUT = 'USER_PAYOUT', 'User Payout Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PayoutStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        DISBURSED = 'DISBURSED', 'Disbursed'

    order_id = models.CharField(max_length=20, unique=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='pickup_orders')
    address = models.ForeignKey(UserAddress, on_delete=models.SET_NULL, null=True, related_name='pickup_orders')
    category = models.ForeignKey(ScrapCategory, on_delete=models.SET_NULL, null=True, related_name='pickup_orders')
    subcategory = models.ForeignKey(ScrapSubCategory, on_delete=models.SET_NULL, null=True, related_name='pickup_orders')
    approx_weight = models.DecimalField(max_digits=8, decimal_places=2)
    pickup_date = models.DateField()
    time_slot = models.CharField(max_length=50)
    notes = models.TextField(blank=True, default='')
    approx_price = models.DecimalField(max_digits=10, decimal_places=2)
    final_agreed_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    final_weight = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    final_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.NEGOTIATION_PENDING, db_index=True)
    pickup_otp = models.CharField(max_length=6)
    is_otp_verified = models.BooleanField(default=False)
    assigned_vendor_name = models.CharField(max_length=150, blank=True, null=True)
    assigned_vendor_phone = models.CharField(max_length=15, blank=True, null=True)
    assigned_vendor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_pickup_orders')
    pickup_otp_expires_at = models.DateTimeField(null=True, blank=True)
    pickup_otp_attempts = models.PositiveSmallIntegerField(default=0)
    pickup_otp_verified_at = models.DateTimeField(null=True, blank=True)
    proof_submitted_at = models.DateTimeField(null=True, blank=True)
    payout_status = models.CharField(max_length=20, choices=PayoutStatus.choices, default=PayoutStatus.PENDING)
    payout_reference = models.CharField(max_length=100, blank=True, default='')
    payout_method = models.CharField(max_length=30, blank=True, default='')
    payout_disbursed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    acceptance_deadline = models.DateTimeField(null=True, blank=True, db_index=True)
    arrival_deadline = models.DateTimeField(null=True, blank=True)
    is_escalated = models.BooleanField(default=False, db_index=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(approx_weight__gt=0), name='pickup_approx_weight_positive'),
            models.CheckConstraint(condition=models.Q(approx_price__gte=0), name='pickup_approx_price_non_negative'),
        ]

    def __str__(self):
        return self.order_id

    def save(self, *args, **kwargs):
        if not self.order_id:
            for _ in range(20):
                candidate = generated_reference('ORD')
                if not type(self).objects.filter(order_id=candidate).exists():
                    self.order_id = candidate
                    break
            else:
                raise RuntimeError('Unable to allocate a unique order number.')
        if not self.pickup_otp:
            self.pickup_otp = f"{secrets.randbelow(900000) + 100000}"
        if not self.pickup_otp_expires_at:
            self.pickup_otp_expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    @property
    def payout_amount(self):
        return self.final_agreed_price or self.final_amount or self.approx_price


class PickupImage(models.Model):
    order = models.ForeignKey(PickupOrder, on_delete=models.CASCADE, related_name='images')
    image = models.CharField(max_length=500)
    uploaded_file = models.FileField(upload_to='pickup_proofs/%Y/%m/', blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']


class VendorLocationTrack(models.Model):
    order = models.OneToOneField(PickupOrder, on_delete=models.CASCADE, related_name='vendor_tracking')
    vendor_name = models.CharField(max_length=150)
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    updated_at = models.DateTimeField(auto_now=True)


class OrderInvoice(models.Model):
    class PaymentStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PAID = 'PAID', 'Paid'

    invoice_number = models.CharField(max_length=50, unique=True, editable=False)
    order = models.OneToOneField(PickupOrder, on_delete=models.PROTECT, related_name='invoice')
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2)
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2, default=50.00)
    total_paid_by_vendor = models.DecimalField(max_digits=10, decimal_places=2)
    payment_gateway_ref = models.CharField(max_length=100, blank=True)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.invoice_number

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            for _ in range(20):
                candidate = generated_reference('INV')
                if not type(self).objects.filter(invoice_number=candidate).exists():
                    self.invoice_number = candidate
                    break
            else:
                raise RuntimeError('Unable to allocate a unique invoice number.')
        super().save(*args, **kwargs)


class OrderReview(models.Model):
    order = models.OneToOneField(PickupOrder, on_delete=models.CASCADE, related_name='review')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews_given')
    rating = models.PositiveSmallIntegerField()
    comments = models.TextField(blank=True, default='')
    is_approved_by_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name='review_rating_between_1_and_5'),
        ]


class UserBankDetail(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='bank_details')
    account_holder_name = models.CharField(max_length=150)
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50)
    ifsc_code = models.CharField(max_length=20)
    upi_id = models.CharField(max_length=50, blank=True, null=True)
    is_verified = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.bank_name}"

    @property
    def masked_account_number(self):
        value = self.account_number or ''
        return f"{'X' * max(0, len(value) - 4)}{value[-4:]}" if value else ''


class NegotiationProposal(models.Model):
    class ProposerRole(models.TextChoices):
        USER = 'USER', 'User'
        ADMIN = 'ADMIN', 'Admin'

    order = models.ForeignKey(PickupOrder, on_delete=models.CASCADE, related_name='negotiation_proposals')
    proposed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='pickup_proposals')
    proposer_role = models.CharField(max_length=10, choices=ProposerRole.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.TextField(blank=True, default='')
    is_accepted = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='proposal_amount_positive')]


class UserNotification(models.Model):
    class EventType(models.TextChoices):
        ORDER_CREATED = 'ORDER_CREATED', 'Order Created'
        PRICE_PROPOSED = 'PRICE_PROPOSED', 'Price Proposed'
        ORDER_PUBLISHED = 'ORDER_PUBLISHED', 'Order Published'
        VENDOR_ASSIGNED = 'VENDOR_ASSIGNED', 'Vendor Assigned'
        STATUS_UPDATED = 'STATUS_UPDATED', 'Status Updated'
        PAYMENT_VERIFIED = 'PAYMENT_VERIFIED', 'Payment Verified'
        PICKUP_COMPLETED = 'PICKUP_COMPLETED', 'Pickup Completed'
        REVIEW_MODERATED = 'REVIEW_MODERATED', 'Review Moderated'
        PAYOUT_DISBURSED = 'PAYOUT_DISBURSED', 'Payout Disbursed'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    order = models.ForeignKey(PickupOrder, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    title = models.CharField(max_length=150)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class PaymentTransaction(models.Model):
    class Status(models.TextChoices):
        CREATED = 'CREATED', 'Created'
        VERIFIED = 'VERIFIED', 'Verified'
        FAILED = 'FAILED', 'Failed'

    order = models.ForeignKey(PickupOrder, on_delete=models.PROTECT, related_name='payment_transactions')
    payment_id = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    item_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission_tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fixed_platform_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    gateway_signature = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['order'], condition=models.Q(status='CREATED'),
                name='one_created_payment_per_order',
            ),
            models.UniqueConstraint(
                fields=['order'], condition=models.Q(status='VERIFIED'),
                name='one_verified_payment_per_order',
            ),
        ]


class PaymentWebhookEvent(models.Model):
    event_id = models.CharField(max_length=120, unique=True)
    payment = models.ForeignKey(PaymentTransaction, on_delete=models.PROTECT, related_name='webhook_events')
    payload_hash = models.CharField(max_length=64)
    processed_at = models.DateTimeField(auto_now_add=True)


class VendorProfile(models.Model):
    class KYCStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        UNDER_REVIEW = 'UNDER_REVIEW', 'Under Review'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        SUSPENDED = 'SUSPENDED', 'Suspended'

    class AadhaarStatus(models.TextChoices):
        NOT_STARTED = 'NOT_STARTED', 'Not Started'
        PENDING = 'PENDING', 'Pending'
        VERIFIED = 'VERIFIED', 'Verified'
        FAILED = 'FAILED', 'Failed'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vendor_profile')
    shop_name = models.CharField(max_length=180)
    owner_name = models.CharField(max_length=150)
    profile_picture = models.FileField(upload_to='vendor_profiles/%Y/%m/', blank=True, null=True)
    full_address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=6)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    operating_zones = models.ManyToManyField(ServiceZone, related_name='vendors', blank=True)
    categories = models.ManyToManyField(ScrapCategory, related_name='vendors', blank=True)
    subcategories = models.ManyToManyField(ScrapSubCategory, related_name='vendors', blank=True)
    is_online = models.BooleanField(default=False, db_index=True)
    kyc_status = models.CharField(max_length=20, choices=KYCStatus.choices, default=KYCStatus.DRAFT, db_index=True)
    kyc_rejection_reason = models.TextField(blank=True, default='')
    aadhaar_document = models.FileField(upload_to='vendor_kyc/aadhaar/%Y/%m/', blank=True, null=True)
    pan_document = models.FileField(upload_to='vendor_kyc/pan/%Y/%m/', blank=True, null=True)
    gst_certificate = models.FileField(upload_to='vendor_kyc/gst/%Y/%m/', blank=True, null=True)
    aadhaar_number = models.CharField(max_length=20, blank=True, default='')
    pan_number = models.CharField(max_length=20, blank=True, default='')
    gst_number = models.CharField(max_length=30, blank=True, default='')
    aadhaar_last4 = models.CharField(max_length=4, blank=True, default='')
    pan_last4 = models.CharField(max_length=4, blank=True, default='')
    aadhaar_status = models.CharField(max_length=20, choices=AadhaarStatus.choices, default=AadhaarStatus.NOT_STARTED)
    aadhaar_provider_reference = models.CharField(max_length=100, blank=True, default='')
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def display_vendor_id(self):
        return f"VND-{1000 + self.id}"

    class Meta:
        ordering = ['shop_name']

    def __str__(self):
        return self.shop_name


class VendorOfferRejection(models.Model):
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='offer_rejections')
    order = models.ForeignKey(PickupOrder, on_delete=models.CASCADE, related_name='vendor_rejections')
    reason = models.CharField(max_length=250, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['vendor', 'order'], name='unique_vendor_order_rejection')]


class VendorBillingSetting(models.Model):
    class CommissionBasis(models.TextChoices):
        ITEM_AMOUNT = 'ITEM_AMOUNT', 'Item Amount Before GST'
        GST_INCLUSIVE = 'GST_INCLUSIVE', 'GST Inclusive Item Amount'

    commission_percent = models.DecimalField(max_digits=5, decimal_places=2)
    commission_tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    fixed_platform_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission_basis = models.CharField(max_length=20, choices=CommissionBasis.choices, default=CommissionBasis.ITEM_AMOUNT)
    is_approved = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True, default='')
    effective_from = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from', '-id']
        constraints = [
            models.CheckConstraint(condition=models.Q(commission_percent__gte=0, commission_percent__lte=100), name='vendor_commission_rate_range'),
            models.CheckConstraint(condition=models.Q(commission_tax_percent__gte=0, commission_tax_percent__lte=100), name='vendor_commission_tax_range'),
            models.CheckConstraint(condition=models.Q(fixed_platform_fee__gte=0), name='vendor_fixed_fee_nonnegative'),
        ]

    @classmethod
    def current(cls):
        return cls.objects.filter(is_active=True, is_approved=True, effective_from__lte=timezone.now()).first()


class PlatformConfiguration(models.Model):
    """Persisted operational deadlines used by both admin and API workflows."""

    acceptance_minutes = models.PositiveIntegerField(default=30)
    arrival_minutes = models.PositiveIntegerField(default=90)
    settlement_days = models.PositiveIntegerField(default=2)
    refund_hours = models.PositiveIntegerField(default=24)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Platform Configuration'
        verbose_name_plural = 'Platform Configuration'

    @classmethod
    def current(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class MarketplaceAuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='marketplace_audit_events')
    actor_role = models.CharField(max_length=20)
    action = models.CharField(max_length=80, db_index=True)
    entity_type = models.CharField(max_length=40)
    entity_id = models.CharField(max_length=80)
    order = models.ForeignKey(PickupOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_events')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']


class RefundRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'REQUESTED', 'Requested'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        PROCESSING = 'PROCESSING', 'Processing'
        SUCCEEDED = 'SUCCEEDED', 'Succeeded'
        FAILED = 'FAILED', 'Failed'

    payment = models.OneToOneField(PaymentTransaction, on_delete=models.PROTECT, related_name='refund_request')
    vendor = models.ForeignKey(VendorProfile, on_delete=models.PROTECT, related_name='refund_requests')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    admin_note = models.TextField(blank=True, default='')
    gateway_refund_ref = models.CharField(max_length=120, blank=True, default='')
    requested_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-requested_at']
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='refund_amount_positive')]
