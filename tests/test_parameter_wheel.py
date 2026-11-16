import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QComboBox, QAbstractSpinBox, QPushButton
from shiboken6 import delete
from src.desktop import configure_app
from src.micro_settings import MicroSettings


class ParameterWheelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_app(cls.app)

    def setUp(self):
        self.scroll = QScrollArea()
        self.settings = MicroSettings()
        self.scroll.setWidget(self.settings)
        self.scroll.setWidgetResizable(True)
        self.scroll.resize(650, 400)
        self.scroll.show()
        self.app.processEvents()

    def tearDown(self):
        self.scroll.close()
        delete(self.scroll)
        self.app.processEvents()

    def wheel(self, widget, delta=-120, pixels=0):
        center = widget.rect().center()
        event = QWheelEvent(QPointF(center), QPointF(widget.mapToGlobal(center)),
                            QPoint(0, pixels), QPoint(0, delta), Qt.NoButton,
                            Qt.NoModifier, Qt.ScrollUpdate, False)
        QApplication.sendEvent(widget, event)
        self.app.processEvents()

    def test_hover_or_focus_does_not_modify_combo_or_number_and_scrolls_page(self):
        for focused in (False, True):
            for widget in (self.settings.fields['background'], self.settings.fields['foreground_scale']):
                with self.subTest(focused=focused, control=type(widget).__name__):
                    self.scroll.verticalScrollBar().setValue(0)
                    if focused: widget.setFocus()
                    else: widget.clearFocus()
                    before = self.settings.values()
                    self.wheel(widget)
                    self.assertEqual(self.settings.values(), before)
                    self.assertGreater(self.scroll.verticalScrollBar().value(), 0)

    def test_touchpad_and_spin_editor_keep_parameters_unchanged(self):
        spin = self.settings.fields['foreground_scale']
        for widget in (spin, spin.lineEdit(), self.settings.resolution_preset):
            before = self.settings.values()
            self.wheel(widget, delta=0, pixels=-25)
            self.assertEqual(self.settings.values(), before)

    def test_keyboard_typing_and_explicit_step_buttons_still_work(self):
        combo = self.settings.fields['background']
        combo.setFocus()
        QTest.keyClick(combo, Qt.Key_Down)
        self.assertEqual(combo.currentIndex(), 1)
        spin = self.settings.fields['foreground_scale']
        spin.setFocus()
        old = spin.value()
        QTest.keyClick(spin, Qt.Key_Up)
        self.assertEqual(spin.value(), old + spin.singleStep())
        spin.lineEdit().selectAll()
        QTest.keyClicks(spin.lineEdit(), '75')
        QTest.keyClick(spin, Qt.Key_Return)
        self.assertEqual(spin.value(), 75)
        plus = next(x for x in spin.parentWidget().findChildren(QPushButton) if x.text() == '+')
        QTest.mouseClick(plus, Qt.LeftButton)
        self.assertEqual(spin.value(), 76)

    def test_all_micro_tabs_use_protected_native_controls(self):
        for tab in range(self.settings.tabs.count()):
            self.settings.tabs.setCurrentIndex(tab)
            self.app.processEvents()
            page = self.settings.tabs.widget(tab)
            for widget in page.findChildren(QComboBox) + page.findChildren(QAbstractSpinBox):
                if not widget.isEnabled(): continue
                before = self.settings.values()
                self.wheel(widget)
                self.assertEqual(self.settings.values(), before, widget.objectName())

    def test_open_dropdown_list_still_scrolls(self):
        combo = self.settings.fields['background']
        for index in range(60): combo.addItem(str(index), str(index))
        combo.setMaxVisibleItems(5)
        combo.showPopup()
        self.app.processEvents()
        view = combo.view()
        before = view.verticalScrollBar().value()
        self.wheel(view.viewport())
        self.assertGreater(view.verticalScrollBar().value(), before)
        combo.hidePopup()

    def test_standalone_controls_also_ignore_wheel_without_changing_focus(self):
        combo = QComboBox()
        combo.addItems(['A', 'B', 'C'])
        combo.show()
        combo.setFocus()
        self.app.processEvents()
        focused = combo.hasFocus()
        self.wheel(combo)
        self.assertEqual(combo.currentIndex(), 0)
        self.assertEqual(combo.hasFocus(), focused)
        combo.close()
        delete(combo)
