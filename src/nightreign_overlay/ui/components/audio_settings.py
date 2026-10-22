"""Reusable audio notification cards bound to feature cue configuration."""

from __future__ import annotations

from pathlib import Path

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
from nightreign_overlay.plugins.audio.api import AudioApi, AudioNotifications
from nightreign_overlay.plugins.audio.config import LoopAudioConfig
from nightreign_overlay.ui.components.page import SelectableSettingContainer, SettingSection
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
        self.slider = Slider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setMinimumWidth(120)
        self.volumeLabel = BodyLabel(self)
        self.spinBox = DoubleSpinBox(self)
        self.spinBox.setRange(0.0, 3600.0)
        self.spinBox.setDecimals(1)
        self.spinBox.setSingleStep(0.1)
        self.spinBox.setSuffix(" s")
        self.spinBox.setKeyboardTracking(False)
        self.spinBox.setMinimumWidth(100)
        enabled = QHBoxLayout()
        enabled.setSpacing(10)
        enabled_label = BodyLabel(tr("audio.enabled"), self)
        enabled_label.setMinimumWidth(96)
        enabled.addWidget(enabled_label)
        enabled.addWidget(self.switchButton)
        enabled.addSpacing(24)
        volume_label = BodyLabel(tr("audio.volume"), self)
        volume_label.setMinimumWidth(64)
        enabled.addWidget(volume_label)
        enabled.addWidget(self.slider, 1)
        enabled.addWidget(self.volumeLabel)
        self.vBoxLayout.addLayout(enabled)

        timing = QHBoxLayout()
        timing.setSpacing(10)
        delay_label = BodyLabel(tr("audio.advance" if advance else "audio.delay"), self)
        delay_label.setMinimumWidth(96)
        timing.addWidget(delay_label)
        timing.addWidget(self.spinBox)
        timing.addStretch(1)
        self.vBoxLayout.addLayout(timing)

        self.selectButton = PushButton(self)
        self.clearButton = PushButton(tr("audio.clear"), self)
        self.testButton = PushButton(tr("audio.test"), self)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        for button in (self.selectButton, self.clearButton, self.testButton):
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.vBoxLayout.addLayout(buttons)
        self.vBoxLayout.setSpacing(14)
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
            self, tr("audio.select"), self.cue.path.value, tr("audio.filter")
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


class LoopAudioSettingCard(SettingCard):
    """Owner-controlled looping cue with independent fade-in/fade-out times."""

    def __init__(
        self,
        config,
        audio,
        owner: str,
        title: str,
        default_path: str = "",
        parent: QWidget | None = None,
    ) -> None:
        self.default_path = default_path
        self.default_filename = Path(default_path).name if default_path else ""
        initial = config.path.value or (
            tr("audio.builtin_loop", filename=self.default_filename)
            if self.default_filename
            else tr("audio.unset")
        )
        super().__init__(FluentIcon.MUSIC, title, initial, parent)
        self.config, self.audio, self.owner = config, audio, f"{owner}:test"
        self.enabledSwitch = localize_switch(SwitchButton(self, IndicatorPosition.RIGHT))
        self.slider = Slider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setMinimumWidth(120)
        self.volumeLabel = BodyLabel(self)
        self.fadeIn = DoubleSpinBox(self)
        self.fadeOut = DoubleSpinBox(self)
        for spin in (self.fadeIn, self.fadeOut):
            spin.setRange(0, 60)
            spin.setDecimals(1)
            spin.setSingleStep(0.1)
            spin.setSuffix(" s")
            spin.setKeyboardTracking(False)
            spin.setMinimumWidth(80)
        self._add_parameter_rows(
            (self.enabledSwitch, self.slider, self.volumeLabel),
            (tr("audio.fade_in"), self.fadeIn, tr("audio.fade_out"), self.fadeOut),
        )
        self.selectButton = PushButton(self)
        self.clearButton = PushButton(tr("audio.clear"), self)
        self.testButton = PushButton(tr("audio.test"), self)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        for button in (self.selectButton, self.clearButton, self.testButton):
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.vBoxLayout.addLayout(buttons)
        self.vBoxLayout.setSpacing(16)
        self.selectButton.clicked.connect(self._select)
        self.clearButton.clicked.connect(lambda: self.config.path.set(""))
        self.enabledSwitch.checkedChanged.connect(self.config.enabled.set)
        self.config.enabled.valueChanged.connect(self._enabled_changed)
        self.slider.valueChanged.connect(self.config.volume.set)
        self.fadeIn.valueChanged.connect(self.config.fade_in.set)
        self.fadeOut.valueChanged.connect(self.config.fade_out.set)
        self.testButton.clicked.connect(self._toggle_test)
        for item in self.config.items().values():
            item.valueChanged.connect(self._sync)
        self._sync()

    def _add_parameter_rows(self, first: tuple[QWidget, QWidget, QWidget], second: tuple) -> None:
        enabled_switch, slider, volume_label = first
        enabled = QHBoxLayout()
        enabled.setSpacing(10)
        enabled_label = BodyLabel(tr("audio.enabled"), self)
        enabled_label.setMinimumWidth(96)
        enabled.addWidget(enabled_label)
        enabled.addWidget(enabled_switch)
        enabled.addSpacing(24)
        volume_label_title = BodyLabel(tr("audio.volume"), self)
        volume_label_title.setMinimumWidth(64)
        enabled.addWidget(volume_label_title)
        enabled.addWidget(slider, 1)
        enabled.addWidget(volume_label)
        self.vBoxLayout.addLayout(enabled)

        timing = QHBoxLayout()
        timing.setSpacing(10)
        for title, control in ((second[0], second[1]), (second[2], second[3])):
            field = QHBoxLayout()
            field.setSpacing(10)
            label = BodyLabel(title, self)
            label.setMinimumWidth(96)
            field.addWidget(label)
            field.addWidget(control, 1)
            timing.addLayout(field, 1)
        timing.setSpacing(24)
        self.vBoxLayout.addLayout(timing)

    def _select(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("audio.select"), self.config.path.value, tr("audio.filter")
        )
        if path:
            self.config.path.set(path)

    def _toggle_test(self) -> None:
        if self.audio.is_loop_playing(self.owner):
            self.audio.stop_loop(self.owner, self.config.fade_out.value)
        elif self.config.enabled.value and (self.config.path.value or self.default_path):
            path = self.config.path.value or self.default_path
            self.audio.play_loop(
                path, self.config.volume.value, self.config.fade_in.value, owner=self.owner
            )

    def _enabled_changed(self, enabled: bool) -> None:
        if not enabled:
            self.audio.stop_loop(self.owner)

    def _sync(self, *_args: object) -> None:
        with (
            QSignalBlocker(self.slider),
            QSignalBlocker(self.fadeIn),
            QSignalBlocker(self.fadeOut),
            QSignalBlocker(self.enabledSwitch),
        ):
            self.slider.setValue(self.config.volume.value)
            self.fadeIn.setValue(self.config.fade_in.value)
            self.fadeOut.setValue(self.config.fade_out.value)
            self.enabledSwitch.setChecked(self.config.enabled.value)
        self.volumeLabel.setText(f"{self.config.volume.value}%")
        self.setContent(
            self.config.path.value
            or (
                tr("audio.builtin_loop", filename=self.default_filename)
                if self.default_filename
                else tr("audio.unset")
            )
        )
        self.selectButton.setText(tr("audio.change" if self.config.path.value else "audio.select"))
        self.clearButton.setEnabled(bool(self.config.path.value))
        self.testButton.setEnabled(
            self.config.enabled.value and bool(self.config.path.value or self.default_path)
        )


def audio_section(
    notifications: AudioNotifications,
    advance: tuple[str, ...],
    loop_cues: tuple[tuple[LoopAudioConfig, AudioApi, str, str, str, str], ...] = (),
) -> SettingSection:
    """Build the final feature settings group with localized titles."""
    section = SettingSection(tr("audio.title"))
    if loop_cues:
        container = SelectableSettingContainer(tr("audio.select_option_group"))
        for config, audio, owner, option, title, default_path in loop_cues:
            container.addOption(
                option, LoopAudioSettingCard(config, audio, owner, title, default_path)
            )
        section.addCard(container)
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
