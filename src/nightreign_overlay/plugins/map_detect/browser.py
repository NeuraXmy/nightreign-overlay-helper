from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, FluentWidget, LineEdit, PrimaryPushButton

from nightreign_overlay.plugins.map_detect.detector import (
    MapDetector,
    MapPatternMatchResult,
    get_poi_image,
    get_poi_key,
)
from nightreign_overlay.plugins.map_detect.resources import get_data_path

_NIGHTLORD_MARKER_SIZE = 115
_PRISON_MARKER_SIZE = round(_NIGHTLORD_MARKER_SIZE / 6)


class _MapPreview(QWidget):
    """Fit the original map to the available space without distorting it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:
        return QSize(563, 563)

    def setPixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:
        if self._pixmap.isNull():
            return
        size = self._pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRect((self.width() - size.width()) // 2, 0, size.width(), size.height())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, self._pixmap)


class MapBrowserWindow(FluentWidget):
    def __init__(self, tr, language: str | None = None, parent=None):
        super().__init__(parent)
        self.setMicaEffectEnabled(False)
        self._tr = tr
        self.setWindowTitle(tr("settings.browser.window_title"))
        self.resize(599, 700)
        self.setMinimumSize(560, 500)
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(BodyLabel(tr("settings.browser.input_label")))
        self.input = LineEdit()
        self.input.setPlaceholderText(tr("settings.browser.placeholder"))
        self.input.setClearButtonEnabled(True)
        self.button = PrimaryPushButton(tr("settings.browser.browse"))
        self.status = BodyLabel()
        self.status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        controls.addWidget(self.input)
        controls.addWidget(self.button)
        layout.addLayout(controls)
        layout.addWidget(self.status)
        self.image = _MapPreview()
        layout.addWidget(self.image, 1)
        window_layout = QVBoxLayout(self)
        window_layout.setContentsMargins(0, self.titleBar.height(), 0, 0)
        window_layout.setSpacing(0)
        window_layout.addWidget(root)
        self.titleBar.raise_()
        self.button.clicked.connect(self.browse)
        self.input.returnPressed.connect(self.browse)
        self._detector = MapDetector(language=language)

    def browse(self):
        try:
            pattern_id = int(self.input.text().strip())
        except ValueError:
            self.status.setText(self._tr("settings.browser.invalid"))
            return
        self.status.setText(self._tr("settings.browser.drawing"))
        self.button.setEnabled(False)
        QTimer.singleShot(0, lambda: self._draw(pattern_id))

    def _draw(self, pattern_id: int):
        try:
            pattern = next(p for p in self._detector.info.patterns if p.id == pattern_id)
        except StopIteration:
            self.status.setText(self._tr("settings.browser.not_found"))
            self.button.setEnabled(True)
            return
        try:
            size = (750, 750)
            bg = Image.open(get_data_path(f"maps/{pattern.earth_shifting}.jpg")).convert("RGBA").resize(size)
            # Place prison markers beneath every POI, including overlapping neighbouring POIs.
            with Image.open(get_data_path("icons/prison.png")) as source:
                prison = source.convert("RGBA")
            prison.thumbnail((_PRISON_MARKER_SIZE, _PRISON_MARKER_SIZE), Image.Resampling.LANCZOS)
            for pos, construct in pattern.pos_constructions.items():
                if construct.type // 1000 == 46 and construct.type // 10 % 10 == 0:
                    x = int(pos[0] * size[0] / 750 - prison.width / 2)
                    y = int(pos[1] * size[1] / 750 - prison.height / 2)
                    bg.alpha_composite(prison, (x, y))

            # Draw all POIs first, so the map information layer remains readable above them.
            for pos, construct in pattern.pos_constructions.items():
                ctype = construct.type
                if get_poi_key(ctype) is None:
                    continue
                icon = get_poi_image(ctype, with_subicon=True)
                x = int(pos[0] * size[0] / 750 - icon.width / 2)
                y = int(pos[1] * size[1] / 750 - icon.height / 2)
                bg.alpha_composite(icon, (x, y))

            # Evernight uses the same ordinary nightlord portrait as the selected nightlord.
            nl = Image.open(get_data_path("icons/nightlord/bg.png")).convert("RGBA")
            try:
                icon = Image.open(get_data_path(f"icons/nightlord/{pattern.nightlord}.png")).convert("RGBA")
            except FileNotFoundError:
                icon = Image.open(get_data_path("icons/nightlord/unk.png")).convert("RGBA")
            icon.thumbnail((int(nl.width * 0.65), int(nl.height * 0.65)))
            nl.alpha_composite(icon, ((nl.width - icon.width) // 2, (nl.height - icon.height) // 2))
            nl.thumbnail((_NIGHTLORD_MARKER_SIZE, _NIGHTLORD_MARKER_SIZE))
            bg.alpha_composite(nl, (18, size[1] - nl.height - 18))

            overlay = self._detector._draw_overlay_image(
                MapPatternMatchResult(pattern, pattern.nightlord, 0, 0), size, 0
            )
            bg.alpha_composite(overlay)
            qimg = QImage(bg.tobytes("raw", "RGBA"), bg.width, bg.height, QImage.Format.Format_RGBA8888)
            self.image.setPixmap(QPixmap.fromImage(qimg.copy()))
            self.status.setText(self._tr("settings.browser.done", id=pattern_id))
        except (OSError, ValueError, KeyError):
            self.status.setText(self._tr("settings.browser.not_found"))
        finally:
            self.button.setEnabled(True)
