"""
URL configuration for meddocparser project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from django.http import HttpResponse

# Simple placeholder view for missing URLs
def placeholder_view(request):
    """Temporary placeholder for unimplemented views"""
    return HttpResponse("This feature is coming soon!")

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    
    # Authentication (django-allauth)
    path('accounts/', include('allauth.urls')),
    
    # Dashboard and user management
    path('dashboard/', include('apps.accounts.urls')),
    
    # Home page - redirect to dashboard if logged in
    path('', RedirectView.as_view(url='/dashboard/', permanent=False), name='home'),
    
    # App URLs
    path('core/', include('apps.core.urls')),  # HIPAA audit trail and compliance
    path('documents/', include('apps.documents.urls')),
    path('patients/', include('apps.patients.urls')),
    path('providers/', include('apps.providers.urls')),
    path('fhir/', include('apps.fhir.urls')),
    path('reports/', include('apps.reports.urls')),
    
    # Placeholder URLs for base template links
    path('help/', placeholder_view, name='help'),
    path('privacy/', placeholder_view, name='privacy'),
    path('terms/', placeholder_view, name='terms'),
]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
    # Debug toolbar
    if 'debug_toolbar' in settings.INSTALLED_APPS:
        import debug_toolbar
        urlpatterns = [
            path('__debug__/', include(debug_toolbar.urls)),
        ] + urlpatterns
