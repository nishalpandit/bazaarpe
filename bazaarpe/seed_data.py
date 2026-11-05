from django.contrib.auth.models import User
from .models import UserProfile, ScrapCategory, ScrapSubCategory


DEFAULT_SCRAP_CATEGORIES = {
    'Paper': {
        'icon': 'newspaper',
        'subcategories': [
            ('Newspaper', '18.00', '18.00', '5.00'),
            ('Corrugated Cardboard', '12.00', '18.00', '5.00'),
            ('Office Paper', '16.00', '18.00', '5.00'),
        ],
    },
    'Metal': {
        'icon': 'recycle',
        'subcategories': [
            ('Copper Wire', '650.00', '18.00', '2.00'),
            ('Iron Scrap', '40.00', '18.00', '5.00'),
            ('Aluminium', '145.00', '18.00', '3.00'),
        ],
    },
    'Plastic': {
        'icon': 'bottle',
        'subcategories': [
            ('PET Bottles', '22.00', '18.00', '5.00'),
            ('Hard Plastic', '28.00', '18.00', '5.00'),
        ],
    },
    'E-waste': {
        'icon': 'cpu',
        'subcategories': [
            ('Mixed Electronics', '75.00', '18.00', '2.00'),
            ('Computer Components', '180.00', '18.00', '1.00'),
        ],
    },
}


def seed_scrap_categories():
    """Idempotently create the default active scrap catalogue and rates."""
    for category_name, config in DEFAULT_SCRAP_CATEGORIES.items():
        category, _ = ScrapCategory.objects.update_or_create(
            name=category_name,
            defaults={'icon': config['icon'], 'is_active': True},
        )
        for name, rate, gst, min_weight in config['subcategories']:
            ScrapSubCategory.objects.update_or_create(
                category=category,
                name=name,
                defaults={
                    'rate_per_kg': rate,
                    'gst_percent': gst,
                    'min_weight_kg': min_weight,
                    'is_active': True,
                },
            )


def seed_initial_users():
    """Seeds demo users if no user profiles exist."""
    if UserProfile.objects.exists():
        return

    demo_users = [
        {
            'username': '9876511200',
            'full_name': 'Arjun Rao',
            'phone': '9876511200',
            'email': 'arjun.rao@example.com',
            'address': 'B-704, Indiranagar Residency, 12th Main',
            'pincode': '560038',
            'city': 'Bengaluru',
            'account_status': 'Active',
            'orders_count': 4,
            'settlement_due': 1800.00,
            'settlement_status': 'Pending',
            'bank_name': 'HDFC Bank',
            'account_number_masked': 'XXXXXXXX4471',
            'ifsc_code': 'HDFC0001234',
        },
        {
            'username': '9012388420',
            'full_name': 'Meera Iyer',
            'phone': '9012388420',
            'email': 'meera.iyer@example.com',
            'address': '14, Rose Villa, Koregaon Park',
            'pincode': '411001',
            'city': 'Pune',
            'account_status': 'Active',
            'orders_count': 9,
            'settlement_due': 4250.00,
            'settlement_status': 'Pending',
            'bank_name': 'ICICI Bank',
            'account_number_masked': 'XXXXXXXX9930',
            'ifsc_code': 'ICIC0000456',
        },
        {
            'username': '8765422100',
            'full_name': 'Fatima Sheikh',
            'phone': '8765422100',
            'email': 'fatima.s@example.com',
            'address': '22, Hill Road, Bandra West',
            'pincode': '400050',
            'city': 'Mumbai',
            'account_status': 'Active',
            'orders_count': 3,
            'settlement_due': 0.00,
            'settlement_status': 'Settled',
            'bank_name': 'Axis Bank',
            'account_number_masked': 'XXXXXXXX1187',
            'ifsc_code': 'UTIB0002211',
        },
        {
            'username': '9988744020',
            'full_name': 'Sana Kapoor',
            'phone': '9988744020',
            'email': 'sana.kapoor@example.com',
            'address': '55, Civil Lines',
            'pincode': '302017',
            'city': 'Jaipur',
            'account_status': 'Active',
            'orders_count': 2,
            'settlement_due': 0.00,
            'settlement_status': 'Not due',
            'bank_name': 'State Bank of India',
            'account_number_masked': 'XXXXXXXX6620',
            'ifsc_code': 'SBIN0031222',
        },
        {
            'username': '7012399110',
            'full_name': 'Deepak Verma',
            'phone': '7012399110',
            'email': 'deepak.v@example.com',
            'address': 'Flat 102, Kothrud',
            'pincode': '411038',
            'city': 'Pune',
            'account_status': 'Blocked',
            'orders_count': 6,
            'settlement_due': 2050.00,
            'settlement_status': 'On hold',
            'bank_name': 'Kotak Mahindra Bank',
            'account_number_masked': 'XXXXXXXX3312',
            'ifsc_code': 'KKBK0007788',
        },
    ]

    for data in demo_users:
        user, _ = User.objects.get_or_create(username=data['username'])
        user.email = data['email']
        user.first_name = data['full_name'].split()[0]
        user.last_name = ' '.join(data['full_name'].split()[1:])
        user.set_unusable_password()
        user.save()

        UserProfile.objects.create(
            user=user,
            full_name=data['full_name'],
            phone=data['phone'],
            email=data['email'],
            address=data['address'],
            pincode=data['pincode'],
            city=data['city'],
            account_status=data['account_status'],
            orders_count=data['orders_count'],
            settlement_due=data['settlement_due'],
            settlement_status=data['settlement_status'],
            bank_name=data['bank_name'],
            account_number_masked=data['account_number_masked'],
            ifsc_code=data['ifsc_code'],
        )
    print("Initial demo users seeded successfully.")
