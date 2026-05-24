"""Vista de importación de archivos .FIT / .TCX.

Funcionalidad:
- Botón para seleccionar archivos
- Drop zone (drag & drop)
- Barra de progreso
- Tabla de resultados (creado/duplicado/error)
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from db.athlete_manager import AthleteProfile
from services.import_service import ImportResult, import_activity_file
from ui.theme import (
    COLORS, FONT_SIZE_BASE, FONT_SIZE_SM, FONT_SIZE_LG, FONT_SIZE_TITLE,
    FONT_SIZE_XS, ICON_LG, ICON_XL, ICON_MD,
)


# ---- Worker thread para no bloquear la UI ----

class _ImportWorker(QThread):
    """Hilo que importa archivos uno a uno y emite señales de progreso."""
    progress = Signal(int, object)   # (indice, ImportResult)
    finished_all = Signal(list)      # lista de ImportResult

    def __init__(self, paths: List[Path], ftp: int, hr_max: int, weight_kg: float, hr_lthr: int | None = None):
        super().__init__()
        self.paths = paths
        self.ftp = ftp
        self.hr_max = hr_max
        self.hr_lthr = hr_lthr
        self.weight_kg = weight_kg

    def run(self) -> None:
        results: list[ImportResult] = []
        for i, path in enumerate(self.paths):
            result = import_activity_file(
                path, ftp=self.ftp, hr_max=self.hr_max, hr_lthr=self.hr_lthr, weight_kg=self.weight_kg
            )
            results.append(result)
            self.progress.emit(i, result)
        self.finished_all.emit(results)


# ---- Vista principal ----

class ImportView(QWidget):
    """Vista de importación de archivos de actividad."""

    import_completed = Signal()      # Señal cuando se completa la importación
    request_show_all = Signal()       # Pide a la vista de actividades cambiar filtro a "Todo"

    def __init__(self, profile: AthleteProfile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self._worker: _ImportWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        # Título
        title = QLabel("\U0001F4E5  Importar archivos")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_TITLE}; font-weight: bold; color: {COLORS['fg']};"
        )
        layout.addWidget(title)

        desc = QLabel("Selecciona archivos .FIT o .TCX exportados de tu ciclocomputador o Strava.")
        desc.setStyleSheet(f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg_muted']};")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Drop zone
        self.drop_zone = _DropZone()
        self.drop_zone.files_dropped.connect(self._on_files_selected)
        layout.addWidget(self.drop_zone)

        # Botón seleccionar
        btn_row = QHBoxLayout()
        self.btn_select = QPushButton("\U0001F4C2  Seleccionar archivos")
        self.btn_select.setFixedHeight(44)
        self.btn_select.setMinimumWidth(220)
        self.btn_select.setStyleSheet(f"font-size: {FONT_SIZE_BASE};")
        self.btn_select.clicked.connect(self._open_file_dialog)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_select)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Barra de progreso (oculta inicialmente)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(22)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        # Área de resultados
        self.results_area = QScrollArea()
        self.results_area.setWidgetResizable(True)
        self.results_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(8)
        self.results_layout.addStretch()
        self.results_area.setWidget(self.results_container)
        layout.addWidget(self.results_area, stretch=1)

    def _open_file_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar archivos de actividad",
            str(Path.home()),
            "Archivos de actividad (*.fit *.tcx *.FIT *.TCX);;Todos los archivos (*)",
        )
        if files:
            self._on_files_selected([Path(f) for f in files])

    def _on_files_selected(self, paths: List[Path]) -> None:
        if self._worker and self._worker.isRunning():
            return  # Ya hay importación en curso

        # Limpiar resultados previos
        while self.results_layout.count() > 1:  # Mantener el stretch
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.progress_bar.setMaximum(len(paths))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress_label.setText(f"Importando 0/{len(paths)}...")
        self.btn_select.setEnabled(False)

        config = self.profile.config
        self._worker = _ImportWorker(
            paths,
            ftp=config.get("ftp", 200),
            hr_max=config.get("hr_max", 185),
            weight_kg=config.get("weight_kg", 70.0),
            hr_lthr=config.get("hr_lthr"),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, index: int, result: ImportResult) -> None:
        self.progress_bar.setValue(index + 1)
        total = self.progress_bar.maximum()
        self.progress_label.setText(f"Importando {index + 1}/{total}...")

        # Añadir resultado a la lista
        row = _ResultRow(result)
        # Insertar antes del stretch
        self.results_layout.insertWidget(self.results_layout.count() - 1, row)

    def _on_finished(self, results: List[ImportResult]) -> None:
        self.btn_select.setEnabled(True)
        created = sum(1 for r in results if r.status == "created")
        dupes = sum(1 for r in results if r.status == "duplicate")
        errors = sum(1 for r in results if r.status == "error")

        parts = []
        if created:
            parts.append(f"\u2705 {created} importado{'s' if created > 1 else ''}")
        if dupes:
            parts.append(f"\u26a0\ufe0f {dupes} duplicado{'s' if dupes > 1 else ''}")
        if errors:
            parts.append(f"\u274c {errors} error{'es' if errors > 1 else ''}")

        self.progress_label.setText("  ·  ".join(parts))
        self._worker = None

        if created > 0:
            self.import_completed.emit()
            # Si alguna actividad importada es antigua (> 90 días), pedir
            # que la vista de actividades cambie el filtro a "Todo" para que
            # el usuario las vea de inmediato.
            self.request_show_all.emit()


# ---- Componentes auxiliares ----

class _DropZone(QFrame):
    """Zona de drop para arrastrar archivos."""
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)
        self.setMaximumHeight(170)
        self._set_normal_style()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("\U0001F4C1")
        icon.setStyleSheet(f"font-size: {ICON_XL}; background: transparent;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        text = QLabel("Arrastra archivos .FIT o .TCX aquí")
        text.setStyleSheet(f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg_muted']}; background: transparent;")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text)

    def _set_normal_style(self):
        self.setStyleSheet(
            f"background-color: {COLORS['bg_secondary']}; "
            f"border: 2px dashed {COLORS['border']}; "
            f"border-radius: 10px;"
        )

    def _set_hover_style(self):
        self.setStyleSheet(
            f"background-color: {COLORS['primary_dim']}; "
            f"border: 2px dashed {COLORS['primary']}; "
            f"border-radius: 10px;"
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_hover_style()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """Necesario para que Windows procese correctamente el drop."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_normal_style()

    def dropEvent(self, event):
        self._set_normal_style()
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        event.acceptProposedAction()
        urls = event.mimeData().urls()
        paths = []
        for url in urls:
            local = url.toLocalFile()
            if not local:
                continue
            p = Path(local)
            if p.suffix.lower() in (".fit", ".tcx", ".xml"):
                paths.append(p)
        if paths:
            self.files_dropped.emit(paths)


class _ResultRow(QFrame):
    """Fila de resultado de importación."""

    STATUS_STYLES = {
        "created":   ("\u2705", COLORS["success"]),
        "duplicate": ("\u26a0\ufe0f", COLORS["warning"]),
        "error":     ("\u274c", COLORS["destructive"]),
    }

    def __init__(self, result: ImportResult, parent=None):
        super().__init__(parent)
        icon, color = self.STATUS_STYLES.get(result.status, ("\u2753", COLORS["fg_muted"]))

        self.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; "
            f"border-left: 3px solid {color}; "
            f"border-radius: 6px; padding: 10px 14px;"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        ico = QLabel(icon)
        ico.setStyleSheet(f"font-size: {ICON_MD}; background: transparent;")
        layout.addWidget(ico)

        name = QLabel(result.file_name)
        name.setStyleSheet(
            f"font-size: {FONT_SIZE_BASE}; font-weight: 600; "
            f"color: {COLORS['fg']}; background: transparent;"
        )
        layout.addWidget(name)

        msg = QLabel(result.message)
        msg.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        layout.addWidget(msg, stretch=1)
