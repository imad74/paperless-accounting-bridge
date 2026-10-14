import json
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from documents.paperless_api import PaperlessApiClient, PaperlessApiError


class PaperlessApiClientTests(SimpleTestCase):
    def test_exact_title_and_filename_matches_are_merged(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            query = parse_qs(urlsplit(request.full_url).query)
            common_document = {
                "id": 10,
                "title": "21-10-2023 CA",
                "original_filename": "21-10-2023 CA.pdf",
                "created": "2023-10-21",
                "page_count": 2,
            }
            if "title__iexact" in query:
                results = [common_document]
            else:
                results = [
                    common_document,
                    {
                        "id": 11,
                        "title": "Titre modifié",
                        "original_filename": "21-10-2023 CA.pdf",
                        "created": "2023-10-22",
                        "page_count": 1,
                    },
                ]
            payload = {"count": len(results), "next": None, "results": results}
            return BytesIO(json.dumps(payload).encode("utf-8"))

        client = PaperlessApiClient(
            base_url="https://archive.example.com/",
            token="secret-token",
            timeout=7,
            urlopen_func=fake_urlopen,
        )

        groups = client.search_exact_names(["21-10-2023 CA"])

        self.assertEqual(len(groups), 1)
        self.assertEqual([item.id for item in groups[0].documents], [10, 11])
        self.assertEqual(
            groups[0].documents[0].web_url,
            "https://archive.example.com/documents/10/details",
        )
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0][1], 7)
        self.assertEqual(
            requests[0][0].get_header("Authorization"),
            "Token secret-token",
        )
        title_query = parse_qs(urlsplit(requests[0][0].full_url).query)
        filename_query = parse_qs(urlsplit(requests[1][0].full_url).query)
        self.assertEqual(
            title_query["title__iexact"],
            ["21-10-2023 CA"],
        )
        self.assertEqual(
            filename_query["original_filename__iexact"],
            ["21-10-2023 CA.pdf"],
        )

    def test_invalid_configuration_is_rejected_without_a_request(self):
        with self.assertRaisesMessage(
            PaperlessApiError,
            "L’adresse de l’API Paperless n’est pas configurée.",
        ):
            PaperlessApiClient(base_url="", token="secret-token")

        with self.assertRaisesMessage(
            PaperlessApiError,
            "Le jeton de l’API Paperless n’est pas configuré.",
        ):
            PaperlessApiClient(
                base_url="https://archive.example.com",
                token="",
            )

    def test_authentication_failure_has_a_safe_message(self):
        def fake_urlopen(request, timeout):
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)

        client = PaperlessApiClient(
            base_url="https://archive.example.com",
            token="invalid-token",
            urlopen_func=fake_urlopen,
        )

        with self.assertRaisesMessage(
            PaperlessApiError,
            "Paperless a refusé le jeton API ou ses permissions.",
        ):
            client.search_exact_names(["Facture"])
