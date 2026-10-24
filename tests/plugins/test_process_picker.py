from types import SimpleNamespace

from PyQt6.QtWidgets import QWidget

from nightreign_overlay.plugins.capture import process_picker


def test_process_picker_populates_and_selects_process(qapp, monkeypatch):
    monkeypatch.setattr(process_picker, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        process_picker,
        "list_window_processes",
        lambda: [("Remote Play", "RemotePlay.exe"), ("Browser", "browser.exe")],
    )

    parent = QWidget()
    parent.resize(800, 600)
    dialog = process_picker.ProcessPickerDialog(parent, current="RemotePlay.exe", tr=lambda key: key)
    try:
        assert dialog.listWidget.count() == 3
        assert dialog.selected_process() == "RemotePlay.exe"
    finally:
        dialog.close()
        parent.close()


def test_process_picker_defaults_to_auto_detect(qapp, monkeypatch):
    monkeypatch.setattr(process_picker, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(process_picker, "list_window_processes", lambda: [("Remote Play", "RemotePlay.exe")])

    parent = QWidget()
    parent.resize(800, 600)
    dialog = process_picker.ProcessPickerDialog(parent, tr=lambda key: key)
    try:
        assert dialog.selected_process() == ""
    finally:
        dialog.close()
        parent.close()
