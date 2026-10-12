"""Setting cards bound to :class:`ConfigItem` objects.

qfluentwidgets' own cards are tied to its global ``qconfig`` (which persists to ``config/config.json`` in the
working directory), so these thin equivalents bind to our config system instead. Bindings are two-way: user
input updates the item, and external changes to the item update the widget.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import (
    BodyLabel,
    ColorPickerButton,
    ComboBox,
    FluentIconBase,
    IndicatorPosition,
    SettingCard,
    Slider,
    SwitchButton,
)

from nightreign_overlay.core.config import ConfigItem, RangeOption
from nightreign_overlay.core.i18n import tr

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
