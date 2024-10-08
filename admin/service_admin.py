from django.contrib import admin
from django.contrib.admin.models import LogEntry, DELETION
from django.utils.safestring import mark_safe
from django.utils.html import escape
from django.utils.translation import gettext_lazy as _
from django.urls import reverse
from django.contrib.admin import widgets
from django.contrib.admin.options import get_ul_class
from .models import Attachment, Customer, Location, EmployeeWorkBlock, Job, ServiceTicket, Settings

class ServiceTicketGeneralInfo:

    def get_job_status(self, obj):
        return obj.connected_job.get_status_display()
    get_job_status.short_description = 'Job Status'

    def get_job_customer(self, obj):
        return obj.connected_job.customer
    get_job_customer.short_description = 'Customer'

    def get_job_location(self, obj):
        return obj.connected_job.location
    get_job_location.short_description = 'Location'

    def get_job_number(self, obj):
        return obj.connected_job.number
    get_job_number.short_description = 'Number'


class ServiceTicketInline(ServiceTicketGeneralInfo, admin.TabularInline):
    model = ServiceTicket
    fk_name = 'connected_job'
    fields = (
        'get_title', 'get_job_status', 'get_job_location', 'get_job_customer', 'status',
        'additional_notes',
    )
    readonly_fields = fields  # make the form readonly completely
    max_num = 0

    def get_title(self, obj):
        url = reverse('admin:api_serviceticket_change', args=[obj.id])
        return mark_safe(f'<a href=\'{url}\'>{escape(str(obj))}</a>')
    get_title.short_description = 'Title'

    def has_change_permission(self, request, obj=None):
        return False


class EmployeeWorkBlockInLine(admin.TabularInline):
    model = EmployeeWorkBlock
    extra = 0
    fields = (
        'employee', 'start_time', 'end_time', 'mileage', 'hotel', 'per_diem', 'get_hours_worked',
    )
    readonly_fields = ('get_hours_worked',)

    def get_hours_worked(self, obj):
        if obj.hours_worked:
            return '%d:%02d' % divmod(divmod(obj.hours_worked.total_seconds(), 60)[0], 60)
    get_hours_worked.short_description = 'Total Hours Worked'


class AttachmentInLine(admin.TabularInline):
    model = Attachment
    extra = 0


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    fields = (
        'created_by', 'requester', 'approval', 'status', 'description', 'customer', 'location',
        'number', 'number_id', 'mechanics', 'managers', 'is_archive',
    )
    readonly_fields = ('number_id', 'requester', 'approval', 'is_archive',)
    list_display = (
        '__str__', 'status', 'location', 'customer', 'creation_date',
        'get_service_tickets_count', 'is_archive',
    )
    inlines = [ServiceTicketInline]
    search_fields = ['number']
    ordering = ("-number",)
    def get_service_tickets_count(self, obj):
        return obj.serviceticket_set.count()
    get_service_tickets_count.short_description = 'Service Tickets'

# class JobFilter(AutocompleteFilter):
#     title = 'Jobs' # display title
#     field_name = 'connected_job' # name of the foreign key field

@admin.register(ServiceTicket)
class ServiceTicketAdmin(ServiceTicketGeneralInfo, admin.ModelAdmin):
    list_display = (
        '__str__', 'get_job_status', 'get_job_location', 'get_job_customer', 'status',
        'additional_notes', 'get_job_number', 'is_archive',
    )
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'connected_job':
            kwargs['queryset'] = Job.objects.filter(status=1).order_by('-number')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    readonly_fields = ('is_archive', 'requester', 'approval',)
    search_fields = ['id']
    inlines = (EmployeeWorkBlockInLine, AttachmentInLine,)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('__str__',)
    filter_horizontal = ('locations',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    pass


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):

    date_hierarchy = 'action_time'

    list_filter = [
        'user',
        'content_type',
        'action_flag'
    ]

    search_fields = [
        'object_repr',
        'change_message'
    ]

    list_display = [
        'action_time',
        'user',
        'content_type',
        'object_link',
        'action_flag_',
        'change_message',
    ]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.get_fields()]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser and request.method != 'POST'

    def has_delete_permission(self, request, obj=None):
        return False

    def action_flag_(self, obj):
        flags = {
            1: _("Addition"),
            2: _("Changed"),
            3: _("Deleted"),
        }
        return flags[obj.action_flag]

    def object_link(self, obj):
        if obj.action_flag == DELETION:
            link = escape(obj.object_repr)
        else:
            ct = obj.content_type
            link = mark_safe(
                '<a href="{link}">{text}</a>'.format(
                    link=reverse('admin:%s_%s_change' % (ct.app_label, ct.model), args=[obj.object_id]),
                    text=escape(obj.object_repr),
                )
            )
        return link
    object_link.admin_order_field = 'object_repr'
    object_link.short_description = 'object'


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
