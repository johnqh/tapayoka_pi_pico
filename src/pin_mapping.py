"""Logical action-pin mapping for Pico relay outputs."""

from __future__ import annotations

# Early logical pins use easy general-purpose GPIO outputs first.
LOGICAL_TO_GPIO = (
    15,
    14,
    13,
    12,
    11,
    10,
    9,
    8,
    7,
    6,
    5,
    4,
    3,
    2,
    1,
    0,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    26,
    27,
    28,
)

MIN_LOGICAL_PIN = 1
MAX_LOGICAL_PIN = len(LOGICAL_TO_GPIO)


def logical_pin_to_gpio(pin):
    if pin < MIN_LOGICAL_PIN or pin > MAX_LOGICAL_PIN:
        raise ValueError("Logical pin out of range: {}".format(pin))
    return LOGICAL_TO_GPIO[pin - 1]


def map_signal(signal):
    mapped = dict(signal)
    mapped["pinNumber"] = logical_pin_to_gpio(int(signal["pinNumber"]))
    return mapped


def map_signals(signals):
    return [map_signal(signal) for signal in signals]
