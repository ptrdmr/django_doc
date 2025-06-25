"""
URL configuration for documents app.
"""
from django.urls import path
from django.http import HttpResponse

app_name = 'documents'

# Placeholder view function
def placeholder_view(request):
    """Temporary placeholder for document views"""
    return HttpResponse("Document processing features coming soon!")

urlpatterns = [
    # Document upload and management
    path('', placeholder_view, name='list'),
    path('upload/', placeholder_view, name='upload'),
    path('<int:pk>/', placeholder_view, name='detail'),
    path('<int:pk>/process/', placeholder_view, name='process'),
] 