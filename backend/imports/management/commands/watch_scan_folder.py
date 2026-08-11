import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from imports.services import ScanConfigurationError, ScanFolderImporter


class Command(BaseCommand):
    help = (
        "Surveille le dossier des scans, importe les PDF stables et les "
        "remet à Paperless-ngx."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Traite un cycle puis quitte.",
        )
        parser.add_argument(
            "--poll-seconds",
            type=int,
            default=settings.SCAN_POLL_SECONDS,
            help="Délai entre deux cycles de surveillance.",
        )

    def handle(self, *args, **options):
        poll_seconds = options["poll_seconds"]
        if poll_seconds < 1:
            raise CommandError("--poll-seconds doit être supérieur à zéro.")

        importer = ScanFolderImporter.from_settings()
        if options["once"]:
            self._run_cycle(importer)
            return

        should_stop = False

        def request_stop(signum, frame):
            nonlocal should_stop
            should_stop = True

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        self.stdout.write(
            self.style.SUCCESS(
                "Surveillance automatique des scans démarrée."
            )
        )

        while not should_stop:
            self._run_cycle(importer)
            if not should_stop:
                time.sleep(poll_seconds)

    def _run_cycle(self, importer):
        try:
            results = importer.process_ready_files()
        except ScanConfigurationError as error:
            raise CommandError(str(error)) from error

        for result in results:
            if result.success:
                self.stdout.write(self.style.SUCCESS(result.message))
            else:
                self.stderr.write(self.style.ERROR(result.message))
