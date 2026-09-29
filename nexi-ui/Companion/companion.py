"""Nexi's face.

A screen-style robot face drawn entirely with QPainter (no image files, no
QLabels), so it stays crisp, animates smoothly, and cannot ghost the way the
old QLabel version did.

The rest of the project only needs one call, unchanged from before:
    companion.set_state("Idle" | "Listening" | "Thinking" | "Acting" | "Speaking")
"""
import math
import random
import sys
import time

from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt5.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)
from PyQt5.QtWidgets import QApplication, QWidget

# One expression per state. The face glides smoothly between them.
#   eye_w / eye_h : eye size in px
#   lid_in        : fraction of eye height cut off the INNER top corner
#                   (angry / focused, like the Tabbie reference)
#   lid_out       : same for the OUTER top corner (sad / sceptical)
#   smile         : mouth curve, -1 frown .. 1 big smile
#   mouth_w       : mouth width in px
#   glow          : eye glow strength 0..1
FACES = {
    "Idle":      dict(eye_w=34, eye_h=44, lid_in=0.00, lid_out=0.00,
                      smile=0.60, mouth_w=34, glow=0.55, color="#e8f4ff"),
    "Listening": dict(eye_w=38, eye_h=56, lid_in=0.00, lid_out=0.00,
                      smile=0.30, mouth_w=20, glow=0.95, color="#06d6a0"),
    "Thinking":  dict(eye_w=32, eye_h=38, lid_in=0.00, lid_out=0.28,
                      smile=0.00, mouth_w=18, glow=0.70, color="#ffd166"),
    "Acting":    dict(eye_w=36, eye_h=40, lid_in=0.40, lid_out=0.00,
                      smile=0.25, mouth_w=30, glow=0.95, color="#ef476f"),
    "Speaking":  dict(eye_w=34, eye_h=46, lid_in=0.00, lid_out=0.00,
                      smile=0.60, mouth_w=36, glow=0.80, color="#4cc9f0"),
}
NUM_KEYS = ("eye_w", "eye_h", "lid_in", "lid_out", "smile", "mouth_w", "glow")

# Kept so other modules that import it don't break.
STATE_COLORS = {name: face["color"] for name, face in FACES.items()}


class NexiCompanion(QWidget):
    WIDTH, HEIGHT = 220, 200

    def __init__(self):
        super().__init__()
        self._drag_offset = None
        self._caption = "Idle"
        self._state = "Idle"

        start = FACES["Idle"]
        self._cur = {k: float(start[k]) for k in NUM_KEYS}
        self._cur.update(gaze_x=0.0, gaze_y=0.0, mouth_open=0.0)
        self._target = dict(self._cur)
        self._color_cur = QColor(start["color"])
        self._color_target = QColor(start["color"])

        now = time.monotonic()
        self._t0 = now
        self._last_tick = now
        self._blink = 1.0
        self._blink_start = None
        self._next_blink = now + random.uniform(1.5, 3.5)
        self._next_wander = now + 2.0

        self._setup_window()

        # ~30 fps is plenty for a face and keeps CPU use tiny.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # ---------- window ----------
    def _setup_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.WIDTH, self.HEIGHT)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - self.WIDTH - 20,
                  screen.height() - self.HEIGHT - 20)

    # ---------- public API ----------
    def set_state(self, state: str):
        face = FACES.get(state, FACES["Idle"])
        self._state = state if state in FACES else "Idle"
        self._caption = state
        for key in NUM_KEYS:
            self._target[key] = float(face[key])
        self._color_target = QColor(face["color"])

    def snap(self):
        """Jump straight to the current expression (used for screenshots/tests)."""
        for key, value in self._target.items():
            self._cur[key] = value
        self._color_cur = QColor(self._color_target)
        self._blink = 1.0
        self.update()

    # ---------- animation ----------
    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last_tick, 0.1)
        self._last_tick = now

        self._update_behaviours(now)

        k = 1.0 - math.exp(-dt * 14.0)
        for key, target in self._target.items():
            self._cur[key] += (target - self._cur[key]) * k
        self._color_cur = self._mix(self._color_cur, self._color_target, k)
        self.update()

    def _update_behaviours(self, now):
        t = now - self._t0
        state = self._state

        # Where the eyes look
        if state == "Thinking":
            self._target["gaze_x"] = 7 * math.sin(t * 1.6)
            self._target["gaze_y"] = -7
        elif state == "Listening":
            self._target["gaze_x"], self._target["gaze_y"] = 0.0, -2.0
        elif state == "Idle":
            if now >= self._next_wander:
                self._target["gaze_x"] = random.uniform(-6, 6)
                self._target["gaze_y"] = random.uniform(-3, 3)
                self._next_wander = now + random.uniform(1.8, 4.0)
        else:
            self._target["gaze_x"], self._target["gaze_y"] = 0.0, 0.0

        # Mouth flaps while speaking
        if state == "Speaking":
            flap = abs(math.sin(t * 9.0)) * (0.65 + 0.35 * math.sin(t * 2.3))
            self._cur["mouth_open"] = self._target["mouth_open"] = flap
        else:
            self._target["mouth_open"] = 0.0

        # Blinking
        if self._blink_start is None:
            if now >= self._next_blink:
                self._blink_start = now
        else:
            p = (now - self._blink_start) / 0.18
            if p >= 1.0:
                self._blink = 1.0
                self._blink_start = None
                self._next_blink = now + random.uniform(2.2, 5.5)
            else:
                self._blink = 1.0 - 0.92 * math.sin(math.pi * p)

    @staticmethod
    def _mix(a: QColor, b: QColor, k: float) -> QColor:
        return QColor(
            int(a.red() + (b.red() - a.red()) * k),
            int(a.green() + (b.green() - a.green()) * k),
            int(a.blue() + (b.blue() - a.blue()) * k),
        )

    # ---------- drawing ----------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        # Wipe to fully transparent first, so nothing can ghost.
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        card = QRectF(8, 8, self.WIDTH - 16, self.HEIGHT - 16)
        color = self._color_cur

        bg = QLinearGradient(card.topLeft(), card.bottomLeft())
        bg.setColorAt(0.0, QColor("#11151d"))
        bg.setColorAt(1.0, QColor("#090b10"))
        border = QColor(color)
        border.setAlpha(120)
        p.setPen(QPen(border, 2))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(card, 34, 34)

        gx, gy = self._cur["gaze_x"], self._cur["gaze_y"]
        cx0 = card.center().x()
        cy = card.top() + card.height() * 0.38 + gy
        for side in (-1, 1):
            self._draw_eye(p, cx0 + side * 40 + gx, cy, side, color)
        self._draw_mouth(p, cx0 + gx * 0.5, cy + 50, color)

        font = QFont("Segoe UI", 8)
        font.setBold(True)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1.6)
        p.setFont(font)
        caption_color = QColor(color)
        caption_color.setAlpha(150)
        p.setPen(caption_color)
        p.drawText(
            QRectF(card.left(), card.bottom() - 30, card.width(), 22),
            Qt.AlignCenter, self._caption.upper(),
        )
        p.end()

    def _draw_eye(self, p, cx, cy, side, color):
        w = self._cur["eye_w"]
        h = max(3.0, self._cur["eye_h"] * self._blink)
        top = cy - h / 2

        shape = QPainterPath()
        radius = min(w, h) / 2
        shape.addRoundedRect(QRectF(cx - w / 2, top, w, h), radius, radius)

        # Eyelid: slice off the top at an angle. Inner side = towards the
        # nose, so a bigger lid_in gives the angry/focused look.
        x_out = cx + side * (w / 2 + 4)
        x_in = cx - side * (w / 2 + 4)
        lid = QPainterPath()
        lid.moveTo(x_out, top + self._cur["lid_out"] * h)
        lid.lineTo(x_in, top + self._cur["lid_in"] * h)
        lid.lineTo(x_in, top - 30)
        lid.lineTo(x_out, top - 30)
        lid.closeSubpath()
        shape = shape.subtracted(lid)

        glow = self._cur["glow"]
        if glow > 0.01:
            r = max(w, h) * 1.3
            g = QRadialGradient(QPointF(cx, cy), r)
            c0 = QColor(color)
            c0.setAlpha(max(0, min(255, int(85 * glow))))
            c1 = QColor(color)
            c1.setAlpha(0)
            g.setColorAt(0.0, c0)
            g.setColorAt(1.0, c1)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(cx, cy), r, r)

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawPath(shape)

        if h > 16:  # little shine so the eye looks alive
            p.save()
            p.setClipPath(shape)
            p.setBrush(QBrush(QColor(255, 255, 255, 110)))
            p.drawEllipse(QPointF(cx - w * 0.14, cy - h * 0.22), w * 0.11, w * 0.11)
            p.restore()

    def _draw_mouth(self, p, mx, my, color):
        half = self._cur["mouth_w"] / 2
        depth = self._cur["smile"] * 9
        opening = self._cur["mouth_open"]
        left, right = QPointF(mx - half, my), QPointF(mx + half, my)

        path = QPainterPath(left)
        if opening > 0.06:
            d_up = depth * 0.6
            d_lo = d_up + opening * 11
            path.quadTo(QPointF(mx, my + 2 * d_up), right)
            path.quadTo(QPointF(mx, my + 2 * d_lo), left)
            path.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(color))
            p.drawPath(path)
        else:
            path.quadTo(QPointF(mx, my + 2 * depth), right)
            pen = QPen(color, 3.4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

    # ---------- interaction ----------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    def contextMenuEvent(self, event):
        QApplication.instance().quit()


def _demo_cycle_states(companion: NexiCompanion):
    """Standalone preview: cycles through every expression."""
    order = ["Idle", "Listening", "Thinking", "Acting", "Speaking"]
    index = {"i": 0}

    def step():
        companion.set_state(order[index["i"] % len(order)])
        index["i"] += 1

    step()
    timer = QTimer(companion)
    timer.timeout.connect(step)
    timer.start(2500)
    return timer


if __name__ == "__main__":
    # Run this file directly to preview the face on its own.
    app = QApplication(sys.argv)
    nexi = NexiCompanion()
    nexi.show()
    demo_timer = _demo_cycle_states(nexi)
    sys.exit(app.exec_())
