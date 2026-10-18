import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from dragshift import converter as c


def test_targets_exclude_own_format(tmp_path):
    p = tmp_path / "a.png"
    p.touch()
    assert "png" not in c.targets_for(p)
    assert "jpg" in c.targets_for(p)
    assert c.targets_for(tmp_path / "x.unknown") == []


def test_image_png_to_jpg_with_alpha(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 128)).save(src)
    out = c.convert(src, "jpg")[0]
    assert out.exists() and out.suffix == ".jpg"
    assert src.exists()


def test_never_overwrites(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (5, 5)).save(src)
    first = c.convert(src, "jpg")[0]
    second = c.convert(src, "jpg")[0]
    assert first != second and first.exists() and second.exists()


def test_image_to_pdf_and_pdf_to_png(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (50, 50), "blue").save(src)
    pdf = c.convert(src, "pdf")[0]
    pngs = c.convert(pdf, "png")
    assert pngs and pngs[0].exists()
    txt = c.convert(pdf, "txt")[0]
    assert txt.exists()


def test_bad_target(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (5, 5)).save(src)
    with pytest.raises(c.ConversionError):
        c.convert(src, "mp4")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
def test_audio_and_video(tmp_path):
    wav = tmp_path / "t.wav"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", str(wav)],
        check=True,
    )
    assert c.convert(wav, "mp3")[0].exists()
    mp4 = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
         "-pix_fmt", "yuv420p", str(mp4)],
        check=True,
    )
    assert c.convert(mp4, "gif")[0].exists()
    with pytest.raises(c.ConversionError):  # this test clip has no audio track
        c.convert(mp4, "mp3")


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice missing")
def test_office_to_pdf(tmp_path):
    txt = tmp_path / "n.txt"
    txt.write_text("hello")
    assert c.convert(txt, "pdf")[0].exists()


def test_image_and_pdf_to_pptx(tmp_path):
    pptx = pytest.importorskip("pptx")
    pymupdf = pytest.importorskip("pymupdf")
    from PIL import Image

    Image.new("RGBA", (400, 300), (255, 120, 0, 255)).save(tmp_path / "a.png")
    out = converter.convert(tmp_path / "a.png", "pptx")[0]
    assert len(pptx.Presentation(out).slides) == 1

    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page().insert_text((72, 72), "hello")
    doc.save(tmp_path / "m.pdf")
    out = converter.convert(tmp_path / "m.pdf", "pptx")[0]
    assert len(pptx.Presentation(out).slides) == 3


def test_slide_targets(tmp_path):
    assert converter.targets_for(tmp_path / "x.pptx") == ["pdf", "png", "jpg", "ppt"]
    assert "pptx" in converter.targets_for(tmp_path / "x.ppt")
