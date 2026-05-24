"""Vista de listado de actividades importadas.

Muestra una tabla con todas las actividades, barra de búsqueda,
filtro de periodo, botón de renombrar y borrado.
Al hacer doble-click se abre la vista de detalle completa.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QInputDialog,
)

from db.engine import get_session
from db.models import Activity, ProfileSnapshot
from ui.dialogs import confirmar
from ui.widgets.manual_session_dialog import ManualSessionDialog
from ui.theme import (
    COLORS, FONT_SIZE_BASE, FONT_SIZE_SM, FONT_SIZE_LG, FONT_SIZE_TITLE,
    FONT_SIZE_XS, FONT_SIZE_XL, ICON_MD, ICON_LG,
)


def _fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return "\u2014"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def _fmt_date(dt: datetime | None) -> str:
    if not dt:
        return "\u2014"
    return dt.strftime("%d/%m/%Y  %H:%M")


def _fmt_date_short(dt: datetime | None) -> str:
    if not dt:
        return "\u2014"
    day = dt.strftime("%d").lstrip("0")
    months = ["ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "sep", "oct", "nov", "dic"]
    month = months[dt.month - 1]
    return f"{day} {month}\n{dt.year}"


def _fmt_float(val: float | None, decimals: int = 1) -> str:
    if val is None:
        return "\u2014"
    return f"{val:.{decimals}f}"


def _fmt_int(val: int | float | None) -> str:
    if val is None:
        return "\u2014"
    return str(round(val))


# Periodos de filtro
PERIOD_OPTIONS = [
    ("Últimos 30 días", 30),
    ("Últimos 60 días", 60),
    ("Últimos 90 días", 90),
    ("Últimos 6 meses", 180),
    ("Último año", 365),
    ("Todo", 0),
]


class ActivitiesView(QWidget):
    """Vista listado de actividades."""

    # Signal emitido cuando se quiere abrir detalle de actividad
    open_detail = Signal(int)  # activity.id

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        # Título
        title = QLabel("Entrenamientos")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_TITLE}; font-weight: bold; color: {COLORS['fg']};"
        )
        layout.addWidget(title)

        # Contador
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg_muted']};")
        layout.addWidget(self.count_label)

        # Barra de filtros: búsqueda + periodo
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(14)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar por nombre, archivo o deporte...")
        self._search.setMinimumWidth(300)
        self._search.setFixedHeight(38)
        self._search.textChanged.connect(self._apply_filters)
        filter_bar.addWidget(self._search)

        # Botón sesión manual
        self._manual_btn = QPushButton("➕  Sesión manual")
        self._manual_btn.setFixedHeight(38)
        self._manual_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manual_btn.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; font-weight: 600; "
            f"background: {COLORS['primary']}; color: #fff; "
            f"border: none; border-radius: 8px; padding: 0 16px;"
        )
        self._manual_btn.clicked.connect(self._open_manual_dialog)
        filter_bar.addWidget(self._manual_btn)

        filter_bar.addStretch()

        self._period_combo = QComboBox()
        self._period_combo.setFixedHeight(38)
        self._period_combo.setMinimumWidth(180)
        for label, _days in PERIOD_OPTIONS:
            self._period_combo.addItem(label)
        self._period_combo.setCurrentIndex(2)  # "Últimos 90 días"
        self._period_combo.currentIndexChanged.connect(self._apply_filters)
        filter_bar.addWidget(self._period_combo)

        layout.addLayout(filter_bar)

        # Tabla  —  12 columnas: 0..9 datos, 10 renombrar, 11 eliminar
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._on_double_click)

        columns = [
            "Fecha", "Nombre", "Duración", "Dist\n(km)",
            "Pot\nmedia", "NP", "IF", "TSS",
            "FC\nmedia", "FC\nmáx", "", "",
        ]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        # Anchos de columna
        header = self.table.horizontalHeader()
        # Fecha
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 72)
        # Nombre — se estira para llenar el espacio sobrante
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # Duración
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 78)
        # Columnas numéricas — ResizeToContents para que Qt ajuste al texto
        for i in range(3, 10):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        # Acciones (renombrar + eliminar)
        header.setSectionResizeMode(10, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(10, 40)
        header.setSectionResizeMode(11, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(11, 40)

        # Alinear cabeceras numéricas al centro
        for i in range(3, 10):
            hi = self.table.horizontalHeaderItem(i)
            if hi:
                hi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.table, stretch=1)

        # Cargar datos
        self._all_activities: List[Activity] = []
        self._filtered: List[Activity] = []
        self.refresh()

    def show_all(self) -> None:
        """Cambia el filtro de periodo a 'Todo' y refresca."""
        todo_idx = next(
            (i for i, (_, days) in enumerate(PERIOD_OPTIONS) if days == 0), len(PERIOD_OPTIONS) - 1
        )
        self._period_combo.setCurrentIndex(todo_idx)
        # setCurrentIndex ya dispara _apply_filters via currentIndexChanged

    def refresh(self) -> None:
        """Recarga la lista de actividades desde la DB."""
        session = get_session()
        try:
            self._all_activities = (
                session.query(Activity)
                .order_by(Activity.started_at.desc())
                .all()
            )
            session.expunge_all()
        finally:
            session.close()
        self._apply_filters()

    def _apply_filters(self, *_args) -> None:
        """Filtra actividades por periodo y texto de búsqueda."""
        idx = self._period_combo.currentIndex()
        _label, days = PERIOD_OPTIONS[idx]
        if days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            activities = [
                a for a in self._all_activities
                if a.started_at and a.started_at.replace(tzinfo=timezone.utc) >= cutoff
            ]
        else:
            activities = list(self._all_activities)

        query = self._search.text().strip().lower()
        if query:
            activities = [
                a for a in activities
                if query in (a.display_name or "").lower()
                or query in (a.file_name or "").lower()
                or query in (a.sport or "").lower()
            ]

        self._filtered = activities
        self.count_label.setText(f"{len(activities)} actividades en el periodo seleccionado.")
        self._populate_table()

    def _populate_table(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._filtered))

        # Estilo compacto para botones dentro de la tabla (sin padding grande del QSS global)
        _ACTION_BTN_STYLE = (
            f"QPushButton {{ background: transparent; color: {COLORS['fg_muted']}; "
            f"border: none; padding: 2px; font-size: 16px; }}"
            f"QPushButton:hover {{ background: {COLORS['bg_hover']}; color: {COLORS['fg']}; "
            f"border-radius: 4px; }}"
        )

        for row, act in enumerate(self._filtered):
            self.table.setRowHeight(row, 40)

            self.table.setItem(row, 0, _SortableItem(_fmt_date_short(act.started_at), act.started_at))

            name_item = QTableWidgetItem(act.display_name or "")
            name_item.setData(Qt.ItemDataRole.UserRole, act.id)
            self.table.setItem(row, 1, name_item)

            self.table.setItem(row, 2, _CenterItem(_fmt_duration(act.moving_time_sec or act.duration_sec)))
            self.table.setItem(row, 3, _NumItem(_fmt_float(act.distance_km), act.distance_km))
            self.table.setItem(row, 4, _NumItem(_fmt_int(act.avg_power), act.avg_power))
            self.table.setItem(row, 5, _NumItem(_fmt_int(act.normalized_power), act.normalized_power))
            self.table.setItem(row, 6, _NumItem(_fmt_float(act.intensity_factor, 2), act.intensity_factor))
            self.table.setItem(row, 7, _NumItem(_fmt_int(act.tss), act.tss))
            self.table.setItem(row, 8, _NumItem(_fmt_int(act.avg_hr), act.avg_hr))
            self.table.setItem(row, 9, _NumItem(_fmt_int(act.max_hr), act.max_hr))

            # Botón renombrar (lápiz)  —  estilo inline para evitar el padding QSS global
            rename_btn = QPushButton("✏")
            rename_btn.setFixedSize(36, 34)
            rename_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            rename_btn.setToolTip("Renombrar actividad")
            rename_btn.setStyleSheet(_ACTION_BTN_STYLE)
            rename_btn.clicked.connect(lambda checked=False, aid=act.id: self.rename_activity(aid))
            self.table.setCellWidget(row, 10, rename_btn)

            # Botón borrar
            del_btn = QPushButton("✖")
            del_btn.setFixedSize(36, 34)
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setToolTip("Eliminar actividad")
            del_btn.setStyleSheet(_ACTION_BTN_STYLE)
            del_btn.clicked.connect(lambda checked=False, aid=act.id: self._delete_activity(aid))
            self.table.setCellWidget(row, 11, del_btn)

        self.table.setSortingEnabled(True)

    def _on_double_click(self, index) -> None:
        """Abre el detalle al hacer doble-click en una fila."""
        row = index.row()
        if 0 <= row < len(self._filtered):
            act = self._filtered[row]
            self.open_detail.emit(act.id)

    def rename_activity(self, activity_id: int) -> None:
        """Abre diálogo para renombrar una actividad."""
        session = get_session()
        try:
            act = session.query(Activity).get(activity_id)
            if not act:
                return
            current_name = act.display_name
            new_name, ok = QInputDialog.getText(
                self, "Renombrar actividad",
                "Nuevo nombre:",
                text=current_name,
            )
            if ok and new_name.strip():
                act.custom_name = new_name.strip()[:120]
                session.commit()
                self.refresh()
        finally:
            session.close()

    def _open_manual_dialog(self) -> None:
        """Abre el diálogo de sesión manual y guarda la actividad."""
        # Get current FTP from latest snapshot
        session = get_session()
        try:
            snap = (
                session.query(ProfileSnapshot)
                .order_by(ProfileSnapshot.effective_at.desc())
                .first()
            )
            ftp = snap.ftp if snap else 0
        finally:
            session.close()

        dlg = ManualSessionDialog(ftp=ftp, parent=self)
        if dlg.exec() != ManualSessionDialog.DialogCode.Accepted:
            return

        data = dlg.get_result()
        if not data:
            return

        session = get_session()
        try:
            act = Activity(**data)
            session.add(act)
            session.commit()
        finally:
            session.close()

        self.refresh()

    def _delete_activity(self, activity_id: int) -> None:
        """Elimina una actividad tras confirmación."""
        if not confirmar(
            self,
            "Eliminar actividad",
            "¿Estás seguro de que quieres eliminar esta actividad?\n"
            "Esta acción no se puede deshacer.",
        ):
            return

        session = get_session()
        try:
            act = session.query(Activity).get(activity_id)
            if act:
                session.delete(act)
                session.commit()
        finally:
            session.close()
        self.refresh()


# ---- Items personalizados para ordenación ----

class _SortableItem(QTableWidgetItem):
    def __init__(self, text: str, sort_key):
        super().__init__(text)
        self._sort_key = sort_key

    def __lt__(self, other):
        if isinstance(other, _SortableItem):
            if self._sort_key is None:
                return True
            if other._sort_key is None:
                return False
            return self._sort_key < other._sort_key
        return super().__lt__(other)


class _CenterItem(QTableWidgetItem):
    """Item centrado para duración y similares."""
    def __init__(self, text: str):
        super().__init__(text)
        self.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)


class _NumItem(QTableWidgetItem):
    """Item numérico centrado y ordenable."""
    def __init__(self, text: str, value: float | None):
        super().__init__(text)
        self._value = value
        self.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other):
        if isinstance(other, _NumItem):
            a = self._value if self._value is not None else -1
            b = other._value if other._value is not None else -1
            return a < b
        return super().__lt__(other)
