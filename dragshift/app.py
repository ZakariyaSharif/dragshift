"""DragShift: macOS menu bar app. Hold SHIFT while dragging a file and a
panel of target formats appears under the cursor. Drop the file on one.

macOS only. UNTESTED on a real Mac when this was written: if something
misbehaves, run `python -m dragshift` from Terminal to see the errors.
"""
from __future__ import annotations

import threading
from pathlib import Path

import objc
import rumps
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSDragOperationCopy,
    NSDragOperationNone,
    NSEvent,
    NSEventMaskLeftMouseDragged,
    NSEventMaskLeftMouseUp,
    NSEventModifierFlagShift,
    NSFont,
    NSMakeRect,
    NSPanel,
    NSPasteboard,
    NSPasteboardNameDrag,
    NSPasteboardTypeFileURL,
    NSScreen,
    NSSound,
    NSTextAlignmentCenter,
    NSTextField,
    NSView,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSURL
from PyObjCTools import AppHelper

from . import converter

TILE_W, TILE_H, GAP, PAD = 84, 64, 8, 12


def check_permissions():
    """Report (and request) the permissions the global drag monitor needs."""
    import ctypes

    try:
        lib = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        lib.CGPreflightListenEventAccess.restype = ctypes.c_bool
        lib.CGRequestListenEventAccess.restype = ctypes.c_bool
        if not lib.CGPreflightListenEventAccess():
            lib.CGRequestListenEventAccess()
            print(
                "DragShift needs Input Monitoring: System Settings > Privacy & Security > "
                "Input Monitoring, enable Terminal, then restart this app.",
                flush=True,
            )
        else:
            print("Input Monitoring: OK", flush=True)
    except Exception as e:
        print(f"(could not check Input Monitoring: {e})", flush=True)


def dragged_files() -> list[Path]:
    pb = NSPasteboard.pasteboardWithName_(NSPasteboardNameDrag)
    urls = pb.readObjectsForClasses_options_([NSURL], None) or []
    return [Path(u.path()) for u in urls if u.isFileURL() and Path(u.path()).is_file()]


class Tile(NSView):
    """One drop target, e.g. 'JPG'."""

    def initWithFrame_ext_owner_(self, frame, ext, owner):
        self = objc.super(Tile, self).initWithFrame_(frame)
        if self is None:
            return None
        self.ext, self.owner, self.hot = ext, owner, False
        self.setWantsLayer_(True)
        self.layer().setCornerRadius_(12)
        self._paint()
        label = NSTextField.labelWithString_(ext.upper())
        label.setFont_(NSFont.boldSystemFontOfSize_(16))
        label.setTextColor_(NSColor.whiteColor())
        label.setAlignment_(NSTextAlignmentCenter)
        label.setFrame_(NSMakeRect(0, (TILE_H - 22) / 2, TILE_W, 22))
        self.addSubview_(label)
        self.registerForDraggedTypes_([NSPasteboardTypeFileURL])
        return self

    def _paint(self):
        c = NSColor.systemOrangeColor() if self.hot else NSColor.colorWithWhite_alpha_(0.25, 1.0)
        self.layer().setBackgroundColor_(c.CGColor())

    def draggingEntered_(self, sender):
        self.hot = True
        self._paint()
        return NSDragOperationCopy

    def draggingExited_(self, sender):
        self.hot = False
        self._paint()

    def performDragOperation_(self, sender):
        pb = sender.draggingPasteboard()
        urls = pb.readObjectsForClasses_options_([NSURL], None) or []
        files = [Path(u.path()) for u in urls if u.isFileURL()]
        self.hot = False
        self._paint()
        self.owner.convert_files(files, self.ext)
        AppHelper.callLater(0.2, self.owner.hide)
        return True


class DropPanel:
    def __init__(self, app):
        self.app, self.panel, self.files = app, None, []

    def show(self, files: list[Path]):
        exts = converter.targets_for(files[0])
        if not exts:
            return
        self.hide()
        self.files = files
        w = PAD * 2 + len(exts) * TILE_W + (len(exts) - 1) * GAP
        h = PAD * 2 + TILE_H
        p = NSEvent.mouseLocation()
        screen = NSScreen.mainScreen().frame()
        x = min(max(p.x - w / 2, 10), screen.size.width - w - 10)
        y = p.y + 30 if p.y + 30 + h < screen.size.height else p.y - h - 30
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, w, h),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(1000)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.colorWithWhite_alpha_(0.1, 0.92))
        panel.setHasShadow_(True)
        panel.setHidesOnDeactivate_(False)
        content = panel.contentView()
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(16)
        for i, ext in enumerate(exts):
            tile = Tile.alloc().initWithFrame_ext_owner_(
                NSMakeRect(PAD + i * (TILE_W + GAP), PAD, TILE_W, TILE_H), ext, self
            )
            content.addSubview_(tile)
        panel.orderFrontRegardless()
        self.panel = panel

    def hide(self):
        if self.panel is not None:
            self.panel.orderOut_(None)
            self.panel = None

    def convert_files(self, files: list[Path], ext: str):
        self.app.run_conversion(files, ext)


class DragShift(rumps.App):
    def __init__(self):
        super().__init__("DragShift", title="⇧", quit_button="Quit")
        self.menu = [rumps.MenuItem("Hold ⇧ while dragging a file"), None]
        self.menu["Hold ⇧ while dragging a file"].set_callback(None)
        self.drop = DropPanel(self)
        check_permissions()
        mask = NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp
        self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, self._on_event)

    def _flash(self, text: str):
        """Show a result in the menu bar and play a sound; works without notification permission."""
        def apply():
            self.title = text
            NSSound.soundNamed_("Glass").play()
            AppHelper.callLater(3.0, lambda: setattr(self, "title", "⇧"))
        AppHelper.callAfter(apply)

    def _on_event(self, event):
        if event.type() == 2:  # NSEventTypeLeftMouseUp: give the drop time to land
            AppHelper.callLater(0.4, self.drop.hide)
            return
        shift = bool(event.modifierFlags() & NSEventModifierFlagShift)
        if shift and self.drop.panel is None:
            files = dragged_files()
            if files:
                self.drop.show(files)
        elif not shift and self.drop.panel is not None:
            self.drop.hide()

    @staticmethod
    def _notify(title: str, message: str):
        try:
            rumps.notification("DragShift", title, message)
        except Exception as e:  # unbundled Python often cannot post notifications
            print(f"(notification unavailable: {e})", flush=True)

    def run_conversion(self, files: list[Path], ext: str):
        def work():
            done, errors = [], []
            for f in files:
                try:
                    done += converter.convert(f, ext)
                except converter.ConversionError as e:
                    errors.append(f"{f.name}: {e}")
            if done:
                names = ", ".join(p.name for p in done[:3])
                print(f"Converted to .{ext}: {names}", flush=True)
                self._flash("✓")
                self._notify(f"Converted to .{ext}", names)
            if errors:
                msg = "; ".join(errors)[:200]
                print(f"Failed: {msg}", flush=True)
                self._flash("✗")
                self._notify("Some files failed", msg)

        threading.Thread(target=work, daemon=True).start()


def main():
    DragShift().run()


if __name__ == "__main__":
    main()
