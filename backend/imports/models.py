from django.conf import settings
from django.db import models


class ImportJob(models.Model):
    """Stores metadata about an import batch executed by the application."""

    filename = models.CharField(max_length=255, verbose_name="filename")
    source = models.CharField(max_length=255, verbose_name="source")
    duration = models.DurationField(null=True, blank=True, verbose_name="duration")
    success = models.BooleanField(default=False, verbose_name="success")
    message = models.TextField(blank=True, verbose_name="message")
    processed_documents = models.PositiveIntegerField(default=0, verbose_name="processed documents")
    failed_documents = models.PositiveIntegerField(default=0, verbose_name="failed documents")
    warning_count = models.PositiveIntegerField(default=0, verbose_name="warning count")
    execution_log = models.TextField(blank=True, verbose_name="execution log")
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="import_jobs", verbose_name="imported by")
    started_at = models.DateTimeField(auto_now_add=True, verbose_name="started at")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="finished at")

    class Meta:
        verbose_name = "import job"
        verbose_name_plural = "import jobs"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["success", "started_at"]),
            models.Index(fields=["imported_by", "started_at"]),
        ]

    def __str__(self) -> str:
        return self.filename


class PaperlessOutbox(models.Model):
    """Tracks stamped PDFs waiting to be handed to Paperless-ngx."""

    document = models.OneToOneField(
        "documents.Document",
        on_delete=models.CASCADE,
        related_name="paperless_outbox",
        verbose_name="document",
    )
    filename = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="filename",
    )
    attempt_count = models.PositiveIntegerField(
        default=0,
        verbose_name="attempt count",
    )
    last_error = models.TextField(blank=True, verbose_name="last error")
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="delivered at",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="created at",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="updated at",
    )

    class Meta:
        verbose_name = "Paperless outbox item"
        verbose_name_plural = "Paperless outbox items"
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["delivered_at", "created_at"],
                name="imports_outbox_pending_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.filename
