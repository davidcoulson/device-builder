"""Tests for the descriptive ``network`` mDNS TXT key on configured devices."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from esphome_device_builder.controllers._device_state_monitor import DeviceStateMonitor
from esphome_device_builder.models import Device, EventType

from .conftest import (
    make_device,
    make_devices_controller_with_bus,
    make_state_monitor_with_callbacks,
)


def _device(**overrides: Any) -> Device:
    overrides.setdefault("current_version", "2026.5.0")
    return make_device(**overrides)


def _apply(monitor: DeviceStateMonitor, name: str, **props: str) -> None:
    monitor.mdns._apply_network_txt(name, dict(props))


def test_first_observation_fires_callback() -> None:
    """A first ``network`` value reaches the controller."""
    devices = [_device()]
    monitor, callbacks = make_state_monitor_with_callbacks(devices)

    _apply(monitor, "kitchen", network="wifi")

    assert devices[0].runtime_state.network == "wifi"
    assert callbacks.calls == [("on_network_change", "kitchen", "wifi")]


def test_dedupes_same_value() -> None:
    """Repeated identical announces forward once."""
    monitor, callbacks = make_state_monitor_with_callbacks([_device()])

    _apply(monitor, "kitchen", network="wifi")
    _apply(monitor, "kitchen", network="wifi")

    assert callbacks.calls == [("on_network_change", "kitchen", "wifi")]


def test_last_announce_wins() -> None:
    """A dual-interface device follows the freshest announce."""
    devices = [_device()]
    monitor, _callbacks = make_state_monitor_with_callbacks(devices)

    _apply(monitor, "kitchen", network="wifi")
    _apply(monitor, "kitchen", network="ethernet")

    assert devices[0].runtime_state.network == "ethernet"


def test_absent_or_empty_key_never_blanks_known_value() -> None:
    """A missing or empty ``network`` leaves the known value alone."""
    devices = [_device(network="wifi")]
    monitor, callbacks = make_state_monitor_with_callbacks(devices)

    _apply(monitor, "kitchen", version="2026.8.2")
    _apply(monitor, "kitchen", network="")

    assert devices[0].runtime_state.network == "wifi"
    assert callbacks.calls == []


def test_ignores_unknown_device() -> None:
    """Announces for devices not in the catalog are dropped."""
    monitor, callbacks = make_state_monitor_with_callbacks([_device()])

    _apply(monitor, "ghost", network="wifi")

    assert callbacks.calls == []


def test_unwired_callback_silently_drops() -> None:
    """A monitor without ``on_network_change`` ignores the key."""
    monitor = DeviceStateMonitor(
        get_devices=lambda: [_device()],
        on_state_change=MagicMock(),
        on_ip_change=MagicMock(),
    )

    assert monitor._apply_network("kitchen", "wifi") is False


def test_refires_after_device_rebuild() -> None:
    """A rebuilt Device with an empty ``network`` is refilled by the next announce."""
    devices = [_device()]
    monitor, _callbacks = make_state_monitor_with_callbacks(devices)

    _apply(monitor, "kitchen", network="wifi")
    devices[0] = _device()
    _apply(monitor, "kitchen", network="wifi")

    assert devices[0].runtime_state.network == "wifi"


async def test_on_network_change_updates_device_persists_and_fires_event() -> None:
    """The controller callback updates the device, persists, and fires DEVICE_UPDATED."""
    device = _device(network="")
    controller, captured = make_devices_controller_with_bus([device])

    controller._on_network_change("kitchen", "ethernet")

    assert device.runtime_state.network == "ethernet"
    assert controller._metadata_store.get("kitchen.yaml")["network"] == "ethernet"
    assert any(e.event_type == EventType.DEVICE_UPDATED for e in captured)


async def test_on_network_change_skips_when_same() -> None:
    """No event when the device already carries the announced value."""
    device = _device(network="wifi")
    controller, captured = make_devices_controller_with_bus([device])

    controller._on_network_change("kitchen", "wifi")

    assert captured == []


async def test_on_network_change_unknown_device_is_noop() -> None:
    """A callback for an unknown device neither raises nor fires."""
    controller, captured = make_devices_controller_with_bus([])

    controller._on_network_change("ghost", "wifi")

    assert captured == []


def test_esphomelib_txt_applies_network_alongside_identity() -> None:
    """One ``_esphomelib._tcp`` announce populates identity and ``network`` together."""
    devices = [_device()]
    monitor, _callbacks = make_state_monitor_with_callbacks(devices)

    monitor.mdns._apply_txt_properties(
        "kitchen", {"version": "2026.8.2", "config_hash": "8600af66", "network": "wifi"}
    )

    assert devices[0].runtime_state.deployed_version == "2026.8.2"
    assert devices[0].runtime_state.network == "wifi"


def test_http_txt_applies_network_for_non_api_devices() -> None:
    """A non-API device's ``_http._tcp`` TXT carries ``network`` too."""
    devices = [_device(api_enabled=False)]
    monitor, _callbacks = make_state_monitor_with_callbacks(devices)

    monitor.mdns._apply_http_identity_props(
        "kitchen", {"version": "2026.8.2", "network": "ethernet"}
    )

    assert devices[0].runtime_state.network == "ethernet"


def test_network_only_http_txt_does_not_vouch_for_identity() -> None:
    """A TXT carrying only ``network`` must not stamp ``deployed_identity_live``."""
    devices = [_device(api_enabled=False)]
    monitor, callbacks = make_state_monitor_with_callbacks(devices)

    monitor.mdns._apply_http_identity_props("kitchen", {"network": "wifi"})

    assert devices[0].runtime_state.network == "wifi"
    assert devices[0].runtime_state.deployed_identity_live is False
    assert callbacks.calls_for("on_deployed_identity_live_change") == []
