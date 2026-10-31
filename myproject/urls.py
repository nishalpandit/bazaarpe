import os
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.http import Http404

def static_loader(request, path):
    """
    Static file loader view for cPanel (Passenger WSGI) and production deployments.
    Seamlessly resolves files from STATIC_ROOT (after collectstatic) or falls back
    directly to project static directory (STATICFILES_DIRS / static).
    """
    # 1. Try collected static files if directory exists
    if hasattr(settings, 'STATIC_ROOT') and settings.STATIC_ROOT and os.path.exists(settings.STATIC_ROOT):
        target = os.path.join(settings.STATIC_ROOT, path)
        if os.path.exists(target):
            return serve(request, path, document_root=settings.STATIC_ROOT)

    # 2. Fallback to project static directory (local / uncollected cPanel deploy)
    base_dir = getattr(settings, 'BASE_DIR', None)
    if base_dir:
        fallback_dir = base_dir / 'static'
        if os.path.exists(fallback_dir):
            target = os.path.join(str(fallback_dir), path)
            if os.path.exists(target):
                return serve(request, path, document_root=fallback_dir)

    raise Http404(f"Static file '{path}' not found.")


urlpatterns = [
    # Static and Media loaders placed first to guarantee asset routing on cPanel
    re_path(r'^static/(?P<path>.*)$', static_loader, name='static_loader'),
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}, name='media_loader'),

    path('django-admin/', admin.site.urls),
    path('', include('nainjyoti.urls')),
]

# Standard Django static helper (active when DEBUG=True)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
