# DragShift

Free, personal file converter for macOS. Hold **Shift** while dragging a file and a panel of formats appears next to your cursor. Drop the file on one. The converted file lands beside the original, and nothing is ever overwritten.

Inspired by a post about Tangerine for Mac. This is an independent, open build for personal use.

## Supports

- Images: HEIC, PNG, JPG, WebP, GIF, TIFF, BMP to PNG, JPG, WebP, PDF, GIF
- Video: MOV, MP4, MKV, AVI, WebM, M4V to MP4, MOV, WebM, GIF, MP3
- Audio: WAV, MP3, M4A, AAC, FLAC, OGG, AIFF to MP3, M4A, WAV, FLAC, OGG
- Documents: DOCX, XLSX, ODT, RTF, TXT to PDF. PDF to PNG (one per page), TXT or PPTX
- Slides: PPT and PPTX to PDF, PNG or JPG (one per slide), or to each other. Images and PDFs to PPTX (one slide per image or page)

## Install

```bash
brew install ffmpeg
brew install --cask libreoffice      # only needed for Office to PDF
git clone <this repo> && cd dragshift
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m dragshift
```

A ⇧ icon appears in the menu bar. If the panel never shows, check System Settings, Privacy & Security, and allow Terminal (or your Python app) under Accessibility and Input Monitoring.

## Run at login

System Settings, General, Login Items, add a small shell script that runs `.venv/bin/python -m dragshift`.

## Test the converter (any OS)

```bash
pip install pytest && python -m pytest
```

The conversion engine is tested. The menu bar UI (`dragshift/app.py`) needs a Mac and has not been tested on one yet.
