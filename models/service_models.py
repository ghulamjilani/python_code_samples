from auditlog.registry import auditlog

from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe
# from django.contrib.postgres.fields.citext import CICharField

from apps.authentication.models import Manager, Mechanic
from apps.utils.clean_single_field import CleanFieldsModelMixin
from apps.utils.fields import DecimalField
from apps.utils.request_middleware import RequestMiddleware
from apps.utils.clean_single_field import CleanFieldsModelMixin
from apps.utils.fields import DecimalField
from apps.utils.notifications import JobActionNotifications, ServiceTicketActionNotifications
from .constants import US_STATES
from .model_validators import validate_attachment_file_type, validate_request_job_perm
from .utils import delete_file, get_customer_signature_img_path, get_file_attachment_path
from solo.models import SingletonModel


class DBLockDate(SingletonModel):
    lock_date = models.DateField(_("DB Lock Date"), null=True, blank=True)


class CommonInfo(CleanFieldsModelMixin, models.Model):

    class Meta:
        abstract = True

    OPEN = 1
    PENDING_FOR_APPROVAL = 2
    REJECTED = 3
    APPROVED = 4

    STATUSES = (
        (OPEN, 'Open',),
        (PENDING_FOR_APPROVAL, 'Pending for Approval',),
        (REJECTED, 'Rejected',),
        (APPROVED, 'Approved',),
    )

    # who has transferred the ST and Job status from 1 to 2
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name='%(class)s_relate_requester'
    )

    # who has transferred the ST and Job status to 4
    approval = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name='%(class)s_relate_approval'
    )

    creation_date = models.DateTimeField(_('Creation Date'), auto_now_add=True)
    update_date = models.DateField(_('Update Date'), auto_now=True)

    is_archive = models.BooleanField(_('Is archive'), default=False)

    def validate_status(self):
        if self._status_validation_check(CommonInfo.OPEN):
            raise ValidationError({'status': mark_safe(self._error_message())})

        if self._status_validation_check(CommonInfo.REJECTED):
            raise ValidationError({'status': mark_safe(self._error_message())})

        if self._status_validation_check(CommonInfo.APPROVED):
            raise ValidationError({'status': mark_safe(self._error_message())})

    def _error_message(self):
        status_dict = dict(CommonInfo.STATUSES)
        return f"{status_dict.get(self._original_status)} " \
            f"status can only be transferred to {status_dict.get(CommonInfo.PENDING_FOR_APPROVAL)}"

    def _is_original_status(self, status):
        return self._original_status == status

    def _status_validation_check(self, status):
        is_list_of_statuses = self.status in [status, CommonInfo.PENDING_FOR_APPROVAL]
        is_original_status = self._is_original_status(status)
        if is_original_status and not is_list_of_statuses:
            return True
        return False

    def save(self, *args, **kwargs):
        if self._original_status == CommonInfo.OPEN and self.status == CommonInfo.PENDING_FOR_APPROVAL:
            self.requester = RequestMiddleware.get_request().user
        if self.status == CommonInfo.OPEN:
            self.requester = None

        if self._original_status == CommonInfo.PENDING_FOR_APPROVAL and self.status == CommonInfo.APPROVED:
            self.approval = RequestMiddleware.get_request().user
        elif self.status == CommonInfo.PENDING_FOR_APPROVAL:
            self.approval = None
        super().save(*args, **kwargs)
        # creation of notifications
        self.run_notifications


class Settings(models.Model):
    """Singletone Model with custom settings."""
    job_number_starting_point = models.PositiveIntegerField(
        default=1,
        validators=[MaxValueValidator(99999)],
        verbose_name=_('Job number starting point')
    )

    class Meta:
        verbose_name_plural = _('Settings')

    def __str__(self):
        return 'Settings'

    def save(self, *args, **kwargs):
        """Disable creating new instances."""
        if not self.pk and Settings.objects.exists():
            raise ValidationError('There is can be only one Settings instance')
        return super(Settings, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Blocked delete method."""
        pass


class Location(models.Model):
    """
    Location model.
    """
    name = models.CharField(_('Location code name'), max_length=4, unique=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.upper()
        return super().save(*args, **kwargs)


class Customer(models.Model):
    """
    Customer model.
    """
    name = models.CharField(_('Customer name'), max_length=255, unique=True)
    locations = models.ManyToManyField(Location, verbose_name=_('Locations'))

    def __str__(self):
        return self.name


class Job(CommonInfo, JobActionNotifications):
    """
    Job model.
    """
    # currently this field uses User model,
    # after requirements clarifications set the appropriate one
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_by',

    )

    status = models.PositiveSmallIntegerField(
        _('Status'),
        choices=CommonInfo.STATUSES,
        default=CommonInfo.OPEN,
        validators=[validate_request_job_perm]
    )

    request_date = models.DateTimeField(_('Request date'), null=True, blank=True)
    description = models.CharField(_('Description'), max_length=255, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    number = models.CharField(_('Job number'), max_length=50, unique=True)
    number_id = models.PositiveIntegerField(_('Job number starting point'), null=True, blank=True)
    mechanics = models.ManyToManyField(
        Mechanic, blank=True, related_name='mechanics', verbose_name=_('Mechanics')
    )
    managers = models.ManyToManyField(
        Manager, blank=True, related_name='managers', verbose_name=_('Managers')
    )

    class Meta:
        permissions = [
            ('can_set_pending_for_approval_job', 'Can set Job status Pending for Approval'),
            ('can_archive_jobs', 'Can set Archive Jobs'),
            ('can_restore_jobs', 'Can set Restore Jobs')
        ]

    def __init__(self, *args, **kwargs):
        super(Job, self).__init__(*args, **kwargs)
        self._original_status = self.status

    def __str__(self):
        return f'Job #{self.number}'

    def generate_number(self):
        if self.number_id is None:
            last_job = Job.objects.last()
            settings_number_id = Settings.objects.get().job_number_starting_point
            if last_job is None or settings_number_id > last_job.number_id:
                self.number_id = settings_number_id
            else:
                self.number_id = last_job.number_id + 1
        return f'{date.today().strftime("%y%m")}-{"{:04d}".format(self.number_id)}'

    def clean_status(self):
        self.validate_status()
        if self._is_status_check(CommonInfo.PENDING_FOR_APPROVAL):
            self._if_all_service_tickets_in_status_aproved()

        if self._is_status_check(CommonInfo.APPROVED):
            self._if_can_a_role_change_status()
            self._if_all_service_tickets_in_status_aproved()
        return self.status

    @property
    def time_worked(self):
        work_blocks = list(EmployeeWorkBlock.objects.filter(service_ticket__connected_job_id=self.id))
        total_time = timedelta(0)
        for wb in work_blocks:
            if wb.hours_worked:
                total_time += wb.hours_worked
        return total_time/timedelta(hours=1)

    def _if_all_service_tickets_in_status_aproved(self):
        service_tickets = ServiceTicket.objects.filter(connected_job=self)
        if service_tickets.exclude(status=CommonInfo.APPROVED).exists():
            raise ValidationError(
                    mark_safe(
                        "Not all \"Service ticket\" are Approved yet"
                    )
                )

    # do not use in this implementation
    def _if_role_not_admin(self):
        requester = RequestMiddleware.get_request().user
        status_dict = dict(self.STATUSES)
        if requester.is_admin:
            raise ValidationError(
                mark_safe(
                    _(f"You do not have permissions to set {status_dict.get(self.PENDING_FOR_APPROVAL)} status.")
                )
            )

    def _if_can_a_role_change_status(self):
        requester = RequestMiddleware.get_request().user

        if self.requester.is_biller and not requester.is_superuser:
            if not requester.is_manager and not requester.is_admin:
                self._error_message_closed_status()

        if self.requester.is_manager and not requester.is_superuser:
            if not requester.is_admin and not requester.is_biller:
                self._error_message_closed_status()

    def _error_message_closed_status(self):
        raise ValidationError(
            mark_safe(
                _("You do not have permissions to set Closed status.")
            )
        )

    def _is_status(self, status):
        return self.status == status

    def _is_original_status(self, status):
        return self._original_status == status

    def _is_status_check(self, status):
        is_status = self._is_status(status)
        is_original_status = self._is_original_status(status)
        if is_status and not is_original_status:
            return True
        return False

    def clean(self):
        if self.pk is None:
            if self.status != CommonInfo.OPEN:
                raise ValidationError(
                        mark_safe(
                            "You cannot create a Job with this status"
                        )
                    )
        super(Job, self).clean()


class ServicABC(models.Model):
    """
    Header block Service Ticket
    """

    date = models.DateField(_('Date'), blank=True, null=True)
    unit = models.CharField(_('Unit'), max_length=20, blank=True)
    lease_name = models.CharField(_('Lease Name'), max_length=120, blank=True)
    state = models.PositiveSmallIntegerField(_('State'), choices=US_STATES, blank=True, null=True)
    who_called = models.CharField(_('Who Called?'), max_length=120, blank=True)
    engine_model = models.CharField(_('Engine Model'), max_length=120, blank=True)
    comp_model = models.CharField(_('Comp Model'), max_length=120, blank=True)

    class Meta:
        abstract = True

    @property
    def is_nones_and_fields(self):
        """
        Are all fields of the abstract model filled
        """
        data = {}
        for f in ServicABC._meta.local_fields:
            data[f.name] = f.value_from_object(self)
        fields = [key for key, value in data.items() if not value or value is None]
        is_nones = not all(data.values())
        return is_nones, fields


class ServiceTicket(CommonInfo, ServicABC, ServiceTicketActionNotifications):
    """
    Service Ticket model.
    """

    status = models.PositiveSmallIntegerField(
        _('Status'),
        choices=CommonInfo.STATUSES,
        default=CommonInfo.OPEN
    )
    connected_job = models.ForeignKey(
        'api.Job',
        on_delete=models.PROTECT,
        verbose_name=_('Job'),
        help_text=_('This is connected job')
    )
    submitted_for_approval_timestamp = models.DateTimeField(
        _('ST was submitted for approval'), null=True, blank=True
    )
    approved_timestamp = models.DateTimeField(_('ST was approved'), null=True, blank=True)

    # Header optional block Service Ticket
    comp_serial = models.CharField(_('Comp Serial #'), max_length=120, blank=True)
    unit_hours = models.PositiveIntegerField(_('Unit Hours'), blank=True, null=True)
    customer_po_wo = models.CharField(_('Customer PO/WO'), max_length=120, blank=True)
    engine_serial = models.CharField(_('Engine Serial #'), max_length=120, blank=True)
    county = models.CharField(_('County'), max_length=120, blank=True)

    # Safety Setting block
    rpm = DecimalField(_('RPM'))
    suction = DecimalField(_('Suction'))
    discharge1 = DecimalField(_('Discharge'))
    discharge2 = DecimalField(_('Discharge'))
    discharge3 = DecimalField(_('Discharge'))
    safety_setting_lo1 = DecimalField(_('LO'))
    safety_setting_lo2 = DecimalField(_('LO'))
    safety_setting_lo3 = DecimalField(_('LO'))
    safety_setting_lo4 = DecimalField(_('LO'))
    safety_setting_lo5 = DecimalField(_('LO'))
    safety_setting_hi1 = DecimalField(_('HI'))
    safety_setting_hi2 = DecimalField(_('HI'))
    safety_setting_hi3 = DecimalField(_('HI'))
    safety_setting_hi4 = DecimalField(_('HI'))
    safety_setting_hi5 = DecimalField(_('HI'))
    engine_oil_pressure = DecimalField(_('Enfine Oil Pressure / Kill'))
    engine_oil_temp = DecimalField(_('Engine Oil Temp'))
    compressor_oil_pressure = DecimalField(_('Compressor Oil Pressure / Kill'))
    compressor_oil_temp = DecimalField(_('Compressor Oil Temp'))

    # Cylinder Temperature block
    ts1 = DecimalField(_('TS1'))
    ts2 = DecimalField(_('TS2'))
    ts3 = DecimalField(_('TS3'))
    ts4 = DecimalField(_('TS4'))
    td1 = DecimalField(_('TD1'))
    td2 = DecimalField(_('TD2'))
    td3 = DecimalField(_('TD3'))
    td4 = DecimalField(_('TS4'))
    cylinder_temperature_hi1 = DecimalField(_('HI'))
    cylinder_temperature_hi2 = DecimalField(_('HI'))
    cylinder_temperature_hi3 = DecimalField(_('HI'))
    cylinder_temperature_hi4 = DecimalField(_('HI'))

    # Exhaust Temperature block
    exhaust_temperature_l = DecimalField(_('L'))
    exhaust_temperature_r = DecimalField(_('R'))
    exhaust_temperature_hi = DecimalField(_('HI'))

    # Manifold Temperature block
    manifold_temperature_l = DecimalField(_('L'))
    manifold_temperature_r = DecimalField(_('R'))
    manifold_temperature_hi = DecimalField(_('HI'))

    # Manifold Pressure block
    manifold_pressure_l = DecimalField(_('L'))
    manifold_pressure_r = DecimalField(_('R'))
    manifold_pressure_hi1 = DecimalField(_('HI'))
    manifold_pressure_hi2 = DecimalField(_('HI'))
    lo_hi = DecimalField(_('LO/HI'))
    jacket_water_pressure = DecimalField(_('Jacket Water Pressure'))
    mmcfd = DecimalField(_('MMCFD'))
    aux_temp = DecimalField(_('Aux Temp'))
    hour_meter_reading = DecimalField(_('Hour Meter Reading'))
    created_by = models.ForeignKey(
        'authentication.User',
        on_delete=models.PROTECT,
        related_name='created_service_tickets',
        blank=True,
        null=True
    )

    # text notes
    what_was_the_call = models.CharField(_('What Was the Call'), max_length=290, blank=True)
    what_was_found = models.CharField(_('What Was Found'), max_length=1000, blank=True)
    what_was_performed = models.CharField(_('What Was Performed'), max_length=1000, blank=True)
    future_work_needed = models.CharField(_('Parts Used'), max_length=500, blank=True)
    # Replaced "Future Work Needed" with "Parts Used"
    additional_notes = models.CharField(_('Additional Notes'), max_length=2400, blank=True)

    customer_signature = models.ImageField(
        _('Customer Signature'), upload_to=get_customer_signature_img_path, blank=True, null=True
    )
    customer_printed_name = models.CharField(
        _('Customer Printed Name'), max_length=120, blank=True
    )

    reject_description = models.CharField(_('Reject description'), max_length=500, blank=True)


    class Meta:
        verbose_name = _('Service Ticket')
        verbose_name_plural = _('Service Tickets')
        permissions = [
            (
                'can_set_pending_for_approval_service_ticket',
                'Can set Service Ticket status Pending for Approval'
            ),
            ('add_mechanic_to_service_ticket', 'Add mechanic to the Service Ticket'),
            ('can_approve_service_ticket', 'Can approve Service Ticket'),
            ('can_reject_service_ticket', 'Can reject Service Ticket'),
        ]

    def __init__(self, *args, **kwargs):
        super(ServiceTicket, self).__init__(*args, **kwargs)
        self._original_status = self.status
        self.initialize_connected_job()

    def initialize_connected_job(self):
        try:
            self._original_connected_job = self.connected_job
        except:
            self._original_connected_job = None

    def __str__(self):
        return 'Service ticket #{}' #.format(self.connected_job.number)

    @property
    def total_worked_hours(self):
        total = 0
        for employee_work in self.employee_works.all():
            hours = employee_work.hours_worked
            if hours:
                total += hours.total_seconds()
        if total == 0:
            return ''
        minutes = divmod(total, 60)[0]
        return '%dh %02dm' % divmod(minutes, 60)

    @property
    def total_mileage(self):
        result = self.employee_works.all().aggregate(Sum('mileage'))
        total = result.get('mileage__sum', 0)
        if total is None or total == 0:
            return ''
        return str(total)

    @property
    def list_all_employees(self):
        result = []
        for employee_work in self.employee_works.all():
            employee = employee_work.employee
            result.append(f"{employee.first_name} {employee.last_name}")
        if not result:
            return ''
        return ",".join(result)

    @property
    def sum_hotel_checkboxes(self):
        return self.employee_works.filter(hotel=True).count()

    @property
    def sum_per_diem_checkboxes(self):
        return self.employee_works.filter(per_diem=True).count()

    def clean_status(self):
        self.validate_status()
        requester = RequestMiddleware.get_request().user
        if self._is_status_check(CommonInfo.APPROVED) and not requester.is_admin:
            raise ValidationError(
                mark_safe(
                    f"In status {self.get_status_display()} you cannot change data"
                )
            )
        if self.status == CommonInfo.PENDING_FOR_APPROVAL:
            header_block, fields = self.is_nones_and_fields
            employee = EmployeeWorkBlock.objects.filter(service_ticket=self.id).exists()
            if header_block:
                raise ValidationError(
                     {field: f"{ServicABC._meta.get_field(field).verbose_name} is required." for field in fields}
                )
            if not employee:
                raise ValidationError({
                    'employee_works': _("Service Ticket must have at least one employee.")
                })
        return self.status

    def clean(self):
        try:
            job_status = self.connected_job.status
        except Job.DoesNotExist:
            raise ValidationError({'connected_job': mark_safe("Job is required field")})
        if job_status == CommonInfo.APPROVED:
            raise ValidationError(
                {'connected_job': mark_safe(
                    "You cannot change this service ticket. The connected job is approved already."
                )}
            )
        if self.pk is None:
            if self.status != CommonInfo.OPEN:
                raise ValidationError(
                    {'status': mark_safe("You cannot create a Service Ticket with this status")}
                )
            if job_status == CommonInfo.PENDING_FOR_APPROVAL:
                raise ValidationError(
                    {
                        'status': mark_safe(
                            f"You cannot add a Service Ticket to a Job " \
                            f"when it has a status - {self.connected_job.get_status_display()}"
                        )
                    }
                )
        if self._original_status != CommonInfo.OPEN:
            requester = RequestMiddleware.get_request().user
            if self.requester != requester and requester.is_mechanic:
                raise ValidationError(
                    mark_safe(
                        "You are not allowed to update or submit this ticket. " \
                        "The Main Mechanic of the ticket is " \
                        f"{self.requester.first_name} {self.requester.last_name}."
                    )
                )
        # Manager, biller, admin should write the reason for ST rejection
        if self.status == ServiceTicket.REJECTED:
            requester = RequestMiddleware.get_request().user
            if not requester.is_mechanic and not self.reject_description.strip():
                raise ValidationError({'reject_description':
                    'Please write the reason for Service Ticket rejection'
                })
        # Restrict reassigning ST to another Job
        if self._original_connected_job and self._original_connected_job != self.connected_job:
            raise ValidationError({'connected_job': mark_safe(
                    "Service Ticket can not be reassigned to another Job."
                )}
            )
        super(ServiceTicket, self).clean()

    def _is_status(self, status):
        return self.status == status

    def _is_original_status(self, status):
        return self._original_status == status

    def _is_status_check(self, status):
        is_status = self._is_status(status)
        is_original_status = self._is_original_status(status)
        if is_status and is_original_status:
            return True
        return False

    def save(self, *args, **kwargs):
        if self.status == ServiceTicket.PENDING_FOR_APPROVAL:
            self.submitted_for_approval_timestamp = datetime.now(timezone.utc)
            if self._original_status == ServiceTicket.APPROVED:
                self.approved_timestamp = None
        elif self.status == ServiceTicket.APPROVED and self._original_status != self.status:
            self.approved_timestamp = datetime.now(timezone.utc)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        try:
            delete_file(self.customer_signature.path)
        except ValueError:  # file can be null
            pass
    def __str__(self):
        return self.lease_name
    

class Attachment(models.Model):
    """File Attachment model."""

    service_ticket = models.ForeignKey(
        ServiceTicket, on_delete=models.CASCADE, related_name='attachments'
    )
    description = models.CharField(_('Description'), max_length=255)
    file = models.FileField(
        _('File'),
        upload_to=get_file_attachment_path,
        validators=[validate_attachment_file_type],
    )

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        try:
            delete_file(self.file.path)
        except ValueError:  # file can be null
            pass


class EmployeeWorkBlock(CleanFieldsModelMixin, models.Model):

    """Service Ticket block with employees work information."""

    service_ticket = models.ForeignKey(
        ServiceTicket, on_delete=models.PROTECT, related_name='employee_works'
    )
    per_diem = models.BooleanField(_('Per Diem'), blank=True, null=True)
    employee = models.ForeignKey(
        Mechanic, verbose_name=_('Employee'), on_delete=models.PROTECT
    )
    start_time = models.DateTimeField(_('Start Time'), blank=True, null=True)
    end_time = models.DateTimeField(_('End Time'), blank=True, null=True)
    mileage = DecimalField(_('Mileage'))
    hotel = models.BooleanField(_('Hotel'), blank=True, null=True)

    @property
    def hours_worked(self):
        if not self.start_time or not self.end_time:
            return None
        return self.end_time - self.start_time

    def clean_employee(self):
        print(self.start_time, self.end_time)
        if self.employee:
            mech_in_job = self.service_ticket.connected_job.mechanics.filter(id=self.employee.id)
            if not mech_in_job.exists():
                raise ValidationError(
                    {'employee': mark_safe("Selected employee is not present in the related Job.")}
                )

    def clean(self):
        start_time = self.start_time
        end_time = self.end_time

        if (start_time and end_time) and (start_time > end_time):
            msg = 'Start Time can not be ahead of the End Time'
            raise ValidationError({'start_time': _(msg)})

auditlog.register(ServiceTicket)
