import functools

from apps.accounts.decorators import mfa
from django.contrib.auth import get_user
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import User, UserToken


class TestBasic(TestCase):

    def setUp(self) -> None:
        self._user: User = User.objects.create_user(username="test1", password="123456")
        self._token: UserToken = UserToken.objects.create(user=self._user, scope="test_scope")

    def test_user_str_repr(self):
        self.assertEqual(str(self._user), "test1")
        self._user.first_name = "John"
        self._user.last_name = "Smith"
        self._user.save()
        self.assertEqual(str(self._user), "John Smith")

    def test_token_str_repr(self):
        self.assertEqual(str(self._token), "test1  ==>  test_scope")


class TestMFADecorator(TestCase):

    def setUp(self) -> None:
        self._user: User = User.objects.create_user(username="test1", password="123456")
        self.client.force_login(self._user)
        self._user = get_user(self.client)

    def test_decorator_redirect_2fa_setup(self):
        """Check an authenticated user but without 2fa setup"""
        factory = RequestFactory()

        @mfa
        def a_view(request):
            return HttpResponse()
        req = factory.get('/')
        req.user = self._user
        resp = a_view(req)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('two_factor:setup'))

    def test_decorator_redirect_2fa_login(self):
        """Check an authenticated user with 2fa setup but without token_url verification"""
        factory = RequestFactory()

        @mfa
        def a_view(request):
            return HttpResponse()

        def is_verified(user):
            return user.otp_device is not None

        TOTPDevice.objects.create(confirmed=True, name='default', user=self._user)
        self._user.otp_device = None
        self._user.is_verified = functools.partial(is_verified, self._user)

        req = factory.get('/')
        req.user = self._user
        resp = a_view(req)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('two_factor:login'))

    def test_decorator_redirect_2fa_success(self):
        """Check an authenticated user with 2fa verification"""
        factory = RequestFactory()

        @mfa
        def a_view(request):
            return HttpResponse()

        def is_verified():
            return True

        self._user.is_verified = functools.partial(is_verified)
        TOTPDevice.objects.create(confirmed=True, name='default', user=self._user)

        req = factory.get('/')
        req.user = self._user
        resp = a_view(req)
        self.assertEqual(resp.status_code, 200)

    def test_decorator_ignore_2fa(self):
        """Check ignore 2fa verification"""
        factory = RequestFactory()

        @mfa(ignore_mfa=True)
        def a_view(request):
            return HttpResponse()

        req = factory.get('/')
        req.user = self._user
        resp = a_view(req)
        self.assertEqual(resp.status_code, 200)
