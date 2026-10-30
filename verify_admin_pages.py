import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from decimal import Decimal
from nainjyoti.models import (
    ScrapCategory, ScrapSubCategory, ServiceCity, ServiceZone, VendorProfile,
    UserProfile, PickupOrder, UserAddress, LegalDocument,
    VendorBillingSetting, OrderReview, RefundRequest, PaymentTransaction, OrderInvoice,
    UserBankDetail,
)

def run_verification():
    print("======================================================================")
    print("STARTING ADMIN PANEL VERIFICATION (GET PAGES + CRUD FLOWS)")
    print("======================================================================")
    
    # Ensure superuser
    admin_user, _ = User.objects.get_or_create(username='admin@gmail.com', defaults={'email': 'admin@gmail.com', 'is_staff': True, 'is_superuser': True})
    admin_user.set_password('Admin@123')
    admin_user.is_staff = True
    admin_user.is_superuser = True
    admin_user.save()

    client = Client()
    client.force_login(admin_user)

    # 1. Test GET on all Admin URLs
    pages_to_test = [
        '/',
        '/dashboard/',
        '/index.html',
        '/users.html',
        '/user-detail.html',
        '/vendors.html',
        '/vendor-detail.html',
        '/kyc.html',
        '/categories.html',
        '/locations.html',
        '/payments.html',
        '/invoices.html',
        '/invoice-detail.html',
        '/settlements.html',
        '/refunds.html',
        '/ratings.html',
        '/ledgers.html',
        '/cms.html',
        '/cms-edit.html',
        '/settings.html',
        '/requests.html',
        '/request-detail.html',
        '/orders.html',
        '/order-detail.html',
    ]

    print("\n--- PHASE 1: TESTING GET REQUESTS FOR ALL 24 ADMIN URLS ---")
    get_failures = []
    for page in pages_to_test:
        resp = client.get(page)
        status = resp.status_code
        if status in (200, 302):
            print(f"  [PASS] GET {page:25} -> HTTP {status}")
        else:
            print(f"  [FAIL] GET {page:25} -> HTTP {status}")
            get_failures.append((page, status))

    if get_failures:
        print(f"\nGET Errors detected: {get_failures}")
        return False

    print("\n--- PHASE 2: TESTING CRUD OPERATIONS VIA /admin/<path> ---")

    # 1. Categories CRUD
    print("1. Categories CRUD:")
    cat_resp = client.post('/admin/categories/create', {'name': 'Test Electronics Cat', 'description': 'Tested via Admin'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    cat = ScrapCategory.objects.filter(name='Test Electronics Cat').first()
    assert cat is not None, "Category creation failed"
    print("  [PASS] Create Category: Created category ID", cat.id)

    sub_resp = client.post('/admin/categories/subcategory', {'category_id': str(cat.id), 'name': 'Motherboard Scrap', 'rate_per_kg': '150.00'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    sub = ScrapSubCategory.objects.filter(name='Motherboard Scrap', category=cat).first()
    assert sub is not None, "Subcategory creation failed"
    print("  [PASS] Create Subcategory: Created subcategory ID", sub.id, "at Rs.150/kg")

    # 2. Locations CRUD
    print("2. Locations CRUD:")
    city_resp = client.post('/admin/locations/cities/create', {'name': 'Hyderabad Test', 'state': 'Telangana'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    city = ServiceCity.objects.filter(name='Hyderabad Test').first()
    assert city is not None, "City creation failed"
    print("  [PASS] Create City: Created city ID", city.id)

    zone_resp = client.post('/admin/locations/zones/create', {'city_id': str(city.id), 'name': 'Hitec City Test', 'pincodes': '500081, 500082'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    zone = ServiceZone.objects.filter(name='Hitec City Test', city=city).first()
    assert zone is not None, "Zone creation failed"
    print("  [PASS] Create Zone: Created zone ID", zone.id)

    # 3. Users CRUD
    print("3. Users CRUD:")
    user_resp = client.post('/admin/users/create', {
        'name': 'Pooja Test User',
        'phone': '9988776655',
        'email': 'pooja.test@example.com',
        'city': 'Hyderabad Test',
        'address': 'Hitec City Phase 2',
        'pincode': '500081',
        'status': 'Active'
    }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    created_u = User.objects.filter(username='9988776655').first()
    assert created_u is not None, "User creation failed"
    u_prof = UserProfile.objects.filter(user=created_u).first()
    assert u_prof is not None and u_prof.full_name == 'Pooja Test User', "User Profile creation failed"
    print("  [PASS] Create User: Created user", created_u.username, "Profile ID", u_prof.id)

    edit_u_resp = client.post('/admin/users/edit', {
        'user_id': str(u_prof.id),
        'name': 'Pooja Updated Name',
        'phone': '9988776655',
        'city': 'Hyderabad Test',
        'status': 'Active'
    }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    u_prof.refresh_from_db()
    assert u_prof.full_name == 'Pooja Updated Name', "User edit failed"
    print("  [PASS] Edit User: Updated profile name to", u_prof.full_name)

    # 4. Vendors CRUD & KYC
    print("4. Vendors CRUD & KYC:")
    vnd_resp = client.post('/admin/vendors/create', {
        'shop_name': 'Hitec Scrap Solvers',
        'owner_name': 'Suresh Reddy',
        'phone': '9876549999',
        'email': 'suresh@hitecscrap.com',
        'city': 'Hyderabad Test',
        'state': 'Telangana',
        'aadhaar_number': '123456789012',
        'pan_number': 'ABCDE1234F'
    }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    created_vnd_u = User.objects.filter(username='9876549999').first()
    assert created_vnd_u is not None, "Vendor user creation failed"
    vnd_prof = VendorProfile.objects.filter(user=created_vnd_u).first()
    assert vnd_prof is not None, "Vendor profile creation failed"
    print("  [PASS] Create Vendor: Created vendor profile ID", vnd_prof.id, vnd_prof.shop_name)

    # KYC Approve
    kyc_resp = client.post(f'/admin/vendors/{vnd_prof.id}/kyc/approve', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    vnd_prof.refresh_from_db()
    assert vnd_prof.kyc_status == VendorProfile.KYCStatus.APPROVED, f"Vendor KYC approval failed, was {vnd_prof.kyc_status}"
    print("  [PASS] Approve KYC: Vendor KYC status is now", vnd_prof.kyc_status)

    # 5. Settings update
    print("5. Platform Settings:")
    set_resp = client.post('/admin/settings/commission', {'commission_rate': '3.50', 'commission_basis': 'proposed_item_total'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    billing_setting = VendorBillingSetting.current()
    assert billing_setting.commission_percent == Decimal('3.50'), f"Commission update failed, was {billing_setting.commission_percent}"
    print("  [PASS] Update Settings: Commission percent updated to", billing_setting.commission_percent)

    # 6. Orders Creation, Negotiation, Publish, and Settlement
    print("6. Orders, Negotiation, Publication & Settlement:")
    user_addr = UserAddress.objects.create(
        user=created_u, profile=u_prof,
        address_type='Home',
        formatted_address='Hitec City Flat 101',
        city='Hyderabad Test',
        pincode='500081',
        service_zone=zone,
        latitude=17.4435,
        longitude=78.3772
    )
    order_create_resp = client.post('/admin/orders/create', {
        'user_phone': created_u.username,
        'category_id': str(cat.id),
        'approx_weight': '25.5',
        'address_id': str(user_addr.id),
        'approx_price': '3800.00'
    }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    test_order = PickupOrder.objects.filter(user=created_u).order_by('-created_at').first()
    assert test_order is not None, "Order creation failed"
    print("  [PASS] Create Order: Created order", test_order.order_id, "Status:", test_order.status)

    # Admin negotiate
    neg_resp = client.post(f'/admin/orders/{test_order.order_id}/negotiate', {'proposed_price': '4000.00', 'message': 'Special bulk price agreed'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    test_order.refresh_from_db()
    assert test_order.final_agreed_price == Decimal('4000.00'), f"Negotiation failed, price: {test_order.final_agreed_price}"
    print("  [PASS] Negotiate Order: Price updated to Rs.4000.00, Status:", test_order.status)

    # User accepts proposal
    prop = test_order.negotiation_proposals.last()
    if prop:
        prop.is_accepted = True
        prop.save()

    # Admin publish
    pub_resp = client.post(f'/admin/orders/{test_order.order_id}/publish', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    test_order.refresh_from_db()
    assert test_order.status == PickupOrder.Status.SEARCHING_VENDOR, f"Order publish failed, status: {test_order.status}"
    print("  [PASS] Publish Order: Order published to marketplace, Status:", test_order.status)

    # Assign vendor
    assign_resp = client.post(f'/admin/orders/{test_order.order_id}/assign-vendor', {'vendor_id': str(vnd_prof.id)}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    test_order.refresh_from_db()
    assert test_order.assigned_vendor == created_vnd_u, "Vendor assignment failed"
    print("  [PASS] Assign Vendor: Vendor", created_vnd_u.username, "assigned to order")

    # Complete order & settle
    test_order.status = PickupOrder.Status.COMPLETED
    test_order.final_amount = Decimal('4000.00')
    test_order.payout_status = PickupOrder.PayoutStatus.PENDING
    test_order.save()
    UserBankDetail.objects.update_or_create(
        user=created_u,
        defaults={
            'account_holder_name': created_u.profile.full_name,
            'bank_name': 'Verification Bank',
            'account_number': '123456789012',
            'ifsc_code': 'HDFC0001234',
            'is_verified': True,
        },
    )
    OrderInvoice.objects.get_or_create(
        order=test_order,
        defaults={
            'subtotal': Decimal('4000.00'),
            'gst_amount': Decimal('0.00'),
            'platform_fee': Decimal('0.00'),
            'total_paid_by_vendor': Decimal('4000.00'),
            'payment_status': OrderInvoice.PaymentStatus.PAID,
        },
    )

    disburse_resp = client.post(f'/admin/settlements/{test_order.order_id}/disburse', {'reference': 'UTR99881122'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    test_order.refresh_from_db()
    assert test_order.payout_status == PickupOrder.PayoutStatus.DISBURSED, f"Disburse failed, status: {test_order.payout_status}"
    print("  [PASS] Disburse Settlement: Payout disbursed with reference", test_order.payout_reference)

    # 7. Reviews CRUD
    print("7. Customer Reviews Moderation:")
    rev = OrderReview.objects.create(
        order=test_order,
        user=created_u,
        rating=5,
        comments="Excellent pickup service!",
        is_approved_by_admin=False
    )
    rev_resp = client.post(f'/admin/ratings/{rev.id}/approve', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    rev.refresh_from_db()
    assert rev.is_approved_by_admin is True, "Review approval failed"
    print("  [PASS] Approve Review: Review ID", rev.id, "approved successfully")

    # 8. CMS CRUD
    print("8. CMS & Legal Documents:")
    cms_resp = client.post('/admin/cms/save', {
        'title': 'Test Guarantee Policy',
        'document_type': 'TERMS',
        'content': 'This is dynamic test content.'
    }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    doc = LegalDocument.objects.filter(title='Test Guarantee Policy').first()
    assert doc is not None, "CMS Document save failed"
    print("  [PASS] Save CMS Document: Created document ID", doc.id, doc.title)

    # 9. Clean-up Deletions CRUD
    print("9. Clean-up Deletions CRUD:")
    del_cat_resp = client.post('/admin/categories/delete', {'category_id': str(cat.id)}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    assert ScrapCategory.objects.filter(id=cat.id).count() == 0, "Category delete failed"
    print("  [PASS] Delete Category: Category removed")

    del_loc_resp = client.post('/admin/locations/delete', {'item_name': zone.name}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    assert ServiceZone.objects.filter(id=zone.id).count() == 0, "Zone delete failed"
    print("  [PASS] Delete Zone: Service zone removed")

    del_u_resp = client.post('/admin/users/delete', {'user_id': str(u_prof.id)}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    assert UserProfile.objects.filter(id=u_prof.id).count() == 0, "User profile delete failed"
    print("  [PASS] Delete User: User profile removed")

    del_v_resp = client.post('/admin/vendors/delete', {'vendor_id': str(vnd_prof.id)}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    assert VendorProfile.objects.filter(id=vnd_prof.id).count() == 0, "Vendor profile delete failed"
    print("  [PASS] Delete Vendor: Vendor profile removed")

    print("\n======================================================================")
    print("ALL ADMIN PANEL VERIFICATIONS & CRUD CHECKS COMPLETED SUCCESSFULLY!")
    print("======================================================================")
    return True

if __name__ == '__main__':
    run_verification()
