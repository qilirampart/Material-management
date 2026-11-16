"""Keep wheel gestures for scrolling, not accidental parameter edits."""
from PySide6.QtCore import QObject, QEvent, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication, QAbstractScrollArea, QAbstractSpinBox, QComboBox, QLineEdit,
)


class ParameterWheelGuard(QObject):
    def eventFilter(self, watched, event):
        if event.type() != QEvent.Wheel:
            return False
        control = watched
        if isinstance(control, QLineEdit):
            control = control.parentWidget()
        if not isinstance(control, (QComboBox, QAbstractSpinBox)):
            return False

        # Consume the parameter's wheel event even when it has keyboard focus.
        # Forward to the nearest scroll viewport so a long form keeps scrolling.
        parent = control.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                viewport = parent.viewport()
                forwarded = QWheelEvent(
                    QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                    event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                    event.buttons(), event.modifiers(), event.phase(), event.inverted(),
                    event.source(), event.pointingDevice(),
                )
                QApplication.sendEvent(viewport, forwarded)
                break
            parent = parent.parentWidget()
        event.accept()
        return True


def install_parameter_wheel_guard(app):
    if not hasattr(app, '_parameter_wheel_guard'):
        app._parameter_wheel_guard = ParameterWheelGuard(app)
        app.installEventFilter(app._parameter_wheel_guard)
