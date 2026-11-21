from pdfeditor.engine import PageRef, read_pdf
from pdfeditor.model import PageListModel

from .conftest import make_pdf


def labels(model):
    return [r.index + 1 for r in model.pages]


def make_model(tmp_path, qapp, n=6):
    src = read_pdf(make_pdf(tmp_path / "a.pdf", n))
    return PageListModel([PageRef(src, i) for i in range(n)]), src


def test_move_forward_and_backward(tmp_path, qapp):
    m, _ = make_model(tmp_path, qapp)
    assert m.move_rows([0], 3) == [2]
    assert labels(m) == [2, 3, 1, 4, 5, 6]
    assert m.move_rows([4, 5], 0) == [0, 1]
    assert labels(m) == [5, 6, 2, 3, 1, 4]
    assert m.move_rows([1, 3], 6) == [4, 5]          # 不连续的多页移到末尾
    assert labels(m) == [5, 2, 1, 4, 6, 3]


def test_move_onto_itself_is_noop(tmp_path, qapp):
    m, _ = make_model(tmp_path, qapp)
    m.move_rows([2, 3], 3)
    assert labels(m) == [1, 2, 3, 4, 5, 6]
    assert not m.can_undo()
    assert not m.is_modified()


def test_insert_remove_rotate_undo_redo(tmp_path, qapp):
    m, src = make_model(tmp_path, qapp, 3)
    m.insert_pages(1, [PageRef(src, 2)])
    assert labels(m) == [1, 3, 2, 3]
    assert m.remove_rows([0, 1]) == 0
    assert labels(m) == [2, 3]
    m.rotate_rows([1], 90)
    m.rotate_rows([1], 90)
    assert m.page(1).rotation == 180
    assert m.is_modified()
    for _ in range(4):
        m.undo()
    assert labels(m) == [1, 2, 3] and not m.is_modified()
    assert not m.can_undo()
    m.redo()
    assert labels(m) == [1, 3, 2, 3]
    m.mark_saved()
    assert not m.is_modified()
    m.undo()
    assert m.is_modified()


def test_source_uids_include_history(tmp_path, qapp):
    m, src = make_model(tmp_path, qapp, 2)
    other = read_pdf(make_pdf(tmp_path / "b.pdf", 1))
    m.insert_pages(0, [PageRef(other, 0)])
    m.remove_rows([0])
    assert other.uid in m.source_uids()  # 还能撤销回来，所以不能释放
