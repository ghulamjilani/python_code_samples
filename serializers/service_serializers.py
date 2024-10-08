import os
from collections import OrderedDict
from datetime import datetime, timedelta
from dateutil.parser import parse

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from drf_yasg.openapi import Schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.authentication.models import Manager, Mechanic
from apps.authentication.serializers import (
    ManagerSerializer, MechanicSerializer, UserSerializer
)
from apps.utils.fields import IntegerChoiceField
from apps.utils.request_middleware import RequestMiddleware
from .constants import US_STATES
from .exceptions import DBLockedException
from .models import Attachment, Customer, DBLockDate, EmployeeWorkBlock, Location, Job, ServiceTicket


class LocationSerializer(serializers.ModelSerializer):

    name = serializers.CharField(max_length=4)

    class Meta:
        model = Location
        fields = (
            'id', 'name',
        )


class CustomerSerializer(serializers.ModelSerializer):
    locations = LocationSerializer(many=True, required=False)

    class Meta:
        model = Customer
        fields = (
            'id', 'name', 'locations',
        )

    @staticmethod
    def _add_location_to_customer(customer, locations_data):
        for location_data in locations_data:
            location, created = Location.objects.get_or_create(name=location_data.get('name'))
            customer.locations.add(location)
        return customer

    def create(self, validated_data):
        locations_data = validated_data.pop('locations', [])
        customer = Customer.objects.create(**validated_data)
        self._add_location_to_customer(customer, locations_data)
        return customer

    def update(self, instance, validated_data):
        locations_data = validated_data.pop('locations', [])
        instance.name = validated_data.get('name', instance.name)
        if locations_data:
            self._add_location_to_customer(instance, locations_data)
        instance.save()
        return instance


class RemoveCustomerLocationSerializer(serializers.Serializer):
    location_id = serializers.IntegerField()

    def validate_location_id(self, value):
        view = self.context.get('view')
        pk = view.kwargs.get('pk')
        customer = get_object_or_404(Customer, pk=pk)
        if not customer.locations.filter(pk=value).exists():
            raise serializers.ValidationError(_("Location by that ID doesn't exist in Customer"))
        return value


class JobReadSerializer(serializers.ModelSerializer):
    created_by = UserSerializer()
    requester = UserSerializer()
    approval = UserSerializer()
    customer = CustomerSerializer()
    location = serializers.SerializerMethodField()
    status = IntegerChoiceField(choices=Job.STATUSES)
    mechanics = MechanicSerializer(many=True)
    managers = ManagerSerializer(many=True)
    approved_tickets = serializers.SerializerMethodField()
    total_tickets = serializers.SerializerMethodField()
    get_time_worked = serializers.SerializerMethodField()
    creation_date = serializers.DateTimeField(format='%m-%d-%Y')
    request_date = serializers.DateTimeField(format='%m-%d-%Y')
    update_date = serializers.DateField()

    class Meta:
        model = Job
        fields = (
            'id', 'created_by', 'requester', 'approval','status', 'creation_date', 'description',
            'customer', 'location', 'number', 'mechanics', 'managers', 'request_date', 'update_date',
            'approved_tickets', 'total_tickets', 'is_archive', 'time_worked'
        )
        read_only_fields = fields
        swagger_schema_fields = {
            "properties": {
                "approved_tickets": Schema(type="integer", read_only=True),
                "total_tickets": Schema(type="integer", read_only=True),
            }
        }

    def get_location(self, obj):
        return obj.location.name

    def get_time_worked(self, obj):
        return obj.time_worked/timedelta(hours=1)

    def get_approved_tickets(self, obj):
        return obj.serviceticket_set.filter(status=ServiceTicket.APPROVED).count()

    def get_total_tickets(self, obj):
        return obj.serviceticket_set.count()


class JobWriteSerializer(serializers.ModelSerializer):
    managers = serializers.PrimaryKeyRelatedField(
        queryset=Manager.objects.all(), many=True, write_only=True
    )
    mechanics = serializers.PrimaryKeyRelatedField(
        queryset=Mechanic.objects.all(), many=True, write_only=True
    )

    class Meta:
        model = Job
        fields = (
            'status', 'description', 'customer', 'location', 'mechanics', 'managers',
            'number',
        )

    def validate_created_by(self, value):
        if value.groups.get().name == 'Mechanic':
            raise ValidationError({'created_by': 'Job cannot be created by Mechanic.'})
        return value

    def create(self, validated_data):
        created_by = RequestMiddleware.get_request().user
        self.validate_created_by(created_by)
        validated_data.update({'created_by': created_by})
        service_ticket = super().create(validated_data)
        return service_ticket

    def _new_list(self, data, m2m_model):
        new_obj = list(OrderedDict.fromkeys([obj.id for obj in data]))
        old_obj = [obj.id for obj in m2m_model.all()]
        new_list_add = [i for i in new_obj if i not in old_obj or old_obj.remove(i)]
        new_list_remove = [i for i in old_obj if i not in new_obj or new_obj.remove(i)]
        return new_list_add, new_list_remove

    def _del_and_add_m2m_obj(self, new_list_add, new_list_remove, m2m_model):
        for obj_remove in new_list_remove:
            m2m_model.remove(obj_remove)
        for obj_add in new_list_add:
            m2m_model.add(obj_add)

    def update(self, instance, validated_data):
        """
        managers and mechanics lists override current Job managers and mechanics relations.
        """
        managers_data = validated_data.pop('managers', None)
        mechanics_data = validated_data.pop('mechanics', None)
        super().update(instance, validated_data)
        if managers_data is not None:
            new_list_add, new_list_remove = self._new_list(managers_data, instance.managers)
            self._del_and_add_m2m_obj(new_list_add, new_list_remove, instance.managers)
        if mechanics_data is not None:
            new_list_add, new_list_remove = self._new_list(mechanics_data, instance.mechanics)
            self._del_and_add_m2m_obj(new_list_add, new_list_remove, instance.mechanics)
        return instance

    def to_representation(self, instance):
        return JobReadSerializer(instance).data

    def validate(self, data):
        managers = data.pop('managers', None)
        mechanics = data.pop('mechanics', None)
        created_by = RequestMiddleware.get_request().user
        if created_by.is_mechanic:
            raise serializers.ValidationError(
                {'created_by': _("You do not have permissions to create or update Job.")}
        )
        job = self.instance or Job(**data)
        if self.instance:
            # validate Job with data from request
            for key, value in data.items():
                setattr(job, key, value)
        job.clean()
        if managers is not None:
            data.update({"managers": managers})
        if mechanics is not None:
            data.update({"mechanics": mechanics})
        return data


class AttachmentSerializer(serializers.ModelSerializer):
    # make id field not read_only
    id = serializers.IntegerField(label='ID', required=False)
    filename = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = ('id', 'description', 'file', 'filename',)
        extra_kwargs = {
            'file': {'error_messages': {'null': 'File is required for creating an Attachment.'}}
        }

    def to_internal_value(self, value):
        request = RequestMiddleware.get_request()
        if request.method == 'PATCH' and 'id' in value:  # ignore updating file
            self.fields.get('file').required = False
            value.pop('file', None)
        elif 'file' not in value:
            # needs to be done for beautiful error messages
            value['file'] = None
        return super().to_internal_value(value)

    def get_filename(self, obj):
        return os.path.basename(obj.file.name)


class DeleteAttachmentSerializer(serializers.Serializer):
    attachment_ids = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.all(), many=True, source='attachments'
    )

    class Meta:
        model = ServiceTicket
        fields = ('attachment_ids',)

    def validate_attachment_ids(self, attachments):
        for attachment in attachments:
            if not self.instance.attachments.filter(id=attachment.id).exists():
                raise serializers.ValidationError(
                    _(f"Attachment with id {attachment.id} doesn't exist in this ServiceTicket.")
                )
        return attachments


class DeleteEmployeeWorksSerializer(serializers.Serializer):
    employee_work_ids = serializers.PrimaryKeyRelatedField(
        queryset=EmployeeWorkBlock.objects.all(), many=True, source='employee_works'
    )

    class Meta:
        model = ServiceTicket
        fields = ('employee_work_ids',)

    def validate_employee_work_ids(self, employee_works):
        for employee_work in employee_works:
            if not self.instance.employee_works.filter(id=employee_work.id).exists():
                raise serializers.ValidationError(_(
                    f"employee_work with id {employee_work.id} doesn't exist in this ServiceTicket."
                ))
        return employee_works


class EmployeeWorkBlockSerializer(serializers.ModelSerializer):
    # make id field not read_only to get it in validated_data
    id = serializers.IntegerField(label='ID', required=False)
    hours_worked = serializers.SerializerMethodField()
    # TimeField is bugged
    start_time = serializers.DateTimeField(
        format=settings.REST_FRAMEWORK.get('DATETIME_FORMAT'), allow_null=True, required=False
    )
    end_time = serializers.DateTimeField(
        format=settings.REST_FRAMEWORK.get('DATETIME_FORMAT'), allow_null=True, required=False
    )

    class Meta:
        model = EmployeeWorkBlock
        fields = (
            'start_time', 'end_time', 'mileage', 'hotel', 'per_diem',
            'hours_worked', 'employee', 'id',
        )
        extra_kwargs = {
            'employee': {
                'error_messages': {
                    'required': 'Employee name is required.', 'null': 'Employee name is required.'
                }
            }
        }

    def get_hours_worked(self, obj):
        if obj.hours_worked:
            return '%d:%02d' % divmod(divmod(obj.hours_worked.total_seconds(), 60)[0], 60)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if instance.employee is not None:
            representation['employee'] = {
                'id': instance.employee.id,
                'first_name': instance.employee.first_name,
                'last_name': instance.employee.last_name
            }
        return representation

    def to_internal_value(self, value):
        start_time = value.get('start_time')
        end_time = value.get('end_time')
        if not (isinstance(start_time, datetime) or isinstance(end_time, datetime)):
            value = super().to_internal_value(value)
            value['start_time'] = parse(start_time) if start_time else None
            value['end_time'] = parse(end_time) if end_time else None
        return value

    def validate(self, data):
        in_time = data.get('start_time')
        out_time = data.get('end_time')
        workblock_id = data.get('id', None)


        if in_time is None or out_time is None:
            raise ValidationError({'time': 'Enter both start and end time for the work'})

        if (in_time and out_time) and (in_time > out_time):
            msg = 'Start Time can not be ahead of the End Time'
            raise ValidationError({'start_time': _(msg)})

        time_overlap_qs = EmployeeWorkBlock.objects.filter(employee=data.get('employee')) \
            .filter(
            (Q(start_time__lt=out_time) & Q(end_time__gt=in_time))
        )

        print("serializers.py", in_time, out_time, workblock_id, time_overlap_qs.exclude(id=workblock_id).count())

        """
        .filter((Q(start_time__gte=start_time) & Q(end_time__lte=end_time)) |
                (Q(start_time__lte=end_time) & Q(end_time__gte=end_time)) |
                (Q(start_time__lte=start_time) & Q(end_time__gte=start_time)) |
                (Q(start_time__lte=start_time) & Q(end_time__gte=end_time)))
        """

        if (workblock_id is not None and time_overlap_qs.exclude(id=workblock_id).count() > 0) or \
                (workblock_id is None and time_overlap_qs.count() > 0):
            raise ValidationError({'time': 'One or more mechanics were working during these hours'})

        return data


class ServiceTicketReadSerializer(serializers.ModelSerializer):
    employee_works = EmployeeWorkBlockSerializer(many=True)
    state = IntegerChoiceField(choices=US_STATES)
    date = serializers.DateField(format='%a %m-%d-%Y')
    created_by = UserSerializer(read_only=True)
    status = IntegerChoiceField(choices=ServiceTicket.STATUSES)
    attachments = AttachmentSerializer(many=True, required=False)
    requester = UserSerializer()
    approval = UserSerializer()
    mileage = serializers.SerializerMethodField()

    class Meta:
        model = ServiceTicket
        fields = (
            'id', 'status', 'requester', 'approval','connected_job', 'employee_works', 'created_by',
            'date', 'unit', 'lease_name', 'county', 'state', 'attachments',
            'customer_po_wo', 'who_called', 'engine_model', 'engine_serial',
            'comp_model', 'comp_serial', 'unit_hours', 'rpm', 'suction', 'discharge1',
            'discharge2', 'discharge3', 'safety_setting_lo1', 'safety_setting_lo2',
            'safety_setting_lo3', 'safety_setting_lo4', 'safety_setting_lo5', 'safety_setting_hi1',
            'safety_setting_hi2', 'safety_setting_hi3', 'safety_setting_hi4', 'safety_setting_hi5',
            'engine_oil_pressure', 'engine_oil_temp', 'compressor_oil_pressure',
            'compressor_oil_temp', 'ts1', 'ts2', 'ts3', 'ts4', 'td1', 'td2', 'td3', 'td4',
            'cylinder_temperature_hi1', 'cylinder_temperature_hi2', 'cylinder_temperature_hi3',
            'cylinder_temperature_hi4', 'exhaust_temperature_l', 'exhaust_temperature_r',
            'exhaust_temperature_hi', 'manifold_temperature_l', 'manifold_temperature_r',
            'manifold_temperature_hi', 'manifold_pressure_l', 'manifold_pressure_r',
            'manifold_pressure_hi1', 'manifold_pressure_hi2', 'lo_hi', 'jacket_water_pressure',
            'mmcfd', 'aux_temp', 'hour_meter_reading', 'what_was_the_call', 'what_was_found',
            'what_was_performed', 'future_work_needed', 'additional_notes',
            'customer_signature', 'customer_printed_name', 'reject_description', 'is_archive',
            'total_worked_hours', 'submitted_for_approval_timestamp', 'approved_timestamp',
            'mileage',
        )
        read_only_fields = fields

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation['connected_job'] = {
            'id': instance.connected_job.id,
            'status': instance.connected_job.status,
            'number': instance.connected_job.number,
            'customer': CustomerSerializer(instance=instance.connected_job.customer).data,
            'location': instance.connected_job.location.name
        }
        return representation

    def get_total_worked_hours(self, st_instance):
        return st_instance.total_worked_hours

    def get_mileage(self, st_instance):
        return st_instance.total_mileage


class ServiceTicketWriteSerializer(serializers.ModelSerializer):
    employee_works = EmployeeWorkBlockSerializer(many=True, required=False)
    attachments = AttachmentSerializer(many=True, required=False)

    class Meta:
        model = ServiceTicket
        fields = (
            'status', 'connected_job', 'employee_works', 'attachments',
            'date', 'unit', 'lease_name', 'county', 'state',
            'customer_po_wo', 'who_called', 'engine_model', 'engine_serial',
            'comp_model', 'comp_serial', 'unit_hours', 'rpm', 'suction', 'discharge1',
            'discharge2', 'discharge3', 'safety_setting_lo1', 'safety_setting_lo2',
            'safety_setting_lo3', 'safety_setting_lo4', 'safety_setting_lo5', 'safety_setting_hi1',
            'safety_setting_hi2', 'safety_setting_hi3', 'safety_setting_hi4', 'safety_setting_hi5',
            'engine_oil_pressure', 'engine_oil_temp', 'compressor_oil_pressure',
            'compressor_oil_temp', 'ts1', 'ts2', 'ts3', 'ts4', 'td1', 'td2', 'td3', 'td4',
            'cylinder_temperature_hi1', 'cylinder_temperature_hi2', 'cylinder_temperature_hi3',
            'cylinder_temperature_hi4', 'exhaust_temperature_l', 'exhaust_temperature_r',
            'exhaust_temperature_hi', 'manifold_temperature_l', 'manifold_temperature_r',
            'manifold_temperature_hi', 'manifold_pressure_l', 'manifold_pressure_r',
            'manifold_pressure_hi1', 'manifold_pressure_hi2', 'lo_hi', 'jacket_water_pressure',
            'mmcfd', 'aux_temp', 'hour_meter_reading', 'what_was_the_call', 'what_was_found',
            'what_was_performed', 'future_work_needed', 'additional_notes',
            'customer_signature', 'customer_printed_name', 'reject_description',
        )
        extra_kwargs = {
            'connected_job': {'error_messages': {'required': 'Connected job is required.'}}
        }
        swagger_schema_fields = {
            "properties": {
                "attachments": Schema(
                    type="object",
                    properties={
                        "file": Schema(type="file", description="Use `multipart/form-data`"),
                        "description": Schema(type="string"),
                    },
                    required=("file",)
                ),
                "customer_signature": Schema(type="file"),
            }
        }

    def to_representation(self, instance):
        return ServiceTicketReadSerializer(
            instance, context={'request': RequestMiddleware.get_request()}
        ).data

    def validate_created_by(self, value):
        if value.groups.get().name == 'Biller':
            raise ValidationError(
                {'created_by': 'Service Ticket cannot be created by Biller.'}
            )
        return value

    def validate_status(self, status):
        user = RequestMiddleware.get_request().user
        if status == ServiceTicket.PENDING_FOR_APPROVAL:
            if user.is_biller or user.is_manager:
                raise ValidationError(
                    _('Manager and Biller cannot submit Service Ticket for approval.')
                )
        elif status == ServiceTicket.APPROVED and user.is_mechanic:
            raise ValidationError(_('Mechanic cannot approve Service Ticket.'))
        if status == ServiceTicket.REJECTED and user.is_mechanic:
            raise ValidationError(_('Mechanic cannot reject Service Ticket.'))
        return status

    def create(self, validated_data):
        created_by = RequestMiddleware.get_request().user
        self.validate_created_by(created_by)
        validated_data.update({'reject_description': ''})
        employee_works_data = validated_data.pop('employee_works', [])
        attachments_data = validated_data.pop('attachments', [])
        try:
            service_ticket = ServiceTicket.objects.create(created_by=created_by, **validated_data)
            for employee_work_data in employee_works_data:
                EmployeeWorkBlock.objects.create(
                    service_ticket=service_ticket, **employee_work_data
                ).clean_employee()

            for attachment_data in attachments_data:
                Attachment.objects.create(service_ticket=service_ticket, **attachment_data)
        except DjangoValidationError as error:
            # raise DRF ValidationError instead of Django one
            raise ValidationError(detail=serializers.as_serializer_error(error))
        return service_ticket

    def update_employee_works(self, service_ticket, employee_works_data):
        employee_works = service_ticket.employee_works

        # delete all if employee_works for this ST if employee_works is empty str in request body
        if self.initial_data.get('employee_works') == '':
            employee_works.all().delete()
            return None

        if employee_works_data is None:  # there is no employee_works_data in request body
            return None

        all_ids = set(employee_works.values_list('id', flat=True))
        ids_to_update = set()
        for employee_work_data in employee_works_data:
            employee = employee_work_data.get('employee')
            if employee is None:
                raise ValidationError(
                    {'employee': _('Employee is required for creating Service Ticket.')}
                )
            # employee in validated_data is Mechanic object
            employee_work_data.update({'employee': employee.id})
            EmployeeWorkBlockSerializer(data=employee_work_data).is_valid(raise_exception=True)
            id = employee_work_data.get('id', None)
            if id is None:
                employee_work_instance = employee_works.create(
                    employee_id=employee.id, service_ticket=service_ticket
                )
            else:
                employee_work_instance = employee_works.get(id=id)
                ids_to_update.add(id)
            # FIXME: if there is no employee_work with such id in this service_ticket
            #        and id is not None error will be raised
            # update works only on QuerySet
            employee_works.filter(id=employee_work_instance.id).update(**dict(employee_work_data))
        redundant_ids = all_ids - ids_to_update
        for redundant_id in redundant_ids:
            employee_works.get(id=redundant_id).delete()

    def update_attachments(self, service_ticket, attachments_data):
        attachments = service_ticket.attachments

        # delete all attachments for this ST if attachments is empty str in request body
        if self.initial_data.get('attachments') == '':
            for attachment in attachments.all():  # queryset.delete() not calling model delete
                attachment.delete()
            return None

        if attachments_data is None:  # there is no attachments in request body
            return None

        for attachment_data in attachments_data:
            id = attachment_data.get('id', None)
            if id is None:
                attachment_instance = attachments.create(**attachment_data)
            else:
                attachment_instance = attachments.get(id=id)
                attachment_instance.description = attachment_data.get('description')
                attachment_instance.save(update_fields=['description'])

    def update(self, instance, validated_data):
        # Allow ST editing only in 'Open' and 'Rejected' statuses
        # Edit note, we are allowing update in pending approval stage as well
        # original_status = instance._original_status
        # if original_status == ServiceTicket.PENDING_FOR_APPROVAL:
        status = validated_data.pop('status', instance.status)
        reject_description = validated_data.pop('reject_description', '')
        validated_data.update({'status': status, 'reject_description': reject_description})
        print("update() with validated_data", instance.employee_works)
        """
            if len(validated_data) != 0:
                raise ValidationError(
                    {'status': 'Service Ticket can be updated only in Open and Rejected statuses.'}
                )
        """
        try:
            employee_works_data = validated_data.pop('employee_works', None)
            self.update_employee_works(instance, employee_works_data)
            attachments_data = validated_data.pop('attachments', None)
            self.update_attachments(instance, attachments_data)
        except DjangoValidationError as error:
            raise ValidationError(detail=serializers.as_serializer_error(error))
        super().update(instance, validated_data)
        return instance

    def validate(self, data):
        employee_works = data.pop('employee_works', None)
        attachments = data.pop('attachments', None)
        date = data.get('date', None)

        if date and DBLockDate.objects.get().lock_date and date < DBLockDate.objects.get().lock_date:
            raise DBLockedException()

        service_ticket = self.instance or ServiceTicket(**data)
        if self.instance:
            # validate service_ticket with data from request
            for key, value in data.items():
                setattr(service_ticket, key, value)
        service_ticket.clean()
        if employee_works is not None:
            data.update({"employee_works": employee_works})
        if attachments is not None:
            serializer = AttachmentSerializer(data=attachments, many=True)
            serializer.is_valid()
            if serializer.errors:
                raise ValidationError({'attachments': serializer.errors})
            data.update({"attachments": attachments})
        return data
