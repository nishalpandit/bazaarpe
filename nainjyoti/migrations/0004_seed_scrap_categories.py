from django.db import migrations


DEFAULTS = {
    'Paper': ('newspaper', [
        ('Newspaper', '18.00', '18.00', '5.00'),
        ('Corrugated Cardboard', '12.00', '18.00', '5.00'),
        ('Office Paper', '16.00', '18.00', '5.00'),
    ]),
    'Metal': ('recycle', [
        ('Copper Wire', '650.00', '18.00', '2.00'),
        ('Iron Scrap', '40.00', '18.00', '5.00'),
        ('Aluminium', '145.00', '18.00', '3.00'),
    ]),
    'Plastic': ('bottle', [
        ('PET Bottles', '22.00', '18.00', '5.00'),
        ('Hard Plastic', '28.00', '18.00', '5.00'),
    ]),
    'E-waste': ('cpu', [
        ('Mixed Electronics', '75.00', '18.00', '2.00'),
        ('Computer Components', '180.00', '18.00', '1.00'),
    ]),
}


def seed_catalogue(apps, schema_editor):
    Category = apps.get_model('nainjyoti', 'ScrapCategory')
    SubCategory = apps.get_model('nainjyoti', 'ScrapSubCategory')
    for category_name, (icon, subcategories) in DEFAULTS.items():
        category, _ = Category.objects.update_or_create(
            name=category_name,
            defaults={'icon': icon, 'is_active': True},
        )
        for name, rate, gst, minimum in subcategories:
            SubCategory.objects.update_or_create(
                category=category,
                name=name,
                defaults={
                    'rate_per_kg': rate,
                    'gst_percent': gst,
                    'min_weight_kg': minimum,
                    'is_active': True,
                },
            )


class Migration(migrations.Migration):
    dependencies = [('nainjyoti', '0003_scrapcategory_pickuporder_pickupimage_orderinvoice_and_more')]

    operations = [migrations.RunPython(seed_catalogue, migrations.RunPython.noop)]
