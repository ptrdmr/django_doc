"""
URL configuration for providers app.
"""
from django.urls import path
from django.http import HttpResponse

app_name = 'providers'

# Placeholder view function
def placeholder_view(request):
    """Temporary placeholder for provider views"""
    return HttpResponse("Provider management features coming soon!")

urlpatterns = [
    # Provider listing and management
    path('', placeholder_view, name='list'),
    path('add/', placeholder_view, name='add'),
    path('<int:pk>/', placeholder_view, name='detail'),
    path('<int:pk>/edit/', placeholder_view, name='edit'),
] 