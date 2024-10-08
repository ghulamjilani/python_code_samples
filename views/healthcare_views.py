import io
import traceback
from base64 import b64decode
from typing import Optional

from asgiref.sync import sync_to_async
from dacite import from_dict
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views import View

from apps.accounts.models import User
from fhir.fhir_constants import ResType
from fhir.foundation.domain_resource import DomainResource
from fhir.foundation.other.bundle import Bundle as ExpBundle, Entry
from utils.dto.fhir_dto import FhirResult
from utils.helpers.core_helpers import Render
from utils.helpers.fhir_helper import render_fhir_resources
from utils.helpers.pgo_regex import Pgex
from utils.helpers.resource_helper import ResUtil
from utils.http.http_client import PgoHttp
from utils.mixins.async_mixins import AsyncLoginRequiredMixin, AsyncScopeValidationMixin
from utils.mixins.sync_mixins import PgoLogMixin
from utils.pgo_logger import PgoLogger
from utils.xis import HealthcareInfoSystem as HIS
from .health_repo import RepoHealthData
from .models import FhirResource
from ..accounts.auth_repo import RepoAccount
from ..audit.medmij_repo import MedMijLogRepo
from ..providers.menu.menu_dto import ServiceEndpointApi, ServiceID
from ..providers.prov_repo import RepoProvider

logger = PgoLogger()
resource_page_template = 'resource_page.html'

def extract_document_url_from_content(content):
    try:
        first_content = content[0]  # Access the first item in the content list
        attachment = first_content.get('attachment', {})
        return attachment.get('url')  # Extract the URL from the attachment
    except (IndexError, KeyError) as e:
        logger.error(f"Failed to extract document URL: {str(e)}")
        return None


async def handle_db_resource(request, db_resource: FhirResource, user):
    # check the resource belongs to this user
    user_tz = request.COOKIES.get('tz', None)
    nav_title = _(db_resource.resource_type)
    fetched = db_resource.fetched_at
    logger.info(f"resource fetched with title: {nav_title} at {fetched}")
    user_related = await sync_to_async(RepoHealthData.is_user_related)(db_resource, request.user)
    if not user_related:
        msg = "Unauthorized resource access"
        logger.error(msg)
        messages.warning(request, _(msg))
        return render(request, resource_page_template, locals())
    # get the date when resource was cached to show in ui
    rsrc_json = db_resource.resource_json
    logger.info(f"Resource json type: {ResUtil.type(rsrc_json)}")
    logger.info(f"Resource json keys: {rsrc_json.keys()}   ")
    logger.info(f"resourcetype: {rsrc_json.get('resourceType')}, id: {rsrc_json.get('id')} , meta: {rsrc_json.get('meta')}, context: {rsrc_json.get('context')}")
    try:
        if ResUtil.type(rsrc_json) == ResType.BINARY:
            return handle_binary_resource(rsrc_json, request)
        elif ResUtil.type(rsrc_json) == ResType.DOCUMENT_REFERENCE:
            logger.info(f"content: {rsrc_json.get('content')}")
            doc_url = extract_document_url_from_content(rsrc_json.get("content", []))
            if doc_url:
                full_url = request.build_absolute_uri('/')[:-1] + doc_url
                return HttpResponseRedirect(full_url)
            else:
                logger.error("Document not available or URL not found")
                return render(request, resource_page_template, locals())
        rendered_result = await render_single_resource(rsrc_json, request.user)
    except Exception as e:
        logger.error(f"{db_resource.resource_type}/{db_resource.resource_id} \n {traceback.print_exc()}")
        messages.warning(request, f"{db_resource.resource_type}/{db_resource.resource_id}: {e}")
    return render(request, resource_page_template, locals())


async def handle_resource_result(request, resp: FhirResult, endpoint):
    user_tz = request.COOKIES.get('tz', None)
    res_type = ResUtil.type(resp.http_resp.json)
    res_id = ResUtil.id(resp.http_resp.json)
    pgo_session = request.session.session_key
    log_repo = MedMijLogRepo(endpoint=endpoint, session_id=pgo_session, trace_id="", request_id="")
    log_repo.request_id = resp.http_resp.request_id
    log_repo.trace_id = resp.http_resp.trace_id
    if res_type == ResType.OPERATION_OUTCOME or resp.error:
        messages.warning(request, f"{_('Remote fetch failure')}:  {resp.message}")
        await sync_to_async(log_repo.receive_resource_response)(
            user=request.user, status=resp.http_resp.status, description=resp.message)
        return await sync_to_async(render)(request, resource_page_template, locals())

    if res_type == ResType.BUNDLE:
        # we expect to receive a single resource not a bundle
        messages.warning(request, f"Received [ {res_type}] but we expect [ {resp.menu.api_path.split('?')[0]} ]")
        logger.warning(f"Received [ {res_type}/{res_id} ] but we expect [ {resp.menu.api_path.split('?')[0]} ]")
        await sync_to_async(log_repo.receive_resource_response)(user=request.user, status=resp.http_resp.status)
        return await sync_to_async(render)(request, resource_page_template, locals())

    saved_rsrc: FhirResource = await RepoHealthData.save_resource(
        resp.http_resp.json, request.user, endpoint, resp.menu.api_path
    )
    await sync_to_async(log_repo.receive_resource_response)(user=request.user, status=resp.http_resp.status)
    nav_title = _(saved_rsrc.resource_type)
    fetched = saved_rsrc.fetched_at
    if ResUtil.type(resp.http_resp.json) == ResType.BINARY:
        return await sync_to_async(handle_binary_resource)(resp.http_resp.json, request)

    rendered_result = await render_single_resource(resp.http_resp.json, request.user)
    return await sync_to_async(render)(request, resource_page_template, locals())


async def render_single_resource(resource_json: dict, user: User):
    entry: Entry = from_dict(data_class=Entry, data={'resource': resource_json})
    flatten_resources = await render_fhir_resources(user, [entry])
    rendered_result = Render.table(fhir_resources=flatten_resources, render_template="bundle_render.html")
    rendered_result = rendered_result.decode("utf-8").strip()
    return rendered_result


def handle_binary_resource(resource: dict, request):
    base64_pdf = resource.get('content', '')
    doc_id = resource.get('id', '--')
    pdf_out = b64decode(base64_pdf, validate=True)
    logger.info(f"Got document with id {doc_id}")
    if not base64_pdf:
        logger.error("The base64_pdf string is empty")
    # Basic validation to ensure it is a valid PDF file
    if pdf_out[0:4] != b'%PDF':
        logger.error("No pdf signature")
        raise Http404('Missing PDF file signature')
    if any(keyword in pdf_out for keyword in [b"<script>", b"javascript", b"/JS"]) or 'pdf' not in resource.get('contentType', ''):
        logger.error('Suspicious or invalid content found!')
        raise Http404('Suspicious or invalid content found!')

    # Create a BytesIO buffer from the PDF binary data
    pdf_io = io.BytesIO(pdf_out)
    return FileResponse(pdf_io, as_attachment=False, filename=f"{doc_id}.pdf", content_type='application/pdf')

def get_binary_file(request, doc_id):
    doc: FhirResource = RepoHealthData.get_resource_by_id(doc_id)
    base64_pdf = doc.resource_json.get('content', '')
    pdf_out = b64decode(base64_pdf, validate=True)
    return HttpResponse(pdf_out, content_type="application/pdf")

class ResourceView(
    AsyncLoginRequiredMixin,
    AsyncScopeValidationMixin,
    PgoLogMixin,
    View
):

    async def get(self, request, resource, resource_id):
        user_tz = self.user_timezone
        user = request.user
        db_resource: Optional[FhirResource] = await sync_to_async(RepoHealthData.get_resource_by_id)(resource_id,
                                                                                                     self.endpoint)
        # if the resource exist but user it's not related to it, fetch from server to confirm the auth access
        user_related = await sync_to_async(RepoHealthData.is_user_related)(db_resource, request.user)
        if db_resource and not user_related:
            db_resource = None

        """Get resource from db otherwise get from remote"""
        if db_resource:
            # check the resource belongs to this user
            fetched = db_resource.fetched_at
            resource_obj: DomainResource = from_dict(DomainResource, db_resource.resource_json)
            logger.info("Got resource_obj")
            nav_title = _(resource_obj.title)
            return await handle_db_resource(request, db_resource, user)

        """Get resource from remote server"""
        http_cli = PgoHttp()
        try:
            """Check for token validity, otherwise redirect to auth endpoint"""
            auth_redirect, token_str = await sync_to_async(
                RepoAccount.get_authorization
            )(request, self.endpoint)
            if auth_redirect:
                request.session['redirect_to'] = f"{redirect('show_resource', resource=resource, resource_id=resource_id).url}?scope={self.scope}"
                return auth_redirect

            self.info(f"Get resource from provider {resource}/{resource_id}")
            pgo_session = request.session.session_key
            log_repo = MedMijLogRepo(endpoint=self.endpoint, session_id=pgo_session, trace_id="", request_id="")
            api = f"{resource}/{resource_id}?_format=json"
            log_repo.extra_path = api
            res: FhirResult = await HIS.get_health_record(
                http_cli=http_cli, menu=ServiceEndpointApi(api_path=api, name=resource, slug=api, service=self.service_id),
                token=token_str, request=request, endpoint=self.endpoint
            )
            rsrc_json = res.http_resp.json
            await http_cli.close_session()
            return await handle_resource_result(request, res, self.endpoint)
        except Exception as e:
            await http_cli.close_session()
            self.error(f"Fetch resource failure {resource}/{resource_id}")
            messages.warning(request, f"{_('Fetch resource failure at provider')}: {e}")
        return await sync_to_async(render)(request, resource_page_template, locals())


class HealthServicesView(AsyncLoginRequiredMixin, PgoLogMixin, View):

    async def post(self, request, provider):
        nav_title = provider.replace(".", " ")
        user_services = RepoHealthData.get_patient_provider_services(request.user, provider)
        return await sync_to_async(render)(request, 'service_data.html', locals())


class HealthServiceView(AsyncLoginRequiredMixin, PgoLogMixin, View):

    async def post(self, request, provider, service_id):
        """Get the service name and apis related to it"""
        service = await sync_to_async(RepoProvider.get_service_by_id)(service_id)
        if service:
            nav_title = service.name
        service_apis = RepoProvider.get_apis(service_id)
        return await sync_to_async(render)(request, 'service_apis.html', locals())


class MyHealthDataView(AsyncLoginRequiredMixin, PgoLogMixin, View):

    async def get(self, request, provider, service_id, api_slug):
        show_share_pdf_btn = service_id == ServiceID.PDF_A
        user_tz = self.user_timezone
        api_name = RepoProvider.get_apis(service_id=service_id, slug_filter=api_slug)
        scope = f"{provider}~{service_id}"
        if not Pgex.scope(scope) or not api_name:
            messages.warning(request, _(f"Invalid parameters received"))
            return redirect('home')

        nav_title = _(api_name.name)
        resource_data: FhirResource = await sync_to_async(RepoHealthData.get_resource)(
            request.user, provider, service_id, api_name.api_path
        )
        if not resource_data:
            return await sync_to_async(render)(request, 'bundle_page.html', locals())

        json_b = resource_data.resource_json
        resource_type = ResUtil.type(json_b)
        if resource_type == ResType.BUNDLE:
            exp_bundle: ExpBundle = from_dict(data_class=ExpBundle, data=json_b)
            flatten_resources = await render_fhir_resources(request.user, exp_bundle.entry)
            rendered_result = Render.table(fhir_resources=flatten_resources, render_template="bundle_render.html")
            rendered_result = rendered_result.decode("utf-8").strip()
            # if string is empty, set to none
            if not rendered_result:
                rendered_result = None
        else:
            rendered_result = await render_single_resource(json_b, request.user)

        # set the scope if necessary on other paths for requests
        request.session['scope'] = scope

        return await sync_to_async(render)(request, 'bundle_page.html', locals())

class ExportDataView(AsyncLoginRequiredMixin, View):
    async def get(self, request):
        user = request.user
        logger.info(f"Export data request received for user: {user}")
        try:
            resource_data: list[FhirResource] = await sync_to_async(list)(RepoHealthData.get_resource_by_userid(
                user
            ))

            if not resource_data:
                logger.warning(f"No resources found for user: {user}")
                return JsonResponse({}, status=200)
         
            logger.info(f"Successfully fetched {len(resource_data)} resources for user: {user}")
            return JsonResponse(resource_data, safe=False)

        except Exception as e:
            logger.error(f"Error retrieving resources for user {user}: {str(e)}")
            return JsonResponse({}, status=500)