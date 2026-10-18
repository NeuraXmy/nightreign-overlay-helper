"""Shared presentation for Markdown rendered in the UI."""

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QImage, QMouseEvent, QResizeEvent, QTextBlockFormat, QTextCursor, QTextDocument
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout
from qfluentwidgets import TextBrowser

MARKDOWN_STYLE_SHEET = """
body {
    line-height: 150%;
}
p {
    margin-top: 0;
    margin-bottom: 12px;
}
h1 {
    font-size: 1.8em;
    margin-top: 20px;
    margin-bottom: 14px;
}
h2 {
    font-size: 1.5em;
    margin-top: 20px;
    margin-bottom: 12px;
}
h3 {
    font-size: 1.25em;
    margin-top: 16px;
    margin-bottom: 10px;
}
h4, h5, h6 {
    margin-top: 14px;
    margin-bottom: 8px;
}
ul, ol {
    margin-top: 4px;
    margin-bottom: 12px;
}
li {
    margin-bottom: 5px;
}
blockquote {
    margin-top: 12px;
    margin-bottom: 12px;
}
"""


class MarkdownTextBrowser(TextBrowser):
    """Text browser whose Markdown document follows the available viewport width."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(self.LineWrapMode.WidgetWidth)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.document().setTextWidth(max(0, self.viewport().width()))
        self._resize_images()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            image = self._image_at(event.position().toPoint())
            if image is not None:
                self._show_image(image)
                event.accept()
                return
        super().mousePressEvent(event)

    def _image_at(self, position):
        cursor = self.cursorForPosition(position)
        if not cursor.charFormat().isImageFormat():
            return None
        name = cursor.charFormat().toImageFormat().name()
        image = self.document().resource(QTextDocument.ResourceType.ImageResource, QUrl(name))
        return image if isinstance(image, QImage) and not image.isNull() else None

    @staticmethod
    def _show_image(image: QImage) -> None:
        dialog = QDialog()
        dialog.setWindowTitle("Image")
        label = QLabel(dialog)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        screen = dialog.screen().availableGeometry() if dialog.screen() else None
        max_width = screen.width() * 0.9 if screen else image.width()
        max_height = screen.height() * 0.9 if screen else image.height()
        pixmap = image.scaled(
            int(max_width),
            int(max_height),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(pixmap)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label)
        dialog.resize(pixmap.size())
        dialog.exec()

    def resize_images(self) -> None:
        self._resize_images()

    def _resize_images(self) -> None:
        width = self.viewport().width()
        if width <= 0:
            return
        document = self.document()
        resized = False
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.charFormat().isImageFormat():
                    image_format = fragment.charFormat().toImageFormat()
                    resource = document.resource(
                        QTextDocument.ResourceType.ImageResource, QUrl(image_format.name())
                    )
                    if resource is not None and not resource.isNull():
                        original_size = resource.size()
                        target_width = width * 0.75
                        target_height = target_width * original_size.height() / original_size.width()
                        image_format.setWidth(target_width)
                        image_format.setHeight(target_height)
                        cursor = QTextCursor(document)
                        cursor.setPosition(fragment.position())
                        cursor.movePosition(
                            QTextCursor.MoveOperation.NextCharacter,
                            QTextCursor.MoveMode.KeepAnchor,
                            fragment.length(),
                        )
                        cursor.setCharFormat(image_format)
                        resized = True
                iterator += 1
            block = block.next()
        if resized:
            # Image edits can leave later blocks without a layout in Qt's lazy
            # layout cache. Invalidate the whole document after resizing them.
            document.markContentsDirty(0, document.characterCount())


def configure_markdown_browser(browser: TextBrowser) -> None:
    """Apply readable spacing to a Markdown-capable text browser."""

    browser.document().setDefaultStyleSheet(MARKDOWN_STYLE_SHEET)
    document = browser.document()
    block = document.begin()
    while block.isValid():
        format_ = QTextBlockFormat(block.blockFormat())
        format_.setLineHeight(150, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        contains_image = False
        fragment_iterator = block.begin()
        fragment_format = None
        while not fragment_iterator.atEnd():
            candidate = fragment_iterator.fragment()
            if candidate.isValid():
                fragment_format = candidate
                contains_image = candidate.charFormat().isImageFormat()
                break
            fragment_iterator += 1
        font = (
            fragment_format.charFormat().font() if fragment_format is not None else block.charFormat().font()
        )
        font_size = font.pointSizeF()
        if font_size <= 0:
            font_size = float(font.pixelSize())
        if contains_image:
            format_.setLineHeight(100, QTextBlockFormat.LineHeightTypes.SingleHeight.value)
            format_.setTopMargin(0)
            format_.setBottomMargin(10)
        elif font_size >= 26:
            format_.setTopMargin(20)
            format_.setBottomMargin(14)
        elif font_size >= 20:
            format_.setTopMargin(18)
            format_.setBottomMargin(12)
        elif font_size >= 16:
            format_.setTopMargin(14)
            format_.setBottomMargin(10)
        else:
            format_.setBottomMargin(max(format_.bottomMargin(), 10))
        cursor = QTextCursor(block)
        cursor.setBlockFormat(format_)
        block = block.next()
    if isinstance(browser, MarkdownTextBrowser):
        browser.resize_images()
