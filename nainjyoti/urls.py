from django.urls import path
from . import views
from . import api_views

urlpatterns = [
    # Core Root & Authentication
    path('', views.home_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('login.html', views.login_view, name='login_html'),
    path('admin/login', views.login_view, name='admin_login_redirect'),
    path('logout/', views.logout_view, name='logout'),

    # Admin Operations Dashboard & Direct Templates
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('index.html', views.dashboard_view, name='index_html'),
    path('dashboard/<str:page_name>/', views.page_view, name='dashboard_subpage'),
    path('dashboard/<str:page_name>', views.page_view, name='dashboard_subpage_direct'),

    # Administrative Actions (Manage, Create, Edit, Delete)
    path('admin/<path:action_path>', views.admin_action_view, name='admin_action'),

    # Customer & User Mobile OTP Authentication REST API
    path('api/user/send-otp/', api_views.send_otp_view, name='api_user_send_otp'),
    path('api/user/verify-otp-login/', api_views.verify_otp_login_view, name='api_user_verify_otp_login'),
    path('api/user/login-otp/', api_views.verify_otp_login_view, name='api_user_login_otp'),
    path('api/user/register/', api_views.register_user_view, name='api_user_register'),
    path('api/user/register-otp/', api_views.register_user_view, name='api_user_register_otp'),
    path('api/user/profile/', api_views.user_profile_view, name='api_user_profile'),
    path('api/user/logout/', api_views.logout_api_view, name='api_user_logout'),
    path('api/legal/documents/', api_views.legal_documents_view, name='api_legal_documents'),
    path('api/content/', api_views.content_documents_view, name='api_content_documents'),
    path('api/user/consents/', api_views.user_consents_view, name='api_user_consents'),
    path('api/user/change-phone/request/', api_views.request_phone_change_view, name='api_user_change_phone_request'),
    path('api/user/change-phone/confirm/', api_views.confirm_phone_change_view, name='api_user_change_phone_confirm'),

    # User Location, Maps & Address REST APIs
    path('api/user/location/detect/', api_views.detect_location_view, name='api_user_location_detect'),
    path('api/user/location/confirm/', api_views.confirm_location_view, name='api_user_location_confirm'),
    path('api/user/address/save/', api_views.confirm_location_view, name='api_user_address_save'),
    path('api/user/service-zones/', api_views.service_zones_view, name='api_user_service_zones'),
    path('api/user/cities/', api_views.service_zones_view, name='api_user_cities'),
    path('api/user/addresses/', api_views.user_addresses_view, name='api_user_addresses'),
    path('api/user/addresses/<int:address_id>/', api_views.user_address_detail_view, name='api_user_address_detail'),
    path('api/user/addresses/<int:address_id>/set-default/', api_views.set_default_address_view, name='api_user_address_set_default'),

    # Scrap pricing, pickup orders, vendor operations, billing, and payouts
    path('api/categories/', api_views.categories_view, name='api_categories'),
    path('api/pricing/calculate/', api_views.calculate_pricing_view, name='api_pricing_calculate'),
    path('api/user/orders/create/', api_views.create_pickup_order_view, name='api_user_order_create'),
    path('api/user/orders/history/', api_views.order_history_view, name='api_user_order_history'),
    path('api/user/orders/<str:order_id>/confirm-price/', api_views.confirm_order_price_view, name='api_user_order_confirm_price'),
    path('api/user/orders/<str:order_id>/counter-price/', api_views.counter_order_price_view, name='api_user_order_counter_price'),
    path('api/user/orders/<str:order_id>/negotiations/', api_views.order_negotiations_view, name='api_user_order_negotiations'),
    path('api/user/orders/<str:order_id>/tracking/', api_views.order_tracking_view, name='api_user_order_tracking'),
    path('api/user/orders/<str:order_id>/invoice/', api_views.order_invoice_view, name='api_user_order_invoice'),
    path('api/user/orders/<str:order_id>/review/', api_views.create_order_review_view, name='api_user_order_review'),
    path('api/user/reviews/', api_views.user_reviews_view, name='api_user_reviews'),
    path('api/reviews/', api_views.public_reviews_view, name='api_public_reviews'),
    path('api/user/bank-details/', api_views.user_bank_details_view, name='api_user_bank_details'),
    path('api/user/home/', api_views.user_home_view, name='api_user_home'),
    path('api/user/notifications/', api_views.notifications_view, name='api_user_notifications'),
    path('api/user/notifications/read-all/', api_views.mark_all_notifications_read_view, name='api_user_notifications_read_all'),
    path('api/user/notifications/<int:notification_id>/read/', api_views.mark_notification_read_view, name='api_user_notification_read'),
    path('api/support/', api_views.support_config_view, name='api_support'),
    path('api/orders/<str:order_id>/tracking/', api_views.authorized_order_tracking_view, name='api_authorized_order_tracking'),

    # Vendor app authentication aliases, business profile, KYC, marketplace, and history
    path('api/vendor/auth/send-otp/', api_views.send_otp_view, name='api_vendor_send_otp'),
    path('api/vendor/auth/login-otp/', api_views.verify_otp_login_view, name='api_vendor_login_otp'),
    path('api/vendor/auth/register/', api_views.register_user_view, name='api_vendor_register'),
    path('api/vendor/auth/logout/', api_views.logout_api_view, name='api_vendor_logout'),
    path('api/vendor/terms/', api_views.legal_documents_view, name='api_vendor_terms'),
    path('api/vendor/profile/', api_views.vendor_profile_view, name='api_vendor_profile'),
    path('api/vendor/states-zones/', api_views.vendor_states_zones_view, name='api_vendor_states_zones'),
    path('api/vendor/operating-zones/', api_views.vendor_operating_zones_view, name='api_vendor_operating_zones'),
    path('api/vendor/categories/', api_views.vendor_categories_view, name='api_vendor_categories'),
    path('api/vendor/availability/', api_views.vendor_availability_view, name='api_vendor_availability'),
    path('api/vendor/kyc/', api_views.vendor_kyc_view, name='api_vendor_kyc'),
    path('api/vendor/kyc/aadhaar/initiate/', api_views.vendor_aadhaar_initiate_view, name='api_vendor_aadhaar_initiate'),
    path('api/vendor/kyc/aadhaar/confirm/', api_views.vendor_aadhaar_confirm_view, name='api_vendor_aadhaar_confirm'),
    path('api/vendor/dashboard/', api_views.vendor_dashboard_view, name='api_vendor_dashboard'),
    path('api/vendor/orders/available/', api_views.vendor_available_orders_view, name='api_vendor_available_orders'),
    path('api/vendor/orders/history/', api_views.vendor_order_history_view, name='api_vendor_order_history'),
    path('api/vendor/orders/<str:order_id>/', api_views.vendor_order_detail_view, name='api_vendor_order_detail'),
    path('api/vendor/orders/<str:order_id>/reject/', api_views.vendor_reject_order_view, name='api_vendor_order_reject'),
    path('api/vendor/orders/<str:order_id>/accept/', api_views.vendor_accept_order_view, name='api_vendor_order_accept'),
    path('api/vendor/orders/<str:order_id>/status/', api_views.vendor_order_status_view, name='api_vendor_order_status'),
    path('api/vendor/orders/<str:order_id>/update-location/', api_views.update_vendor_location_view, name='api_vendor_order_location'),
    path('api/vendor/orders/<str:order_id>/pickup-details/', api_views.submit_pickup_details_view, name='api_vendor_order_pickup_details'),
    path('api/vendor/orders/<str:order_id>/verify-otp/', api_views.verify_pickup_otp_view, name='api_vendor_order_verify_otp'),
    path('api/vendor/orders/<str:order_id>/billing/', api_views.vendor_billing_view, name='api_vendor_order_billing'),
    path('api/vendor/orders/<str:order_id>/payment/verify/', api_views.verify_vendor_payment_view, name='api_vendor_payment_verify'),
    path('api/payments/webhook/', api_views.payment_webhook_view, name='api_payment_webhook'),
    path('api/vendor/orders/<str:order_id>/complete/', api_views.complete_pickup_view, name='api_vendor_order_complete'),
    path('api/vendor/orders/<str:order_id>/invoice/', api_views.vendor_invoice_view, name='api_vendor_invoice'),
    path('api/vendor/reviews/', api_views.vendor_reviews_view, name='api_vendor_reviews'),
    path('api/vendor/notifications/', api_views.notifications_view, name='api_vendor_notifications'),
    path('api/vendor/notifications/read-all/', api_views.mark_all_notifications_read_view, name='api_vendor_notifications_read_all'),
    path('api/vendor/notifications/<int:notification_id>/read/', api_views.mark_notification_read_view, name='api_vendor_notification_read'),
    path('api/vendor/refunds/', api_views.vendor_refunds_view, name='api_vendor_refunds'),
    path('api/vendor/refunds/<int:refund_id>/', api_views.vendor_refund_detail_view, name='api_vendor_refund_detail'),

    # Convenience aliases for mobile clients
    path('api/auth/send-otp/', api_views.send_otp_view, name='api_auth_send_otp'),
    path('api/auth/login-otp/', api_views.verify_otp_login_view, name='api_auth_login_otp'),
    path('api/auth/register-otp/', api_views.register_user_view, name='api_auth_register_otp'),

    # Dynamic Admin Template Views (catch-all for HTML pages)
    path('<str:page_name>/', views.page_view, name='page_view'),
    path('<str:page_name>', views.page_view, name='page_view_direct'),
]
