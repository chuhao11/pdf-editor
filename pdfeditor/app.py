"""程序入口。"""

from __future__ import annotations

import os
import sys


def _set_windows_app_id() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PDFEditor.App")
        except Exception:
            pass


def _load_translations(app) -> None:
    """让 Qt 自带的对话框按钮等也显示中文。"""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for name in ("qtbase_zh_CN", "qt_zh_CN"):
        tr = QTranslator(app)
        if tr.load(name, path):
            app.installTranslator(tr)
            break
    QLocale.setDefault(QLocale(QLocale.Language.Chinese, QLocale.Country.China))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    _set_windows_app_id()

    from PySide6.QtWidgets import QApplication

    from . import APP_ID, APP_NAME
    from .icons import app_icon

    QApplication.setOrganizationName(APP_ID)
    QApplication.setApplicationName(APP_ID)
    app = QApplication(argv)
    app.setWindowIcon(app_icon())
    _load_translations(app)

    if "--selftest" in argv:
        from .selftest import run_selftest
        i = argv.index("--selftest")
        out = argv[i + 1] if i + 1 < len(argv) else None
        return run_selftest(out)

    paths = [os.path.abspath(a) for a in argv[1:] if not a.startswith("-") and os.path.isfile(a)]

    from .single_instance import SingleInstance
    instance = SingleInstance(APP_ID)
    if not instance.is_primary and instance.send(paths):
        return 0

    from .mainwindow import MainWindow
    win = MainWindow()
    win.setWindowTitle(APP_NAME)
    instance.messageReceived.connect(win.receive_from_other_instance)
    win.show()
    if paths:
        win.open_paths(paths)
    return app.exec()
