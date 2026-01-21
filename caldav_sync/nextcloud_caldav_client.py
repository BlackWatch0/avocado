from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

DAV_NAMESPACE = "DAV:"


class CalDAVError(Exception):
    """Base error for CalDAV operations."""


class AuthenticationError(CalDAVError):
    """Authentication failed."""


class NotFoundError(CalDAVError):
    """Resource not found."""


class ConflictError(CalDAVError):
    """Conflict or invalid sync token."""


class BadResponseError(CalDAVError):
    """Unexpected response from CalDAV server."""


@dataclass(frozen=True)
class SyncItem:
    href: str
    etag: Optional[str] = None


@dataclass(frozen=True)
class SyncResult:
    new_sync_token: str
    changed: list[SyncItem]
    deleted: list[SyncItem]


class NextcloudCalDAVClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: float | tuple[float, float] = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.username = username
        self.password = password
        self.timeout = timeout
        import requests

        self._requests = requests
        self.session = requests.Session()
        auth_token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode(
            "utf-8"
        )
        self.session.headers.update(
            {
                "Authorization": f"Basic {auth_token}",
                "Content-Type": "application/xml; charset=utf-8",
            }
        )

    def propfind(self, url: str, depth: int = 0, props: Iterable[str] | None = None) -> dict:
        request_url = self._normalize_url(url)
        body = self._build_propfind_body(props)
        response = self.session.request(
            "PROPFIND",
            request_url,
            data=body,
            headers={"Depth": str(depth)},
            timeout=self.timeout,
        )
        self._raise_for_status(response)
        return self._parse_propfind(response.text)

    def report_sync_collection(
        self,
        collection_url: str,
        sync_token: Optional[str],
        sync_level: int = 1,
        include_etag: bool = True,
        limit: Optional[int] = None,
    ) -> SyncResult:
        request_url = self._normalize_url(collection_url)
        body = self._build_sync_collection_body(
            sync_token=sync_token,
            sync_level=sync_level,
            include_etag=include_etag,
            limit=limit,
        )
        response = self.session.request(
            "REPORT",
            request_url,
            data=body,
            headers={"Depth": "1"},
            timeout=self.timeout,
        )
        if response.status_code == 409:
            raise ConflictError("Sync token invalid or out of date.")
        self._raise_for_status(response)
        return self._parse_sync_collection_response(response.text, collection_url)

    def get_ics(self, href_url: str) -> tuple[Optional[str], str]:
        request_url = self._normalize_url(href_url)
        response = self.session.get(request_url, timeout=self.timeout)
        self._raise_for_status(response)
        return response.headers.get("ETag"), response.text

    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return url
        return urljoin(self.base_url, url.lstrip("/"))

    @staticmethod
    def _build_propfind_body(props: Iterable[str] | None) -> str:
        if not props:
            props = ["displayname"]
        prop_xml = "".join(f"<d:{prop}/>" for prop in props)
        return (
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>"
            "<d:propfind xmlns:d=\"DAV:\">"
            f"<d:prop>{prop_xml}</d:prop>"
            "</d:propfind>"
        )

    @staticmethod
    def _build_sync_collection_body(
        sync_token: Optional[str],
        sync_level: int,
        include_etag: bool,
        limit: Optional[int],
    ) -> str:
        prop_section = "<d:prop><d:getetag/></d:prop>" if include_etag else ""
        token_section = (
            f"<d:sync-token>{sync_token}</d:sync-token>" if sync_token else ""
        )
        limit_section = (
            f"<d:limit><d:nresults>{limit}</d:nresults></d:limit>"
            if limit is not None and sync_token
            else ""
        )
        return (
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>"
            "<d:sync-collection xmlns:d=\"DAV:\">"
            f"{token_section}"
            f"<d:sync-level>{sync_level}</d:sync-level>"
            f"{limit_section}"
            f"{prop_section}"
            "</d:sync-collection>"
        )

    def _raise_for_status(self, response) -> None:
        if response.status_code == 401:
            raise AuthenticationError("Authentication failed (401).")
        if response.status_code == 403:
            raise AuthenticationError("Access forbidden (403).")
        if response.status_code == 404:
            raise NotFoundError("Resource not found (404).")
        if response.status_code == 409:
            raise ConflictError("Conflict (409).")
        if response.status_code >= 400:
            raise BadResponseError(
                f"Unexpected CalDAV response: {response.status_code}"
            )

    @staticmethod
    def _parse_propfind(xml_text: str) -> dict:
        root = ET.fromstring(xml_text)
        ns = {"d": DAV_NAMESPACE}
        results: dict[str, dict] = {}
        for response in root.findall("d:response", ns):
            href = response.findtext("d:href", default="", namespaces=ns)
            props: dict[str, str] = {}
            propstat = response.find("d:propstat", ns)
            if propstat is not None:
                prop = propstat.find("d:prop", ns)
                if prop is not None:
                    for child in prop:
                        props[child.tag] = child.text or ""
            results[href] = props
        return results

    def _parse_sync_collection_response(
        self, xml_text: str, collection_url: str
    ) -> SyncResult:
        root = ET.fromstring(xml_text)
        ns = {"d": DAV_NAMESPACE}
        changed: list[SyncItem] = []
        deleted: list[SyncItem] = []
        for response in root.findall("d:response", ns):
            href_text = response.findtext("d:href", default="", namespaces=ns)
            href = self._normalize_href(collection_url, href_text)
            status_text = response.findtext("d:status", default="", namespaces=ns)
            propstat = response.find("d:propstat", ns)
            etag = None
            if propstat is not None:
                etag = propstat.findtext("d:prop/d:getetag", default=None, namespaces=ns)
            if " 404 " in status_text:
                deleted.append(SyncItem(href=href))
            else:
                changed.append(SyncItem(href=href, etag=etag))
        new_sync_token = root.findtext("d:sync-token", default="", namespaces=ns)
        if not new_sync_token:
            raise BadResponseError("Missing sync-token in response.")
        return SyncResult(new_sync_token=new_sync_token, changed=changed, deleted=deleted)

    def _normalize_href(self, collection_url: str, href: str) -> str:
        parsed = urlparse(href)
        if parsed.scheme and parsed.netloc:
            return href
        return urljoin(collection_url, href)
