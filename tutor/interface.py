"""Two first-class frontends sharing one Protocol. The orchestrator only ever
holds a TutorInterface and never branches on which concrete frontend it is."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol


class TutorInterface(Protocol):
    def speak(self, message: str) -> None: ...
    def listen(self) -> str: ...
    def wave(self) -> None: ...
    def shine(self, color: str) -> None: ...
    def pulse(self, color: str, duration: float = 1.0) -> None: ...


class DashboardHooks(Protocol):
    """The slice of TutorUI that ConsoleInterface needs -- kept as a narrow
    Protocol here (rather than importing tutor.ui.app) so this module has no
    dependency on the UI package."""

    def paused(self) -> AbstractContextManager[None]: ...
    def log_event(self, kind: str, detail: str) -> None: ...
    def prompt_user(self) -> str: ...


class ConsoleInterface:
    """Drives the entire user experience through this Mac's terminal: prints
    the tutor's speech, reads typed responses, and prints a description of
    any wave/shine/pulse action. Fully supported in its own right -- not a
    dev stand-in for the real TJBotInterface."""

    def __init__(self, ui: DashboardHooks) -> None:
        self._ui = ui

    def speak(self, message: str) -> None:
        self._ui.log_event("speak", message)

    def listen(self) -> str:
        return self._ui.prompt_user()

    def wave(self) -> None:
        self._ui.log_event("wave", "waves arm")

    def shine(self, color: str) -> None:
        self._ui.log_event("shine", color)

    def pulse(self, color: str, duration: float = 1.0) -> None:
        self._ui.log_event("pulse", f"{color} for {duration:.1f}s")


class TJBotInterface:
    """The real frontend. Only ever instantiated when --interface tjbot is
    explicitly selected -- never auto-detected, never the default."""

    def __init__(self, listen_timeout_secs: float | None = None) -> None:
        # Local import: only touch the hardware-aware tjbot-ce package when
        # this class is actually instantiated.
        from tjbot import TJBot

        self._listen_timeout_secs = listen_timeout_secs
        self._tj = TJBot(
            override_config={
                "hardware": {
                    "microphone": True,
                    "led": True,
                    "speaker": True,
                    "servo": True,
                }
            },
            auto_initialize=True,
        )

    def speak(self, message: str) -> None:
        self._tj.speak(message)

    def listen(self) -> str:
        return self._tj.listen(timeout=self._listen_timeout_secs)

    def wave(self) -> None:
        self._tj.wave()

    def shine(self, color: str) -> None:
        self._tj.shine(color)

    def pulse(self, color: str, duration: float = 1.0) -> None:
        self._tj.pulse(color, duration)
