from django.utils.translation import gettext_lazy as _

from drf_yasg.openapi import Schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.authentication.models import Mechanic
from apps.authentication.serializers import MechanicSerializer
from apps.utils.fields import IntegerChoiceField
from apps.utils.request_middleware import RequestMiddleware

from .models import IndirectHours, TimeCode


class TimeCodeReadSerializer(serializers.ModelSerializer):

    class Meta:
        model = TimeCode
        fields = ('id', 'name',)


class IndirectHoursReadSerializer(serializers.ModelSerializer):
    date = serializers.DateField(format='%m-%d-%Y')
    mechanic = MechanicSerializer(many=True)
    status = IntegerChoiceField(choices=IndirectHours.STATUSES)
    time_code = TimeCodeReadSerializer()

    class Meta:
        model = IndirectHours
        fields = (
            'id', 'creation_date', 'update_date', 'date', 'hours', 'time_code',
            'notes', 'mechanic', 'status', 'is_archive',
        )
        swagger_schema_fields = {
            "properties": {
                "mechanic": Schema(
                    title="Mechanic object",
                    type="object",
                    read_only=True,
                    properties={
                        "id": Schema(type="integer", description="ID"),
                        "first_name": Schema(type="string", description="First name"),
                        "last_name": Schema(type="string", description="Last name"),
                        "email": Schema(type="string", description="Email"),
                        "role": Schema(
                            type="object",
                            description="Role",
                            properties={
                                "value": Schema(type="integer", description="Role value"),
                                "name": Schema(type="string", description="Role name"),
                            }
                        ),
                    }
                ),
                "status": Schema(
                    type="object",
                    read_only=True,
                    description="Role",
                    properties={
                        "value": Schema(type="integer", description="Status value"),
                        "name": Schema(type="string", description="Status name"),
                    }
                ),
            }
        }


class IndirectHoursWriteSerializer(serializers.ModelSerializer):
    mechanic = serializers.PrimaryKeyRelatedField(
        queryset=Mechanic.objects.all(), many=True, write_only=True
    )
    class Meta:
        model = IndirectHours
        fields = (
            'id', 'creation_date', 'update_date', 'date', 'hours', 'time_code',
            'notes', 'mechanic', 'status',
        )
        extra_kwargs = {
            'date': {'error_messages': {'required': 'Date field is required.'}},
            'hours': {'error_messages': {'required': 'Hours field is required.'}},
            'time_code': {'error_messages': {'required': 'Time code field is required.'}},
            'notes': {'error_messages': {'required': 'Notes field is required.'}},
            'mechanic': {'error_messages': {'required': 'Mechanic field is required.'}}
        }


    def to_representation(self, instance):
        return IndirectHoursReadSerializer(instance).data

    def validate_mechanic(self, value):
        created_by = RequestMiddleware.get_request().user
        if created_by.is_mechanic and value[0].id != created_by.id:
            raise ValidationError({'mechanic': 'Invalid id'})
        return value

    def raise_if_not_status(self, data, msg):
        if len(data.keys()) > 1 or not 'status' in data:
            raise serializers.ValidationError(_(msg))

    def validate(self, data):
        created_by = RequestMiddleware.get_request().user
        mechanics = data.pop('mechanic', None)
        if created_by.is_manager or created_by.is_biller:
            # the key must be one and only 'status'
            self.raise_if_not_status(
                data,
                "You do not have permissions to create or update Indirect Hours."
            )

        if self.instance:
            status = self.instance.status
            msg = "You do not have permissions to update Indirect Hours."
            if status == IndirectHours.PENDING_FOR_APPROVAL:
                # Allow only admin or manager to edit IH status field in status 1
                if created_by.is_admin or created_by.is_manager or created_by.is_biller:
                    self.raise_if_not_status(data, msg)
            elif status == IndirectHours.REJECTED:
                # Allow only admin or mechanic to edit IH fields in status 2
                if created_by.is_manager or created_by.is_biller:
                    raise serializers.ValidationError(_(msg))
            elif status == IndirectHours.APPROVED:
                # Allow only admin to edit IH status field in status 3
                if not created_by.is_admin:
                    self.raise_if_not_status(data, msg)
        ih = self.instance or IndirectHours(**data)
        if self.instance:
            # validate IndirectHours with data from request
            for key, value in data.items():
                setattr(ih, key, value)
        ih.clean()
        if mechanics is not None:
            data.update({"mechanic": mechanics})
        return data
    
    
