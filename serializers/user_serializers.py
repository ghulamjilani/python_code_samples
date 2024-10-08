from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

from drf_yasg.openapi import Schema
from rest_framework import serializers
# from rest_framework_simplejwt.serializers import TokenObtainSerializer
from rest_framework_jwt.serializers import JSONWebTokenSerializer

from apps.utils.communication import decode_base64_to_dict
from apps.utils.fields import IntegerChoiceField
from .group_permissions import USER_ROLES
from .models import Admin, Biller, Manager, Mechanic, User


class UserSerializer(serializers.ModelSerializer):
    role = IntegerChoiceField(choices=USER_ROLES, write_only=True)
    status = IntegerChoiceField(choices=User.STATUSES, required=False)

    class Meta:
        model = User
        fields = (
            'id', 'first_name', 'last_name', 'email','manager',
            'role', 'status', 'sent_email_notifications',
            'sent_push_notifications',
        )
        swagger_schema_fields = {
            "properties": {
                "password": Schema(type="string", write_only=True),
                "password_check": Schema(type="string", write_only=True),
            }
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        role_value = instance.groups.get().id
        data['role'] = self.fields.get('role').to_representation(role_value)
        return data


class BasePasswordSerializer(serializers.Serializer):
    """
    Serializer for update password API.
    """
    password = serializers.CharField(required=True, min_length=8)
    password_check = serializers.CharField(required=True, min_length=8)

    def validate(self, data):
        """Validation for checking password match."""
        if data['password'] != data['password_check']:
            raise serializers.ValidationError({'password_check': _("Passwords don't match!")})
        return data


class UpdatePasswordSerializer(BasePasswordSerializer):
    """
    Serializer for password change endpoint.
    """
    old_password = serializers.CharField(required=True)

    def validate_old_password(self, value):
        """ self.context - user instance """
        if not self.context.check_password(value):
            raise serializers.ValidationError(_('Current password is incorrect'))
        return value

    def validate(self, data):
        if data['old_password'] == data['password']:
            raise serializers.ValidationError(
            {'old_password': _('New password cannot be the same as your old password')}
        )
        return super().validate(data)


class HashSerializer(serializers.Serializer):
    """
    Serializer for hash validation.
    """
    hash = serializers.CharField(required=True)

    def __init__(self, cache_key_action=None, *args, **kwargs):
        self.cache_key_action = cache_key_action
        super().__init__(self, *args, **kwargs)

    def validate_hash(self, value):
        decoded_data = decode_base64_to_dict(value, serializers.ValidationError(_(
            'Link is invalid. Please, try again.'
        )))
        if self.cache_key_action is not None:
            cache_key = f"{self.cache_key_action}{decoded_data.get('id')}"
            data_from_cache = cache.get(cache_key)
            if data_from_cache != decoded_data:
                raise serializers.ValidationError(
                    _('Email confirmation link is not valid. Please try again.')
                )
            cache.delete(cache_key)
        return decoded_data


class RestorePasswordSerializer(BasePasswordSerializer, HashSerializer):
    pass


class AdminSerializer(UserSerializer):

    class Meta(UserSerializer.Meta):
        model = Admin


class BillerSerializer(UserSerializer):

    class Meta(UserSerializer.Meta):
        model = Biller


class ManagerSerializer(UserSerializer):

    class Meta(UserSerializer.Meta):
        model = Manager


class MechanicSerializer(UserSerializer):

    class Meta(UserSerializer.Meta):
        model = Mechanic


class JSONWebTokenSerializer(JSONWebTokenSerializer):

    class Meta:
        swagger_schema_fields = {
            "type": "object",
            "properties": {
                "email": Schema(type="string", write_only=True, description="Email"),
                "password": Schema(type="string", write_only=True, description="Password"),
                "token": Schema(type="string", read_only=True, description="JWT Token"),
                "user": Schema(
                    title="User object",
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
                                "name": Schema(type="string", description="Role name"),
                                "value": Schema(type="integer", description="Role value"),
                            }
                        ),
                        "permissions": Schema(
                            type="array",
                            read_only=True,
                            items=Schema(type="string"),
                            description="User permissions"
                        ),
                    }
                ),
                "user_roles": Schema(
                    type="array",
                    description='Enum: `{"name":"Admin","value":1}` `{"name":"Biller","value":2}` `{"name":"Manager","value":3}` `{"name":"Mechanic","value":4}`',
                    read_only=True,
                    items=Schema(
                        type="object",
                        properties={
                            "name": Schema(type="string", description="Role name"),
                            "value": Schema(type="integer", description="Role value"),
                        }
                    ),
                ),
                "states": Schema(
                    type="array",
                    description="USA states",
                    read_only=True,
                    items=Schema(
                        type="object",
                        properties={
                            "name": Schema(type="string", description="State name"),
                            "value": Schema(type="string", description="State value"),
                        }
                    ),
                ),
            },
            "required": ["email", "password"],
         }
