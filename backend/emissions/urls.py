from django.urls import path

from .views import (
    get_records,
    upload_file,
    approve_record,
    reject_record,
    suspicious_records,
    audit_logs,
    batch_list,
    dashboard_summary
)

urlpatterns = [

    path('records/', get_records),

    path('upload/', upload_file),

    path('approve/<str:pk>/', approve_record),

    path('reject/<str:pk>/', reject_record),

    path('suspicious/', suspicious_records),

    path('audit-logs/', audit_logs),
    path('api/batches/', batch_list),
    path('api/summary/', dashboard_summary),
]