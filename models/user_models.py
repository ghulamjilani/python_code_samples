from datetime import datetime, timedelta

from django.contrib.auth.models import (
    AbstractBaseUser, Permission, PermissionsMixin,
)
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from .managers import (
    AdminUserManager, BillerUserManager, ManagerUserManager, MechanicUserManager, UserManager,
    SuperuserManager
)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model.
    """

    ACTIVE = 1
    ARCHIVED = 2

    STATUSES = (
        (ACTIVE, 'Active',),
        (ARCHIVED, 'Archived',),
    )

    first_name = models.CharField(_('First name'), max_length=50)
    last_name = models.CharField(_('Last name'), max_length=50)
    email = models.EmailField(_('Email'), unique=True)
    date_joined = models.DateTimeField(_('Date joined'), auto_now_add=True)
    is_staff = models.BooleanField(_('Is staff'), default=True)
    is_confirmed_email = models.BooleanField(_('Email confirmed'), default=False)
    manager = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,related_name='Managers')
    status = models.PositiveSmallIntegerField(
        _('Status'),
        choices=STATUSES,
        default=ACTIVE,
    )
    sent_email_notifications = models.BooleanField(_('Sent Email Notifications'), default=True)
    sent_push_notifications = models.BooleanField(_('Sent Push Notifications'), default=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def get_short_name(self):
        return self.first_name

    def get_full_name(self):
        """
        Returns user's concatenated first and last name
        """
        return '{0} {1}'.format(self.first_name, self.last_name)

    def __str__(self):
        return self.get_full_name()

    @property
    def is_admin(self):
        return self.groups.filter(name='admin').exists()

    @property
    def is_manager(self):
        return self.groups.filter(name='Manager').exists()

    @property
    def is_biller(self):
        return self.groups.filter(name='Biller').exists()

    @property
    def is_mechanic(self):
        return self.groups.filter(name='Mechanic').exists()

    @property
    def is_status_archived(self):
        return self.status == 2  # Archived


class Admin(User):
    """
    admin proxy model.
    """

    objects = AdminUserManager()

    class Meta:
        proxy = True
        verbose_name = 'admin'
        verbose_name_plural = 'Admins'
        permissions = [
            ('can_archive_users', 'Can set Archive Users'),
            ('can_restore_users', 'Can set Restore Users'),
            ('can_get_reports', 'Can get Reports'),
            ('can_editing_approved_st', 'Can editing approved service tickets')
        ]

    def save(self, *args, **kwargs):
        """Set all permissions to admin users."""
        is_new = self.pk is None
        if is_new:
            self.is_superuser = True
        super(User, self).save(*args, **kwargs)


class Biller(User):
    """
    Biller proxy model.
    """

    objects = BillerUserManager()

    class Meta:
        proxy = True
        verbose_name = 'Biller'
        verbose_name_plural = 'Billers'


class Manager(User):
    """
    Manager proxy model.
    """

    objects = ManagerUserManager()

    class Meta:
        proxy = True
        verbose_name = 'Manager'
        verbose_name_plural = 'Managers'


class Mechanic(User):
    """
    Mechanic proxy model.
    """

    objects = MechanicUserManager()

    class Meta:
        proxy = True
        verbose_name = 'Mechanic'
        verbose_name_plural = 'Mechanics'

    def get_unique_indirect_hours(self, queryset):
        # TODO: Optimize it
        unique_time_codes = set(queryset.values_list('time_code__name', flat=True))
        unique_indirect_hours = {time_code: 0 for time_code in unique_time_codes}
        for indirect_hour in queryset:
            unique_indirect_hours[indirect_hour.time_code.name] += indirect_hour.hours
        return unique_indirect_hours

    def get_total_working_time(self, start_date, end_date):
        # TODO: Optimize it
        from apps.api.models import CommonInfo
        qs = self.employeeworkblock_set.filter(
            service_ticket__status=CommonInfo.APPROVED,
            service_ticket__date__gte=start_date,
            service_ticket__date__lte=end_date,
            service_ticket__is_archive=False,
            start_time__isnull=False,
            end_time__isnull=False
        )
        sum = 0
        for instance in qs:
            sum += instance.hours_worked.total_seconds()
        return round(sum / 3600, 2)


class Superuser(User):
    """
    Superuser proxy model.
    """

    objects = SuperuserManager()

    class Meta:
        proxy = True
        verbose_name = 'Superuser'
        verbose_name_plural = 'Superusers'
