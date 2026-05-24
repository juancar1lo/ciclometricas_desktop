"""
Diálogos para selección y creación de perfiles de atleta.
- AthleteChooserDialog: se muestra al arrancar si hay >1 perfil
- NewAthleteDialog: wizard para crear un perfil nuevo (con foto opcional)

v2 — Tipografía mejorada, foto de perfil, mejor jerarquía visual.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from db.athlete_manager import AthleteManager, DATA_DIR
from ui.dialogs import confirmar
from ui.theme import COLORS, FONT_SIZE_TITLE, FONT_SIZE_LG, FONT_SIZE_BASE, FONT_SIZE_SM, ICON_XL

PHOTO_FILENAME = "avatar.png"


def _get_photo_path(profile_name: str) -> Path:
    """Devuelve la ruta a la foto de perfil de un atleta."""
    return DATA_DIR / profile_name / PHOTO_FILENAME


def _load_avatar_pixmap(profile_name: str, size: int = 64) -> QPixmap | None:
    """Carga la foto de perfil como QPixmap circular, o None si no existe."""
    path = _get_photo_path(profile_name)
    if not path.exists():
        return None
    pix = QPixmap(str(path))
    if pix.isNull():
        return None
    # Escalar manteniendo aspecto y recortar a cuadrado
    pix = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                     Qt.TransformationMode.SmoothTransformation)
    # Centrar recorte
    if pix.width() > size or pix.height() > size:
        x = (pix.width() - size) // 2
        y = (pix.height() - size) // 2
        pix = pix.copy(x, y, size, size)
    return pix


def _make_avatar_label(pixmap: QPixmap | None, size: int = 64, fallback_emoji: str = "🧑\u200d🚀") -> QLabel:
    """Crea un QLabel con la foto (circular con máscara CSS) o un emoji grande."""
    label = QLabel()
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if pixmap:
        label.setPixmap(pixmap)
        label.setStyleSheet(
            f"border-radius: {size // 2}px; "
            f"border: 2px solid {COLORS['primary']}; "
            f"background: transparent;"
        )
        label.setScaledContents(False)
    else:
        fs = size // 2
        label.setText(fallback_emoji)
        label.setStyleSheet(
            f"font-size: {fs}px; "
            f"background-color: {COLORS['bg_secondary']}; "
            f"border-radius: {size // 2}px; "
            f"border: 2px solid {COLORS['border']};"
        )
    return label


# ---------------------------------------------------------------------------
# Diálogo: Crear nuevo atleta
# ---------------------------------------------------------------------------
class NewAthleteDialog(QDialog):
    """Wizard para crear un perfil de atleta con foto opcional."""

    def __init__(self, manager: AthleteManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Nuevo perfil de atleta")
        self.setMinimumWidth(460)
        self._result_name: str | None = None
        self._photo_path: Path | None = None  # ruta temporal de la foto seleccionada

        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(28, 24, 28, 24)

        # Título
        title = QLabel("🚴  Crear perfil")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_TITLE}; font-weight: bold; "
            f"color: {COLORS['fg']}; letter-spacing: -0.3px;"
        )
        layout.addWidget(title)

        desc = QLabel("Introduce los datos básicos del ciclista. Puedes añadir una foto de perfil.")
        desc.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # --- Foto de perfil ---
        photo_row = QHBoxLayout()
        photo_row.setSpacing(16)
        photo_row.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._avatar_label = _make_avatar_label(None, size=80, fallback_emoji="📷")
        photo_row.addWidget(self._avatar_label)

        photo_btns = QVBoxLayout()
        photo_btns.setSpacing(6)
        btn_photo = QPushButton("🖼️  Subir foto")
        btn_photo.setFixedHeight(34)
        btn_photo.clicked.connect(self._on_select_photo)
        photo_btns.addWidget(btn_photo)

        self.btn_remove_photo = QPushButton("Quitar")
        self.btn_remove_photo.setProperty("class", "ghost")
        self.btn_remove_photo.setFixedHeight(28)
        self.btn_remove_photo.setVisible(False)
        self.btn_remove_photo.clicked.connect(self._on_remove_photo)
        photo_btns.addWidget(self.btn_remove_photo)

        photo_hint = QLabel("JPG o PNG, máx 2 MB")
        photo_hint.setStyleSheet(f"font-size: 10px; color: {COLORS['fg_dim']};")
        photo_btns.addWidget(photo_hint)

        photo_row.addLayout(photo_btns)
        photo_row.addStretch()
        layout.addLayout(photo_row)

        # --- Formulario ---
        form = QFormLayout()
        form.setSpacing(14)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Ej: Carlos, María...")
        self.name_input.setMaxLength(50)
        form.addRow(self._form_label("🆔 Nombre:"), self.name_input)

        self.ftp_input = QSpinBox()
        self.ftp_input.setRange(50, 600)
        self.ftp_input.setValue(200)
        self.ftp_input.setSuffix(" W")
        form.addRow(self._form_label("⚡ FTP:"), self.ftp_input)

        self.weight_input = QDoubleSpinBox()
        self.weight_input.setRange(30.0, 200.0)
        self.weight_input.setValue(70.0)
        self.weight_input.setSuffix(" kg")
        self.weight_input.setDecimals(1)
        form.addRow(self._form_label("🏋️ Peso:"), self.weight_input)

        self.hr_max_input = QSpinBox()
        self.hr_max_input.setRange(100, 230)
        self.hr_max_input.setValue(185)
        self.hr_max_input.setSuffix(" ppm")
        form.addRow(self._form_label("❤️ FC máx:"), self.hr_max_input)

        self.hr_lthr_input = QSpinBox()
        self.hr_lthr_input.setRange(80, 220)
        self.hr_lthr_input.setValue(165)
        self.hr_lthr_input.setSuffix(" ppm")
        self.hr_lthr_input.setToolTip("Frecuencia cardíaca de umbral anaeróbico (LTHR)")
        form.addRow(self._form_label("🫀 FCL:"), self.hr_lthr_input)

        layout.addLayout(form)

        # Botones
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.name_input.setFocus()

    @staticmethod
    def _form_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: {FONT_SIZE_BASE}; font-weight: 600; color: {COLORS['fg']};")
        return lbl

    def _on_select_photo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar foto de perfil",
            str(Path.home()),
            "Imágenes (*.png *.jpg *.jpeg *.bmp *.webp);;Todos (*)",
        )
        if not path:
            return
        p = Path(path)
        if p.stat().st_size > 2 * 1024 * 1024:  # 2 MB
            QMessageBox.warning(self, "Archivo demasiado grande",
                                "La foto no puede superar 2 MB. Elige otra.")
            return

        self._photo_path = p
        pix = QPixmap(str(p)).scaled(80, 80,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        if pix.width() > 80 or pix.height() > 80:
            x = (pix.width() - 80) // 2
            y = (pix.height() - 80) // 2
            pix = pix.copy(x, y, 80, 80)

        self._avatar_label.setPixmap(pix)
        self._avatar_label.setStyleSheet(
            f"border-radius: 40px; border: 2px solid {COLORS['primary']}; background: transparent;"
        )
        self._avatar_label.setText("")
        self.btn_remove_photo.setVisible(True)

    def _on_remove_photo(self) -> None:
        self._photo_path = None
        self._avatar_label.setPixmap(QPixmap())  # limpiar
        self._avatar_label.setText("📷")
        self._avatar_label.setStyleSheet(
            f"font-size: 40px; background-color: {COLORS['bg_secondary']}; "
            f"border-radius: 40px; border: 2px solid {COLORS['border']};"
        )
        self.btn_remove_photo.setVisible(False)

    def _on_accept(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "El nombre no puede estar vacío.")
            return
        try:
            self.manager.create_profile(
                name=name,
                ftp=self.ftp_input.value(),
                weight_kg=self.weight_input.value(),
                hr_max=self.hr_max_input.value(),
                hr_lthr=self.hr_lthr_input.value(),
            )
            # Copiar foto al directorio del perfil
            if self._photo_path and self._photo_path.exists():
                dest = _get_photo_path(name)
                shutil.copy2(str(self._photo_path), str(dest))

            self._result_name = name
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))

    @property
    def result_name(self) -> str | None:
        return self._result_name


# ---------------------------------------------------------------------------
# Diálogo: Selector de atleta
# ---------------------------------------------------------------------------
class AthleteChooserDialog(QDialog):
    """Selector de perfiles al arrancar (si hay >1 perfil)."""

    def __init__(self, manager: AthleteManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Ciclométricas — Elegir atleta")
        self.setMinimumSize(480, 440)
        self._chosen_name: str | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(28, 24, 28, 24)

        # Título grande
        title = QLabel("🚴  Ciclométricas")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_TITLE}; font-weight: bold; "
            f"color: {COLORS['fg']}; letter-spacing: -0.3px;"
        )
        layout.addWidget(title)

        subtitle = QLabel("Selecciona un perfil de atleta para continuar.")
        subtitle.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        layout.addWidget(subtitle)

        # Lista de perfiles
        self.profile_list = QListWidget()
        self.profile_list.setAlternatingRowColors(True)
        self.profile_list.itemDoubleClicked.connect(self._on_open)
        layout.addWidget(self.profile_list, stretch=1)

        # Botones de acción
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_new = QPushButton("+ Nuevo")
        self.btn_new.setProperty("class", "ghost")
        self.btn_new.setFixedHeight(34)
        self.btn_new.clicked.connect(self._on_new)

        self.btn_delete = QPushButton("Eliminar")
        self.btn_delete.setProperty("class", "destructive")
        self.btn_delete.setFixedHeight(34)
        self.btn_delete.clicked.connect(self._on_delete)

        btn_row.addWidget(self.btn_new)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_delete)
        layout.addLayout(btn_row)

        # Botón principal
        self.btn_open = QPushButton("Abrir")
        self.btn_open.setDefault(True)
        self.btn_open.setFixedHeight(40)
        self.btn_open.clicked.connect(self._on_open)
        layout.addWidget(self.btn_open)

        self._refresh_list()

    def _refresh_list(self) -> None:
        self.profile_list.clear()
        profiles = self.manager.list_profiles()
        last = self.manager.last_open
        for name in profiles:
            item = QListWidgetItem(name)
            self.profile_list.addItem(item)
            if name == last:
                self.profile_list.setCurrentItem(item)

        has_profiles = len(profiles) > 0
        self.btn_open.setEnabled(has_profiles)
        self.btn_delete.setEnabled(has_profiles)

    def _on_open(self) -> None:
        item = self.profile_list.currentItem()
        if item:
            self._chosen_name = item.text()
            self.accept()

    def _on_new(self) -> None:
        dlg = NewAthleteDialog(self.manager, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_name:
            self._refresh_list()
            for i in range(self.profile_list.count()):
                if self.profile_list.item(i).text() == dlg.result_name:
                    self.profile_list.setCurrentRow(i)
                    break

    def _on_delete(self) -> None:
        item = self.profile_list.currentItem()
        if not item:
            return
        name = item.text()
        if confirmar(
            self,
            "Confirmar eliminación",
            f"¿Eliminar el perfil «{name}» y todos sus datos?\n\nEsta acción no se puede deshacer.",
        ):
            self.manager.delete_profile(name)
            self._refresh_list()

    @property
    def chosen_name(self) -> str | None:
        return self._chosen_name
