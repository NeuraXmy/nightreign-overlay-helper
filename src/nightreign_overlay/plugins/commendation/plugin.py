from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import BodyLabel, FluentIcon, LineEdit, PushButton, SettingCard

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.day_timer.api import DayStarted
from nightreign_overlay.plugins.p2p_latency.api import P2PStateChanged, PeerSnapshot
from nightreign_overlay.plugins.steam_recovery.api import RecoveryApi
from nightreign_overlay.ui.components import (
    ConfigRangeCard,
    MultiButtonSettingCard,
    OverlaySettingSection,
    SettingSection,
    SettingsPanel,
)
from nightreign_overlay.ui.overlay import OverlayManager

from .config import CommendationConfig, CommendationOverlayConfig
from .overlay import CommendationOverlay
from .service import CommendationService


class _CommentCard(SettingCard):
    def __init__(self, item, tr, on_error):
        super().__init__(FluentIcon.EDIT, tr("settings.comment"))
        self.editor = LineEdit(self)
        self.editor.setMaxLength(500)
        self.editor.setMinimumWidth(280)
        self.editor.setText(item.value)
        self.button = PushButton(tr("settings.save"), self)
        self.hBoxLayout.addWidget(self.editor, 1, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addWidget(self.button)
        self.hBoxLayout.addSpacing(16)
        item.valueChanged.connect(self.editor.setText)

        def save():
            try:
                item.set(self.editor.text().strip())
                on_error("saved")
            except ValueError:
                on_error("invalid_comment")

        self.button.clicked.connect(save)


class CommendationPlugin(Plugin):
    manifest = PluginManifest(
        id="commendation",
        kind=PluginKind.FEATURE,
        icon="CERTIFICATE",
        order=60,
        requires=("p2p_latency",),
        optional=("day_timer",),
    )
    statusChanged = pyqtSignal(str)

    def on_load(self) -> None:
        self.config = self.ctx.config(CommendationConfig)
        self.overlay_config = self.ctx.config(CommendationOverlayConfig, "overlay")
        self._service = None
        self._window = None
        self._status = "idle"

    def on_activate(self) -> None:
        window = CommendationOverlay(
            self.ctx.services.require(OverlayManager), self.overlay_config, self.ctx.tr
        )
        self._window = window
        self.ctx.on_cleanup(window.dispose)

        def pending(account, target):
            recovery = self.ctx.services.get(RecoveryApi)
            return bool(recovery and recovery.pending(account, target))

        service = CommendationService(self.config, self, recovery_pending=pending)
        self._service = service
        service.rowsChanged.connect(window.set_rows)
        service.statusChanged.connect(self._set_status)
        window.commendClicked.connect(service.send, Qt.ConnectionType.QueuedConnection)
        window.dismissed.connect(service.dismiss)
        self.ctx.subscribe(PeerSnapshot, service.on_snapshot)
        self.ctx.subscribe(P2PStateChanged, service.on_status)
        self.ctx.subscribe(DayStarted, service.on_day_started)
        self.ctx.on_cleanup(lambda: self._stop(service))
        self._set_status("idle")

    def _stop(self, service) -> None:
        service.stop()
        service.deleteLater()
        self._service = self._window = None
        self._set_status("disabled")

    def _set_status(self, state: str) -> None:
        self._status = state
        self.statusChanged.emit(self.ctx.tr("state." + state))

    def _show_recent(self) -> None:
        if self._service:
            self._service.show_recent()
        else:
            self._set_status("disabled")

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        tr = self.ctx.tr
        panel = SettingsPanel(parent)
        settings = SettingSection(tr("settings.behavior"))
        settings.addCard(
            ConfigRangeCard(
                self.config.close_seconds,
                FluentIcon.STOP_WATCH,
                tr("settings.close_seconds"),
                tr("settings.close_help"),
                formatter=lambda value: tr("settings.seconds", value=value),
            )
        )
        settings.addCard(_CommentCard(self.config.comment, tr, self._set_status))
        settings.addCard(
            MultiButtonSettingCard(
                [(tr("settings.show_recent"), self._show_recent)],
                FluentIcon.PEOPLE,
                tr("settings.manual"),
                tr("settings.manual_help"),
            )
        )
        panel.addSection(settings)
        panel.addSection(
            OverlaySettingSection(self.overlay_config, tr("settings.window"), include_horizontal_reset=False)
        )
        status = SettingSection(tr("settings.status"))
        label = BodyLabel(tr("state." + self._status), status)
        label.setWordWrap(True)
        self.statusChanged.connect(label.setText)
        status.addCard(label)
        panel.addSection(status)
        return panel
