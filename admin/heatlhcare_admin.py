from datetime import datetime

from django.contrib import admin
from django.db import models
from django_json_widget.widgets import JSONEditorWidget

from apps.healthcare import models as model
from utils.config import GlobalConfig

config = GlobalConfig()

@admin.register(model.Medication)
class MedicationAdmin(admin.ModelAdmin):
    search_fields = [
        'patient__username', "resource_id", "profile"
    ]
    list_display = [
        'identifier',
        'reference',
        'title',
        'profile',
        'resource_type',
        'status',
        'patient'
    ]

    def has_add_permission(self, request):
        return config.dev_mode

    def has_delete_permission(self, request, obj=None):
        return config.dev_mode

    def has_change_permission(self, request, obj=None):
        return config.dev_mode


@admin.register(model.SharedDocuments)
class SharedDocumentsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return config.dev_mode
        # return False

    def has_delete_permission(self, request, obj=None):
        return config.dev_mode
        # return False

    def has_change_permission(self, request, obj=None):
        return config.dev_mode


@admin.action(description='Update fetched date')
def update_resource_date(modeladmin, request, queryset):
    queryset.update(fetched_at=datetime.now())


@admin.register(model.FhirResource)
class ResourceAdmin(admin.ModelAdmin):
    list_filter = [
        ("data_source__service", admin.RelatedFieldListFilter),
        ("resource_type"),

    ]
    readonly_fields = ["data_source", "users"]
    formfield_overrides = {
        models.JSONField: {'widget': JSONEditorWidget(height="600px")},
    }
    actions = [update_resource_date]

    def has_add_permission(self, request):
        return config.dev_mode
        # return False

    def has_delete_permission(self, request, obj=None):
        return config.dev_mode
        # return False

    def has_change_permission(self, request, obj=None):
        return config.dev_mode
        # return False
    """
    search_fields = [
        'resource_id', "resource_type", "api_source", "users__username"
    ]
    list_display = [
        'id',
        'resource_type',
        'resource_id',
        'data_source',
        'api_source'
    ]
    """

@admin.register(model.TerminologyCode)
class TerminologyAdmin(admin.ModelAdmin):
    search_fields = [
        'code',
        'system'
    ]
    list_display = [
        'id',
        'code',
        'system',
        'description'
    ]
    readonly_fields = [
        'id',
        'code',
        'system',
        'description'
    ]


    def has_add_permission(self, request):
        return config.dev_mode

    def has_delete_permission(self, request, obj=None):
        return config.dev_mode








