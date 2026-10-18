"""DragShift: macOS menu bar app. Hold SHIFT while dragging a file and a
panel of target formats appears under the cursor. Drop the file on one.

macOS only. UNTESTED on a real Mac when this was written: if something
misbehaves, run `python -m dragshift` from Terminal to see the errors.
"""
from __future__ import annotations

import math
import threading
import time
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
    NSMakePoint,
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

LOG = Path(__file__).resolve().parent.parent / "debug.log"


def log(msg: str):
    print(msg, flush=True)
    try:
        with LOG.open("a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def logged(fn):
    """Log any exception from a PyObjC callback instead of failing silently."""
    import functools, traceback

    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except Exception:
            log("ERROR in " + fn.__name__ + ":\n" + traceback.format_exc())
            raise
    return wrapper



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


R_OUT, R_IN, MARGIN, GAP_DEG = 128, 40, 10, 2.5


def wedge_index(dx: float, dy: float, n: int) -> int:
    if not (R_IN <= math.hypot(dx, dy) <= R_OUT):
        return -1
    cw = (90 - math.degrees(math.atan2(dy, dx))) % 360  # clockwise from the top
    return int(cw // (360 / n))


class Wheel(NSView):
    """Radial menu: wedges around the cursor, the whole view is the drop destination."""

    def initWithFrame_exts_owner_(self, frame, exts, owner):
        self = objc.super(Wheel, self).initWithFrame_(frame)
        if self is None:
            return None
        self.exts, self.owner, self.hot = list(exts), owner, -1
        self.registerForDraggedTypes_([NSPasteboardTypeFileURL, NSFilenamesPboardType])
        return self

    @objc.python_method
    def center(self):
        b = self.bounds()
        return b.size.width / 2, b.size.height / 2

    @objc.python_method
    def indexFor(self, sender):
        pt = self.convertPoint_fromView_(sender.draggingLocation(), None)
        cx, cy = self.center()
        return wedge_index(pt.x - cx, pt.y - cy, len(self.exts))

    @objc.python_method
    def setHot(self, i):
        if i != self.hot:
            self.hot = i
            self.setNeedsDisplay_(True)

    @logged
    def drawRect_(self, rect):
        cx, cy = self.center()
        c = NSMakePoint(cx, cy)
        n = len(self.exts)
        span = 360 / n
        style = NSMutableParagraphStyle.alloc().init()
        style.setAlignment_(NSTextAlignmentCenter)

        def attrs(size, color):
            return {
                NSFontAttributeName: NSFont.boldSystemFontOfSize_(size),
                NSForegroundColorAttributeName: color,
                NSParagraphStyleAttributeName: style,
            }

        for i, ext in enumerate(self.exts):
            hi = 90 - i * span - GAP_DEG
            lo = 90 - (i + 1) * span + GAP_DEG
            path = NSBezierPath.bezierPath()
            path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(c, R_OUT, lo, hi, False)
            path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(c, R_IN, hi, lo, True)
            path.closePath()
            if i == self.hot:
                NSColor.systemOrangeColor().set()
            else:
                NSColor.colorWithWhite_alpha_(0.12, 0.88).set()
            path.fill()
            mid = math.radians(90 - (i + 0.5) * span)
            rm = (R_IN + R_OUT) / 2
            tx, ty = cx + rm * math.cos(mid), cy + rm * math.sin(mid)
            NSString.stringWithString_(ext.upper()).drawInRect_withAttributes_(
                NSMakeRect(tx - 40, ty - 11, 80, 22), attrs(15, NSColor.whiteColor())
            )
        hint = "\u21e7" if self.hot < 0 else self.exts[self.hot].upper()
        NSString.stringWithString_(hint).drawInRect_withAttributes_(
            NSMakeRect(cx - 36, cy - 12, 72, 24), attrs(18, NSColor.colorWithWhite_alpha_(1.0, 0.8))
        )

    @logged
    def draggingEntered_(self, sender):
        log("drag ENTERED wheel")
        return NSDragOperationCopy

    @logged
    def draggingUpdated_(self, sender):
        i = self.indexFor(sender)
        if i != self.hot:
            log(f"drag over wedge {i}")
        self.setHot(i)
        return NSDragOperationCopy if i >= 0 else NSDragOperationNone

    @logged
    def draggingExited_(self, sender):
        self.setHot(-1)

    @logged
    def prepareForDragOperation_(self, sender):
        log("prepareForDragOperation")
        return self.indexFor(sender) >= 0

    @logged
    def performDragOperation_(self, sender):
        log("performDragOperation")
        i = self.indexFor(sender)
        if i < 0:
            return False
        urls = sender.draggingPasteboard().readObjectsForClasses_options_([NSURL], None) or []
        files = [Path(u.path()) for u in urls if u.isFileURL()]
        log(f"DROP on {self.exts[i]}: {[f.name for f in files]}")
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
        size = 2 * (R_OUT + MARGIN)
        p = NSEvent.mouseLocation()
        scr = NSScreen.mainScreen().frame()
        x = min(max(p.x - size / 2, 4), scr.size.width - size - 4)
        y = min(max(p.y - size / 2, 4), scr.size.height - size - 4)
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, size, size),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(1000)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(False)
        panel.setHidesOnDeactivate_(False)
        wheel = Wheel.alloc().initWithFrame_exts_owner_(NSMakeRect(0, 0, size, size), exts, self)
        panel.setContentView_(wheel)
        self.wheel = wheel
        wheel.registerForDraggedTypes_([NSPasteboardTypeFileURL, NSFilenamesPboardType])
        log(f"show wheel for {files[0].name}: {exts}")
        panel.setAlphaValue_(0.0)
        panel.orderFrontRegardless()
        panel.animator().setAlphaValue_(1.0)
        self.panel = panel

    def index_at_mouse(self) -> int:
        if self.panel is None:
            return -1
        p, f = NSEvent.mouseLocation(), self.panel.frame()
        return wedge_index(p.x - (f.origin.x + f.size.width / 2), p.y - (f.origin.y + f.size.height / 2), len(self.wheel.exts))

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
        if event.type() == 2:  # left mouse up: convert if released over a wedge
            self._seen = False
            i = self.drop.index_at_mouse()
            log(f"mouse up (global), wedge={i}")
            if i >= 0:
                self.run_conversion(self.drop.files, self.drop.wheel.exts[i])
            AppHelper.callLater(0.4, self.drop.hide)
            return
        shift = bool(event.modifierFlags() & NSEventModifierFlagShift)
        if self.drop.panel is not None:
            self.drop.wheel.setHot(self.drop.index_at_mouse())
        elif shift:
            files = dragged_files()
            if files:
                self.drop.show(files)

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
