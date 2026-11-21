"""一个标签页 = 一个文档：左边缩略图（可拖拽排序），右边阅读视图。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from .grid import PAD, SPACING, PageGridView
from .model import PageListModel
from .reader import ReaderView
from .render import RenderService

MODE_READ = "read"
MODE_ORGANIZE = "organize"


class DocumentTab(QWidget):
    changed = Signal()                       # 内容、选择、当前页等变化
    filesDropped = Signal(object, list, int)  # (标签, 文件, 插入位置)
    contextMenuRequested = Signal(object, object)  # (标签, 全局坐标)

    def __init__(self, svc: RenderService, pages, path: str | None = None,
                 title: str | None = None, mode: str = MODE_READ, organize_thumb: int = 170):
        super().__init__()
        self.path = path
        self.title = title or "未命名"
        self.model = PageListModel(pages, self)
        self.grid = PageGridView(self.model, svc)
        self.reader = ReaderView(self.model, svc)
        self.organize_thumb = organize_thumb
        self.mode = None

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.grid)
        self.splitter.addWidget(self.reader)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([210, 900])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.splitter)

        self.model.pagesChanged.connect(self.changed)
        self.grid.selectionModel().selectionChanged.connect(lambda *_: self.changed.emit())
        self.grid.clicked.connect(self._on_grid_clicked)
        self.grid.doubleClicked.connect(self._on_grid_double_clicked)
        self.grid.filesDropped.connect(lambda files, pos: self.filesDropped.emit(self, files, pos))
        self.grid.customContextMenuRequested.connect(
            lambda pt: self.contextMenuRequested.emit(self, self.grid.viewport().mapToGlobal(pt)))
        self.grid.resized.connect(self._fit_sidebar_thumbs)
        self.grid.zoomRequested.connect(self._on_grid_zoom)
        self.reader.currentPageChanged.connect(self._on_reader_page)
        self.reader.zoomChanged.connect(self.changed)
        self.set_mode(mode)

    # ------------------------------------------------------------ 名称
    def display_name(self) -> str:
        return Path(self.path).name if self.path else self.title

    def suggested_filename(self) -> str:
        if self.path:
            return Path(self.path).name
        name = self.title
        for ch in '\\/:*?"<>|':
            name = name.replace(ch, "_")
        return name + ".pdf"

    # ------------------------------------------------------------ 视图模式
    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        if mode == MODE_ORGANIZE:
            self.reader.hide()
            self.grid.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.grid.set_thumb_size(self.organize_thumb)
        else:
            self.reader.show()
            self.grid.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self._fit_sidebar_thumbs()
            rows = self.grid.selected_rows()
            if rows:
                self.reader.go_to_page(rows[0])
        self.changed.emit()

    def set_organize_thumb(self, size: int) -> None:
        self.organize_thumb = size
        if self.mode == MODE_ORGANIZE:
            self.grid.set_thumb_size(size)

    def _fit_sidebar_thumbs(self) -> None:
        if self.mode != MODE_READ:
            return
        avail = self.grid.viewport().width() - 2 * PAD - 2 * SPACING - 6
        self.grid.set_thumb_size(max(60, min(600, avail)))

    def _on_grid_zoom(self, step: int) -> None:
        if self.mode == MODE_ORGANIZE:
            self.set_organize_thumb(max(80, min(400, self.organize_thumb + step * 20)))
            self.changed.emit()
        else:
            (self.reader.zoom_in if step > 0 else self.reader.zoom_out)()

    def _on_grid_clicked(self, index) -> None:
        if self.mode == MODE_READ and index.isValid():
            self.reader.go_to_page(index.row())

    def _on_grid_double_clicked(self, index) -> None:
        if not index.isValid():
            return
        if self.mode == MODE_ORGANIZE:
            self.set_mode(MODE_READ)
        self.reader.go_to_page(index.row())

    def _on_reader_page(self, row: int) -> None:
        self.grid.set_current_row(row)
        if self.mode == MODE_READ and row >= 0 and self.grid.is_idle():
            self.grid.scrollTo(self.model.index(row, 0), self.grid.ScrollHint.EnsureVisible)
        self.changed.emit()

    # ------------------------------------------------------------ 编辑
    def selected_rows(self) -> list[int]:
        return self.grid.selected_rows()

    def selected_pages(self):
        return [self.model.page(r) for r in self.selected_rows()]

    def insert_pages(self, pos: int, refs) -> list[int]:
        rows = self.model.insert_pages(pos, refs)
        self.grid.select_rows(rows)
        return rows

    def delete_selected(self) -> int:
        rows = self.selected_rows()
        if not rows:
            return 0
        nxt = self.model.remove_rows(rows)
        if nxt >= 0:
            self.grid.select_rows([nxt])
        return len(rows)

    def rotate_selected(self, delta: int) -> int:
        rows = self.selected_rows()
        if rows:
            self.grid.select_rows(self.model.rotate_rows(rows, delta))
        return len(rows)

    def undo(self) -> None:
        self.model.undo()

    def redo(self) -> None:
        self.model.redo()
