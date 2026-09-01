from __future__ import annotations

from email.message import Message
from typing import Any

import pytest

from app.errors import RegistryError
from app.federation.network import NetworkPolicy
from app.media.credentials import CredentialLease
from app.media.onvif import OnvifMediaNegotiator


def _headers() -> Message:
    return Message()


def test_onvif_negotiates_and_selects_low_bandwidth_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    negotiator = OnvifMediaNegotiator(NetworkPolicy(), timeout_seconds=2)
    bodies: list[bytes] = []
    responses = iter(
        [
            b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>'
            b"<Capabilities><Media><XAddr>http://8.8.8.8/onvif/media</XAddr></Media>"
            b"</Capabilities></s:Body></s:Envelope>",
            b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>'
            b'<Profiles token="main"><VideoEncoderConfiguration><Encoding>H264</Encoding>'
            b"<Resolution><Width>1920</Width><Height>1080</Height></Resolution>"
            b"<RateControl><FrameRateLimit>25</FrameRateLimit><BitrateLimit>4096</BitrateLimit>"
            b'</RateControl></VideoEncoderConfiguration></Profiles><Profiles token="sub">'
            b"<VideoEncoderConfiguration><Encoding>H264</Encoding><Resolution><Width>640</Width>"
            b"<Height>360</Height></Resolution><RateControl><FrameRateLimit>10</FrameRateLimit>"
            b"<BitrateLimit>512</BitrateLimit></RateControl></VideoEncoderConfiguration></Profiles>"
            b"</s:Body></s:Envelope>",
            b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>'
            b"<MediaUri><Uri>rtsp://8.8.8.8/Streaming/Channels/102</Uri></MediaUri>"
            b"</s:Body></s:Envelope>",
        ]
    )

    def exchange(*args: Any, **kwargs: Any) -> tuple[int, Message, bytes]:
        bodies.append(kwargs["body"])
        return 200, _headers(), next(responses)

    monkeypatch.setattr(negotiator, "_exchange", exchange)
    lease = CredentialLease("camera-user", "camera-password", "test")
    stream = negotiator.resolve(
        "http://8.8.8.8/onvif/device_service",
        credentials=lease,
        stream_role="substream",
    )
    assert stream.endpoint == "rtsp://8.8.8.8/Streaming/Channels/102"
    assert (stream.width, stream.height, stream.frame_rate, stream.bitrate_kbps) == (
        640,
        360,
        10,
        512,
    )
    assert b"<ProfileToken>sub</ProfileToken>" in bodies[-1]
    assert all(b"camera-password" not in body for body in bodies)


def test_onvif_revalidates_derived_media_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    negotiator = OnvifMediaNegotiator(NetworkPolicy(), timeout_seconds=2)

    def exchange(*args: Any, **kwargs: Any) -> tuple[int, Message, bytes]:
        del args, kwargs
        return (
            200,
            _headers(),
            b"<Envelope><Media><XAddr>http://169.254.169.254/onvif/media</XAddr></Media>"
            b"</Envelope>",
        )

    monkeypatch.setattr(negotiator, "_exchange", exchange)
    with pytest.raises(RegistryError) as captured:
        negotiator.resolve(
            "http://8.8.8.8/onvif/device_service",
            credentials=CredentialLease("user", "password", "test"),
            stream_role="primary",
        )
    assert captured.value.code == "FEDERATION_ENDPOINT_BLOCKED"
