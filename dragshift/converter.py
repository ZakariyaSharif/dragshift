"""Core conversion engine. Pure Python, no UI, works on macOS and Linux.

Tools used (all free): Pillow, pillow-heif, PyMuPDF, ffmpeg, LibreOffice.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE = {"heic", "heif", "png", "jpg", "jpeg", "webp", "gif", "tiff", "tif", "bmp"}
VIDEO = {"mov", "mp4", "mkv", "avi", "webm", "m4v"}
AUDIO = {"wav", "mp3", "m4a", "aac", "flac", "ogg", "aiff", "aif"}
OFFICE = {"docx", "doc", "pptx", "ppt", "xlsx", "xls", "odt", "rtf", "txt"}
PDF = {"pdf"}

TARGETS = {
    "image": ["png", "jpg", "webp", "pdf", "gif"],
    "video": ["mp4", "mov", "webm", "gif", "mp3"],
    "audio": ["mp3", "m4a", "wav", "flac", "ogg"],
    "office": ["pdf"],
    "pdf": ["png", "txt"],
}


class ConversionError(Exception):
    pass


def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower().lstrip(".")
    if ext in IMAGE:
        return "image"
    if ext in VIDEO:
        return "video"
    if ext in AUDIO:
        return "audio"
    if ext in OFFICE:
        return "office"
    if ext in PDF:
        return "pdf"
    return None


def targets_for(path: Path) -> list[str]:
    """Formats offered for this file, never the format it already is."""
    kind = kind_of(path)
    if kind is None:
        return []
    own = path.suffix.lower().lstrip(".")
    own = "jpg" if own == "jpeg" else own
    return [t for t in TARGETS[kind] if t != own]


def unique_path(src: Path, ext: str) -> Path:
    """Output beside the original. Never overwrites an existing file."""
    out = src.with_suffix(f".{ext}")
    n = 1
    while out.exists():
        out = src.with_name(f"{src.stem} ({n}).{ext}")
        n += 1
    return out


def _run(cmd: list[str]) -> None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except FileNotFoundError:
        raise ConversionError(f"'{cmd[0]}' is not installed. See README.")
    if r.returncode != 0:
        raise ConversionError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "failed")


def _image(src: Path, ext: str) -> list[Path]:
    from PIL import Image

    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    out = unique_path(src, ext)
    with Image.open(src) as im:
        if ext in ("jpg", "pdf") and im.mode in ("RGBA", "P", "LA"):
            im = im.convert("RGB")
        fmt = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF", "pdf": "PDF"}[ext]
        im.save(out, fmt)
    return [out]


def _ffmpeg(src: Path, ext: str) -> list[Path]:
    out = unique_path(src, ext)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    if ext == "gif":
        cmd += ["-vf", "fps=12,scale=720:-1:flags=lanczos", "-loop", "0"]
    elif ext == "mp3":
        cmd += ["-vn", "-q:a", "2"]
    elif ext in ("m4a",):
        cmd += ["-vn", "-c:a", "aac", "-b:a", "192k"]
    elif ext == "mp4":
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart"]
    elif ext == "mov":
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    elif ext == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-c:a", "libopus"]
    elif ext == "flac":
        cmd += ["-vn", "-c:a", "flac"]
    elif ext == "ogg":
        cmd += ["-vn", "-c:a", "libvorbis", "-q:a", "5"]
    elif ext == "wav":
        cmd += ["-vn"]
    cmd.append(str(out))
    _run(cmd)
    return [out]


def _soffice() -> str:
    for name in ("soffice", "libreoffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if shutil.which(name) or Path(name).exists():
            return name
    raise ConversionError("LibreOffice is not installed (brew install --cask libreoffice).")


def _office(src: Path, ext: str) -> list[Path]:
    out = unique_path(src, ext)
    with tempfile.TemporaryDirectory() as tmp:
        _run([_soffice(), "--headless", "--convert-to", ext, "--outdir", tmp, str(src)])
        made = Path(tmp) / f"{src.stem}.{ext}"
        if not made.exists():
            raise ConversionError("LibreOffice produced no file.")
        shutil.move(str(made), out)
    return [out]


def _pdf(src: Path, ext: str) -> list[Path]:
    import pymupdf

    doc = pymupdf.open(src)
    outs: list[Path] = []
    if ext == "txt":
        out = unique_path(src, "txt")
        out.write_text("\n\n".join(p.get_text() for p in doc), encoding="utf-8")
        return [out]
    # png: one file per page
    for i, page in enumerate(doc, start=1):
        base = src if len(doc) == 1 else src.with_name(f"{src.stem}-p{i}.pdf")
        out = unique_path(base, "png")
        page.get_pixmap(dpi=200).save(out)
        outs.append(out)
    return outs


def convert(src: str | Path, ext: str) -> list[Path]:
    """Convert `src` to `ext`. Returns the created files. Raises ConversionError."""
    src = Path(src)
    ext = ext.lower().lstrip(".")
    if not src.is_file():
        raise ConversionError(f"Not a file: {src.name}")
    if ext not in targets_for(src):
        raise ConversionError(f"Can't convert {src.suffix} to .{ext}")
    kind = kind_of(src)
    try:
        if kind == "image":
            return _image(src, ext)
        if kind in ("video", "audio"):
            return _ffmpeg(src, ext)
        if kind == "office":
            return _office(src, ext)
        return _pdf(src, ext)
    except ConversionError:
        raise
    except Exception as e:  # surface library errors as one clean type
        raise ConversionError(str(e)) from e
