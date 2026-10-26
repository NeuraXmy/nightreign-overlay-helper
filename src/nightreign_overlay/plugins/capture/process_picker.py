"""Manual capture-process picker for setups where the game window is not on this PC.

The game is auto-detected by window title; when playing through a PS5 remote-play app
(or any streaming client) that title never exists locally, so the user pins the process
providing the game image instead.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem
from qfluentwidgets import BodyLabel, ListWidget, MessageBoxBase, SubtitleLabel

from nightreign_overlay.plugins.capture.win32 import list_window_processes as list_windows_win32

#: Translations come from the capture plugin namespace via the injected ``tr`` callable.
Tr = Callable[[str], str]


class ProcessPickerDialog(MessageBoxBase):
    """List windows with their owning process; the empty value means auto-detect."""

    def __init__(self, parent=None, current: str = "", tr: Tr = lambda key: key) -> None:
        super().__init__(parent)
        self._tr = tr
        self.titleLabel = SubtitleLabel(tr("settings.process.dialog_title"), self)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(BodyLabel(tr("settings.process.dialog_hint")))

        self.listWidget = ListWidget(self)
        self.listWidget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.listWidget.setTextElideMode(Qt.TextElideMode.ElideRight)
        auto = tr("settings.process.auto")
        self._add_row(auto, "", selected=not current)
        if sys.platform == "win32":
            entries = list_windows_win32()
        elif sys.platform == "darwin":
            from nightreign_overlay.plugins.capture.macos import list_window_processes

            entries = list_window_processes()
        else:
            entries = []
        for title, image in entries:
            self._add_row(f"{title}    [{image}]", image, selected=image.casefold() == current.casefold())
        if not current and self.listWidget.count():
            self.listWidget.setCurrentRow(0)
        self.listWidget.itemDoubleClicked.connect(lambda _item: self.accept())
        self.viewLayout.addWidget(self.listWidget, 1)

        self.yesButton.setText(tr("settings.process.confirm"))
        self.cancelButton.setText(tr("settings.process.cancel"))
        self.widget.setMinimumSize(520, 420)

    def _add_row(self, label: str, process: str, selected: bool = False) -> None:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, process)
        self.listWidget.addItem(item)
        if selected:
            self.listWidget.setCurrentItem(item)

    def selected_process(self) -> str:
        """Process image name pinned as the capture target; empty string means auto-detect."""
        item = self.listWidget.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""
