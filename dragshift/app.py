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
    NSBezierPath,
    NSColor,
    NSDragOperationCopy,
    NSDragOperationNone,
    NSEvent,
    NSEventMaskLeftMouseDragged,
    NSEventMaskLeftMouseUp,
    NSEventModifierFlagShift,
    NSFilenamesPboardType,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSMakeRect,
    NSMutableParagraphStyle,
    NSPanel,
    NSPointInRect,
    NSParagraphStyleAttributeName,
    NSPasteboard,
    NSPasteboardNameDrag,
    NSPasteboardTypeFileURL,
    NSScreen,
    NSSound,
    NSTextAlignmentCenter,
    NSView,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSURL, NSString
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


class Strip(NSView):
    """The whole panel: draws every tile and is the single drop destination."""

    def initWithFrame_exts_owner_(self, frame, exts, owner):
        self = objc.super(Strip, self).initWithFrame_(frame)
        if self is None:
            return None
        self.exts, self.owner, self.hot = list(exts), owner, -1
        self.registerForDraggedTypes_([NSPasteboardTypeFileURL, NSFilenamesPboardType])
        return self

    @objc.python_method
    def tileRect(self, i):
        return NSMakeRect(PAD + i * (TILE_W + GAP), PAD, TILE_W, TILE_H)

    @objc.python_method
    def indexFor(self, sender):
        pt = self.convertPoint_fromView_(sender.draggingLocation(), None)
        for i in range(len(self.exts)):
            if NSPointInRect(pt, self.tileRect(i)):
                return i
        return -1

    @objc.python_method
    def setHot(self, i):
        if i != self.hot:
            self.hot = i
            self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        NSColor.colorWithWhite_alpha_(0.1, 0.92).set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 16, 16).fill()
        style = NSMutableParagraphStyle.alloc().init()
        style.setAlignment_(NSTextAlignmentCenter)
        attrs = {
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(16),
            NSForegroundColorAttributeName: NSColor.whiteColor(),
            NSParagraphStyleAttributeName: style,
        }
        for i, ext in enumerate(self.exts):
            r = self.tileRect(i)
            (NSColor.systemOrangeColor() if i == self.hot else NSColor.colorWithWhite_alpha_(0.25, 1.0)).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, 12, 12).fill()
            NSString.stringWithString_(ext.upper()).drawInRect_withAttributes_(
                NSMakeRect(r.origin.x, r.origin.y + (TILE_H - 22) / 2, TILE_W, 22), attrs
            )

    def draggingEntered_(self, sender):
        return self.draggingUpdated_(sender)

    def draggingUpdated_(self, sender):
        i = self.indexFor(sender)
        self.setHot(i)
        return NSDragOperationCopy if i >= 0 else NSDragOperationNone

    def draggingExited_(self, sender):
        self.setHot(-1)

    def prepareForDragOperation_(self, sender):
        return self.indexFor(sender) >= 0

    def performDragOperation_(self, sender):
        i = self.indexFor(sender)
        if i < 0:
            return False
        urls = sender.draggingPasteboard().readObjectsForClasses_options_([NSURL], None) or []
        files = [Path(u.path()) for u in urls if u.isFileURL()]
        print(f"drop on {self.exts[i]}: {[f.name for f in files]}", flush=True)
        self.setHot(-1)
        self.owner.convert_files(files, self.exts[i])
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
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setHidesOnDeactivate_(False)
        strip = Strip.alloc().initWithFrame_exts_owner_(NSMakeRect(0, 0, w, h), exts, self)
        panel.setContentView_(strip)
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
