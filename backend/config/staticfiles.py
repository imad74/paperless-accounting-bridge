from django.contrib.staticfiles.apps import StaticFilesConfig


class PABStaticFilesConfig(StaticFilesConfig):
    """Exclude unused Tabler bundles whose optional assets are not vendored."""

    ignore_patterns = [
        *StaticFilesConfig.ignore_patterns,
        "vendor/tabler/css/tabler-flags*",
        "vendor/tabler/css/tabler-payments*",
        "vendor/tabler/css/tabler-socials*",
    ]
