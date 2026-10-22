"""Reusable audio notification cards bound to feature cue configuration."""

from __future__ import annotations

from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    DoubleSpinBox,
    FluentIcon,
    IndicatorPosition,
    PushButton,
    SettingCard,
    Slider,
    SwitchButton,
)

from nightreign_overlay.core.audio import AudioCueConfig
from nightreign_overlay.core.i18n import tr
from nightreign_overlay.plugins.audio.api import AudioNotifications
from nightreign_overlay.ui.components.page import SettingSection
from nightreign_overlay.ui.components.setting_cards import localize_switch


class AudioSettingCard(SettingCard):
    """Per-cue switch, volume, custom/default audio, timing offset, and immediate preview."""

    def __init__(
        self,
        notifications: AudioNotifications,
        key: str,
        title: str,
        *,
        advance: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        self.cue: AudioCueConfig = notifications.cues[key]
        super().__init__(FluentIcon.MUSIC, title, self.cue.path.value or tr("audio.unset"), parent)
        self._notifications = notifications
        self.switchButton = localize_switch(SwitchButton(self, IndicatorPosition.RIGHT))
        enabled = QHBoxLayout()
        enabled.addWidget(BodyLabel(tr("audio.enabled"), self))
        enabled.addStretch(1)
        enabled.addWidget(self.switchButton)
        self.vBoxLayout.addLayout(enabled)
        self.slider = Slider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setMinimumWidth(100)
        self.volumeLabel = BodyLabel(self)
        self.spinBox = DoubleSpinBox(self)
        self.spinBox.setRange(0.0, 3600.0)
        self.spinBox.setDecimals(1)
        self.spinBox.setSingleStep(0.1)
        self.spinBox.setSuffix(" s")
        self.spinBox.setKeyboardTracking(False)
        self.spinBox.setMinimumWidth(120)
        timing = QHBoxLayout()
        timing.addWidget(BodyLabel(tr("audio.volume"), self))
        timing.addWidget(self.slider, 1)
        timing.addWidget(self.volumeLabel)
        timing.addSpacing(16)
        timing.addWidget(BodyLabel(tr("audio.advance" if advance else "audio.delay"), self))
        timing.addWidget(self.spinBox)
        self.vBoxLayout.addLayout(timing)

        self.selectButton = PushButton(self)
        self.clearButton = PushButton(tr("audio.clear"), self)
        self.testButton = PushButton(tr("audio.test"), self)
        buttons = QHBoxLayout()
        for button in (self.selectButton, self.clearButton, self.testButton):
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.vBoxLayout.addLayout(buttons)
        self.vBoxLayout.setSpacing(10)
        self.hBoxLayout.addSpacing(16)
        self.selectButton.clicked.connect(self._select_file)
        self.clearButton.clicked.connect(self._clear)
        self.testButton.clicked.connect(self._toggle_test)
        self.switchButton.checkedChanged.connect(self.cue.enabled.set)
        self.slider.valueChanged.connect(self.cue.volume.set)
        self.spinBox.valueChanged.connect(self.cue.seconds.set)
        for item in self.cue.items().values():
            item.valueChanged.connect(self._sync)
        self._sync()

    def _toggle_test(self) -> None:
        if self._notifications.is_test_playing(self.cue):
            self._notifications.stop_test()
        else:
            self._notifications.play_test(self.cue)
        self._sync_test_button()

    def _sync_test_button(self, *_args: object) -> None:
        self.testButton.setText(
            tr("audio.stop_test" if self._notifications.is_test_playing(self.cue) else "audio.test")
        )

    def _select_file(self) -> None:
        self._notifications.stop_test()
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("audio.select"),
            self.cue.path.value,
            tr("audio.filter"),
        )
        if path:
            self.cue.path.set(path)

    def _clear(self) -> None:
        self._notifications.stop_test()
        self.cue.path.set("")

    def _sync(self, *_args: object) -> None:
        with (
            QSignalBlocker(self.slider),
            QSignalBlocker(self.spinBox),
            QSignalBlocker(self.switchButton),
        ):
            self.slider.setValue(self.cue.volume.value)
            self.spinBox.setValue(self.cue.seconds.value)
            self.switchButton.setChecked(self.cue.enabled.value)
        self.volumeLabel.setText(f"{self.cue.volume.value}%")
        path = self.cue.path.value
        default = self._notifications.default_path(self.cue)
        self.setContent(path or tr("audio.builtin" if default else "audio.unset"))
        self.contentLabel.setToolTip(self._notifications.path_for(self.cue))
        self.selectButton.setText(tr("audio.change" if path else "audio.select"))
        self.clearButton.setText(tr("audio.restore_default" if default else "audio.clear"))
        self.clearButton.setEnabled(bool(path))
        self.testButton.setEnabled(self.cue.enabled.value and bool(path or default))
        self._sync_test_button()


def audio_section(notifications: AudioNotifications, advance: tuple[str, ...]) -> SettingSection:
    """Build the final feature settings group with localized titles."""
    section = SettingSection(tr("audio.title"))
    for key in notifications.cues:
        section.addCard(
            AudioSettingCard(
                notifications,
                key,
                notifications.ctx.tr(f"audio.{key}"),
                advance=key in advance,
            )
        )
    return section
