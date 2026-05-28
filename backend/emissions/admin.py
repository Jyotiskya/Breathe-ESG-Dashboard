from django.contrib import admin

from .models import (
    Company,
    EmissionRecord,
    AuditLog
)

admin.site.register(Company)
admin.site.register(EmissionRecord)
admin.site.register(AuditLog)