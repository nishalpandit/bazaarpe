from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from nainjyoti.models import PickupOrder, UserNotification


class Command(BaseCommand):
    help = 'Idempotently flag published orders whose vendor-acceptance deadline expired.'

    def handle(self, *args, **options):
        now = timezone.now()
        with transaction.atomic():
            orders = list(PickupOrder.objects.select_for_update().filter(
                status=PickupOrder.Status.SEARCHING_VENDOR,
                assigned_vendor__isnull=True,
                acceptance_deadline__lt=now,
                is_escalated=False,
            ))
            for order in orders:
                order.is_escalated = True
                order.escalated_at = now
                order.save(update_fields=['is_escalated', 'escalated_at', 'updated_at'])
                UserNotification.objects.create(
                    user=order.user,
                    order=order,
                    event_type=UserNotification.EventType.STATUS_UPDATED,
                    title='Vendor search escalated',
                    message=f'{order.order_id} is still awaiting admin-assisted assignment.',
                )
        self.stdout.write(self.style.SUCCESS(f'Escalated {len(orders)} order(s).'))
