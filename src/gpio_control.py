"""GPIO relay control for Pico W."""

try:
    from machine import Pin, Timer
    MACHINE_AVAILABLE = True
except ImportError:
    MACHINE_AVAILABLE = False
    print("[GPIO] machine module not available - mock mode")

from .config import DEFAULT_RELAY_PIN


class RelayController:
    def __init__(self, pin_num=DEFAULT_RELAY_PIN):
        self._pin_num = pin_num
        self._active = False
        self._timer = None

        if MACHINE_AVAILABLE:
            self._pin = Pin(pin_num, Pin.OUT, value=0)
            self._timer = Timer()
            print("[GPIO] Initialized pin", pin_num)
        else:
            self._pin = None
            print("[GPIO] Mock mode - pin", pin_num)

    @property
    def is_active(self):
        return self._active

    def activate(self, duration_seconds=0):
        self._cancel_timer()
        if self._pin:
            self._pin.value(1)
        self._active = True
        print("[GPIO] Relay ON")

        if duration_seconds > 0 and self._timer:
            self._timer.init(
                mode=Timer.ONE_SHOT,
                period=duration_seconds * 1000,
                callback=lambda t: self.deactivate(),
            )

    def deactivate(self, _timer=None):
        self._cancel_timer()
        if self._pin:
            self._pin.value(0)
        self._active = False
        print("[GPIO] Relay OFF")

    def _cancel_timer(self):
        if self._timer and MACHINE_AVAILABLE:
            try:
                self._timer.deinit()
                self._timer = Timer()
            except Exception:
                pass

    def cleanup(self):
        self.deactivate()
        if self._timer and MACHINE_AVAILABLE:
            self._timer.deinit()
