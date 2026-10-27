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

    # User Location, Maps & Address REST APIs
    path('api/user/location/detect/', api_views.detect_location_view, name='api_user_location_detect'),
    path('api/user/location/confirm/', api_views.confirm_location_view, name='api_user_location_confirm'),
    path('api/user/address/save/', api_views.confirm_location_view, name='api_user_address_save'),
    path('api/user/service-zones/', api_views.service_zones_view, name='api_user_service_zones'),
    path('api/user/cities/', api_views.service_zones_view, name='api_user_cities'),
    path('api/user/addresses/', api_views.user_addresses_view, name='api_user_addresses'),
    path('api/user/addresses/<int:address_id>/', api_views.user_address_detail_view, name='api_user_address_detail'),
    path('api/user/addresses/<int:address_id>/set-default/', api_views.set_default_address_view, name='api_user_address_set_default'),

    # Convenience aliases for mobile clients
    path('api/auth/send-otp/', api_views.send_otp_view, name='api_auth_send_otp'),
    path('api/auth/login-otp/', api_views.verify_otp_login_view, name='api_auth_login_otp'),
    path('api/auth/register-otp/', api_views.register_user_view, name='api_auth_register_otp'),

    # Dynamic Admin Template Views (catch-all for HTML pages)
    path('<str:page_name>/', views.page_view, name='page_view'),
    path('<str:page_name>', views.page_view, name='page_view_direct'),
]
