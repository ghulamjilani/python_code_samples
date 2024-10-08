from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Admin, Biller, Manager, Mechanic, Superuser
from .forms import UserCreationForm, UserChangeForm


class UserAdmin(BaseUserAdmin):

    fieldsets = (
        (None, {'fields': ('email', 'password',)}),
        ('Personal info', {'fields': ('first_name', 'last_name',)}),
        ('Important dates', {'fields': ('last_login', 'date_joined',)}),
        ('Settings',
            {'fields': ('status', 'sent_email_notifications', 'sent_push_notifications',)}),
    )
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'password1', 'password2',)
            }
        ),
    )
    form = UserChangeForm
    add_form = UserCreationForm

    empty_value_display = 'unknown'
    list_display = ('__str__', 'email', 'date_joined', 'status')
    list_display_links = ('__str__', 'email',)
    list_filter = ('date_joined', 'status')

    readonly_fields = ('last_login', 'date_joined',)
    search_fields = ('first_name', 'last_name', 'email',)
    ordering = ('email',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'manager':
            # If the user is a mechanic, filter the managers in the dropdown
            kwargs['queryset'] = Manager.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


    def get_fieldsets(self, request, obj=None):
        if obj and obj.is_mechanic:
            # If the user is a mechanic, include the 'manager' field in the fieldsets
            return super().get_fieldsets(request, obj) + (
                ('Settings', {'fields': ('status', 'manager', 'sent_email_notifications', 'sent_push_notifications',)}),
            )
        return super().get_fieldsets(request, obj)
    


@admin.register(Admin)
class AdminAdmin(UserAdmin):
    pass


@admin.register(Biller)
class BillerAdmin(UserAdmin):
    pass


@admin.register(Manager)
class ManagerAdmin(UserAdmin):
    pass


@admin.register(Mechanic)
class MechanicAdmin(UserAdmin):
    pass


@admin.register(Superuser)
class SuperuserAdmin(UserAdmin):
    pass
