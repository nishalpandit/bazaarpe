from django.contrib import admin

from .models import (
    ScrapCategory, ScrapSubCategory, PickupOrder, PickupImage,
    VendorLocationTrack, OrderInvoice, OrderReview, UserBankDetail,
    LegalDocument, UserConsent, NegotiationProposal, UserNotification,
    PaymentTransaction, PaymentWebhookEvent,
    VendorProfile, VendorOfferRejection, VendorBillingSetting, RefundRequest,
    PlatformConfiguration, MarketplaceAuditLog,
)


@admin.register(ScrapCategory)
class ScrapCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    list_filter = ('is_active',)


@admin.register(ScrapSubCategory)
class ScrapSubCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'rate_per_kg', 'gst_percent', 'min_weight_kg', 'is_active')
    list_filter = ('category', 'is_active')


@admin.register(PickupOrder)
class PickupOrderAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'user', 'subcategory', 'pickup_date', 'status', 'final_agreed_price', 'payout_status')
    list_filter = ('status', 'payout_status', 'pickup_date', 'category')
    search_fields = ('order_id', 'user__username', 'assigned_vendor_name', 'assigned_vendor_phone')
    readonly_fields = ('order_id', 'pickup_otp', 'created_at', 'updated_at')


@admin.register(OrderReview)
class OrderReviewAdmin(admin.ModelAdmin):
    list_display = ('order', 'user', 'rating', 'is_approved_by_admin', 'created_at')
    list_filter = ('rating', 'is_approved_by_admin')


@admin.register(OrderInvoice)
class OrderInvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'order', 'payment_status', 'total_paid_by_vendor', 'paid_at')
    list_filter = ('payment_status',)


admin.site.register(PickupImage)
admin.site.register(VendorLocationTrack)
admin.site.register(UserBankDetail)
admin.site.register(LegalDocument)
admin.site.register(UserConsent)
admin.site.register(NegotiationProposal)
admin.site.register(UserNotification)
admin.site.register(PaymentTransaction)
admin.site.register(PaymentWebhookEvent)
admin.site.register(VendorProfile)
admin.site.register(VendorOfferRejection)
admin.site.register(VendorBillingSetting)
admin.site.register(RefundRequest)
admin.site.register(PlatformConfiguration)
admin.site.register(MarketplaceAuditLog)
