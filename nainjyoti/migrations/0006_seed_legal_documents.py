from django.db import migrations


def seed_legal_documents(apps, schema_editor):
    LegalDocument = apps.get_model('nainjyoti', 'LegalDocument')
    documents = [
        ('PRIVACY', '2026.1', 'Bazaarpe Privacy Policy', 'Bazaarpe processes account, location, pickup, payment-reference and payout details to operate the scrap pickup service.'),
        ('TERMS', '2026.1', 'Bazaarpe Terms and Conditions', 'Users and vendors must provide accurate information and follow the verified pickup, payment and payout workflow.'),
    ]
    for document_type, version, title, content in documents:
        LegalDocument.objects.update_or_create(
            document_type=document_type,
            version=version,
            defaults={'title': title, 'content': content, 'is_active': True},
        )
    PickupOrder = apps.get_model('nainjyoti', 'PickupOrder')
    UserProfile = apps.get_model('nainjyoti', 'UserProfile')
    for order in PickupOrder.objects.filter(assigned_vendor__isnull=True).exclude(assigned_vendor_phone__isnull=True).exclude(assigned_vendor_phone=''):
        digits = ''.join(ch for ch in order.assigned_vendor_phone if ch.isdigit())[-10:]
        profile = UserProfile.objects.filter(phone=digits).first()
        if profile:
            order.assigned_vendor_id = profile.user_id
            order.save(update_fields=['assigned_vendor'])


class Migration(migrations.Migration):
    dependencies = [('nainjyoti', '0005_pickupimage_uploaded_file_and_more')]
    operations = [migrations.RunPython(seed_legal_documents, migrations.RunPython.noop)]
