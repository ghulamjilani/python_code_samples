from django.contrib import admin
from django.db import models
from django.utils.html import format_html
from django.utils.timesince import timesince
from django.utils.timezone import now
from django.utils.translation import gettext as _
from django_json_widget.widgets import JSONEditorWidget

from apps.audit.models import LogSyncHistory, MedMijLog
from utils.config import GlobalConfig

config = GlobalConfig()

@admin.register(LogSyncHistory)
class MedMijSyncHistoryAdmin(admin.ModelAdmin):
    list_display = ('sync_date', 'time_since_sync', 'logs_sent', 'sync_success', 'result_html')
    list_filter = [("sync_success")]
    def time_since_sync(self, obj):
        if obj.sync_date:
            return format_html('{} {}', timesince(obj.sync_date, now()), _("ago"))
        return '--'

    time_since_sync.short_description = _('Synchronized')

    def result_html(self, obj):
        from django.utils.safestring import mark_safe
        return mark_safe(obj.result.replace('\n', '<br>'))

    result_html.short_description = 'Details'


@admin.action(description='Update sync state to True')
def update_sync_state(modeladmin, request, queryset):
    queryset.update(is_synced=True, sync_date=now())
@admin.register(MedMijLog)
class MedMijLogAdmin(admin.ModelAdmin):

    search_fields = [
        'user__username', "log__event__type", "log__request__id"
    ]
    list_display = ('medmijlog_id', 'user', 'event_type', 'trace_id', 'request_id', 'description',
                    'is_synced', 'sync_date', 'event_date')
    formfield_overrides = {
        models.JSONField: {'widget': JSONEditorWidget(height="300px")},
    }
    list_filter = [
        ("is_synced")
    ]
    list_per_page = 20
    actions = [update_sync_state]

    
    def medmijlog_id(self, obj):
        return obj.id if obj.id else ''
    medmijlog_id.short_description = 'ID'

    def has_add_permission(self, request):
        return config.dev_mode
        # return False

    def has_delete_permission(self, request, obj=None):
        return config.dev_mode
        # return False

    def has_change_permission(self, request, obj=None):
        return config.dev_mode
