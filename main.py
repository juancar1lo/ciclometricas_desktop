"""
Ciclométricas Desktop — Entry point.
Copyright (C) 2025-2026 Juan Carlos López San Joaquín

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

Flujo de arranque:
1. Si no hay perfiles → diálogo "Crear tu primer perfil"
2. Si hay perfiles → diálogo selector de atleta (permite crear nuevos con "+ Nuevo")
3. Se abre la ventana principal con el perfil seleccionado
4. Si el usuario pulsa "Cambiar atleta" → se cierra la ventana y vuelve al paso 2
"""
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtCore import Qt

from db.athlete_manager import AthleteManager
from ui.athlete_dialog import AthleteChooserDialog, NewAthleteDialog
from ui.main_window import MainWindow
from ui.theme import get_stylesheet


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Ciclométricas")
    app.setApplicationVersion("0.1.0")

    # Icono de la aplicación (ciclista)
    icon_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "assets", "icon.png",
    )
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Aplicar tema oscuro
    app.setStyleSheet(get_stylesheet())

    manager = AthleteManager()

    while True:
        profile_name = _choose_profile(manager)

        if profile_name is None:
            # El usuario canceló → salir
            break

        # Abrir perfil e inicializar DB
        profile = manager.open_profile(profile_name)

        # Crear y mostrar la ventana principal
        window = MainWindow(manager, profile)
        window.show()
        app.exec()

        # ¿El usuario pidió cambiar de perfil?
        if getattr(window, "_switch_requested", False):
            # Volver al selector
            continue
        else:
            # Cierre normal
            break

    sys.exit(0)


def _choose_profile(manager: AthleteManager) -> str | None:
    """
    Determina qué perfil abrir según la cantidad de perfiles existentes.
    Devuelve el nombre del perfil o None si el usuario cancela.
    """
    profiles = manager.list_profiles()

    if len(profiles) == 0:
        # Primer arranque — crear perfil
        dlg = NewAthleteDialog(manager)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_name:
            return dlg.result_name
        return None

    # Uno o más perfiles → siempre mostrar selector
    # (permite crear nuevos perfiles y elegir entre los existentes)
    dlg = AthleteChooserDialog(manager)
    if dlg.exec() == QDialog.DialogCode.Accepted and dlg.chosen_name:
        return dlg.chosen_name
    return None


if __name__ == "__main__":
    main()
