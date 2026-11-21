"""一个文档 = 一串 PageRef。所有编辑操作都在这里，并支持撤销/重做。"""

from __future__ import annotations

import itertools
import weakref

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal

from .engine import PageRef

PAGE_MIME = "application/x-pdfeditor-pages"
PAGE_ROLE = int(Qt.ItemDataRole.UserRole) + 1
UNDO_LIMIT = 200

_model_ids = itertools.count(1)
MODELS: "weakref.WeakValueDictionary[int, PageListModel]" = weakref.WeakValueDictionary()


class PageListModel(QAbstractListModel):
    pagesChanged = Signal()

    def __init__(self, pages=(), parent=None):
        super().__init__(parent)
        self.uid = next(_model_ids)
        MODELS[self.uid] = self
        self._pages: list[PageRef] = list(pages)
        self._undo: list[tuple[PageRef, ...]] = []
        self._redo: list[tuple[PageRef, ...]] = []
        self._saved = tuple(self._pages)

    # ------------------------------------------------------------ Qt 接口
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._pages)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._pages):
            return None
        ref = self._pages[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return str(index.row() + 1)
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"第 {index.row() + 1} 页\n来自：{ref.src.name} 第 {ref.index + 1} 页"
        if role == PAGE_ROLE:
            return ref
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        return (Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemNeverHasChildren)

    def supportedDragActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    # ------------------------------------------------------------ 读取
    @property
    def pages(self) -> list[PageRef]:
        return list(self._pages)

    def page(self, row: int) -> PageRef:
        return self._pages[row]

    def __len__(self) -> int:
        return len(self._pages)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def is_modified(self) -> bool:
        return tuple(self._pages) != self._saved

    def mark_saved(self) -> None:
        self._saved = tuple(self._pages)
        self.pagesChanged.emit()

    def source_uids(self) -> set[int]:
        """当前内容以及撤销历史里用到的所有来源文档。"""
        uids = {r.src.uid for r in self._pages}
        for snap in itertools.chain(self._undo, self._redo):
            uids.update(r.src.uid for r in snap)
        return uids

    # ------------------------------------------------------------ 编辑
    def _commit(self, new: list[PageRef]) -> bool:
        if new == self._pages:
            return False
        self._undo.append(tuple(self._pages))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self._set(new)
        return True

    def _set(self, new) -> None:
        self.beginResetModel()
        self._pages = list(new)
        self.endResetModel()
        self.pagesChanged.emit()

    def move_rows(self, rows, dest: int) -> list[int]:
        """把 rows 这些页移动到 dest 位置之前（dest 是移动前的下标）。"""
        rows = sorted(set(r for r in rows if 0 <= r < len(self._pages)))
        if not rows:
            return []
        moving = [self._pages[r] for r in rows]
        rowset = set(rows)
        rest = [p for i, p in enumerate(self._pages) if i not in rowset]
        d = max(0, min(dest, len(self._pages))) - sum(1 for r in rows if r < dest)
        self._commit(rest[:d] + moving + rest[d:])
        return list(range(d, d + len(moving)))

    def insert_pages(self, pos: int, refs) -> list[int]:
        refs = list(refs)
        if not refs:
            return []
        pos = max(0, min(pos, len(self._pages)))
        self._commit(self._pages[:pos] + refs + self._pages[pos:])
        return list(range(pos, pos + len(refs)))

    def remove_rows(self, rows) -> int:
        """删除页面，返回删除后应该选中的位置。"""
        rowset = set(r for r in rows if 0 <= r < len(self._pages))
        if not rowset:
            return -1
        self._commit([p for i, p in enumerate(self._pages) if i not in rowset])
        return min(min(rowset), len(self._pages) - 1)

    def rotate_rows(self, rows, delta: int) -> list[int]:
        rowset = set(r for r in rows if 0 <= r < len(self._pages))
        if not rowset:
            return []
        self._commit([p.rotated(delta) if i in rowset else p for i, p in enumerate(self._pages)])
        return sorted(rowset)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(tuple(self._pages))
        self._set(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(tuple(self._pages))
        self._set(self._redo.pop())
        return True
