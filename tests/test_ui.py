import json

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from pdfeditor.document import MODE_ORGANIZE, MODE_READ
from pdfeditor.mainwindow import MainWindow
from pdfeditor.model import PAGE_MIME

from .conftest import make_pdf, page_texts, pump


@pytest.fixture
def win(qapp):
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    pump(0.1)
    yield w
    for t in w.tabs():
        t.model.mark_saved()
    w.close()
    pump(0.05)


def labels(tab):
    return [f"{r.src.name}:{r.index + 1}" for r in tab.model.pages]


def drop(view, pos, md, mods=Qt.KeyboardModifier.NoModifier):
    ev = QDropEvent(QPointF(pos), Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, md,
                    Qt.MouseButton.LeftButton, mods)
    view.dropEvent(ev)
    pump(0.05)
    return ev


def page_mime(tab, rows):
    md = QMimeData()
    md.setData(PAGE_MIME, json.dumps({"model": tab.model.uid, "rows": rows}).encode())
    return md


def test_open_reorder_by_drag_and_save(win, tmp_path):
    path = make_pdf(tmp_path / "a.pdf", 6, "A")
    win.open_paths([path])
    tab = win.current_tab()
    tab.set_mode(MODE_ORGANIZE)
    pump(0.2)
    g = tab.grid
    r0 = g.visualRect(tab.model.index(0, 0))
    r3 = g.visualRect(tab.model.index(3, 0))
    # 拖到第 4 页右半边 → 插到第 4 页后面
    idx, line = g.compute_drop(QPoint(r3.center().x() + 10, r3.center().y()))
    assert idx == 4 and line is not None
    idx, _ = g.compute_drop(QPoint(r0.left() + 2, r0.center().y()))
    assert idx == 0
    idx, _ = g.compute_drop(QPoint(r0.center().x(), g.viewport().height() - 2))
    assert idx == 6  # 最后一行下面的空白 → 放到末尾

    drop(g, QPoint(r3.center().x() + 10, r3.center().y()), page_mime(tab, [0, 1]))
    assert labels(tab) == ["a.pdf:3", "a.pdf:4", "a.pdf:1", "a.pdf:2", "a.pdf:5", "a.pdf:6"]
    assert tab.selected_rows() == [2, 3]
    assert tab.model.is_modified()
    assert win.tabbar.tabText(0).endswith("*")

    win.save_current()  # 直接覆盖原文件
    assert page_texts(path) == ["A3", "A4", "A1", "A2", "A5", "A6"]
    assert not tab.model.is_modified()
    assert not win.tabbar.tabText(0).endswith("*")


def test_ctrl_drag_copies_within_same_document(win, tmp_path):
    win.open_paths([make_pdf(tmp_path / "a.pdf", 3)])
    tab = win.current_tab()
    tab.set_mode(MODE_ORGANIZE)
    pump(0.1)
    r = tab.grid.visualRect(tab.model.index(2, 0))
    drop(tab.grid, QPoint(r.right() - 2, r.center().y()), page_mime(tab, [0]),
         Qt.KeyboardModifier.ControlModifier)
    assert labels(tab) == ["a.pdf:1", "a.pdf:2", "a.pdf:3", "a.pdf:1"]


def test_cross_tab_drag_copies_pages(win, tmp_path):
    win.open_paths([make_pdf(tmp_path / "a.pdf", 3, "A"), make_pdf(tmp_path / "b.pdf", 2, "B")])
    a, b = win.tabs()
    win.tabbar.setCurrentIndex(1)
    b.set_mode(MODE_ORGANIZE)
    pump(0.1)
    r = b.grid.visualRect(b.model.index(0, 0))
    drop(b.grid, QPoint(r.right() - 2, r.center().y()), page_mime(a, [1, 2]))
    assert labels(b) == ["b.pdf:1", "a.pdf:2", "a.pdf:3", "b.pdf:2"]
    assert labels(a) == ["a.pdf:1", "a.pdf:2", "a.pdf:3"]  # 来源文档不变


def test_drop_pages_on_tab_appends(win, tmp_path):
    win.open_paths([make_pdf(tmp_path / "a.pdf", 2), make_pdf(tmp_path / "b.pdf", 1)])
    a, b = win.tabs()
    win._on_pages_dropped_on_tab(1, (a.model, [0]), False)
    assert labels(b) == ["b.pdf:1", "a.pdf:1"]
    assert win.current_tab() is b


def test_drop_files_into_grid_inserts_at_position(win, tmp_path):
    from PIL import Image
    win.open_paths([make_pdf(tmp_path / "a.pdf", 3)])
    tab = win.current_tab()
    tab.set_mode(MODE_ORGANIZE)
    pump(0.1)
    extra = make_pdf(tmp_path / "x.pdf", 2)
    img = tmp_path / "photo.png"
    Image.new("RGB", (100, 80), "red").save(img)
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(extra), QUrl.fromLocalFile(str(img))])
    r = tab.grid.visualRect(tab.model.index(0, 0))
    drop(tab.grid, QPoint(r.right() - 2, r.center().y()), md)
    pump(0.2)
    names = labels(tab)
    assert names[0] == "a.pdf:1"
    assert names[1:4] == ["photo:1", "x.pdf:1", "x.pdf:2"]  # 按文件名自然排序
    assert names[4:] == ["a.pdf:2", "a.pdf:3"]


def test_open_same_file_twice_reuses_tab(win, tmp_path):
    p = make_pdf(tmp_path / "a.pdf", 2)
    win.open_paths([p])
    win.open_paths([p])
    assert len(win.tabs()) == 1


def test_toolbar_actions_and_undo(win, tmp_path):
    win.open_paths([make_pdf(tmp_path / "a.pdf", 4)])
    tab = win.current_tab()
    tab.grid.select_rows([1])
    win.act_rot_r.trigger()
    assert tab.model.page(1).rotation == 90
    tab.grid.select_rows([0, 2])
    win.act_delete.trigger()
    assert labels(tab) == ["a.pdf:2", "a.pdf:4"]
    win.act_undo.trigger()
    assert labels(tab) == ["a.pdf:1", "a.pdf:2", "a.pdf:3", "a.pdf:4"]
    win.act_redo.trigger()
    assert len(tab.model) == 2


def test_copy_paste_extract_and_merge(win, tmp_path):
    win.open_paths([make_pdf(tmp_path / "a.pdf", 3), make_pdf(tmp_path / "b.pdf", 2)])
    a, b = win.tabs()
    win.tabbar.setCurrentIndex(0)
    a.grid.select_rows([0, 2])
    win.act_copy.trigger()
    win.tabbar.setCurrentIndex(1)
    b.grid.select_rows([0])
    win.act_paste.trigger()
    assert labels(b) == ["b.pdf:1", "a.pdf:1", "a.pdf:3", "b.pdf:2"]
    b.grid.select_rows([1, 2])
    win.act_extract.trigger()
    c = win.current_tab()
    assert labels(c) == ["a.pdf:1", "a.pdf:3"] and c.path is None
    win.merge_all_tabs()
    assert len(win.current_tab().model) == 3 + 4 + 2


def test_closing_tab_releases_sources(win, tmp_path):
    win.open_paths([make_pdf(tmp_path / "a.pdf", 2), make_pdf(tmp_path / "b.pdf", 1)])
    a, b = win.tabs()
    src_a = a.model.page(0).src
    assert win.close_tab(0)
    assert src_a.closed
    assert not b.model.page(0).src.closed


def test_reader_zoom_and_navigation(win, tmp_path):
    win.open_paths([make_pdf(tmp_path / "a.pdf", 5)])
    tab = win.current_tab()
    assert tab.mode == MODE_READ
    pump(0.2)
    assert tab.reader.is_fit_width()
    tab.reader.go_to_page(3)
    pump(0.05)
    assert tab.reader.current_page() == 3
    win.act_zoom_in.trigger()
    assert not tab.reader.is_fit_width()
    assert tab.reader.current_page() == 3  # 缩放时停留在当前页
    win.act_fit.trigger()
    assert tab.reader.is_fit_width()
    pump(1.0)
    assert len(win.svc.cache) > 0


def test_save_as_and_export(win, tmp_path, monkeypatch):
    win.open_paths([make_pdf(tmp_path / "a.pdf", 3, "A")])
    tab = win.current_tab()
    target = tmp_path / "另存为.pdf"
    monkeypatch.setattr(win, "_ask_save_path", lambda suggested: str(target))
    win.save_current_as()
    assert tab.path == str(target)
    tab.grid.select_rows([1])
    export = tmp_path / "导出.pdf"
    monkeypatch.setattr(win, "_ask_save_path", lambda suggested: str(export))
    win.export_selected()
    assert page_texts(export) == ["A2"]


def test_start_drag_builds_payload_and_drops(win, tmp_path, monkeypatch):
    """模拟真实拖拽：startDrag 生成的数据直接交给另一个标签的网格。"""
    import pdfeditor.grid as grid_mod
    win.open_paths([make_pdf(tmp_path / "a.pdf", 3), make_pdf(tmp_path / "b.pdf", 1)])
    a, b = win.tabs()
    captured = {}

    class FakeDrag:
        def __init__(self, source):
            self.source = source

        def setMimeData(self, md):
            captured["md"] = md

        def setPixmap(self, pm):
            captured["pm"] = pm

        def setHotSpot(self, pt):
            pass

        def exec(self, *args):
            drop(b.grid, target, captured["md"])
            return Qt.DropAction.CopyAction

    monkeypatch.setattr(grid_mod, "QDrag", FakeDrag)
    win.tabbar.setCurrentIndex(0)
    a.grid.select_rows([0, 2])
    win.tabbar.setCurrentIndex(1)  # 拖着页面切到 b 标签（悬停切换的效果）
    pump(0.1)
    r = b.grid.visualRect(b.model.index(0, 0))
    target = QPoint(r.center().x(), r.bottom() - 5)  # 侧栏是单列：下半部分 = 插到后面
    a.grid.startDrag(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
    assert not captured["pm"].isNull()
    assert labels(b) == ["b.pdf:1", "a.pdf:1", "a.pdf:3"]


def test_hovering_page_drag_over_tab_switches(win, tmp_path):
    from PySide6.QtGui import QDragMoveEvent
    win.open_paths([make_pdf(tmp_path / "a.pdf", 2), make_pdf(tmp_path / "b.pdf", 1)])
    a, _ = win.tabs()
    win.tabbar.setCurrentIndex(0)
    pos = win.tabbar.tabRect(1).center()
    md = page_mime(a, [0])  # 必须保持引用，事件里只存指针
    ev = QDragMoveEvent(pos, Qt.DropAction.CopyAction, md,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.tabbar.dragMoveEvent(ev)
    assert ev.isAccepted()
    pump(0.7)
    assert win.tabbar.currentIndex() == 1
