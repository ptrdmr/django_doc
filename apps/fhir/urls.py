"""
URL configuration for fhir app.
"""
from django.urls import path
from . import api_views, merge_api_views, dashboard_views

app_name = 'fhir'

urlpatterns = [
    # Configuration management API
    path('api/configurations/', api_views.list_configurations, name='api_list_configurations'),
    path('api/configurations/<int:config_id>/', api_views.get_configuration, name='api_get_configuration'),
    path('api/configurations/default/', api_views.get_configuration, name='api_get_default_configuration'),
    path('api/configurations/create/', api_views.create_configuration, name='api_create_configuration'),
    path('api/configurations/<int:config_id>/update/', api_views.update_configuration, name='api_update_configuration'),
    path('api/configurations/<int:config_id>/set-default/', api_views.set_default_configuration, name='api_set_default_configuration'),
    path('api/configurations/<int:config_id>/activate/', api_views.activate_configuration, name='api_activate_configuration'),
    path('api/configurations/<int:config_id>/deactivate/', api_views.deactivate_configuration, name='api_deactivate_configuration'),
    
    # FHIR Merge Operations API
    path('api/merge/trigger/', merge_api_views.trigger_merge_operation, name='api_trigger_merge_operation'),
    path('api/merge/operations/', merge_api_views.list_merge_operations, name='api_list_merge_operations'),
    path('api/merge/operations/<uuid:operation_id>/', merge_api_views.get_merge_operation_status, name='api_get_merge_operation_status'),
    path('api/merge/operations/<uuid:operation_id>/result/', merge_api_views.get_merge_operation_result, name='api_get_merge_operation_result'),
    path('api/merge/operations/<uuid:operation_id>/cancel/', merge_api_views.cancel_merge_operation, name='api_cancel_merge_operation'),
    
    # Performance Monitoring Dashboard
    path('dashboard/', dashboard_views.performance_dashboard, name='performance_dashboard'),
    path('api/performance-metrics/', dashboard_views.api_performance_metrics, name='api_performance_metrics'),
    path('api/system-health/', dashboard_views.api_system_health, name='api_system_health'),
    path('api/clear-cache/', dashboard_views.api_clear_cache, name='api_clear_cache'),
    path('api/operations/<uuid:operation_id>/details/', dashboard_views.api_operation_details, name='api_operation_details'),
] 