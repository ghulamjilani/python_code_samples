from datetime import datetime, timezone

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views import View

from apps.accounts.auth_repo import RepoAccount
from apps.audit.medmij_repo import MedMijLogRepo
from apps.providers.menu.menu_dto import ServiceEndpointApi
from apps.providers.models import CareProvider
from apps.providers.prov_repo import RepoProvider
from pgo.settings import TOUCHSTONE
from utils import ocsp_util as OCSP
from utils.app_exceptions import PgoHttpException
from utils.decorators.decorators import provider_required
from utils.dvza import ProviderCatalog
from utils.mixins.async_mixins import AsyncLoginRequiredMixin, AsyncRemoteTokenValidationMixin, \
	AsyncScopeValidationMixin
from utils.mixins.sync_mixins import LoginRequiredMixin, PgoLogMixin
from utils.xis import HealthcareInfoSystem


class ProviderView(AsyncLoginRequiredMixin, PgoLogMixin, View):
    async def get_providers(self):
        self.warning("Healthcare providers list must be updated")
        catalog = ProviderCatalog()
        await catalog.get_catalogs()

    async def post(self, request):
        error_msg = _("Provider list couldn't be retrieved.")
        error = False
        # Remove starting and ending whitespaces from search term
        provider: str = request.POST.get('search', '').strip()
        try:
            if await sync_to_async(RepoProvider.fetch_needed)():
                await self.get_providers()
        except PgoHttpException as e:
            error, error_msg = True, f"{error_msg} {e.message}"
            self.error(f"Get sandbox list (PgoHttpException): {error_msg}")
        except Exception as e:
            error, error_msg = True, f"{error_msg} {e}"
            self.exception(f"Get sandbox list (Exception): {error_msg}")
        provider_list = await RepoProvider.search_providers(provider)
        return await sync_to_async(render)(request, 'provider_list.html', locals())

    async def get(self, request):
        nav_title = _("Add healthcare provider")
        provider_list = await RepoProvider.search_providers()
        return await sync_to_async(render)(request, 'select_provider.html', locals())


class ServiceView(LoginRequiredMixin, PgoLogMixin, View):

    @provider_required
    def post(self, request):
        nav_title = _("Add healthcare provider")
        provider = request.POST.get('provider', '')
        service_list, ids = RepoProvider.get_provider_services(request, provider)
        
        return render(request, 'select_service.html', locals())


class GetBundlesView(
    AsyncLoginRequiredMixin,
    AsyncScopeValidationMixin,
    AsyncRemoteTokenValidationMixin,
    PgoLogMixin,
    View
):
    """
    This view it's called from the services page form (as POST, but could also be call as a GET),
    so the first mixin called is AsyncScopeValidationMixin,
    so it validates the scope received and passed to the next mixins.
    AsyncRemoteTokenValidationMixin will check for a valid token otherwise initiate the authorization flow
    """
    def continue_to_resource_endpoint(self, request, endpoint):
        if not RepoProvider.is_trusted_host(endpoint.resource_url):
            self.error("Resource endpoint is not in whitelist")
            messages.warning(request, _(f"Resource endpoint is not in whitelist"))
            return False
        self.info("Resources endpoint is in whitelist")
        if TOUCHSTONE:
            return True  # skip tls verification

        cert_status = OCSP.get_host_ocsp_status(endpoint.resource_url)
        if cert_status != OCSP.CertStatus.GOOD:
            self.warning(f"{endpoint.resource_url}: {OCSP.get_cert_status_description(cert_status)}")
            messages.warning(request, f"{endpoint.resource_url}: {OCSP.get_cert_status_description(cert_status)}")
            return False
        self.info(f"{endpoint.resource_url}: tls certificate chain is good")
        return True


    @sync_to_async
    def get_bundles_api(self, request):
        """Verify resource endpoint in whitelist"""
        if not self.continue_to_resource_endpoint(request, self.endpoint):
            return None
        apis: list[ServiceEndpointApi] = RepoProvider.get_service_apis(request, self.endpoint)
        return apis

    async def post(self, request):
        _response = HttpResponse("Okay")
        _response['HX-Location'] = "/"
        apis = await self.get_bundles_api(request)
        try:
            if apis and self.endpoint and self.provider_token:
                await HealthcareInfoSystem.fetch_data(request, apis, self.endpoint, self.provider_token)
        except Exception as e:
            self.error(f"Error getting health data from provider: {e}")
            messages.error(request, f"Error getting health data from provider: {e}")
        return _response

    async def get(self, request):
        _response = HttpResponse("Okay")
        _response['HX-Location'] = "/"
        apis = await self.get_bundles_api(request)
        prev_url = request.META.get('HTTP_REFERER')
        try:
            if apis and self.endpoint and self.provider_token:
                await HealthcareInfoSystem.fetch_data(request, apis, self.endpoint, self.provider_token)
            else:
                msg = f"No APIs defined for {self.endpoint.service} [{self.service_id}]"
                messages.warning(request, msg)
                self.warning(msg)
        except Exception as e:
            self.error(f"Error getting health data from server: {e}")
            messages.error(request, str(e))
        if not prev_url:
            return redirect('home')
        return _response


class DeleteNoticeView(LoginRequiredMixin, PgoLogMixin, View):

    def get(self, request, delete_option):
        nav_title = f"{_(f'Delete ')} {_(delete_option)} {_(' data')}"
        if delete_option!="all" and not RepoProvider.get_provider(name=delete_option):
            messages.warning(request, _(f"Invalid provider selected: ") + delete_option)
        return render(request, 'delete_data.html', locals())

    def post(self, request, delete_option):
        option = request.POST.get('option', '')
        provider = RepoProvider.get_provider(name=option)
        try:
            if option == "all":
                total = RepoProvider.delete_all_health_data(user=request.user)
                MedMijLogRepo.delete_user_events(user=request.user)
                messages.info(request, _(f"{total} records deleted"))
            elif provider:
                total = RepoProvider.delete_health_data_for_provider(
                    user=request.user, provider=option
                )
                MedMijLogRepo.delete_user_provider_events(user=request.user, provider=option)
                messages.info(request, _(f"{total} records deleted"))
            else:
                messages.info(request, _(f"No records found for provider: " + option))
        except Exception as e:
            self.exception(e)
            messages.warning(request, _(f"Something went wrong deleting records: " + option))

        return redirect('home')


class ManagePermissionsView(LoginRequiredMixin, PgoLogMixin, View):

    def get(self, request):
        nav_title = f"{_(f'Manage Long Term Permissions')}"
        long_term_providers: list[str] = RepoAccount.get_providers_with_long_term_perm(request.user)
        others_providers = CareProvider.objects.filter(due_date__gt=datetime.now(timezone.utc)).exclude(name__in=long_term_providers)
        return render(request, 'permission_management.html', locals())

