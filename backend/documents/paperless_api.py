import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from django.conf import settings


class PaperlessApiError(Exception):
    """Raised when Paperless cannot serve an exact-name search."""


@dataclass(frozen=True)
class PaperlessDocument:
    id: int
    title: str
    original_filename: str
    created: str
    page_count: int | None
    web_url: str


@dataclass(frozen=True)
class PaperlessSearchGroup:
    name: str
    documents: tuple[PaperlessDocument, ...]


class PaperlessApiClient:
    """Small read-only client for exact Paperless document lookups."""

    PAGE_SIZE = 100
    MAX_PAGES = 100
    MAX_WORKERS = 8

    def __init__(
        self,
        *,
        base_url=None,
        token=None,
        timeout=None,
        urlopen_func=None,
    ):
        self.base_url = (
            settings.PAPERLESS_API_URL if base_url is None else base_url
        ).strip().rstrip("/")
        self.token = (
            settings.PAPERLESS_API_TOKEN if token is None else token
        ).strip()
        self.timeout = (
            settings.PAPERLESS_API_TIMEOUT if timeout is None else timeout
        )
        self.urlopen = urlopen if urlopen_func is None else urlopen_func

        parsed_url = urlsplit(self.base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise PaperlessApiError(
                "L’adresse de l’API Paperless n’est pas configurée."
            )
        if not self.token:
            raise PaperlessApiError(
                "Le jeton de l’API Paperless n’est pas configuré."
            )
        if self.timeout <= 0:
            raise PaperlessApiError(
                "Le délai d’attente de l’API Paperless est invalide."
            )

    def search_exact_names(self, names):
        if not names:
            return ()
        worker_count = min(self.MAX_WORKERS, len(names))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            return tuple(executor.map(self._search_exact_name, names))

    def _search_exact_name(self, name):
        documents_by_id = {}
        for document in self._find_documents(title__iexact=name):
            documents_by_id[document.id] = document
        for document in self._find_documents(
            original_filename__iexact=f"{name}.pdf"
        ):
            documents_by_id[document.id] = document

        documents = tuple(
            sorted(
                documents_by_id.values(),
                key=lambda item: (item.title.casefold(), item.id),
            )
        )
        return PaperlessSearchGroup(name=name, documents=documents)

    def _find_documents(self, **filters):
        documents = []
        page = 1

        while page <= self.MAX_PAGES:
            parameters = {
                **filters,
                "page": page,
                "page_size": self.PAGE_SIZE,
            }
            payload = self._request_json(
                f"{self.base_url}/api/documents/?{urlencode(parameters)}"
            )
            results = payload.get("results")
            if not isinstance(results, list):
                raise PaperlessApiError(
                    "La réponse de l’API Paperless est invalide."
                )

            documents.extend(
                self._deserialize_document(item) for item in results
            )
            if not payload.get("next"):
                return documents
            page += 1

        raise PaperlessApiError(
            "La réponse Paperless contient trop de pages de résultats."
        )

    def _request_json(self, url):
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Token {self.token}",
            },
        )
        try:
            with self.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            if error.code in {401, 403}:
                message = (
                    "Paperless a refusé le jeton API ou ses permissions."
                )
            else:
                message = f"Paperless a répondu avec l’erreur HTTP {error.code}."
            raise PaperlessApiError(message) from error
        except (URLError, OSError, TimeoutError) as error:
            raise PaperlessApiError(
                "Paperless est temporairement inaccessible."
            ) from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise PaperlessApiError(
                "La réponse de l’API Paperless est illisible."
            ) from error

        if not isinstance(payload, dict):
            raise PaperlessApiError(
                "La réponse de l’API Paperless est invalide."
            )
        return payload

    def _deserialize_document(self, item):
        if not isinstance(item, dict) or "id" not in item:
            raise PaperlessApiError(
                "Un document retourné par Paperless est invalide."
            )
        try:
            document_id = int(item["id"])
        except (TypeError, ValueError) as error:
            raise PaperlessApiError(
                "Un identifiant retourné par Paperless est invalide."
            ) from error

        page_count = item.get("page_count")
        if page_count is not None:
            try:
                page_count = int(page_count)
            except (TypeError, ValueError):
                page_count = None

        return PaperlessDocument(
            id=document_id,
            title=str(item.get("title") or ""),
            original_filename=str(item.get("original_filename") or ""),
            created=str(item.get("created") or ""),
            page_count=page_count,
            web_url=f"{self.base_url}/documents/{document_id}/details",
        )
