import asyncio

import pytest

from src.gpio_control import RelayController


def test_starts_inactive():
    r = RelayController()
    assert not r.is_active
    assert not r.is_sequence_running


def test_activate_deactivate():
    r = RelayController()
    r.activate()
    assert r.is_active
    r.deactivate()
    assert not r.is_active


def test_run_sequence_drives_pins_in_order(monkeypatch):
    r = RelayController()
    calls = []
    monkeypatch.setattr(r, "_set_pin", lambda pin, high: calls.append((pin, high)))

    async def fake_sleep(_s):
        return None

    monkeypatch.setattr("src.gpio_control.asyncio.sleep", fake_sleep)

    async def drive():
        started = r.run_sequence([{"pinNumber": 23, "duration": 5}, {"pinNumber": 24, "duration": 30}])
        assert started is True
        await r._sequence_task

    asyncio.run(drive())

    assert [pin for pin, high in calls if high] == [23, 24]
    last = {}
    for pin, high in calls:
        last[pin] = high
    assert last == {23: False, 24: False}
    assert not r.is_sequence_running


def test_run_sequence_rejects_when_busy():
    r = RelayController()
    r._sequence_running = True
    assert r.run_sequence([{"pinNumber": 23, "duration": 1}]) is False
