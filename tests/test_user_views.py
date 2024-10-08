import json
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import TestCase
from django.urls import reverse

from rest_framework import status

from apps.utils.communication import encode_dict_to_base64
from ..models import User
from .factories import AdminFactory, UserFactory, MechanicFactory, ManagerFactory
from .utils import RedisMock


class TestUserViewSet(TestCase):

    def setUp(self):
        self.user = AdminFactory()  # only Admin users have access to UserViewSet
        self.redis = RedisMock()
        self.client.force_login(self.user)
        self.user_data = {
            'email': 'webpack@pack.ck',
            'first_name': 'Abraham',
            'last_name': 'Yoba',
            'password': '12345678',
            'password_check': '12345678',
            'role': 4,
        }
        self.data_without_password = {
            'first_name': 'Abraham',
            'last_name': 'Yoba',
            'email':'webpack@pack.ck'
        }
        self.data = {'time': 3}

    def delay(self, id):
        pass

    @patch('apps.authentication.views.send_notification_user_created.delay')
    @patch('apps.authentication.serializers.cache.get')
    def test_email_confirmation(self, mocked_redis_get, mocked_task_delay):
        mocked_task_delay.side_effect = self.delay
        mocked_redis_get.side_effect = self.redis.get

        data = {
            'id': self.user.id,
            'uuid': 'qwefmnib82o6vg7i3uj2n92p[3'
        }
        hash_value = urlencode({'hash': encode_dict_to_base64(data)})
        self.redis.set(f'email_confirmation_{self.user.id}', data)
        url = reverse('authentication:user-confirm-email')
        response = self.client.get(
            f'{url}?{hash_value}', content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get('is_confirmed_email'), True)
        self.assertTrue(User.objects.get(id=self.user.id).is_confirmed_email)

    @patch('apps.authentication.views.send_password_restore_link.delay')
    def test_restore_password_link(self, mocked_task_delay):
        mocked_task_delay.side_effect = self.delay

        restore_data = {'email': self.user.email}
        url = reverse('authentication:user-restore-password-link')
        response = self.client.post(
            url,
            data=json.dumps(restore_data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data.get('detail')[0],
            'Email is sent!'
        )

        self.assertIsNone(mocked_task_delay.assert_called_once_with(self.user.id))

    @patch('apps.authentication.views.send_reset_password.delay')
    def test_send_reset_password(self, mocked_task_delay):
        mocked_task_delay.side_effect = self.delay
        mocked_task_delay.side_effect = 'password'
        new_mechanics = MechanicFactory()
        self.assertTrue(new_mechanics.check_password('12345678'))
        url = reverse('authentication:user-reset-password', args=[new_mechanics.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data.get('detail')[0],
            'Email is sent!'
        )

    def test_restore_password_link_invalid_email(self):
        restore_data = {'email': 'invalid@mail.com'}
        url = reverse('authentication:user-restore-password-link')
        response = self.client.post(
            url,
            data=json.dumps(restore_data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.data.get('email')[0],
            'Email is invalid'
        )

    @patch('apps.authentication.serializers.cache.get')
    def test_restore_password(self, mocked_redis_get):
        mocked_redis_get.side_effect = self.redis.get

        data = {
            'id': self.user.id,
            'uuid': 'qwefmnib82o6vg7i3uj2n92p[3'
        }
        restore_data = {
            'password': '123456789',
            'password_check': '123456789'
        }
        hash_value = urlencode({'hash': encode_dict_to_base64(data)})
        self.redis.set(f'password_restore_{self.user.id}', data)
        url = reverse('authentication:user-restore-password')
        response = self.client.post(
            f'{url}?{hash_value}',
            data=json.dumps(restore_data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(User.objects.get(id=self.user.id).check_password('123456789'))
        self.assertEqual(
            response.data.get('detail')[0],
            'Password is successfully restored!'
        )

    @patch('apps.authentication.managers.MechanicUserManager.create')
    def test_create_user_use_proper_manager_method(self, mocked_create):
        mocked_create.return_value = self.user
        response = self.client.post(
            path=reverse('authentication:user-list'),
            data=json.dumps(self.user_data),
            content_type='application/json'
        )

        # we don't have password_check in response
        self.user_data.pop('password_check', None)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_role_binding_on_create(self):
        response = self.client.post(
            path=reverse('authentication:user-list'),
            data=json.dumps(self.user_data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            User.objects.get(id=response.data.get('user').get('id')).groups.first().name,
            'Mechanic'
        )

    def test_archived_users(self):
        error_id = 10000000
        self.assertEqual(self.user.status, User.ACTIVE)
        restore_data = {'ids': [self.user.id, error_id]}
        url = reverse('authentication:user-archive-users')
        response = self.client.post(
            url,
            data=json.dumps(restore_data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data.get('Successfully archived Users (IDs)'),
            [self.user.id]
        )
        self.assertEqual(
            response.data.get('Failed to archive Users (IDs)'),
            [error_id]
        )
        new_status = User.objects.get(id=self.user.id).status
        self.assertEqual(new_status, User.ARCHIVED)

    def test_unarchived_users(self):
        error_id = 10000000
        new_user = UserFactory(status=User.ARCHIVED)
        self.assertEqual(new_user.status, User.ARCHIVED)
        restore_data = {'ids': [new_user.id, error_id]}
        url = reverse('authentication:user-unarchive-users')
        response = self.client.post(
            url,
            data=json.dumps(restore_data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data.get('Successfully unarchived Users (IDs)'),
            [new_user.id]
        )
        self.assertEqual(
            response.data.get('Failed to unarchive Users (IDs)'),
            [error_id]
        )
        new_status = User.objects.get(id=self.user.id).status
        self.assertEqual(new_status, User.ACTIVE)

    def test_archived_users_with_wrong_role(self):
        new_user = ManagerFactory()
        self.client.force_login(new_user)
        id = new_user.id
        url = reverse('authentication:user-archive-users')
        restore_data = {'ids': [id]}
        response = self.client.post(
            url,
            data=json.dumps(restore_data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data.get('detail'),
            'You do not have permission to perform this action.'
        )

    def test_no_pagination(self):
        url = '/api/v1/auth/?all=True'
        response = self.client.get(url, content_type='application/json')
        self.assertNotIn('next', response.data)
        self.assertNotIn('previous', response.data)

    def test_get_all_manager(self):
        new_manager = ManagerFactory()
        url = reverse('authentication:user-get-all-managers')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_get_all_mechanic(self):
        new_mechanic = MechanicFactory()
        url = reverse('authentication:user-get-all-mechanics')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_get_all_manager_with_wrong_role(self):
        self.user = MechanicFactory()
        self.client.force_login(self.user)
        url = reverse('authentication:user-get-all-managers')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data.get('detail'),
            'You do not have permission to perform this action.'
        )

    def test_get_all_mechanic_with_wrong_role(self):
        self.user = MechanicFactory()
        self.client.force_login(self.user)
        url = reverse('authentication:user-get-all-mechanics')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data.get('detail'),
            'You do not have permission to perform this action.'
        )
