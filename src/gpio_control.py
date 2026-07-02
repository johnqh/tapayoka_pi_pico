"""GPIO relay control for Pico W: single-pin timed + multi-pin async sequences."""

try:
    from machine import Pin, Timer
    MACHINE_AVAILABLE = True
except ImportError:
    MACHINE_AVAILABLE = False
    print("[GPIO] machine module not available - mock mode")

try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

from .config import DEFAULT_RELAY_PIN


class RelayController:
    def __init__(self, pin_num=DEFAULT_RELAY_PIN):
        self._pin_num = pin_num
        self._active_pin = pin_num
        self._active = False
        self._timer = Timer() if MACHINE_AVAILABLE else None
        self._pins = {}
        self._sequence_running = False
        self._sequence_task = None
        self._ensure_pin(pin_num)
        print("[GPIO] Initialized pin", pin_num if MACHINE_AVAILABLE else "(mock)")

    @property
    def is_active(self):
        return self._active

    @property
    def is_sequence_running(self):
        return self._sequence_running

    def _ensure_pin(self, pin_num):
        if pin_num in self._pins:
            return
        if MACHINE_AVAILABLE:
            self._pins[pin_num] = Pin(pin_num, Pin.OUT, value=0)
        else:
            self._pins[pin_num] = None

    def _set_pin(self, pin_num, high):
        self._ensure_pin(pin_num)
        pin = self._pins.get(pin_num)
        if pin is not None:
            pin.value(1 if high else 0)

    def activate(self, duration_seconds=0, pin=None):
        self._cancel_timer()
        target = self._pin_num if pin is None else int(pin)
        self._active_pin = target
        self._set_pin(target, True)
        self._active = True
        print("[GPIO] Relay ON", target)
        if duration_seconds > 0 and self._timer:
            self._timer.init(
                mode=Timer.ONE_SHOT,
                period=duration_seconds * 1000,
                callback=lambda t: self.deactivate(),
            )

    def deactivate(self, _timer=None):
        self._cancel_timer()
        self._set_pin(self._active_pin, False)
        self._active = False
        print("[GPIO] Relay OFF")

    def run_sequence(self, signals):
        if self._sequence_running:
            return False
        self._sequence_running = True
        self._sequence_task = asyncio.create_task(self._run_sequence(list(signals)))
        return True

    async def _run_sequence(self, signals):
        touched = []
        try:
            for sig in signals:
                pin_num = int(sig["pinNumber"])
                duration = float(sig["duration"])
                if pin_num not in touched:
                    touched.append(pin_num)
                self._set_pin(pin_num, True)
                await asyncio.sleep(duration)
                self._set_pin(pin_num, False)
        finally:
            for pin_num in touched:
                self._set_pin(pin_num, False)
            self._sequence_running = False
            print("[GPIO] Sequence complete")

    def _cancel_timer(self):
        if self._timer and MACHINE_AVAILABLE:
            try:
                self._timer.deinit()
                self._timer = Timer()
            except Exception:
                pass

    def cleanup(self):
        self.deactivate()
        for pin_num in self._pins:
            self._set_pin(pin_num, False)
        if self._timer and MACHINE_AVAILABLE:
            self._timer.deinit()
