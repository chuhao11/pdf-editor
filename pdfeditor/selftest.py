"""自检：在打包好的 exe 里跑一遍主要功能（GitHub Actions 打包后会自动运行）。

用法：PDFEditor.exe --selftest 结果文件.txt
"""

from __future__ import annotations

import tempfile
import time
import traceback
from pathlib import Path


def _wait(cond, timeout=10.0):
    from PySide6.QtWidgets import QApplication
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def run_selftest(out_path: str | None) -> int:
    lines: list[str] = []
    code = 1
    try:
        import pymupdf
        from PIL import Image
        from PySide6.QtWidgets import QApplication

        from . import __version__
        from .engine import PDF_LOCK, read_pdf
        from .mainwindow import MainWindow

        lines.append(f"version {__version__}, PyMuPDF {pymupdf.__version__}, style {QApplication.style().name()}")
        tmp = Path(tempfile.mkdtemp(prefix="pdfeditor-selftest-"))
        a = tmp / "测试 A.pdf"
        with PDF_LOCK:
            d = pymupdf.open()
            for i in range(3):
                d.new_page(width=300, height=400).insert_text((40, 60), f"A{i + 1}", fontsize=30)
            d.set_toc([[1, "Ch1", 1], [1, "Ch3", 3]])
            d.save(str(a))
            d.close()
        Image.new("RGB", (400, 300), "red").save(tmp / "img1.jpg")
        Image.new("RGBA", (300, 400), (0, 0, 255, 128)).save(tmp / "img2.png")
        import pillow_heif  # noqa: F401  确认 HEIC 支持已打包
        lines.append("pillow_heif ok")

        win = MainWindow()
        win.show()
        win.open_paths([str(a)])
        tab = win.current_tab()
        assert tab is not None and len(tab.model) == 3, "open pdf"
        win.open_paths([str(tmp / "img1.jpg"), str(tmp / "img2.png")])
        img_tab = win.current_tab()
        assert len(img_tab.model) == 2, "images to pdf"
        tab.insert_pages(3, img_tab.model.pages)
        assert len(tab.model) == 5
        tab.model.move_rows([0], 5)
        tab.grid.select_rows([1])
        tab.rotate_selected(90)
        assert _wait(lambda: len(win.svc.cache) > 0), "render thumbnails"
        lines.append(f"rendered {len(win.svc.cache)} images")

        out_pdf = tmp / "输出.pdf"
        assert win.write_pdf(tab.model.pages, str(out_pdf)), "save"
        src = read_pdf(str(out_pdf))
        assert src.page_count == 5, "page count"
        with PDF_LOCK:
            rot = src.doc.load_page(1).rotation
        assert rot == 90, f"rotation {rot}"
        lines.append(f"saved {src.page_count} pages, toc {src.toc}")

        tab.path = str(out_pdf)
        tab.delete_selected()
        assert win.save_tab(tab), "overwrite"
        assert read_pdf(str(out_pdf)).page_count == 4, "overwrite page count"
        lines.append("overwrite ok")

        for t in win.tabs():
            t.model.mark_saved()
        win.close()
        lines.append("OK")
        code = 0
    except Exception:
        lines.append("FAILED")
        lines.append(traceback.format_exc())
    if out_path:
        Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    else:
        print("\n".join(lines))
    return code
