"""Setting cards bound to :class:`ConfigItem` objects.

qfluentwidgets' own cards are tied to its global ``qconfig`` (which persists to ``config/config.json`` in the
working directory), so these thin equivalents bind to our config system instead. Bindings are two-way: user
input updates the item, and external changes to the item update the widget.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtGui import QCloseEvent, QColor, QIcon
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ColorPickerButton,
    ComboBox,
    DoubleSpinBox,
    FluentIconBase,
    IndicatorPosition,
    SettingCard,
    Slider,
    SwitchButton,
)

from nightreign_overlay.core.config import ConfigItem, RangeOption
from nightreign_overlay.core.i18n import tr
from nightreign_overlay.core.input import HotkeyBinding, InputDevice

if TYPE_CHECKING:
    from nightreign_overlay.plugins.input.api import HotkeyApi


Icon = str | QIcon | FluentIconBase


def localize_switch(button: SwitchButton) -> SwitchButton:
    """Label a switch with our own translations; qfluentwidgets does not ship every supported language."""
    button.setOnText(tr("common.on"))
    button.setOffText(tr("common.off"))
    return button


class _ConfigCard(SettingCard):
    def __init__(
        self, item: ConfigItem[Any], icon: Icon, title: str, content: str | None, parent: QWidget | None
    ):
        super().__init__(icon, title, content, parent)
        self.item = item

    def _addControl(self, widget: QWidget) -> None:
        self.hBoxLayout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)


class ConfigSwitchCard(_ConfigCard):
    def __init__(
        self,
        item: ConfigItem[bool],
        icon: Icon,
        title: str,
        content: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(item, icon, title, content, parent)
        self.switchButton = localize_switch(SwitchButton(self, IndicatorPosition.RIGHT))
        self.switchButton.setChecked(item.value)
        self._addControl(self.switchButton)

        self.switchButton.checkedChanged.connect(item.set)
        item.valueChanged.connect(self._sync)

    def _sync(self, value: bool) -> None:
        with QSignalBlocker(self.switchButton):
            self.switchButton.setChecked(value)


class MultiButtonSettingCard(SettingCard):
    """One setting card with several compact action buttons."""

    def __init__(
        self,
        buttons: Sequence[tuple[str, Callable[[], None]]],
        icon: Icon,
        title: str,
        content: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(icon, title, content, parent)
        for index, (label, callback) in enumerate(buttons):
            if index:
                self.hBoxLayout.addSpacing(8)
            button = QPushButton(label, self)
            button.clicked.connect(callback)
            self.hBoxLayout.addWidget(button, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)


class ConfigChoiceCard(_ConfigCard):
    """Combo box over ``(value, label)`` pairs."""

    def __init__(
        self,
        item: ConfigItem[Any],
        choices: Sequence[tuple[Any, str]],
        icon: Icon,
        title: str,
        content: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(item, icon, title, content, parent)
        self.comboBox = ComboBox(self)
        self.comboBox.setMinimumWidth(180)
        for value, label in choices:
            self.comboBox.addItem(label, userData=value)
        self._sync(item.value)
        self._addControl(self.comboBox)

        self.comboBox.currentIndexChanged.connect(lambda index: item.set(self.comboBox.itemData(index)))
        item.valueChanged.connect(self._sync)

    def _sync(self, value: Any) -> None:
        with QSignalBlocker(self.comboBox):
            self.comboBox.setCurrentIndex(max(self.comboBox.findData(value), 0))


_DEVICE_LABELS = {
    InputDevice.KEYBOARD: "input_dialog.device.keyboard",
    InputDevice.MOUSE: "input_dialog.device.mouse",
    InputDevice.JOYSTICK: "input_dialog.device.controller",
}
#: Controller labels from the legacy tool; unknown buttons fall back to ``Btn<index>``.
_JOYSTICK_KEY_LABELS = {
    "button_0": "B",
    "button_1": "A",
    "button_2": "Y",
    "button_3": "X",
    "button_4": "LB",
    "button_5": "RB",
    "button_6": "Select",
    "button_7": "Start",
    "button_8": "LStick",
    "button_9": "RStick",
    "lt": "LT",
    "rt": "RT",
    "dpad_right": "Right",
    "dpad_left": "Left",
    "dpad_down": "Down",
    "dpad_up": "Up",
}


def _binding_key_sort_key(key: str) -> tuple[int, str]:
    return {"ctrl": 0, "alt": 1, "shift": 2, "cmd": 3}.get(key, 10), key


def _format_key(device: InputDevice, key: str) -> str:
    if device != InputDevice.JOYSTICK:
        return key.upper()
    return _JOYSTICK_KEY_LABELS.get(key) or f"Btn{key.removeprefix('button_')}"


def _format_binding(binding: HotkeyBinding) -> str:
    if not binding.enabled:
        return tr("input_dialog.unset")
    device: InputDevice = binding.device  # type: ignore[assignment]
    return f"{tr(_DEVICE_LABELS[device])}: {' + '.join(_format_key(device, key) for key in binding.keys)}"


class _HotkeySettingDialog(QDialog):
    """Modal recorder that locks to the first input device, matching the legacy UX."""

    def __init__(self, hotkeys: HotkeyApi, initial: HotkeyBinding, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hotkeys = hotkeys
        self.binding = initial
        self._locked_device: InputDevice | None = None
        self._pressed_keys: set[str] = set()
        self._clear_requested = False
        self.setWindowTitle(tr("input_dialog.title"))
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        hint = QLabel(tr("input_dialog.hint"), self)
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.valueLabel = QLabel(tr("input_dialog.waiting"), self)
        self.valueLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.valueLabel.setStyleSheet("font-size: 16px; font-weight: bold; padding: 12px; color: #3498db;")
        layout.addWidget(hint)
        layout.addWidget(self.valueLabel)

        buttons = QHBoxLayout()
        clear = QPushButton(tr("input_dialog.clear"), self)
        cancel = QPushButton(tr("input_dialog.cancel"), self)
        confirm = QPushButton(tr("input_dialog.confirm"), self)
        clear.clicked.connect(self._clear)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        buttons.addWidget(clear)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)
        self._hotkeys.subscribe_capture(self._on_input_state)

    def _on_input_state(self, device: InputDevice, keys: tuple[str, ...]) -> None:
        if self._locked_device is None and keys:
            self._locked_device = device
        if self._locked_device != device:
            return

        current_keys = set(keys)
        # The legacy recorder only updates the selected shortcut for press events. Newer
        # state snapshots also arrive on release, so only a state that adds a key may
        # replace the binding; a shrinking state merely updates press tracking.
        if current_keys and not current_keys.issubset(self._pressed_keys):
            self.binding = HotkeyBinding(device, tuple(sorted(current_keys, key=_binding_key_sort_key)))
            self.valueLabel.setText(_format_binding(self.binding))
        self._pressed_keys = current_keys

    def _clear(self) -> None:
        self._clear_requested = True
        self.binding = HotkeyBinding(None)
        self.accept()

    def accept(self) -> None:
        if self._clear_requested or self.binding.enabled:
            super().accept()

    def done(self, result: int) -> None:
        self._hotkeys.unsubscribe_capture(self._on_input_state)
        super().done(result)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._hotkeys.unsubscribe_capture(self._on_input_state)
        super().closeEvent(event)


class HotkeySettingCard(SettingCard):
    """A large button that opens the legacy-style multi-device shortcut recorder for ``action_id``.

    ``actions`` adds buttons before the recorder so a manual trigger can share the card with its shortcut;
    ``accessories`` are small widgets (e.g. a status icon) placed before those buttons. Accessories with a
    ``refresh()`` method are refreshed together with the card and after each action.
    """

    def __init__(
        self,
        hotkeys: HotkeyApi,
        action_id: str,
        default: HotkeyBinding,
        icon: Icon,
        title: str,
        content: str | None = None,
        parent: QWidget | None = None,
        *,
        actions: Sequence[tuple[str, Callable[[], None]]] = (),
        accessories: Sequence[QWidget] = (),
    ) -> None:
        super().__init__(icon, title, content, parent)
        self._hotkeys = hotkeys
        self._action_id = action_id
        self._default = default
        self._accessories = list(accessories)
        for widget in self._accessories:
            widget.setParent(self)
            self.hBoxLayout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
            self.hBoxLayout.addSpacing(8)
        for label, callback in actions:
            button = QPushButton(label, self)
            button.setMinimumHeight(34)
            button.clicked.connect(lambda _checked=False, callback=callback: self._run_action(callback))
            self.hBoxLayout.addWidget(button, 0, Qt.AlignmentFlag.AlignRight)
            self.hBoxLayout.addSpacing(8)
        self.captureButton = QPushButton(self)
        self.captureButton.setMinimumWidth(210)
        self.captureButton.setMinimumHeight(34)
        self.captureButton.setStyleSheet("font-size: 14px; font-weight: 600; padding: 4px 12px;")
        self.captureButton.clicked.connect(self._open_dialog)
        self.hBoxLayout.addWidget(self.captureButton, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.refresh()

    @property
    def binding(self) -> HotkeyBinding:
        return self._hotkeys.binding(self._action_id, self._default)

    def refresh(self) -> None:
        """Re-read the persisted binding and accessory state, e.g. after the page was reset."""
        self.captureButton.setText(_format_binding(self.binding))
        for widget in self._accessories:
            if callable(refresh := getattr(widget, "refresh", None)):
                refresh()

    def _run_action(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        finally:
            # An action such as "calibrate" may change what the accessories display.
            self.refresh()

    def _open_dialog(self) -> None:
        dialog = _HotkeySettingDialog(self._hotkeys, self.binding, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._hotkeys.set_binding(self._action_id, dialog.binding)
            self.refresh()


class ConfigRangeCard(_ConfigCard):
    """Slider for an integer :class:`RangeOption`; ``formatter`` renders the value label."""

    def __init__(
        self,
        item: ConfigItem[int],
        icon: Icon,
        title: str,
        content: str | None = None,
        parent: QWidget | None = None,
        formatter: Callable[[int], str] = str,
    ) -> None:
        super().__init__(item, icon, title, content, parent)
        option = item.option
        if not isinstance(option, RangeOption) or not isinstance(option.default, int):
            raise TypeError("ConfigRangeCard requires an integer RangeOption")
        self._formatter = formatter

        self.valueLabel = BodyLabel(self)
        self.slider = Slider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(option.minimum, option.maximum)
        self.slider.setMinimumWidth(220)
        self._sync(item.value)
        self.hBoxLayout.addWidget(self.valueLabel, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(8)
        self._addControl(self.slider)

        self.slider.valueChanged.connect(self._onSliderChanged)
        item.valueChanged.connect(self._sync)

    def _onSliderChanged(self, value: int) -> None:
        self.valueLabel.setText(self._formatter(value))
        self.item.set(value)

    def _sync(self, value: int) -> None:
        with QSignalBlocker(self.slider):
            self.slider.setValue(value)
        self.valueLabel.setText(self._formatter(value))


class ConfigDoubleSpinCard(_ConfigCard):
    """Spin box for a floating-point :class:`RangeOption`."""

    def __init__(
        self,
        item: ConfigItem[float],
        icon: Icon,
        title: str,
        content: str | None = None,
        parent: QWidget | None = None,
        *,
        decimals: int = 2,
        step: float = 0.1,
        formatter: Callable[[float], str] = str,
    ) -> None:
        super().__init__(item, icon, title, content, parent)
        option = item.option
        if not isinstance(option, RangeOption) or not isinstance(option.default, float):
            raise TypeError("ConfigDoubleSpinCard requires a floating-point RangeOption")
        self._formatter = formatter
        self.spinBox = DoubleSpinBox(self)
        self.spinBox.setKeyboardTracking(False)
        self.spinBox.setRange(option.minimum, option.maximum)
        self.spinBox.setDecimals(decimals)
        self.spinBox.setSingleStep(step)
        self.spinBox.setMinimumWidth(120)
        self._sync(item.value)
        self._addControl(self.spinBox)

        self.spinBox.valueChanged.connect(self._on_value_changed)
        item.valueChanged.connect(self._sync)

    def _on_value_changed(self, value: float) -> None:
        self.item.set(value)

    def _sync(self, value: float) -> None:
        with QSignalBlocker(self.spinBox):
            self.spinBox.setValue(value)
        self.spinBox.setToolTip(self._formatter(value))


class ConfigColorCard(_ConfigCard):
    def __init__(
        self,
        item: ConfigItem[str],
        icon: Icon,
        title: str,
        content: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(item, icon, title, content, parent)
        self.colorPicker = ColorPickerButton(QColor(item.value), title, self)
        self._addControl(self.colorPicker)

        self.colorPicker.colorChanged.connect(lambda color: item.set(color.name()))
        item.valueChanged.connect(self._sync)

    def _sync(self, value: str) -> None:
        self.colorPicker.setColor(QColor(value))
