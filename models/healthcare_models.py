from django.db import models

from apps.accounts.models import User
from apps.providers.models import Endpoint


class FhirResource(models.Model):
    objects = models.Manager()

    fetched_at = models.DateTimeField(auto_now=True, verbose_name="Fetched")
    resource_json = models.JSONField(verbose_name="Resource json", default=dict, null=True, blank=True)
    resource_id = models.CharField(max_length=100, verbose_name="Resource id")
    resource_type = models.CharField(max_length=100, verbose_name="Resource type")

    #  [] we'll use json list instead of new table for many-to-many relation
    users = models.ManyToManyField(User)
    data_source = models.ForeignKey(Endpoint, on_delete=models.CASCADE, related_name='endpoint_resources', null=True)
    api_source = models.CharField(max_length=500, verbose_name="API source")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['resource_id', 'data_source'],
                name='user_provider_resource_unique'
            )
        ]

    def __str__(self):
        return f"{self.data_source}/{self.resource_type}/{self.resource_id}"

    @staticmethod
    def is_empty():
        return FhirResource.objects.count() == 0


class TerminologyCode(models.Model):
    objects = models.Manager()
    code = models.CharField(max_length=50)
    system = models.CharField(max_length=50, choices=(('snomed', 'SNOMED'), ('loinc', 'LOINC'),))
    description = models.CharField(max_length=500)

    def __str__(self):
        return f"{self.system}: {self.code}"


class SharedDocuments(models.Model):

    objects = models.Manager()

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shared_documents', verbose_name="Patient")
    resources = models.ManyToManyField(FhirResource)
    shared_with = models.ForeignKey(Endpoint, on_delete=models.CASCADE, related_name='shared_documents',
                                    verbose_name="Shared with")
    shared_at = models.DateTimeField(auto_now_add=True, verbose_name="Shared at")

    @property
    def total(self):
        return f"{self.resources.count()}"

    def __str__(self):
        return f"{self.user} shared to {self.shared_with}"


class Medication(models.Model):

    objects = models.Manager()

    resource_id = models.CharField(max_length=300, verbose_name="Resource ID", default="")
    identifier = models.CharField(max_length=300, verbose_name="Identifier", default="")
    reference = models.CharField(max_length=300, verbose_name="Reference", default="")
    profile = models.CharField(max_length=300, verbose_name="Profile", default="")
    resource_type = models.CharField(max_length=200, verbose_name="Resource", default="")
    title = models.CharField(max_length=200, verbose_name="Title", default="")
    provider = models.CharField(max_length=200, verbose_name="Provider", default="")
    status = models.CharField(max_length=100, verbose_name="Status", default="")
    product = models.CharField(max_length=300, verbose_name="Product", default="")
    start = models.DateTimeField(verbose_name="Start")
    end = models.DateTimeField(verbose_name="End", null=True, blank=True)
    duration = models.CharField(max_length=100, default="")
    quantity = models.CharField(max_length=100, default="")
    prescriber = models.CharField(max_length=100, default="")
    author = models.CharField(max_length=100, default="")
    performer = models.CharField(max_length=100, default="")

    dosage = models.CharField(max_length=300, verbose_name="Medication dosage", default="")
    treatment = models.CharField(max_length=300, verbose_name="Medication treatment", default="")
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='medications', verbose_name="Patient")

