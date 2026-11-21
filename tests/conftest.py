import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pdfeditor.engine import PDF_LOCK  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    QCoreApplication.setOrganizationName("PDFEditorTests")
    QCoreApplication.setApplicationName("PDFEditorTests")
    app = QApplication.instance() or QApplication([])
    yield app


def pump(seconds=0.2):
    app = QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def make_pdf(path, n=3, label="P", size=(300, 400), toc=None, rotate=None):
    with PDF_LOCK:
        d = pymupdf.open()
        for i in range(n):
            d.new_page(width=size[0], height=size[1]).insert_text((30, 60), f"{label}{i + 1}", fontsize=24)
        if rotate:
            for i, r in rotate.items():
                d[i].set_rotation(r)
        if toc:
            d.set_toc(toc)
        d.save(str(path))
        d.close()
    return str(path)


def page_texts(path):
    with PDF_LOCK:
        d = pymupdf.open(str(path))
        out = [p.get_text().strip() for p in d]
        d.close()
    return out
