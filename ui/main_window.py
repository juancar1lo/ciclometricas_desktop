"""
Ventana principal de Ciclométricas Desktop.
Sidebar con navegación + área de contenido central (QStackedWidget).

v2 — Tipografía mejorada, foto de perfil en sidebar, iconos grandes.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QFont, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget, QFrame,
)

from db.athlete_manager import AthleteManager, AthleteProfile
from ui.views.dashboard_view import DashboardView
from ui.theme import (
    COLORS, FONT_SIZE_TITLE, FONT_SIZE_LG, FONT_SIZE_MD, FONT_SIZE_BASE,
    FONT_SIZE_SM, FONT_SIZE_XS, ICON_LG, ICON_XL, ICON_HERO,
)
from ui.athlete_dialog import _load_avatar_pixmap, _make_avatar_label
from ui.views.import_view import ImportView
from ui.views.settings_view import SettingsView
from ui.views.activities_view import ActivitiesView
from ui.views.activity_detail_view import ActivityDetailView
from ui.views.summary_view import SummaryView
from ui.views.monotony_view import MonotonyView
from ui.views.readiness_view import ReadinessView
from ui.views.fatigue_resistance_view import FatigueResistanceView
from ui.views.durability_view import DurabilityView
from ui.views.recovery_view import RecoveryView
from ui.views.health_view import HealthView


# Definición de las secciones del sidebar
SECTIONS = [
    {"key": "dashboard",          "label": "Panel",            "icon": "📊"},
    {"key": "summary",            "label": "Resumen",          "icon": "📈"},
    {"key": "monotony",           "label": "Monotonía",        "icon": "❤️"},
    {"key": "race_readiness",     "label": "Preparación",      "icon": "🎯"},
    {"key": "fatigue_resistance", "label": "Res. Fatiga",      "icon": "📉"},
    {"key": "durability",         "label": "Durabilidad",      "icon": "🧪"},
    {"key": "recovery",           "label": "Recuperación",     "icon": "🔋"},
    {"key": "health",             "label": "Salud",            "icon": "❤️‍🩹"},
    {"key": "activities",         "label": "Entrenamientos",   "icon": "📋"},
    {"key": "import",             "label": "Importar archivos","icon": "📥"},
    {"key": "settings",           "label": "Configuración",    "icon": "⚙️"},
]


class MainWindow(QMainWindow):
    """Ventana principal: sidebar (izq) | contenido (der, QStackedWidget)"""

    def __init__(self, manager: AthleteManager, profile: AthleteProfile):
        super().__init__()
        self.manager = manager
        self.profile = profile
        self._sidebar_buttons: dict[str, QPushButton] = {}

        self.setWindowTitle(f"Ciclométricas — {profile.name}")
        self.setMinimumSize(1100, 700)
        self.resize(1360, 860)

        # Icono de ventana (ciclista)
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets", "icon.png",
        )
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Widget central
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- Sidebar ---
        sidebar = self._build_sidebar()
        root_layout.addWidget(sidebar)

        # --- Contenido ---
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root_layout.addWidget(self.stack, stretch=1)

        # Crear placeholders para cada sección
        self._pages: dict[str, QWidget] = {}
        for section in SECTIONS:
            page = self._create_placeholder(section["label"], section["icon"])
            self._pages[section["key"]] = page
            self.stack.addWidget(page)

        # Reemplazar placeholders con vistas reales (Fase 3)
        self._init_real_views()

        # Seleccionar la primera sección
        self._navigate("dashboard")

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setProperty("class", "sidebar")
        sidebar.setFixedWidth(240)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(4)

        # --- Logo + nombre app ---
        header = QHBoxLayout()
        header.setSpacing(12)

        logo_label = QLabel()
        logo_icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets", "icon_32.png",
        )
        if os.path.isfile(logo_icon_path):
            pix = QPixmap(logo_icon_path).scaled(
                32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo_label.setPixmap(pix)
        else:
            logo_label.setText("🚴")
            logo_label.setStyleSheet(f"font-size: {ICON_XL};")
        logo_label.setFixedSize(36, 36)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(logo_label)

        title_block = QVBoxLayout()
        title_block.setSpacing(1)
        app_title = QLabel("Ciclométricas")
        app_title.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: bold; "
            f"color: {COLORS['fg']}; letter-spacing: -0.3px;"
        )
        title_block.addWidget(app_title)
        app_sub = QLabel("Análisis de entrenamientos")
        app_sub.setStyleSheet(f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']};")
        title_block.addWidget(app_sub)
        header.addLayout(title_block)
        header.addStretch()

        layout.addLayout(header)
        layout.addSpacing(20)

        # --- Botones de navegación ---
        for section in SECTIONS:
            btn = QPushButton(f"  {section['icon']}  {section['label']}")
            btn.setProperty("class", "sidebar-item")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(40)
            btn.clicked.connect(lambda checked=False, k=section["key"]: self._navigate(k))
            layout.addWidget(btn)
            self._sidebar_buttons[section["key"]] = btn

        layout.addStretch()

        # --- Perfil activo ---
        sep = QFrame()
        sep.setProperty("class", "separator")
        sep.setFixedHeight(1)
        layout.addWidget(sep)
        layout.addSpacing(10)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(10)

        # Foto de perfil (o emoji fallback)
        avatar_pix = _load_avatar_pixmap(self.profile.name, size=44)
        self._avatar_widget = _make_avatar_label(avatar_pix, size=44, fallback_emoji="🧑\u200d🚀")
        profile_row.addWidget(self._avatar_widget)

        profile_info = QVBoxLayout()
        profile_info.setSpacing(1)
        self.profile_name_label = QLabel(self.profile.name)
        self.profile_name_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BASE}; font-weight: 600; color: {COLORS['fg']};"
        )
        profile_info.addWidget(self.profile_name_label)

        ftp_val = self.profile.config.get('ftp', '?')
        weight_val = self.profile.config.get('weight_kg', '?')
        self.ftp_label = QLabel(f"FTP: {ftp_val} W  ·  {weight_val} kg")
        self.ftp_label.setStyleSheet(f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']};")
        profile_info.addWidget(self.ftp_label)
        profile_row.addLayout(profile_info)
        profile_row.addStretch()

        layout.addLayout(profile_row)
        layout.addSpacing(4)

        # Botón cambiar perfil
        btn_switch = QPushButton("Cambiar atleta")
        btn_switch.setProperty("class", "ghost")
        btn_switch.setFixedHeight(32)
        btn_switch.clicked.connect(self._on_switch_profile)
        layout.addWidget(btn_switch)

        return sidebar

    def _init_real_views(self) -> None:
        """Reemplaza los placeholders con vistas reales implementadas."""
        # Dashboard
        self._dashboard_view = DashboardView(self.profile)
        self._dashboard_view.open_activity.connect(self._open_activity_detail)
        self._dashboard_view.request_import.connect(lambda: self._navigate("import"))
        self.set_view("dashboard", self._dashboard_view)

        self._import_view = ImportView(self.profile)
        self._import_view.import_completed.connect(self._on_import_completed)
        self._import_view.request_show_all.connect(self._on_request_show_all)
        self.set_view("import", self._import_view)

        self._settings_view = SettingsView(self.manager, self.profile)
        self._settings_view.profile_updated.connect(self._on_profile_updated)
        self._settings_view.data_changed.connect(self._on_import_completed)
        self.set_view("settings", self._settings_view)

        self._summary_view = SummaryView()
        self.set_view("summary", self._summary_view)

        self._activities_view = ActivitiesView()
        self._activities_view.open_detail.connect(self._open_activity_detail)
        self.set_view("activities", self._activities_view)

        self._monotony_view = MonotonyView()
        self.set_view("monotony", self._monotony_view)

        self._readiness_view = ReadinessView()
        self.set_view("race_readiness", self._readiness_view)

        self._fatigue_resistance_view = FatigueResistanceView()
        self.set_view("fatigue_resistance", self._fatigue_resistance_view)

        self._durability_view = DurabilityView()
        self.set_view("durability", self._durability_view)

        self._recovery_view = RecoveryView()
        self.set_view("recovery", self._recovery_view)

        self._health_view = HealthView()
        self.set_view("health", self._health_view)

    def _on_import_completed(self) -> None:
        self._activities_view.refresh()
        if hasattr(self, "_dashboard_view"):
            self._dashboard_view.refresh()

    def _on_request_show_all(self) -> None:
        """Tras importar, cambia filtro a 'Todo' para mostrar actividades antiguas."""
        self._activities_view.show_all()

    def _on_profile_updated(self) -> None:
        ftp = self.profile.config.get("ftp", "?")
        weight = self.profile.config.get("weight_kg", "?")
        self.ftp_label.setText(f"FTP: {ftp} W  ·  {weight} kg")

    def _create_placeholder(self, section_name: str, icon: str = "🚧") -> QWidget:
        """Placeholder para secciones aún no implementadas."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        emoji = QLabel(icon)
        emoji.setStyleSheet(f"font-size: {ICON_HERO};")
        emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(emoji)

        label = QLabel(section_name)
        label.setStyleSheet(
            f"font-size: {FONT_SIZE_TITLE}; font-weight: bold; color: {COLORS['fg']};"
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(label)

        sub = QLabel("Esta sección se implementará en las próximas fases.")
        sub.setStyleSheet(f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg_muted']};")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)

        return page

    def _navigate(self, key: str) -> None:
        for k, btn in self._sidebar_buttons.items():
            if k == key:
                btn.setProperty("class", "sidebar-item-active")
            else:
                btn.setProperty("class", "sidebar-item")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if key in self._pages:
            self.stack.setCurrentWidget(self._pages[key])
            # Refresh dinámico al navegar
            if key == "dashboard" and hasattr(self, "_dashboard_view"):
                self._dashboard_view.refresh()
            elif key == "summary" and hasattr(self, "_summary_view"):
                self._summary_view.refresh()
            elif key == "activities" and hasattr(self, "_activities_view"):
                self._activities_view.refresh()
            elif key == "monotony" and hasattr(self, "_monotony_view"):
                self._monotony_view.refresh()
            elif key == "race_readiness" and hasattr(self, "_readiness_view"):
                self._readiness_view.refresh()
            elif key == "fatigue_resistance" and hasattr(self, "_fatigue_resistance_view"):
                self._fatigue_resistance_view.refresh()
            elif key == "durability" and hasattr(self, "_durability_view"):
                self._durability_view.refresh()
            elif key == "recovery" and hasattr(self, "_recovery_view"):
                self._recovery_view.refresh()
            elif key == "health" and hasattr(self, "_health_view"):
                self._health_view.refresh()

    def closeEvent(self, event) -> None:
        """Limpia threads worker (Strava, importación) antes de cerrar."""
        # Detener worker de importación Strava si está activo en SettingsView
        if hasattr(self, "_settings_view") and self._settings_view is not None:
            sv = self._settings_view
            # Cancelar hilo de importación (threading.Thread)
            if hasattr(sv, "_import_state") and sv._import_state is not None:
                sv._import_state["cancelled"] = True
            if hasattr(sv, "_import_timer") and sv._import_timer is not None:
                sv._import_timer.stop()
                sv._import_timer = None
            if hasattr(sv, "_import_thread") and sv._import_thread is not None:
                sv._import_thread.join(timeout=3)
                sv._import_thread = None
        # Detener worker de importación si está activo en ImportView
        if hasattr(self, "_import_view") and self._import_view is not None:
            iv = self._import_view
            if hasattr(iv, "_worker") and iv._worker is not None:
                iv._worker.requestInterruption()
                iv._worker.quit()
                if not iv._worker.wait(3000):
                    iv._worker.terminate()
                    iv._worker.wait(1000)
                iv._worker = None
        # Cerrar conexiones SQLite
        try:
            from db.engine import dispose_engine
            dispose_engine()
        except Exception:
            pass
        super().closeEvent(event)

    def _on_switch_profile(self) -> None:
        self.close()
        self._switch_requested = True

    def _open_activity_detail(self, activity_id: int) -> None:
        """Abre la vista de detalle de una actividad."""
        detail = ActivityDetailView(activity_id)
        detail.go_back.connect(self._back_to_activities)
        detail.request_rename.connect(self._rename_from_detail)
        self.set_view("_activity_detail", detail)
        self.stack.setCurrentWidget(detail)

    def _back_to_activities(self) -> None:
        """Vuelve al listado de actividades."""
        self._activities_view.refresh()
        self._navigate("activities")
        # Limpia la vista de detalle
        if "_activity_detail" in self._pages:
            old = self._pages.pop("_activity_detail")
            self.stack.removeWidget(old)
            old.deleteLater()

    def _rename_from_detail(self, activity_id: int) -> None:
        """Renombra una actividad desde la vista de detalle."""
        self._activities_view.rename_activity(activity_id)
        # Re-abrir detalle con datos frescos
        self._open_activity_detail(activity_id)

    def set_view(self, key: str, widget: QWidget) -> None:
        if key in self._pages:
            old = self._pages[key]
            self.stack.removeWidget(old)
            old.deleteLater()
        self._pages[key] = widget
        self.stack.addWidget(widget)
