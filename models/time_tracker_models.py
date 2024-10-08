from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.utils.safestring import mark_safe

from apps.utils.notifications import IndirectHoursActionNotifications
from .model_validators import validate_perm
from auditlog.registry import auditlog


class TimeCode(models.Model):
    """
    Time code model. Store time codes for the Indirect hours.
    """
    name = models.CharField(_('Time Code'), max_length=48, unique=True)

    def __str__(self):
        return self.name


class IndirectHours(models.Model, IndirectHoursActionNotifications):
    """
    IndirectHours is a model that keeps tracking hours of mechanics.

    ``model FK``
        :model:`authentication.Mechanic`
    ``model FK``
        :model:`time_tracker.TimeCode`

    """
    PENDING_FOR_APPROVAL = 1
    REJECTED = 2
    APPROVED = 3

    STATUSES = (
        (PENDING_FOR_APPROVAL, 'Pending for Approval',),
        (REJECTED, 'Rejected',),
        (APPROVED, 'Approved',),
    )

    creation_date = models.DateField(_('Creation Date'), auto_now_add=True)
    update_date = models.DateField(_('Update Date'), auto_now=True)

    status = models.PositiveSmallIntegerField(
        _('Status'),
        choices=STATUSES,
        default=PENDING_FOR_APPROVAL,
        validators=[validate_perm]
    )
    date = models.DateField(_('Date'))
    hours = models.DecimalField(
        _('Spent Hours'),
        max_digits=5,
        decimal_places=2,
        validators=[MaxValueValidator(Decimal('24'))])
    time_code = models.ForeignKey(
        'time_tracker.TimeCode',
        related_name='time_code',
        on_delete=models.PROTECT
    )
    notes = models.CharField(_('Notes'), max_length=255)
    # mechanic_old = models.ForeignKey('authentication.Mechanic',related_name="mechanic", on_delete=models.CASCADE)
    mechanic = models.ManyToManyField('authentication.Mechanic',verbose_name=_('Mechanics'))
    is_archive = models.BooleanField(_('Is archive'), default=False)


    class Meta:
        verbose_name = _('Indirect Hours')
        verbose_name_plural = _('Indirect Hours')
        permissions = [
            ('can_approve_indirect_hours', 'Can approve Indirect Hours'),
            ('can_reject_indirect_hours', 'Can reject Indirect Hours'),
            ('can_archive_indirect_hours', 'Can set Archive IndirectHours'),
            ('can_restore_indirect_hours', 'Can set Restore IndirectHours')
        ]

    def __str__(self):
        return f'Hours of {"  ".join([str(p) for p in self.mechanic.all()])}'

    def clean(self):
        if self.pk is None and self.status != self.PENDING_FOR_APPROVAL:
            raise ValidationError(
                mark_safe({'status': 'You cannot create a Indirect Hours with this status.'})
            )
        super(IndirectHours, self).clean()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # self.run_notifications

auditlog.register(IndirectHours, m2m_fields={"mechanic"})