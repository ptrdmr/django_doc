"""
URL configuration for reports app.
"""
from django.urls import path
from django.http import HttpResponse

app_name = 'reports'

# Placeholder view function
def placeholder_view(request):
    """Temporary placeholder for report views"""
    return HttpResponse("Reporting features coming soon!")

urlpatterns = [
    # Reports dashboard and management
    path('', placeholder_view, name='dashboard'),
    path('audit/', placeholder_view, name='audit'),
    path('analytics/', placeholder_view, name='analytics'),
    path('export/', placeholder_view, name='export'),
] 