"""Tests for the opt-in ``[[silent]]`` silence feature (gateway delivery side).

Contract under test:
- The exact marker is never sent: ``DeliveryTransport.send``,
  ``DeliveryRouter._deliver_to_platform``, and both Relay egress doors
  (``send`` / ``send_for_platform``) swallow it and report
  ``{"success": True, "filtered": "silent", "delivered": False}``.
- Ordinary text (including messages that merely CONTAIN the marker) still sends.
- Relay skips happen before seal-interception and before any transport use.
"""

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.delivery import (
    DeliveryRouter,
    DeliveryTarget,
    DeliveryTransport,
    is_silent_response,
)
from gateway.relay.adapter import RelayAdapter


class RecordingAdapter:
    """Fake native transport: records every send through either door."""

    def __init__(self):
        self.calls = []

    async def send(self, chat_id, content, metadata=None):
        self.calls.append(
            {"door": "send", "chat_id": chat_id, "content": content, "metadata": metadata}
        )
        return {"success": True}

    async def send_for_platform(self, platform, chat_id, content, metadata=None):
        self.calls.append(
            {
                "door": "send_for_platform",
                "platform": platform,
                "chat_id": chat_id,
                "content": content,
                "metadata": metadata,
            }
        )
        return {"success": True}


def test_is_silent_response_exact_only():
    assert is_silent_response("[[silent]]") is True
    assert is_silent_response("  [[silent]]\n") is True
    assert is_silent_response("[[silent]] stay quiet") is False
    assert is_silent_response("note [[silent]]") is False
    assert is_silent_response("") is False
    assert is_silent_response(None) is False


# --- DeliveryTransport (both doors) -----------------------------------------


@pytest.mark.asyncio
async def test_transport_native_door_skips_marker():
    adapter = RecordingAdapter()
    transport = DeliveryTransport(adapter, None, Platform.DISCORD)
    result = await transport.send(Platform.DISCORD, "123", "[[silent]]", None)
    assert adapter.calls == []  # no send on marker
    assert result == {"success": True, "filtered": "silent", "delivered": False}


@pytest.mark.asyncio
async def test_transport_native_door_sends_normal_text():
    adapter = RecordingAdapter()
    transport = DeliveryTransport(adapter, None, Platform.DISCORD)
    result = await transport.send(Platform.DISCORD, "123", "hello", None)
    assert len(adapter.calls) == 1
    assert adapter.calls[0] == {
        "door": "send",
        "chat_id": "123",
        "content": "hello",
        "metadata": None,
    }
    assert result == {"success": True}


@pytest.mark.asyncio
async def test_transport_relay_door_skips_marker():
    adapter = RecordingAdapter()
    transport = DeliveryTransport(adapter, None, Platform.RELAY)
    result = await transport.send(Platform.DISCORD, "123", "[[silent]]", None)
    assert adapter.calls == []  # no send on marker
    assert result == {"success": True, "filtered": "silent", "delivered": False}


@pytest.mark.asyncio
async def test_transport_relay_door_sends_normal_text():
    adapter = RecordingAdapter()
    transport = DeliveryTransport(adapter, None, Platform.RELAY)
    await transport.send(Platform.DISCORD, "123", "hello", None)
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["door"] == "send_for_platform"


# --- DeliveryRouter ----------------------------------------------------------


@pytest.mark.asyncio
async def test_router_skips_marker_pre_send():
    adapter = RecordingAdapter()
    router = DeliveryRouter(GatewayConfig(), adapters={Platform.DISCORD: adapter})
    target = DeliveryTarget.parse("discord:99887766")
    result = await router._deliver_to_platform(target, "[[silent]]", metadata=None)
    assert adapter.calls == []  # adapter.send never invoked
    assert result == {"success": True, "filtered": "silent", "delivered": False}


@pytest.mark.asyncio
async def test_router_sends_text_containing_marker():
    adapter = RecordingAdapter()
    router = DeliveryRouter(GatewayConfig(), adapters={Platform.DISCORD: adapter})
    target = DeliveryTarget.parse("discord:99887766")
    result = await router._deliver_to_platform(
        target, "the marker is [[silent]] ok", metadata=None
    )
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["content"] == "the marker is [[silent]] ok"
    assert result == {"success": True}


# --- Relay egress doors ------------------------------------------------------


def _bare_relay_adapter():
    """RelayAdapter without any state: the marker skip must fire before any
    attribute (transport, draft caches, platform maps) is touched."""
    return RelayAdapter.__new__(RelayAdapter)


@pytest.mark.asyncio
async def test_relay_send_skips_marker_without_transport():
    result = await _bare_relay_adapter().send("chat1", "[[silent]]")
    assert result.success is True
    assert result.message_id is None


@pytest.mark.asyncio
async def test_relay_send_for_platform_skips_marker_without_transport():
    result = await _bare_relay_adapter().send_for_platform(
        Platform.DISCORD, "chat1", "  [[silent]]  "
    )
    assert result.success is True
    assert result.message_id is None


@pytest.mark.asyncio
async def test_relay_send_for_platform_non_marker_still_gated():
    """Control: the skip is exact-match only — other content still reaches the
    normal gating (here: not fronting → typed failure, no silent skip)."""
    adapter = _bare_relay_adapter()
    adapter.fronts_platform = lambda platform: False
    adapter._transport = None
    result = await adapter.send_for_platform(Platform.DISCORD, "chat1", "hello")
    assert result.success is False
    assert "does not front" in (result.error or "")
