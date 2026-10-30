from datetime import timedelta
import tempfile

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .views import PAGES, ensure_demo_user
from .api_views import payment_signature, webhook_signature
from .models import (
    UserProfile, UserAddress, ScrapCategory, ScrapSubCategory, PickupOrder,
    OrderInvoice, OrderReview, PickupImage, UserBankDetail,
    LegalDocument, UserConsent, PaymentTransaction, UserNotification,
    OTPVerification, ServiceCity, ServiceZone, VendorProfile,
    VendorBillingSetting, VendorOfferRejection, RefundRequest,
    NegotiationProposal, PlatformConfiguration, MarketplaceAuditLog,
)


class FullAdminAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='root-admin',
            email='root@example.com',
            password='AdminPass123!',
        )
        self.regular_user = User.objects.create_user(
            username='member',
            email='member@example.com',
            password='MemberPass123!',
        )

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse('index_html'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('index_html')}",
            fetch_redirect_response=False,
        )

    def test_non_admin_is_denied_every_admin_page(self):
        self.client.force_login(self.regular_user)

        self.assertEqual(self.client.get(reverse('index_html')).status_code, 403)
        for page_name in PAGES:
            with self.subTest(page_name=page_name):
                response = self.client.get(f'/{page_name}.html')
                self.assertEqual(response.status_code, 403)

    def test_superuser_can_open_every_admin_page(self):
        self.client.force_login(self.admin)

        for page_name in PAGES:
            with self.subTest(page_name=page_name):
                response = self.client.get(f'/{page_name}.html')
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['admin_capabilities']['can_manage'])
                self.assertTrue(response.context['admin_capabilities']['can_create'])
                self.assertTrue(response.context['admin_capabilities']['can_edit'])
                self.assertTrue(response.context['admin_capabilities']['can_delete'])

    def test_superuser_has_django_create_edit_delete_permissions(self):
        permissions = (
            'auth.view_user',
            'auth.add_user',
            'auth.change_user',
            'auth.delete_user',
        )

        for permission in permissions:
            with self.subTest(permission=permission):
                self.assertTrue(self.admin.has_perm(permission))

    def test_login_rejects_a_non_admin_account(self):
        response = self.client.post(
            reverse('login'),
            {'email': self.regular_user.email, 'password': 'MemberPass123!'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'does not have full administrator access')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_demo_admin_is_repaired_to_full_access(self):
        demo_admin = User.objects.create_user(
            username='admin',
            email='admin@gmail.com',
            password='12345',
            is_staff=False,
            is_superuser=False,
            is_active=False,
        )

        ensure_demo_user()

        demo_admin.refresh_from_db()
        self.assertTrue(demo_admin.is_active)
        self.assertTrue(demo_admin.is_staff)
        self.assertTrue(demo_admin.is_superuser)


class PickupOrderFlowTests(APITestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.user = User.objects.create_user(username='9811223344')
        self.user_profile = UserProfile.objects.create(
            user=self.user, full_name='Vikram Malhotra', phone='9811223344',
            email='vikram@example.com', city='Bengaluru', account_status='Active',
        )
        self.address = UserAddress.objects.create(
            user=self.user, profile=self.user_profile, address_type='Home',
            formatted_address='Flat 402, Oakwood, Indiranagar, Bengaluru',
            city='Bengaluru', state='Karnataka', pincode='560038', is_default=True,
        )
        self.city, _ = ServiceCity.objects.get_or_create(name='Bengaluru', defaults={'state': 'Karnataka'})
        self.zone, _ = ServiceZone.objects.get_or_create(
            city=self.city, name='Indiranagar Test Zone',
            defaults={'code': 'BLR-TEST', 'pincodes': '560038', 'center_latitude': '12.9784', 'center_longitude': '77.6408'},
        )
        self.address.service_zone = self.zone
        self.address.zone_name = self.zone.name
        self.address.latitude = '12.9784'
        self.address.longitude = '77.6408'
        self.address.save(update_fields=['service_zone', 'zone_name', 'latitude', 'longitude'])
        self.vendor = User.objects.create_user(username='9876512345')
        UserProfile.objects.create(
            user=self.vendor, full_name='GreenLoop Scrap Traders', phone='9876512345',
            city='Bengaluru', account_status='Active', is_vendor=True,
        )
        self.vendor_profile = VendorProfile.objects.create(
            user=self.vendor, shop_name='GreenLoop Scrap Traders', owner_name='Ravi Kumar',
            full_address='Indiranagar, Bengaluru', city='Bengaluru', state='Karnataka', pincode='560038',
            latitude='12.9784', longitude='77.6408', is_online=True,
            kyc_status=VendorProfile.KYCStatus.APPROVED,
            aadhaar_status=VendorProfile.AadhaarStatus.VERIFIED,
        )
        self.vendor_profile.operating_zones.add(self.zone)
        self.admin = User.objects.create_superuser('flow-admin', 'admin@example.com', 'Pass123!')
        self.user_token = Token.objects.create(user=self.user)
        self.vendor_token = Token.objects.create(user=self.vendor)
        category, _ = ScrapCategory.objects.get_or_create(name='Metal', defaults={'icon': 'recycle'})
        self.subcategory, _ = ScrapSubCategory.objects.get_or_create(
            category=category, name='Iron Scrap',
            defaults={'rate_per_kg': '40.00', 'gst_percent': '18.00', 'min_weight_kg': '5.00'},
        )
        self.vendor_profile.categories.add(category)
        self.vendor_profile.subcategories.add(self.subcategory)
        for doc in LegalDocument.objects.filter(is_active=True):
            UserConsent.objects.get_or_create(user=self.user, document=doc)
            UserConsent.objects.get_or_create(user=self.vendor, document=doc)
        VendorBillingSetting.objects.create(
            commission_percent='0.00', commission_tax_percent='0.00', fixed_platform_fee='50.00',
            is_approved=True, is_active=True, note='Explicit test policy',
        )

    def authenticate(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.key}')

    def create_order(self):
        self.authenticate(self.user_token)
        response = self.client.post('/api/user/orders/create/', {
            'address_id': self.address.id,
            'subcategory_id': self.subcategory.id,
            'approx_weight': 30,
            'pickup_date': (timezone.localdate() + timedelta(days=1)).isoformat(),
            'time_slot': '10:00 AM - 01:00 PM',
            'notes': 'Gate code 4021',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return PickupOrder.objects.get(order_id=response.data['order']['order_id'])

    def publish_order(self, order):
        order.status = PickupOrder.Status.SEARCHING_VENDOR
        order.final_agreed_price = '1200.00'
        order.published_at = timezone.now()
        order.acceptance_deadline = timezone.now() + timedelta(minutes=30)
        order.save(update_fields=['status', 'final_agreed_price', 'published_at', 'acceptance_deadline', 'updated_at'])
        return order

    def test_price_calculation_uses_rate_and_gst(self):
        response = self.client.post('/api/pricing/calculate/', {
            'subcategory_id': self.subcategory.id,
            'approx_weight': 25.5,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['base_price'], 1020.0)
        self.assertEqual(response.data['gst_amount'], 183.6)
        self.assertEqual(response.data['total_approx_price'], 1203.6)

    def test_full_pickup_payment_review_and_payout_flow(self):
        order = self.create_order()
        self.assertEqual(order.status, PickupOrder.Status.NEGOTIATION_PENDING)
        self.assertEqual(len(order.pickup_otp), 6)

        self.client.credentials()
        self.client.force_login(self.admin)
        response = self.client.post(f'/admin/orders/{order.order_id}/negotiate', {'final_agreed_price': '1250.00'})
        self.assertEqual(response.status_code, 302)
        self.client.logout()
        self.authenticate(self.user_token)
        response = self.client.post(f'/api/user/orders/{order.order_id}/confirm-price/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.client.credentials()
        self.client.force_login(self.admin)
        response = self.client.post(f'/admin/orders/{order.order_id}/publish')
        self.assertEqual(response.status_code, 302)
        self.client.logout()

        self.authenticate(self.vendor_token)
        response = self.client.post(f'/api/vendor/orders/{order.order_id}/accept/', {
            'vendor_name': 'GreenLoop Scrap Traders', 'vendor_phone': '9876512345',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        for next_status in ('VENDOR_ON_THE_WAY', 'REACHED_LOCATION'):
            response = self.client.post(f'/api/vendor/orders/{order.order_id}/status/', {'status': next_status}, format='json')
            self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(f'/api/vendor/orders/{order.order_id}/update-location/', {
            'latitude': '12.9784', 'longitude': '77.6408',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        proof = SimpleUploadedFile('scale.gif', b'GIF89a\x01\x00\x01\x00\x00\x00\x00\x00\x00;', content_type='image/gif')
        response = self.client.post(f'/api/vendor/orders/{order.order_id}/pickup-details/', {
            'item_images': proof, 'final_weight': '32.50',
        }, format='multipart')
        self.assertEqual(response.status_code, 201, response.data)
        response = self.client.post(f'/api/vendor/orders/{order.order_id}/verify-otp/', {'otp': order.pickup_otp}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(f'/api/vendor/orders/{order.order_id}/billing/', {
            'final_weight': 32.5,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        payment_id = response.data['payment']['payment_id']
        signature = payment_signature(PaymentTransaction.objects.get(payment_id=payment_id))
        response = self.client.post(f'/api/vendor/orders/{order.order_id}/payment/verify/', {
            'payment_id': payment_id, 'signature': signature,
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['invoice']['payment_status'], 'PAID')
        response = self.client.post(f'/api/vendor/orders/{order.order_id}/complete/', {
            'final_weight': '32.50',
        }, format='multipart')
        self.assertEqual(response.status_code, 200, response.data)

        self.authenticate(self.user_token)
        tracking_res = self.client.get(f'/api/user/orders/{order.order_id}/tracking/')
        self.assertEqual(tracking_res.status_code, 200)
        self.assertIn('pickup_summary', tracking_res.data)
        self.assertEqual(tracking_res.data['pickup_summary']['final_weight'], 32.5)
        self.assertEqual(len(tracking_res.data['pickup_summary']['item_images']), 1)
        response = self.client.post(f'/api/user/orders/{order.order_id}/review/', {
            'rating': 5, 'comments': 'Prompt arrival and fair weighing.',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        response = self.client.post('/api/user/bank-details/', {
            'account_holder_name': 'Vikram Malhotra', 'bank_name': 'HDFC Bank',
            'account_number': '50100234918234', 'ifsc_code': 'HDFC0001234',
            'upi_id': 'vikram@okhdfcbank',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['bank_details']['account_number'], '50100234918234')

        self.client.credentials()
        self.client.force_login(self.admin)
        review = OrderReview.objects.get(order=order)
        response = self.client.post(f'/admin/ratings/{review.id}/approve')
        self.assertEqual(response.status_code, 302)
        response = self.client.post(f'/admin/settlements/{order.order_id}/disburse', {
            'amount': '1250.00', 'method': 'NEFT', 'reference': 'UTR-TEST-1001',
        })
        self.assertEqual(response.status_code, 302)

        order.refresh_from_db()
        review.refresh_from_db()
        self.assertEqual(order.status, PickupOrder.Status.USER_PAYOUT)
        self.assertEqual(order.payout_status, PickupOrder.PayoutStatus.DISBURSED)
        self.assertTrue(review.is_approved_by_admin)
        self.assertEqual(PickupImage.objects.filter(order=order).count(), 1)
        self.assertTrue(PickupImage.objects.get(order=order).uploaded_file.name)
        self.assertEqual(OrderInvoice.objects.get(order=order).payment_status, 'PAID')
        self.assertTrue(UserBankDetail.objects.filter(user=self.user).exists())
        self.assertTrue(UserNotification.objects.filter(user=self.user, event_type='PICKUP_COMPLETED').exists())

    def test_tracking_does_not_leak_another_users_order(self):
        order = self.create_order()
        self.authenticate(self.vendor_token)
        response = self.client.get(f'/api/user/orders/{order.order_id}/tracking/')
        self.assertEqual(response.status_code, 404)

    def test_persistent_auth_cookie_authenticates_order_history(self):
        self.create_order()
        self.client.credentials()
        self.client.cookies['auth_token'] = self.user_token.key
        response = self.client.get('/api/user/orders/history/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 1)

    def test_admin_pickup_pages_render_from_database(self):
        order = self.create_order()
        self.client.credentials()
        self.client.force_login(self.admin)
        for url in ('/requests.html', '/orders.html', f'/order-detail.html?id={order.order_id}', '/ratings.html', '/settlements.html'):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get('/requests.html'), order.order_id)

    def test_admin_cannot_publish_before_user_accepts_proposal(self):
        order = self.create_order()
        self.client.credentials()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(f'/admin/orders/{order.order_id}/negotiate', {'final_agreed_price': '1200.00'}).status_code, 302)
        response = self.client.post(f'/admin/orders/{order.order_id}/publish', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 409)
        order.refresh_from_db()
        self.assertNotEqual(order.status, PickupOrder.Status.SEARCHING_VENDOR)

    def test_forged_payment_signature_does_not_generate_invoice(self):
        order = self.create_order()
        order.assigned_vendor = self.vendor
        order.assigned_vendor_name = 'GreenLoop Scrap Traders'
        order.assigned_vendor_phone = '9876512345'
        order.is_otp_verified = True
        order.status = PickupOrder.Status.PICKUP_IN_PROGRESS
        order.final_weight = '10.00'
        order.proof_submitted_at = timezone.now()
        order.save()
        PickupImage.objects.create(order=order, image='forged-test-proof.jpg')
        self.authenticate(self.vendor_token)
        response = self.client.post(f'/api/vendor/orders/{order.order_id}/billing/', {'final_weight': '10.00'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        response = self.client.post(f'/api/vendor/orders/{order.order_id}/payment/verify/', {
            'payment_id': response.data['payment']['payment_id'], 'signature': 'forged-signature',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(OrderInvoice.objects.filter(order=order).exists())

    def test_non_vendor_profile_cannot_accept_published_order(self):
        order = self.create_order()
        order.status = PickupOrder.Status.SEARCHING_VENDOR
        order.final_agreed_price = '1200.00'
        order.save(update_fields=['status', 'final_agreed_price'])
        self.authenticate(self.user_token)
        response = self.client.post(f'/api/vendor/orders/{order.order_id}/accept/', {
            'vendor_name': 'Not a vendor', 'vendor_phone': self.user_profile.phone,
        }, format='json')
        self.assertEqual(response.status_code, 403)

    def test_consent_is_required_before_order_creation(self):
        UserConsent.objects.filter(user=self.user).delete()
        self.authenticate(self.user_token)
        response = self.client.post('/api/user/orders/create/', {
            'address_id': self.address.id, 'subcategory_id': self.subcategory.id,
            'approx_weight': 30, 'pickup_date': (timezone.localdate() + timedelta(days=1)).isoformat(),
            'time_slot': '10:00 AM - 01:00 PM',
        }, format='json')
        self.assertEqual(response.status_code, 428)
        self.assertTrue(response.data['consent_required'])

    def test_profile_phone_is_immutable_and_photo_upload_persists(self):
        self.authenticate(self.user_token)
        response = self.client.patch('/api/user/profile/', {'mobile_number': '9000000000'}, format='json')
        self.assertEqual(response.status_code, 400)
        photo = SimpleUploadedFile('profile.gif', b'GIF89a\x01\x00\x01\x00\x00\x00\x00\x00\x00;', content_type='image/gif')
        response = self.client.patch('/api/user/profile/', {'profile_photo': photo}, format='multipart')
        self.assertEqual(response.status_code, 200, response.data)
        self.user_profile.refresh_from_db()
        self.assertTrue(self.user_profile.profile_photo.name)

    def test_phone_change_requires_new_number_otp(self):
        self.authenticate(self.user_token)
        requested = self.client.post('/api/user/change-phone/request/', {'new_phone': '9000012345'}, format='json')
        self.assertEqual(requested.status_code, 200, requested.data)
        record = OTPVerification.objects.get(phone='9000012345', purpose='CHANGE_PHONE', is_verified=False)
        wrong = self.client.post('/api/user/change-phone/confirm/', {'new_phone': '9000012345', 'otp': '000000'}, format='json')
        self.assertEqual(wrong.status_code, 400)
        confirmed = self.client.post('/api/user/change-phone/confirm/', {'new_phone': '9000012345', 'otp': record.otp}, format='json')
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.user_profile.refresh_from_db()
        self.assertEqual(self.user_profile.phone, '9000012345')

    def test_unauthenticated_home_is_rejected(self):
        response = self.client.get('/api/user/home/')
        self.assertEqual(response.status_code, 401)

    def test_vendor_marketplace_filters_and_never_exposes_pickup_otp(self):
        order = self.publish_order(self.create_order())
        self.authenticate(self.vendor_token)
        response = self.client.get('/api/vendor/orders/available/?page_size=invalid')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 1)
        listing = response.data['orders'][0]
        self.assertEqual(listing['order_id'], order.order_id)
        self.assertNotIn('pickup_otp', listing)
        self.assertNotIn('customer', listing)
        self.assertNotIn('pickup_address', listing)
        accepted = self.client.post(f'/api/vendor/orders/{order.order_id}/accept/', {}, format='json')
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertNotIn('pickup_otp', accepted.data['order'])
        detail = self.client.get(f'/api/vendor/orders/{order.order_id}/')
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertNotIn('pickup_otp', detail.data['order'])

    def test_vendor_rejection_is_vendor_specific_and_does_not_cancel_order(self):
        order = self.publish_order(self.create_order())
        second_user = User.objects.create_user(username='9888800002')
        UserProfile.objects.create(
            user=second_user, full_name='Second Vendor', phone='9888800002',
            city='Bengaluru', account_status='Active', is_vendor=True,
        )
        second_vendor = VendorProfile.objects.create(
            user=second_user, shop_name='Second Vendor', owner_name='Owner Two',
            full_address='Bengaluru', city='Bengaluru', state='Karnataka', pincode='560038',
            is_online=True, kyc_status=VendorProfile.KYCStatus.APPROVED,
        )
        second_vendor.operating_zones.add(self.zone)
        second_vendor.categories.add(self.subcategory.category)
        second_vendor.subcategories.add(self.subcategory)
        for doc in LegalDocument.objects.filter(is_active=True):
            UserConsent.objects.create(user=second_user, document=doc)
        second_token = Token.objects.create(user=second_user)

        self.authenticate(self.vendor_token)
        rejected = self.client.post(f'/api/vendor/orders/{order.order_id}/reject/', {'reason': 'Schedule conflict'}, format='json')
        self.assertEqual(rejected.status_code, 200, rejected.data)
        order.refresh_from_db()
        self.assertEqual(order.status, PickupOrder.Status.SEARCHING_VENDOR)
        self.assertIsNone(order.assigned_vendor_id)
        self.assertTrue(VendorOfferRejection.objects.filter(vendor=self.vendor_profile, order=order).exists())
        self.assertEqual(self.client.get('/api/vendor/orders/available/').data['count'], 0)

        self.authenticate(second_token)
        self.assertEqual(self.client.get('/api/vendor/orders/available/').data['count'], 1)

    def test_vendor_approval_online_zone_and_publication_are_server_enforced(self):
        order = self.publish_order(self.create_order())
        self.authenticate(self.vendor_token)
        self.vendor_profile.is_online = False
        self.vendor_profile.save(update_fields=['is_online'])
        self.assertEqual(self.client.get('/api/vendor/orders/available/').status_code, 403)
        self.vendor_profile.is_online = True
        self.vendor_profile.kyc_status = VendorProfile.KYCStatus.UNDER_REVIEW
        self.vendor_profile.save(update_fields=['is_online', 'kyc_status'])
        self.assertEqual(self.client.post(f'/api/vendor/orders/{order.order_id}/accept/', {}, format='json').status_code, 403)
        self.vendor_profile.kyc_status = VendorProfile.KYCStatus.APPROVED
        self.vendor_profile.save(update_fields=['kyc_status'])
        self.vendor_profile.operating_zones.clear()
        self.assertEqual(self.client.get(f'/api/vendor/orders/{order.order_id}/').status_code, 403)

    def test_billing_is_blocked_without_an_approved_policy(self):
        order = self.create_order()
        order.assigned_vendor = self.vendor
        order.assigned_vendor_name = self.vendor_profile.shop_name
        order.assigned_vendor_phone = self.vendor.profile.phone
        order.is_otp_verified = True
        order.status = PickupOrder.Status.PICKUP_IN_PROGRESS
        order.final_weight = '10.00'
        order.proof_submitted_at = timezone.now()
        order.save()
        PickupImage.objects.create(order=order, image='billing-policy-proof.jpg')
        VendorBillingSetting.objects.all().delete()
        self.authenticate(self.vendor_token)
        response = self.client.post(f'/api/vendor/orders/{order.order_id}/billing/', {'final_weight': '10.00'}, format='json')
        self.assertEqual(response.status_code, 503, response.data)
        self.assertTrue(response.data['billing_policy_required'])

    def test_refund_requires_captured_payment_and_prevents_excess_and_duplicate(self):
        order = self.create_order()
        order.assigned_vendor = self.vendor
        order.status = PickupOrder.Status.INVOICE_GENERATED
        order.save(update_fields=['assigned_vendor', 'status', 'updated_at'])
        payment = PaymentTransaction.objects.create(
            order=order, payment_id='pay_refund_test', amount='100.00', item_amount='100.00',
            status=PaymentTransaction.Status.VERIFIED,
        )
        self.authenticate(self.vendor_token)
        excessive = self.client.post('/api/vendor/refunds/', {
            'order_id': order.order_id, 'amount': '100.01', 'reason': 'Duplicate charge',
        }, format='json')
        self.assertEqual(excessive.status_code, 400, excessive.data)
        created = self.client.post('/api/vendor/refunds/', {
            'order_id': order.order_id, 'amount': '50.00', 'reason': 'Duplicate charge',
        }, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(RefundRequest.objects.get(payment=payment).status, RefundRequest.Status.REQUESTED)
        duplicate = self.client.post('/api/vendor/refunds/', {
            'order_id': order.order_id, 'amount': '10.00', 'reason': 'Again',
        }, format='json')
        self.assertEqual(duplicate.status_code, 409, duplicate.data)

    def test_expired_unaccepted_order_escalation_is_idempotent(self):
        order = self.publish_order(self.create_order())
        order.acceptance_deadline = timezone.now() - timedelta(minutes=1)
        order.save(update_fields=['acceptance_deadline'])
        call_command('escalate_unaccepted_orders')
        call_command('escalate_unaccepted_orders')
        order.refresh_from_db()
        self.assertTrue(order.is_escalated)
        self.assertEqual(UserNotification.objects.filter(order=order, title='Vendor search escalated').count(), 1)

    @override_settings(AADHAAR_PROVIDER_MODE='unconfigured')
    def test_aadhaar_does_not_fake_success_without_provider_configuration(self):
        self.authenticate(self.vendor_token)
        response = self.client.post('/api/vendor/kyc/aadhaar/initiate/', {'aadhaar_last4': '1234'}, format='json')
        self.assertEqual(response.status_code, 503, response.data)
        self.assertFalse(response.data['provider_configured'])

    def test_vendor_profile_zone_and_history_filters_reject_invalid_values(self):
        self.authenticate(self.vendor_token)
        invalid_coordinate = self.client.patch('/api/vendor/profile/', {'latitude': '91'}, format='json')
        self.assertEqual(invalid_coordinate.status_code, 400, invalid_coordinate.data)
        invalid_zones = self.client.put('/api/vendor/operating-zones/', {'zone_ids': ['not-an-id']}, format='json')
        self.assertEqual(invalid_zones.status_code, 400, invalid_zones.data)
        invalid_date = self.client.get('/api/vendor/orders/history/?from=2026-99-99')
        self.assertEqual(invalid_date.status_code, 400, invalid_date.data)

    def test_user_counter_offer_persists_and_is_audited(self):
        order = self.create_order()
        self.client.credentials()
        self.client.force_login(self.admin)
        self.client.post(f'/admin/orders/{order.order_id}/negotiate', {'final_agreed_price': '1250.00'})
        self.client.logout()
        self.authenticate(self.user_token)
        response = self.client.post(f'/api/user/orders/{order.order_id}/counter-price/', {
            'proposed_price': '1325.50', 'note': 'Includes sorted copper.',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        proposal = NegotiationProposal.objects.get(id=response.data['proposal']['id'])
        self.assertEqual(proposal.proposer_role, NegotiationProposal.ProposerRole.USER)
        self.assertTrue(MarketplaceAuditLog.objects.filter(order=order, action='PRICE_COUNTERED').exists())

    def test_vendor_category_selection_controls_marketplace_matching(self):
        order = self.publish_order(self.create_order())
        self.vendor_profile.categories.clear()
        self.vendor_profile.subcategories.clear()
        self.authenticate(self.vendor_token)
        self.assertEqual(self.client.get('/api/vendor/orders/available/').data['count'], 0)
        selected = self.client.put('/api/vendor/categories/', {
            'category_ids': [self.subcategory.category_id], 'subcategory_ids': [self.subcategory.id],
        }, format='json')
        self.assertEqual(selected.status_code, 200, selected.data)
        self.assertEqual(self.client.get('/api/vendor/orders/available/').data['count'], 1)

    def test_admin_deadlines_and_cms_content_are_persisted(self):
        self.client.credentials()
        self.client.force_login(self.admin)
        response = self.client.post('/admin/settings/deadlines', {
            'accept_deadline_hours': '2', 'arrival_deadline_hours': '3',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        config = PlatformConfiguration.current()
        self.assertEqual((config.acceptance_minutes, config.arrival_minutes), (120, 180))
        response = self.client.post('/admin/cms/create', {
            'title': 'Pickup FAQ', 'type': 'FAQ', 'version': 'flow-1',
            'content': 'How pickup works.', 'status': 'published',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.client.logout()
        content = self.client.get('/api/content/?type=FAQ')
        self.assertEqual(content.status_code, 200, content.data)
        self.assertEqual(content.data['documents'][0]['title'], 'Pickup FAQ')

    def test_failed_vendor_payment_can_be_retried_and_is_audited(self):
        order = self.create_order()
        order.assigned_vendor = self.vendor
        order.assigned_vendor_name = self.vendor_profile.shop_name
        order.assigned_vendor_phone = self.vendor.profile.phone
        order.is_otp_verified = True
        order.status = PickupOrder.Status.PICKUP_IN_PROGRESS
        order.final_weight = '10.00'
        order.proof_submitted_at = timezone.now()
        order.save()
        PickupImage.objects.create(order=order, image='payment-retry-proof.jpg')
        self.authenticate(self.vendor_token)
        created = self.client.post(f'/api/vendor/orders/{order.order_id}/billing/', {'final_weight': '10.00'}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        payment_id = created.data['payment']['payment_id']
        event_id = 'evt-payment-failed-test'
        signature = webhook_signature(event_id, payment_id, 'FAILED')
        self.client.credentials()
        failed = self.client.post('/api/payments/webhook/', {
            'event_id': event_id, 'payment_id': payment_id, 'status': 'FAILED',
        }, format='json', HTTP_X_PAYMENT_SIGNATURE=signature)
        self.assertEqual(failed.status_code, 200, failed.data)
        self.authenticate(self.vendor_token)
        retried = self.client.post(f'/api/vendor/orders/{order.order_id}/billing/', {'final_weight': '10.00'}, format='json')
        self.assertEqual(retried.status_code, 201, retried.data)
        self.assertNotEqual(retried.data['payment']['payment_id'], payment_id)
        self.assertTrue(MarketplaceAuditLog.objects.filter(order=order, action='PAYMENT_FAILED').exists())

    def test_authenticated_vendor_and_admin_receive_full_kyc_values(self):
        self.vendor_profile.aadhaar_number = '543298761234'
        self.vendor_profile.pan_number = 'ABCDE1234F'
        self.vendor_profile.gst_number = '29ABCDE1234F1Z5'
        self.vendor_profile.save(update_fields=['aadhaar_number', 'pan_number', 'gst_number'])
        self.authenticate(self.vendor_token)
        response = self.client.get('/api/vendor/profile/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['vendor']['aadhaar_number'], '543298761234')
        self.assertEqual(response.data['vendor']['pan_number'], 'ABCDE1234F')
        self.client.credentials()
        self.client.force_login(self.admin)
        html = self.client.get(f'/vendor-detail.html?id={self.vendor_profile.id}')
        self.assertEqual(html.status_code, 200)
        self.assertContains(html, '543298761234')
        self.assertContains(html, 'ABCDE1234F')


class OTPControlTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='9123456789')
        UserProfile.objects.create(user=self.user, full_name='OTP User', phone='9123456789', account_status='Active')

    def test_cooldown_attempt_limit_success_and_reuse_rejection(self):
        response = self.client.post('/api/user/send-otp/', {'phone': '9123456789'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        record = OTPVerification.objects.get(phone='9123456789', is_verified=False)
        self.assertEqual(self.client.post('/api/user/send-otp/', {'phone': '9123456789'}, format='json').status_code, 429)
        for _ in range(5):
            wrong = self.client.post('/api/user/login-otp/', {'phone': '9123456789', 'otp': '000000'}, format='json')
            self.assertEqual(wrong.status_code, 400)
        locked = self.client.post('/api/user/login-otp/', {'phone': '9123456789', 'otp': record.otp}, format='json')
        self.assertEqual(locked.status_code, 429)
        record.attempts = 0
        record.save(update_fields=['attempts'])
        success = self.client.post('/api/user/login-otp/', {'phone': '9123456789', 'otp': record.otp}, format='json')
        self.assertEqual(success.status_code, 200, success.data)
        reused = self.client.post('/api/user/login-otp/', {'phone': '9123456789', 'otp': record.otp}, format='json')
        self.assertEqual(reused.status_code, 400)

    def test_expired_otp_is_rejected(self):
        self.assertEqual(self.client.post('/api/user/send-otp/', {'phone': '9123456789'}, format='json').status_code, 200)
        record = OTPVerification.objects.get(phone='9123456789', is_verified=False)
        record.expires_at = timezone.now() - timedelta(seconds=1)
        record.save(update_fields=['expires_at'])
        response = self.client.post('/api/user/login-otp/', {'phone': '9123456789', 'otp': record.otp}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('expired', response.data['message'].lower())
