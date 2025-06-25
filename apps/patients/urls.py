"""
URL configuration for patients app.
"""
from django.urls import path
from django.http import HttpResponse

app_name = 'patients'

# Placeholder view function
def placeholder_view(request):
    """Temporary placeholder for patient views"""
    return HttpResponse("Patient management features coming soon!")

urlpatterns = [
    # Patient listing and management
    path('', placeholder_view, name='list'),
    path('add/', placeholder_view, name='add'),
    path('<int:pk>/', placeholder_view, name='detail'),
    path('<int:pk>/edit/', placeholder_view, name='edit'),
] 