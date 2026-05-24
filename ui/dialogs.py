"""Diálogos de confirmación en español.

PySide6 no traduce automáticamente los botones estándar (Yes/No),
así que usamos botones personalizados siempre en español.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def confirmar(parent: QWidget, titulo: str, mensaje: str) -> bool:
    """Muestra un diálogo de confirmación con botones Sí / No en español.

    Devuelve True si el usuario pulsa 'Sí'.
    """
    box = QMessageBox(parent)
    box.setWindowTitle(titulo)
    box.setText(mensaje)
    box.setIcon(QMessageBox.Icon.Question)
    btn_si = box.addButton("Sí", QMessageBox.ButtonRole.YesRole)
    box.addButton("No", QMessageBox.ButtonRole.NoRole)
    box.setDefaultButton(btn_si)
    box.exec()
    return box.clickedButton() == btn_si
