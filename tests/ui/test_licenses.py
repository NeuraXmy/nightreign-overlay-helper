"""Users can read the full license texts without a browser or network access."""

import pytest

from nightreign_overlay.core.i18n import Translator, install
from nightreign_overlay.core.paths import resource_path
from nightreign_overlay.ui.components.licenses import DOCUMENTS, LicensesDialog
from tests.support.qt import delete_qobjects


@pytest.mark.parametrize("locale", ["zh_CN", "zh_TW", "en_US", "ja_JP"])
def test_offline_license_viewer_displays_source_instructions_and_original_text(qapp, locale):
    translator = Translator(locale)
    translator.load_dir("core", resource_path("i18n"))
    install(translator)
    dialog = LicensesDialog()
    try:
        assert not dialog.windowTitle().startswith("about.")
        for index, (filename, _) in enumerate(DOCUMENTS):
            dialog.selector.setCurrentIndex(index)
            text = dialog.browser.toPlainText()
            if filename.endswith(".txt"):
                assert text.rstrip("\n") == resource_path("licenses", filename).read_text(
                    encoding="utf-8"
                ).rstrip("\n")
            elif filename == "SOURCE.md":
                assert "manifest.json" in text
                assert "build.bat" in text
            else:
                assert "WITHOUT ANY WARRANTY" in text
                assert "Riverbank" in text
    finally:
        delete_qobjects(dialog)
