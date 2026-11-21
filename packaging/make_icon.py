"""生成程序图标 pdfeditor/resources/app.png 和 app.ico（只需在改图标时运行）。"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
OUT = Path(__file__).resolve().parent.parent / "pdfeditor" / "resources"


def rounded(draw, box, r, **kw):
    draw.rounded_rectangle(box, radius=r, **kw)


def make() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # 背景：蓝色渐变圆角方块
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        c = (int(59 + (37 - 59) * t), int(130 + (78 - 130) * t), int(246 + (216 - 246) * t), 255)
        gd.line([(0, y), (S, y)], fill=c)
    mask = Image.new("L", (S, S), 0)
    rounded(ImageDraw.Draw(mask), (40, 40, S - 40, S - 40), 220, fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    # 后面一页（半透明，偏右上）
    back = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(back)
    rounded(bd, (380, 190, 800, 740), 36, fill=(255, 255, 255, 120))
    img.alpha_composite(back)

    # 前面一页：带阴影
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rounded(ImageDraw.Draw(shadow), (236, 300, 676, 860), 40, fill=(0, 0, 40, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(24)))
    rounded(d, (224, 280, 664, 840), 40, fill=(255, 255, 255, 255))
    for i, w in enumerate((300, 340, 260, 320)):
        y = 380 + i * 70
        rounded(d, (290, y, 290 + w, y + 30), 15, fill=(203, 213, 225, 255))
    # 红色 PDF 标签
    rounded(d, (290, 680, 520, 770), 26, fill=(239, 68, 68, 255))
    for x0 in (318, 392, 456):  # 三个小白块代表文字
        rounded(d, (x0, 706, x0 + 46, 744), 10, fill=(255, 255, 255, 235))
    # 右下角的双向箭头圆标：代表“排序/混合”
    d.ellipse((610, 610, 900, 900), fill=(255, 255, 255, 255))
    d.ellipse((630, 630, 880, 880), fill=(249, 115, 22, 255))
    c = (255, 255, 255, 255)
    d.line([(690, 715), (820, 715)], fill=c, width=26)
    d.polygon([(820, 680), (860, 715), (820, 750)], fill=c)
    d.line([(690, 795), (820, 795)], fill=c, width=26)
    d.polygon([(690, 760), (650, 795), (690, 830)], fill=c)
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    big = make()
    big.resize((256, 256), Image.LANCZOS).save(OUT / "app.png")
    big.resize((256, 256), Image.LANCZOS).save(
        OUT / "app.ico", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("written", OUT)
