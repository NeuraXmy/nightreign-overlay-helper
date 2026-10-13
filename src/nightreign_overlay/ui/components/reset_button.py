"""Page level "Reset" button: confirm, restore the defaults, then resync widgets that do not observe them."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, InfoBar, InfoBarPosition, MessageBox, PushButton

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.core.log import get_logger
from nightreign_overlay.ui.components.setting_cards import HotkeySettingCard

log = get_logger(__name__)


def create_reset_button(
    reset: Callable[[], None], scope: QWidget, content: str, parent: QWidget | None = None
) -> PushButton:
    """Button resetting one settings page; ``scope`` holds the page's cards and ``content`` is the prompt."""
    button = PushButton(FluentIcon.HISTORY, tr("settings_reset.button"), parent)
    button.clicked.connect(lambda: _reset_page(button, reset, scope, content))
    return button


def confirm_reset(parent: QWidget, content: str) -> bool:
    box = MessageBox(tr("settings_reset.title"), content, parent.window())
    box.yesButton.setText(tr("settings_reset.confirm"))
    box.cancelButton.setText(tr("settings_reset.cancel"))
    return bool(box.exec())


def _reset_page(button: QWidget, reset: Callable[[], None], scope: QWidget, content: str) -> None:
    if not confirm_reset(button, content):
        return
    try:
        reset()
    except Exception:
        log.exception("Failed to reset settings")
        return
    finally:
        # Config cards follow their items; shortcut cards read the input service and must be refreshed.
        for card in scope.findChildren(HotkeySettingCard):
            card.refresh()
    InfoBar.success(
        "",
        tr("settings_reset.done"),
        duration=2000,
        position=InfoBarPosition.TOP,
        parent=button.window(),
    )
