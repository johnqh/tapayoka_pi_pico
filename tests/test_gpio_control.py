"""Tests for GPIO control (mock mode)."""

from src.gpio_control import RelayController


def test_relay_starts_inactive():
    relay = RelayController()
    assert not relay.is_active


def test_relay_activate():
    relay = RelayController()
    relay.activate()
    assert relay.is_active


def test_relay_deactivate():
    relay = RelayController()
    relay.activate()
    relay.deactivate()
    assert not relay.is_active
