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
1. Si no hay perfiles → diálogo tr("Crear tu primer perfil")
2. Si hay perfiles → diálogo selector de atleta (permite crear nuevos con tr("+ Nuevo"))
3. Se abre la ventana principal con el perfil seleccionado
4. Si el usuario pulsa tr("Cambiar atleta") → se cierra la ventana y vuelve al paso 2
"""
import os
import sys

sys.dont_write_bytecode = True

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtCore import Qt

from db.athlete_manager import AthleteManager
from i18n import tr, set_language, get_language
from ui.athlete_dialog import AthleteChooserDialog, NewAthleteDialog
from ui.main_window import MainWindow
from ui.theme import get_stylesheet


def _load_global_language() -> None:
    """Carga el idioma guardado en config global (~/.ciclometricas/language.json)."""
    import json
    lang_file = os.path.join(os.path.expanduser("~"), ".ciclometricas", "language.json")
    if os.path.isfile(lang_file):
        try:
            with open(lang_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            set_language(data.get("language", "es"))
        except Exception:
            set_language("es")


def _save_global_language(lang: str) -> None:
    """Guarda el idioma elegido en config global."""
    import json
    base_dir = os.path.join(os.path.expanduser("~"), ".ciclometricas")
    os.makedirs(base_dir, exist_ok=True)
    lang_file = os.path.join(base_dir, "language.json")
    with open(lang_file, "w", encoding="utf-8") as f:
        json.dump({"language": lang}, f)


def _ask_language() -> str:
    """Diálogo de selección de idioma (primer arranque)."""
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
    dlg = QDialog()
    dlg.setWindowTitle(tr("Ciclométricas"))
    dlg.setFixedSize(340, 200)
    lay = QVBoxLayout(dlg)
    lay.setSpacing(16)
    lbl = QLabel(tr("Selecciona idioma / Select language"))
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet("font-size: 16px; font-weight: bold;")
    lay.addWidget(lbl)
    btn_es = QPushButton(tr("🇪🇸  Español"))
    btn_es.setFixedHeight(40)
    btn_es.clicked.connect(lambda: (dlg.setProperty("_lang", "es"), dlg.accept()))
    lay.addWidget(btn_es)
    btn_en = QPushButton("🇬🇧  English")
    btn_en.setFixedHeight(40)
    btn_en.clicked.connect(lambda: (dlg.setProperty("_lang", "en"), dlg.accept()))
    lay.addWidget(btn_en)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.property("_lang") or "es"
    return "es"


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(tr("Ciclométricas"))
    app.setApplicationVersion("0.2.0")

    # Icono de la aplicación (ciclista)
    icon_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "assets", "icon.png",
    )
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Paleta oscura a nivel de app (elimina flash blanco antes del CSS)
    from PySide6.QtGui import QPalette, QColor
    from ui.theme import COLORS
    palette = app.palette()
    dark_bg = QColor(COLORS['bg'])
    palette.setColor(QPalette.ColorRole.Window, dark_bg)
    palette.setColor(QPalette.ColorRole.Base, dark_bg)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS['bg_card']))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS['fg']))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS['fg']))
    app.setPalette(palette)

    # Tema (stylesheet)
    app.setStyleSheet(get_stylesheet())

    # Idioma: cargar o pedir en primer arranque
    _load_global_language()
    import json
    lang_file = os.path.join(os.path.expanduser("~"), ".ciclometricas", "language.json")
    if not os.path.isfile(lang_file):
        lang = _ask_language()
        set_language(lang)
        _save_global_language(lang)

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
        app.processEvents()          # procesar estilos antes de pintar
        window.showMaximized()
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
