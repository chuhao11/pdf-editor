import io

import pymupdf
import pytest
from PIL import Image

from pdfeditor.engine import (
    IMAGE_PAGE_A4, IMAGE_PAGE_FIT, PDF_LOCK, PageRef, PasswordRequired, PdfError,
    all_pages, images_to_source, natural_key, read_pdf, save_pdf,
)

from .conftest import make_pdf, page_texts


def test_reorder_duplicate_and_merge(tmp_path):
    a = read_pdf(make_pdf(tmp_path / "a.pdf", 3, "A"))
    b = read_pdf(make_pdf(tmp_path / "b.pdf", 2, "B"))
    pages = [PageRef(a, 2), PageRef(b, 0), PageRef(a, 0), PageRef(a, 0), PageRef(b, 1)]
    out = tmp_path / "out.pdf"
    save_pdf(pages, str(out))
    assert page_texts(out) == ["A3", "B1", "A1", "A1", "B2"]


def test_rotation_adds_to_existing_rotation(tmp_path):
    src = read_pdf(make_pdf(tmp_path / "a.pdf", 2, rotate={1: 90}))
    assert src.sizes[1] == (400, 300)  # 页面自带 90° 旋转，显示为横向
    pages = [PageRef(src, 0).rotated(-90), PageRef(src, 1).rotated(90)]
    assert pages[0].size() == (400, 300)
    out = tmp_path / "out.pdf"
    save_pdf(pages, str(out))
    with PDF_LOCK:
        d = pymupdf.open(str(out))
        assert [p.rotation for p in d] == [270, 180]
        d.close()


def test_toc_follows_pages_and_drops_deleted(tmp_path):
    toc = [[1, "一", 1], [2, "一.1", 2], [1, "二", 3], [2, "二.1", 4]]
    src = read_pdf(make_pdf(tmp_path / "a.pdf", 4, toc=toc))
    # 删除第 3 页（“二”所在页），倒序其余页
    pages = [PageRef(src, 3), PageRef(src, 1), PageRef(src, 0)]
    out = tmp_path / "out.pdf"
    save_pdf(pages, str(out))
    got = read_pdf(str(out)).toc
    assert ["一", 3] in [[t, p] for _, t, p in got]
    assert ["一.1", 2] in [[t, p] for _, t, p in got]
    assert ["二.1", 1] in [[t, p] for _, t, p in got]
    assert "二" not in [t for _, t, _ in got]


def test_overwrite_original_file(tmp_path):
    path = make_pdf(tmp_path / "a.pdf", 3, "A")
    src = read_pdf(path)
    pages = all_pages(src)[::-1]
    save_pdf(pages, path)  # 原文件已读进内存，可以直接覆盖
    assert page_texts(path) == ["A3", "A2", "A1"]
    assert not list(tmp_path.glob("*.tmp"))


def test_empty_document_cannot_be_saved(tmp_path):
    with pytest.raises(PdfError):
        save_pdf([], str(tmp_path / "x.pdf"))


def test_broken_file(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")
    with pytest.raises(PdfError):
        read_pdf(str(bad))


def test_password_protected(tmp_path):
    path = tmp_path / "locked.pdf"
    with PDF_LOCK:
        d = pymupdf.open()
        d.new_page()
        d.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="123", owner_pw="456")
        d.close()
    with pytest.raises(PasswordRequired):
        read_pdf(str(path))
    with pytest.raises(PasswordRequired):
        read_pdf(str(path), "wrong")
    src = read_pdf(str(path), "123")
    save_pdf(all_pages(src), str(tmp_path / "unlocked.pdf"))
    assert read_pdf(str(tmp_path / "unlocked.pdf")).page_count == 1


def _jpeg_with_orientation(path, orientation):
    im = Image.new("RGB", (400, 200), "white")
    im.paste((255, 0, 0), (0, 0, 200, 200))  # 左半边红色
    exif = im.getexif()
    exif[0x0112] = orientation
    im.save(path, "JPEG", exif=exif.tobytes())


def test_images_respect_exif_orientation(tmp_path):
    p = tmp_path / "phone.jpg"
    _jpeg_with_orientation(p, 6)  # 手机竖拍：需要顺时针转 90°
    src, failed = images_to_source([str(p)], IMAGE_PAGE_FIT)
    assert not failed
    w, h = src.sizes[0]
    assert h > w  # 摆正后是竖的
    with PDF_LOCK:
        pix = src.doc[0].get_pixmap()
        r, g, b = pix.pixel(pix.width // 2, 5)[:3]
    assert r > 200 and g < 80  # 原来的左半边现在在上面


def test_images_a4_and_formats(tmp_path):
    Image.new("RGB", (300, 200), "blue").save(tmp_path / "1.png")
    Image.new("RGBA", (100, 300), (0, 255, 0, 100)).save(tmp_path / "2.png")
    Image.new("RGB", (200, 200), "red").save(tmp_path / "3.webp")
    Image.new("RGB", (50, 50), "red").save(tmp_path / "4.bmp")
    (tmp_path / "5.jpg").write_bytes(b"not an image")
    files = [str(tmp_path / f) for f in ("1.png", "2.png", "3.webp", "4.bmp", "5.jpg")]
    src, failed = images_to_source(files, IMAGE_PAGE_A4)
    assert failed == [files[-1]]
    assert src.page_count == 4
    assert src.sizes[0] == pytest.approx((841.8898, 595.2756))  # 横图 → 横向 A4
    assert src.sizes[1] == pytest.approx((595.2756, 841.8898))


def test_heic_if_supported(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    p = tmp_path / "photo.heic"
    try:
        pillow_heif.from_pillow(Image.new("RGB", (64, 48), "orange")).save(str(p), quality=80)
    except Exception:
        pytest.skip("此平台的 pillow-heif 不支持写 HEIC")
    src, failed = images_to_source([str(p)], IMAGE_PAGE_FIT)
    assert not failed and src.page_count == 1


def test_natural_sort():
    names = ["IMG_10.jpg", "IMG_2.jpg", "img_1.jpg"]
    assert sorted(names, key=natural_key) == ["img_1.jpg", "IMG_2.jpg", "IMG_10.jpg"]


def test_multipage_tiff(tmp_path):
    frames = [Image.new("RGB", (100, 150), c) for c in ("red", "green", "blue")]
    buf = tmp_path / "scan.tif"
    frames[0].save(buf, save_all=True, append_images=frames[1:])
    src, failed = images_to_source([str(buf)])
    assert not failed and src.page_count == 3
    assert io  # 保持导入
