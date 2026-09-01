from __future__ import annotations

import base64
import hashlib
import http.client
import os
import re
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from html import escape
from urllib.parse import urlsplit
from xml.etree import ElementTree

from app.errors import RegistryError
from app.federation.network import NetworkPolicy, NetworkTarget
from app.media.credentials import CredentialLease

MAX_ONVIF_RESPONSE_BYTES = 1024 * 1024
_DIGEST_PAIR = re.compile(r'(\w+)=(?:"([^"]*)"|([^,\s]+))')


@dataclass(frozen=True, slots=True)
class OnvifStream:
    endpoint: str
    encoding: str | None
    width: int | None
    height: int | None
    frame_rate: float | None
    bitrate_kbps: int | None


@dataclass(frozen=True, slots=True)
class _Profile:
    token: str
    encoding: str | None
    width: int | None
    height: int | None
    frame_rate: float | None
    bitrate_kbps: int | None

    @property
    def score(self) -> tuple[int, float, int]:
        pixels = (self.width or 0) * (self.height or 0)
        return pixels, self.frame_rate or 0, self.bitrate_kbps or 0


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    for child in element.iter():
        if _local_name(child.tag) == name and child.text:
            return child.text.strip()
    return None


def _as_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _as_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _wsse_header(credentials: CredentialLease) -> str:
    nonce = os.urandom(20)
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    digest = base64.b64encode(
        hashlib.sha1(
            nonce + created.encode("utf-8") + credentials.password.encode("utf-8")
        ).digest()
    ).decode("ascii")
    return (
        '<s:Header><wsse:Security s:mustUnderstand="1" '
        'xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/'
        'oasis-200401-wss-wssecurity-secext-1.0.xsd" '
        'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/'
        'oasis-200401-wss-wssecurity-utility-1.0.xsd">'
        "<wsse:UsernameToken><wsse:Username>"
        f"{escape(credentials.username)}</wsse:Username>"
        '<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/'
        'oasis-200401-wss-username-token-profile-1.0#PasswordDigest">'
        f"{digest}</wsse:Password>"
        '<wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/'
        'oasis-200401-wss-soap-message-security-1.0#Base64Binary">'
        f"{base64.b64encode(nonce).decode('ascii')}</wsse:Nonce>"
        f"<wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security></s:Header>"
    )


def _envelope(body: str, credentials: CredentialLease) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        f"{_wsse_header(credentials)}<s:Body>{body}</s:Body></s:Envelope>"
    ).encode()


def _digest_authorization(
    challenge: str,
    *,
    credentials: CredentialLease,
    method: str,
    request_target: str,
) -> str:
    values = {
        match.group(1).lower(): match.group(2) if match.group(2) is not None else match.group(3)
        for match in _DIGEST_PAIR.finditer(challenge)
    }
    realm = values.get("realm")
    nonce = values.get("nonce")
    if not realm or not nonce:
        raise RegistryError(
            code="ONVIF_AUTH_CHALLENGE_INVALID",
            message="The ONVIF device returned an invalid authentication challenge",
            status_code=502,
        )
    algorithm = values.get("algorithm", "MD5").upper()
    if algorithm not in {"MD5", "SHA-256"}:
        raise RegistryError(
            code="ONVIF_AUTH_ALGORITHM_UNSUPPORTED",
            message="The ONVIF device requested an unsupported authentication algorithm",
            status_code=502,
        )
    hash_fn = hashlib.md5 if algorithm == "MD5" else hashlib.sha256

    def digest(value: str) -> str:
        return hash_fn(value.encode("utf-8")).hexdigest()

    ha1 = digest(f"{credentials.username}:{realm}:{credentials.password}")
    ha2 = digest(f"{method}:{request_target}")
    qop_values = [value.strip() for value in values.get("qop", "").split(",") if value.strip()]
    cnonce = os.urandom(12).hex()
    if qop_values:
        if "auth" not in qop_values:
            raise RegistryError(
                code="ONVIF_AUTH_QOP_UNSUPPORTED",
                message="The ONVIF device requested an unsupported authentication mode",
                status_code=502,
            )
        response = digest(f"{ha1}:{nonce}:00000001:{cnonce}:auth:{ha2}")
    else:
        response = digest(f"{ha1}:{nonce}:{ha2}")
    fields = [
        f'username="{credentials.username.replace(chr(34), "")}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{request_target}"',
        f'response="{response}"',
        f"algorithm={algorithm}",
    ]
    if values.get("opaque"):
        fields.append(f'opaque="{values["opaque"]}"')
    if qop_values:
        fields.extend(["qop=auth", "nc=00000001", f'cnonce="{cnonce}"'])
    return "Digest " + ", ".join(fields)


class OnvifMediaNegotiator:
    """Bounded ONVIF Media1 negotiation over policy-pinned HTTP(S)."""

    def __init__(self, policy: NetworkPolicy, *, timeout_seconds: float) -> None:
        self.policy = policy
        self.timeout_seconds = min(max(timeout_seconds, 0.5), 30.0)

    @staticmethod
    def _request_target(endpoint: str) -> str:
        parsed = urlsplit(endpoint)
        target = parsed.path or "/"
        return f"{target}?{parsed.query}" if parsed.query else target

    def _exchange(
        self,
        endpoint: str,
        *,
        target: NetworkTarget,
        body: bytes,
        action: str,
        authorization: str | None = None,
    ) -> tuple[int, Message, bytes]:
        request_target = self._request_target(endpoint)
        deadline = time.monotonic() + self.timeout_seconds
        last_error: Exception | None = None
        for address in target.resolved_ips:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            connection = http.client.HTTPConnection(target.hostname, target.port, timeout=remaining)
            try:
                raw_socket = socket.create_connection((address, target.port), timeout=remaining)
                if target.scheme == "https":
                    raw_socket = ssl.create_default_context().wrap_socket(
                        raw_socket, server_hostname=target.hostname
                    )
                connection.sock = raw_socket
                headers = {
                    "Content-Type": (f'application/soap+xml; charset=utf-8; action="{action}"'),
                    "SOAPAction": f'"{action}"',
                    "User-Agent": "Drishti-AI-ONVIF/1.0",
                    "Connection": "close",
                }
                if authorization:
                    headers["Authorization"] = authorization
                connection.request("POST", request_target, body=body, headers=headers)
                response = connection.getresponse()
                payload = response.read(MAX_ONVIF_RESPONSE_BYTES + 1)
                if len(payload) > MAX_ONVIF_RESPONSE_BYTES:
                    raise RegistryError(
                        code="ONVIF_RESPONSE_TOO_LARGE",
                        message="The ONVIF device response exceeded the configured safety limit",
                        status_code=502,
                    )
                return response.status, response.headers, payload
            except RegistryError:
                raise
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                last_error = exc
            finally:
                connection.close()
        raise RegistryError(
            code="ONVIF_NETWORK_ERROR",
            message="The ONVIF device could not be reached from this worker",
            status_code=502,
        ) from last_error

    def _soap(
        self,
        endpoint: str,
        *,
        body: str,
        action: str,
        credentials: CredentialLease,
    ) -> ElementTree.Element:
        target = self.policy.validate_network_endpoint(
            endpoint,
            allowed_schemes=("http", "https"),
            default_ports={"http": 80, "https": 443},
        )
        payload = _envelope(body, credentials)
        status, headers, response_body = self._exchange(
            endpoint, target=target, body=payload, action=action
        )
        if status == 401:
            challenge = headers.get("WWW-Authenticate", "")
            if challenge.lower().startswith("digest "):
                authorization = _digest_authorization(
                    challenge,
                    credentials=credentials,
                    method="POST",
                    request_target=self._request_target(endpoint),
                )
            elif challenge.lower().startswith("basic ") and target.scheme == "https":
                token = base64.b64encode(
                    f"{credentials.username}:{credentials.password}".encode()
                ).decode("ascii")
                authorization = f"Basic {token}"
            else:
                raise RegistryError(
                    code="ONVIF_AUTHENTICATION_FAILED",
                    message="The ONVIF device rejected the configured credential profile",
                    status_code=502,
                )
            status, _, response_body = self._exchange(
                endpoint,
                target=target,
                body=payload,
                action=action,
                authorization=authorization,
            )
        if status in {401, 403}:
            raise RegistryError(
                code="ONVIF_AUTHENTICATION_FAILED",
                message="The ONVIF device rejected the configured credential profile",
                status_code=502,
            )
        if not 200 <= status < 300:
            raise RegistryError(
                code="ONVIF_HTTP_ERROR",
                message="The ONVIF device returned an unsuccessful response",
                status_code=502,
            )
        lowered = response_body.lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            raise RegistryError(
                code="ONVIF_XML_UNSAFE",
                message="The ONVIF device returned an unsupported XML document",
                status_code=502,
            )
        try:
            root = ElementTree.fromstring(response_body)
        except ElementTree.ParseError as exc:
            raise RegistryError(
                code="ONVIF_XML_INVALID",
                message="The ONVIF device returned malformed XML",
                status_code=502,
            ) from exc
        if any(_local_name(element.tag) == "Fault" for element in root.iter()):
            raise RegistryError(
                code="ONVIF_SOAP_FAULT",
                message="The ONVIF device could not complete media negotiation",
                status_code=502,
            )
        return root

    @staticmethod
    def _profiles(root: ElementTree.Element) -> list[_Profile]:
        profiles: list[_Profile] = []
        for element in root.iter():
            if _local_name(element.tag) != "Profiles":
                continue
            token = element.attrib.get("token")
            if not token or len(token) > 512:
                continue
            encoder = next(
                (
                    child
                    for child in element.iter()
                    if _local_name(child.tag) == "VideoEncoderConfiguration"
                ),
                None,
            )
            profiles.append(
                _Profile(
                    token=token,
                    encoding=_child_text(encoder, "Encoding") if encoder is not None else None,
                    width=_as_int(_child_text(encoder, "Width")) if encoder is not None else None,
                    height=_as_int(_child_text(encoder, "Height")) if encoder is not None else None,
                    frame_rate=(
                        _as_float(_child_text(encoder, "FrameRateLimit"))
                        if encoder is not None
                        else None
                    ),
                    bitrate_kbps=(
                        _as_int(_child_text(encoder, "BitrateLimit"))
                        if encoder is not None
                        else None
                    ),
                )
            )
        return profiles

    def resolve(
        self,
        device_endpoint: str,
        *,
        credentials: CredentialLease,
        stream_role: str,
    ) -> OnvifStream:
        capabilities = self._soap(
            device_endpoint,
            body=(
                '<GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl">'
                "<Category>Media</Category></GetCapabilities>"
            ),
            action="http://www.onvif.org/ver10/device/wsdl/GetCapabilities",
            credentials=credentials,
        )
        media_endpoint = None
        for element in capabilities.iter():
            if _local_name(element.tag) == "Media":
                media_endpoint = _child_text(element, "XAddr")
                if media_endpoint:
                    break
        if not media_endpoint or len(media_endpoint) > 4096:
            raise RegistryError(
                code="ONVIF_MEDIA_SERVICE_MISSING",
                message="The ONVIF device did not advertise a usable Media service",
                status_code=502,
            )
        # Every derived service endpoint is independently revalidated before use.
        self.policy.validate_network_endpoint(
            media_endpoint,
            allowed_schemes=("http", "https"),
            default_ports={"http": 80, "https": 443},
        )
        profiles_root = self._soap(
            media_endpoint,
            body='<GetProfiles xmlns="http://www.onvif.org/ver10/media/wsdl"/>',
            action="http://www.onvif.org/ver10/media/wsdl/GetProfiles",
            credentials=credentials,
        )
        profiles = self._profiles(profiles_root)
        if not profiles:
            raise RegistryError(
                code="ONVIF_PROFILES_MISSING",
                message="The ONVIF device did not return a usable media profile",
                status_code=502,
            )
        selected = (
            min(profiles, key=lambda item: item.score)
            if stream_role == "substream"
            else max(profiles, key=lambda item: item.score)
        )
        uri_root = self._soap(
            media_endpoint,
            body=(
                '<GetStreamUri xmlns="http://www.onvif.org/ver10/media/wsdl">'
                '<StreamSetup><Stream xmlns="http://www.onvif.org/ver10/schema">RTP-Unicast</Stream>'
                '<Transport xmlns="http://www.onvif.org/ver10/schema"><Protocol>RTSP</Protocol>'
                f"</Transport></StreamSetup><ProfileToken>{escape(selected.token)}</ProfileToken>"
                "</GetStreamUri>"
            ),
            action="http://www.onvif.org/ver10/media/wsdl/GetStreamUri",
            credentials=credentials,
        )
        stream_uri = next(
            (
                element.text.strip()
                for element in uri_root.iter()
                if _local_name(element.tag) == "Uri" and element.text
            ),
            None,
        )
        if not stream_uri or len(stream_uri) > 4096:
            raise RegistryError(
                code="ONVIF_STREAM_URI_MISSING",
                message="The ONVIF device did not return a usable RTSP stream URI",
                status_code=502,
            )
        return OnvifStream(
            endpoint=stream_uri,
            encoding=selected.encoding,
            width=selected.width,
            height=selected.height,
            frame_rate=selected.frame_rate,
            bitrate_kbps=selected.bitrate_kbps,
        )
