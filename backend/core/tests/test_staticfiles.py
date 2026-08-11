from django.apps import apps
from django.contrib.staticfiles.utils import matches_patterns
from django.test import SimpleTestCase

from config.staticfiles import PABStaticFilesConfig


class StaticFilesConfigTests(SimpleTestCase):
    def test_unused_tabler_bundles_are_ignored(self):
        config = apps.get_app_config("staticfiles")

        self.assertIsInstance(config, PABStaticFilesConfig)
        for bundle in ("flags", "payments", "socials"):
            with self.subTest(bundle=bundle):
                self.assertTrue(
                    matches_patterns(
                        f"vendor/tabler/css/tabler-{bundle}.min.css",
                        config.ignore_patterns,
                    )
                )

    def test_main_tabler_stylesheet_is_collected(self):
        config = apps.get_app_config("staticfiles")

        self.assertFalse(
            matches_patterns(
                "vendor/tabler/css/tabler.min.css",
                config.ignore_patterns,
            )
        )
