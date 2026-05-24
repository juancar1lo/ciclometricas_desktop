"""Vista de configuración con pestañas — réplica fiel de la web.

Pestañas:
  1. Perfil       — FTP, Peso, FC máx, Notas
  2. Zonas Coggan — Selector FTP/CP/mFTP con valores reales
  3. Historial    — Tabla de ProfileSnapshots con borrado
  4. Tests de potencia — Formulario CP model
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import threading

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QProgressDialog, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from db.athlete_manager import AthleteManager, AthleteProfile
from db.engine import get_session
from db.models import Activity, PowerTestSet, ProfileSnapshot
from calc.cp_model import (
    CpModelResult, PowerTestPoint, fit_cp_model,
    estimate_mftp, estimate_vo2max, reliability_from_r2,
)
from ui.dialogs import confirmar
from ui.theme import (
    COLORS, FONT_SIZE_BASE, FONT_SIZE_SM, FONT_SIZE_LG, FONT_SIZE_TITLE,
    FONT_SIZE_XS, FONT_SIZE_MD, FONT_SIZE_XL, ICON_MD, ICON_LG,
)


def _fmt_duration_short(seconds: int) -> str:
    """Formatea duración en M:SS, ej: 60→1:00, 300→5:00, 1200→20:00."""
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def _fmt_date(dt: datetime | None) -> str:
    if not dt:
        return "\u2014"
    return dt.strftime("%d %b %Y, %H:%M")


class SettingsView(QWidget):
    """Vista de configuración con pestañas."""

    profile_updated = Signal()
    data_changed = Signal()      # emitida tras importar desde Strava

    def __init__(self, manager: AthleteManager, profile: AthleteProfile, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.profile = profile

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        # Título
        title = QLabel("\u2699\ufe0f  Configuración")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_TITLE}; font-weight: bold; color: {COLORS['fg']};"
        )
        layout.addWidget(title)
        desc = QLabel("Define tu FTP, peso, FC máx, FCL (umbral) y registra tests de potencia para calcular CP, W\u2032 y VO2max.")
        desc.setStyleSheet(f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg_muted']};")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_profile_tab(), "Perfil")
        self.tabs.addTab(self._build_zones_tab(), "Zonas Coggan")
        self.tabs.addTab(self._build_history_tab(), "Historial")
        self.tabs.addTab(self._build_tests_tab(), "Tests de potencia")
        self.tabs.addTab(self._build_strava_tab(), "Strava")
        layout.addWidget(self.tabs, stretch=1)

        # Worker Strava (persistente para evitar GC)
        self._import_thread: threading.Thread | None = None
        self._import_state: dict | None = None
        self._import_timer: QTimer | None = None

    # ============================================================
    # Tab 1: Perfil
    # ============================================================
    def _build_profile_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(18)

        card = _make_card("\U0001F9D1\u200d\U0001F680  Tus datos actuales",
                          "Cada cambio se guarda con fecha. Así puedes ver cómo evoluciona tu FTP y tu peso.")
        form = QFormLayout()
        form.setSpacing(14)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        config = self.profile.config

        self.ftp_input = QSpinBox()
        self.ftp_input.setRange(50, 600)
        self.ftp_input.setValue(config.get("ftp", 200))
        self.ftp_input.setSuffix(" W")
        form.addRow("\u26a1 FTP (W):", self.ftp_input)

        self.weight_input = QDoubleSpinBox()
        self.weight_input.setRange(30.0, 200.0)
        self.weight_input.setValue(config.get("weight_kg", 70.0))
        self.weight_input.setSuffix(" kg")
        self.weight_input.setDecimals(1)
        form.addRow("\U0001F3CB\ufe0f Peso (kg):", self.weight_input)

        self.hr_max_input = QSpinBox()
        self.hr_max_input.setRange(100, 230)
        self.hr_max_input.setValue(config.get("hr_max", 185))
        self.hr_max_input.setSuffix(" ppm")
        form.addRow("❤️ FC máx (ppm):", self.hr_max_input)

        self.hr_lthr_input = QSpinBox()
        self.hr_lthr_input.setRange(0, 220)
        self.hr_lthr_input.setValue(config.get("hr_lthr", 0))
        self.hr_lthr_input.setSuffix(" ppm")
        self.hr_lthr_input.setSpecialValueText("Opcional — sin dato")
        form.addRow("💓 FCL / LTHR (ppm):", self.hr_lthr_input)

        # W/kg calculado
        self.wkg_label = QLabel()
        self.wkg_label.setStyleSheet(
            f"color: {COLORS['accent']}; font-weight: 600; font-size: {FONT_SIZE_LG};"
        )
        form.addRow("W/kg:", self.wkg_label)
        self._update_wkg()
        self.ftp_input.valueChanged.connect(self._update_wkg)
        self.weight_input.valueChanged.connect(self._update_wkg)

        # Notas
        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("Ej: Test de FTP del 20 de marzo")
        form.addRow("Notas (opcional):", self.notes_input)

        card.layout().addLayout(form)
        layout.addWidget(card)

        # Botón guardar
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("\U0001F4BE  Guardar cambios")
        self.btn_save.setFixedHeight(44)
        self.btn_save.setMinimumWidth(200)
        self.btn_save.clicked.connect(self._on_save_profile)
        btn_row.addWidget(self.btn_save)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()
        return page

    # ============================================================
    # Tab 2: Zonas Coggan
    # ============================================================
    def _build_zones_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(18)

        card = _make_card("\u03a3  Cálculo de zonas Coggan",
                          "Elige a partir de qué umbral se calculan las 7 zonas de potencia. "
                          "Las zonas son siempre porcentajes de la referencia (FTP, CP o mFTP).")

        # Cargar datos de CP si existen
        cp_val, mftp_val = self._get_cp_mftp()
        ftp_val = self.profile.config.get("ftp", 200)
        current_source = self.profile.config.get("zone_source", "ftp")

        # Grid de 3 opciones
        options_row = QHBoxLayout()
        options_row.setSpacing(14)
        self._zone_buttons = {}

        options = [
            ("ftp", "FTP", "Tu Functional Threshold Power configurado", ftp_val),
            ("cp", "CP", "Critical Power del último test", cp_val),
            ("mftp", "mFTP", "FTP modelado (0.96 · CP)", mftp_val),
        ]
        for key, label, desc_text, value in options:
            btn = _ZoneOptionCard(key, label, desc_text, value,
                                  active=(current_source == key),
                                  enabled=(value is not None))
            btn.clicked.connect(lambda checked=False, k=key: self._on_zone_source_changed(k))
            options_row.addWidget(btn)
            self._zone_buttons[key] = btn

        card.layout().addLayout(options_row)

        note = QLabel(
            "Las zonas se recalculan automáticamente en el panel usando la referencia elegida. "
            "El bucketing de actividades antiguas conserva el FTP que tenías cuando las subiste."
        )
        note.setStyleSheet(f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']};")
        note.setWordWrap(True)
        card.layout().addWidget(note)

        layout.addWidget(card)
        layout.addStretch()
        return page

    # ============================================================
    # Tab 3: Historial
    # ============================================================
    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(18)

        card = _make_card("\U0001F559  Historial de tu perfil",
                          "Cada vez que actualizas tu FTP, peso o FC máx se guarda una entrada. "
                          "Puedes eliminar las que ya no sean relevantes.")

        self.history_table = QTableWidget()
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        cols = ["Fecha", "FTP", "Peso", "FC máx", "FCL", "Notas", "", ""]
        self.history_table.setColumnCount(len(cols))
        self.history_table.setHorizontalHeaderLabels(cols)
        hdr = self.history_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)

        card.layout().addWidget(self.history_table)
        layout.addWidget(card, stretch=1)

        self._refresh_history()
        return page

    # ============================================================
    # Tab 4: Tests de potencia
    # ============================================================
    def _build_tests_tab(self) -> QWidget:
        # Contenedor exterior: QScrollArea para que todo sea desplazable
        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(18)

        # Formulario para añadir test
        card_new = _make_card("\U0001F9EA  Nuevo test de potencia",
                              "Introduce tus 3 tests: corto (30s–2min), medio (3–5min) y largo (10–20min). "
                              "Se calculará CP, W\u2032, mFTP y VO2max.")

        # Cada fila es un QWidget con altura mínima fija para evitar colapso
        form_container = QVBoxLayout()
        form_container.setSpacing(14)
        form_container.setContentsMargins(4, 10, 4, 4)

        _LABEL_STYLE = f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg']}; font-weight: 500;"
        _ROW_MIN_H = 44  # altura mínima por fila

        def _make_test_row(label_text: str, dur_range, dur_val, pow_range, pow_val):
            """Crea un QWidget-fila con altura mínima: Label | SpinBox(dur) | SpinBox(pow)."""
            row_widget = QWidget()
            row_widget.setMinimumHeight(_ROW_MIN_H)
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(_LABEL_STYLE)
            lbl.setMinimumWidth(130)
            lbl.setMaximumWidth(160)
            row.addWidget(lbl)
            dur = QSpinBox()
            dur.setRange(*dur_range)
            dur.setValue(dur_val)
            dur.setSuffix(" s")
            dur.setMinimumHeight(36)
            row.addWidget(dur, 1)
            pw = QSpinBox()
            pw.setRange(*pow_range)
            pw.setValue(pow_val)
            pw.setSuffix(" W")
            pw.setMinimumHeight(36)
            row.addWidget(pw, 1)
            return row_widget, dur, pw

        r1, self.short_dur, self.short_power = _make_test_row(
            "Corto (30–120s):", (30, 120), 60, (0, 2500), 0)
        form_container.addWidget(r1)

        r2, self.mid_dur, self.mid_power = _make_test_row(
            "Medio (3–5min):", (180, 300), 300, (0, 2000), 0)
        form_container.addWidget(r2)

        r3, self.long_dur, self.long_power = _make_test_row(
            "Largo (10–20min):", (600, 1200), 1200, (0, 2000), 0)
        form_container.addWidget(r3)

        # Sprint máximo (opcional)
        sprint_widget = QWidget()
        sprint_widget.setMinimumHeight(_ROW_MIN_H)
        row_sprint = QHBoxLayout(sprint_widget)
        row_sprint.setContentsMargins(0, 0, 0, 0)
        row_sprint.setSpacing(12)
        lbl_sprint = QLabel("Sprint máx (opc.):")
        lbl_sprint.setStyleSheet(_LABEL_STYLE)
        lbl_sprint.setMinimumWidth(130)
        lbl_sprint.setMaximumWidth(160)
        row_sprint.addWidget(lbl_sprint)
        self.max_power_input = QSpinBox()
        self.max_power_input.setRange(0, 3000)
        self.max_power_input.setValue(0)
        self.max_power_input.setSuffix(" W")
        self.max_power_input.setSpecialValueText("Opcional — sin dato")
        self.max_power_input.setMinimumHeight(36)
        row_sprint.addWidget(self.max_power_input, 1)
        form_container.addWidget(sprint_widget)

        card_new.layout().addLayout(form_container)

        # Botón
        card_new.layout().addSpacing(14)

        btn_row_add = QHBoxLayout()
        btn_row_add.addStretch()
        self.btn_add_test = QPushButton("  ➕  Calcular y guardar test  ")
        self.btn_add_test.setFixedHeight(44)
        self.btn_add_test.setFixedWidth(280)
        self.btn_add_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_test.clicked.connect(self._on_add_test_safe)
        btn_row_add.addWidget(self.btn_add_test)
        btn_row_add.addStretch()
        card_new.layout().addLayout(btn_row_add)

        card_new.layout().addSpacing(8)

        layout.addWidget(card_new)

        # ── Card "Último modelo" ──
        self.last_model_card = _make_card("📊  Último modelo",
                                           "Resultados del modelo CP más reciente.")
        self.last_model_grid = QVBoxLayout()
        self.last_model_grid.setSpacing(6)
        self.last_model_card.layout().addLayout(self.last_model_grid)
        layout.addWidget(self.last_model_card)

        # ── Tabla de tests existentes (historial completo) ──
        card_list = _make_card("🕘  Historial de tests",
                               "Elimina los tests pasados que ya no quieras conservar para refinar el modelo.")

        self.tests_table = QTableWidget()
        self.tests_table.setAlternatingRowColors(True)
        self.tests_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tests_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tests_table.verticalHeader().setVisible(False)
        self.tests_table.setMinimumHeight(180)
        test_cols = [
            "Fecha", "Corto", "Medio", "Largo", "P máx",
            "CP", "W'", "P5min", "mFTP", "VO2max", "Fiabilidad", "",
        ]
        self.tests_table.setColumnCount(len(test_cols))
        self.tests_table.setHorizontalHeaderLabels(test_cols)
        thdr = self.tests_table.horizontalHeader()
        for i in range(len(test_cols) - 1):
            thdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        thdr.setSectionResizeMode(len(test_cols) - 1, QHeaderView.ResizeMode.Stretch)

        card_list.layout().addWidget(self.tests_table)
        layout.addWidget(card_list)

        # Resultado del último cálculo
        self.result_label = QLabel("")
        self.result_label.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['accent']};")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        # Stretch final para empujar todo arriba
        layout.addStretch()

        scroll.setWidget(page)
        outer_lay.addWidget(scroll)

        self._refresh_tests()
        return outer

    # ============================================================
    # Acciones
    # ============================================================
    def _update_wkg(self) -> None:
        ftp = self.ftp_input.value()
        weight = self.weight_input.value()
        if weight > 0:
            self.wkg_label.setText(f"{ftp / weight:.2f} W/kg")

    def _on_save_profile(self) -> None:
        old_ftp = self.profile.config.get("ftp", 200)
        new_ftp = self.ftp_input.value()
        new_weight = self.weight_input.value()
        new_hr = self.hr_max_input.value()
        new_hr_lthr = self.hr_lthr_input.value() if self.hr_lthr_input.value() > 0 else None
        notes = self.notes_input.text().strip() or None

        # Actualizar config.json
        self.profile.config["ftp"] = new_ftp
        self.profile.config["weight_kg"] = new_weight
        self.profile.config["hr_max"] = new_hr
        self.profile.config["hr_lthr"] = new_hr_lthr
        self.manager.save_config(self.profile)

        # Crear snapshot en DB
        session = get_session()
        try:
            snap = ProfileSnapshot(
                ftp=new_ftp,
                weight_kg=new_weight,
                hr_max=new_hr,
                hr_lthr=new_hr_lthr,
                zone_source=self.profile.config.get("zone_source", "ftp"),
                notes=notes,
            )
            session.add(snap)
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

        self.notes_input.clear()
        self._refresh_history()
        self._refresh_zones_values()
        self.profile_updated.emit()
        QMessageBox.information(self, "Guardado", "Perfil actualizado correctamente.")

    def _on_zone_source_changed(self, source: str) -> None:
        self.profile.config["zone_source"] = source
        self.manager.save_config(self.profile)

        for key, btn in self._zone_buttons.items():
            btn.set_active(key == source)

        self.profile_updated.emit()

    def _on_add_test_safe(self) -> None:
        """Wrapper que captura CUALQUIER excepción y la muestra al usuario.

        PySide6 silencia excepciones en slots conectados a señales,
        así que sin este wrapper el botón parece no hacer nada.
        """
        try:
            self._on_add_test()
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            print(f"[TEST] EXCEPCIÓN NO CAPTURADA:\n{tb}")
            QMessageBox.critical(
                self, "Error inesperado",
                f"Ocurrió un error al calcular/guardar el test:\n\n{exc}\n\n"
                "Revisa la consola (CMD) para más detalles.",
            )

    def _on_add_test(self) -> None:
        sp = self.short_power.value()
        mp = self.mid_power.value()
        lp = self.long_power.value()
        print(f"[TEST] _on_add_test llamado: corto={sp} W, medio={mp} W, largo={lp} W")

        missing = []
        if sp <= 0:
            missing.append("Corto")
        if mp <= 0:
            missing.append("Medio")
        if lp <= 0:
            missing.append("Largo")

        if missing:
            QMessageBox.warning(
                self, "Datos incompletos",
                f"Falta potencia en: {', '.join(missing)}.\n\n"
                "Sube la flecha ▲ del campo o escribe un valor > 0 W."
            )
            return

        sd = self.short_dur.value()
        md = self.mid_dur.value()
        ld = self.long_dur.value()
        max_p = self.max_power_input.value() if self.max_power_input.value() > 0 else None

        # Calcular CP model
        points = [
            PowerTestPoint(duration_sec=sd, power=sp),
            PowerTestPoint(duration_sec=md, power=mp),
            PowerTestPoint(duration_sec=ld, power=lp),
        ]
        model = fit_cp_model(points)

        if not model:
            QMessageBox.warning(self, "Error", "No se pudo calcular el modelo CP. Verifica los datos.")
            return

        weight = self.profile.config.get("weight_kg", 70.0)
        mftp = estimate_mftp(model)
        p5min = model.predict_power(300)
        vo2 = estimate_vo2max(p5min, weight) if p5min and p5min > 0 else None

        print(f"[TEST] CP={model.cp:.0f} W, W'={model.w_prime:.0f} J, "
              f"mFTP={mftp:.0f} W, VO2max={vo2}, R²={model.r_squared:.4f}")

        # Guardar en DB
        session = get_session()
        try:
            test = PowerTestSet(
                short_duration=sd, short_power=sp,
                mid_duration=md, mid_power=mp,
                long_duration=ld, long_power=lp,
                max_power=max_p,
                cp=model.cp, w_prime=model.w_prime,
                p5min=p5min, vo2max=vo2,
                m_ftp=mftp, r_squared=model.r_squared,
            )
            session.add(test)
            session.commit()
            print(f"[TEST] Test guardado OK, id={test.id}")
        except Exception as e:
            session.rollback()
            print(f"[TEST] Error al guardar en DB: {e}")
            QMessageBox.warning(self, "Error", f"Error al guardar: {e}")
            return
        finally:
            session.close()

        # Mostrar resultado
        rel = reliability_from_r2(model.r_squared)
        vo2_str = f"{vo2:.1f}" if vo2 else "—"
        self.result_label.setText(
            f"✅  CP = {model.cp:.0f} W  |  W′ = {model.w_prime / 1000:.1f} kJ  |  "
            f"mFTP = {mftp:.0f} W  |  VO₂max = {vo2_str} ml/kg/min  |  "
            f"R² = {model.r_squared:.4f} ({rel.text})"
        )

        self._refresh_tests()
        self._refresh_zones_values()
        self.profile_updated.emit()
        QMessageBox.information(self, "Test guardado",
            f"Test calculado y guardado correctamente.\n\n"
            f"CP = {model.cp:.0f} W\n"
            f"mFTP = {mftp:.0f} W\n"
            f"R² = {model.r_squared:.4f} ({rel.text})"
        )

    def _on_edit_note(self, snap_id: int, current_note: str | None) -> None:
        """Edita la nota de un snapshot del historial."""
        text, ok = QInputDialog.getText(
            self, "Editar nota", "Nota:",
            QLineEdit.EchoMode.Normal, current_note or "",
        )
        if not ok:
            return
        session = get_session()
        try:
            snap = session.query(ProfileSnapshot).filter_by(id=snap_id).first()
            if snap:
                snap.notes = text.strip() or None
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
        self._refresh_history()

    def _on_delete_snapshot(self, snap_id: int) -> None:
        if not confirmar(self, "Confirmar", "¿Eliminar esta entrada del historial?"):
            return
        session = get_session()
        try:
            snap = session.query(ProfileSnapshot).filter_by(id=snap_id).first()
            if snap:
                session.delete(snap)
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
        self._refresh_history()

    def _on_delete_test(self, test_id: int) -> None:
        if not confirmar(self, "Confirmar", "¿Eliminar este test de potencia?"):
            return
        session = get_session()
        try:
            test = session.query(PowerTestSet).filter_by(id=test_id).first()
            if test:
                session.delete(test)
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
        self._refresh_tests()
        self._refresh_zones_values()

    # ============================================================
    # Refresco de datos
    # ============================================================
    def _refresh_history(self) -> None:
        session = get_session()
        try:
            snaps = session.query(ProfileSnapshot).order_by(ProfileSnapshot.effective_at.desc()).all()
            session.expunge_all()
        except Exception:
            snaps = []
        finally:
            session.close()

        self.history_table.setRowCount(len(snaps))
        is_only = len(snaps) <= 1
        for row, s in enumerate(snaps):
            self.history_table.setItem(row, 0, QTableWidgetItem(_fmt_date(s.effective_at)))
            self.history_table.setItem(row, 1, QTableWidgetItem(f"{s.ftp} W"))
            self.history_table.setItem(row, 2, QTableWidgetItem(f"{s.weight_kg} kg"))
            self.history_table.setItem(row, 3, QTableWidgetItem(f"{s.hr_max} ppm"))
            self.history_table.setItem(row, 4, QTableWidgetItem(
                f"{s.hr_lthr} ppm" if s.hr_lthr else "—"))
            self.history_table.setItem(row, 5, QTableWidgetItem(s.notes or "—"))

            # Botón ✏️ editar nota
            btn_edit = QPushButton("✏️")
            btn_edit.setFixedSize(34, 34)
            btn_edit.setProperty("class", "ghost")
            btn_edit.setToolTip("Editar nota")
            btn_edit.clicked.connect(lambda checked=False, sid=s.id, cur=s.notes: self._on_edit_note(sid, cur))
            self.history_table.setCellWidget(row, 6, btn_edit)

            # Botón 🗑 eliminar (solo si hay más de 1)
            if not is_only:
                btn = QPushButton("\U0001F5D1")
                btn.setFixedSize(34, 34)
                btn.setProperty("class", "ghost")
                btn.setToolTip("Eliminar entrada")
                btn.clicked.connect(lambda checked=False, sid=s.id: self._on_delete_snapshot(sid))
                self.history_table.setCellWidget(row, 7, btn)

    def _refresh_tests(self) -> None:
        session = get_session()
        try:
            tests = session.query(PowerTestSet).order_by(PowerTestSet.tested_at.desc()).all()
            session.expunge_all()
        except Exception:
            tests = []
        finally:
            session.close()

        # ── Último modelo card ──
        self._populate_last_model(tests[0] if tests else None)

        # ── Tabla historial ──
        self.tests_table.setRowCount(len(tests))
        for row, t in enumerate(tests):
            col = 0
            self.tests_table.setItem(row, col, QTableWidgetItem(_fmt_date(t.tested_at))); col += 1
            # Corto / Medio / Largo  →  "M:SS @ XW"
            self.tests_table.setItem(row, col, QTableWidgetItem(
                f"{_fmt_duration_short(t.short_duration)} @ {t.short_power}W")); col += 1
            self.tests_table.setItem(row, col, QTableWidgetItem(
                f"{_fmt_duration_short(t.mid_duration)} @ {t.mid_power}W")); col += 1
            self.tests_table.setItem(row, col, QTableWidgetItem(
                f"{_fmt_duration_short(t.long_duration)} @ {t.long_power}W")); col += 1
            # P máx
            self.tests_table.setItem(row, col, QTableWidgetItem(
                f"{t.max_power} W" if t.max_power else "—")); col += 1
            # CP
            self.tests_table.setItem(row, col, QTableWidgetItem(
                f"{t.cp:.0f}" if t.cp else "—")); col += 1
            # W'
            self.tests_table.setItem(row, col, QTableWidgetItem(
                f"{t.w_prime / 1000:.1f} kJ" if t.w_prime else "—")); col += 1
            # P5min
            self.tests_table.setItem(row, col, QTableWidgetItem(
                f"{t.p5min:.0f}" if t.p5min else "—")); col += 1
            # mFTP
            self.tests_table.setItem(row, col, QTableWidgetItem(
                f"{t.m_ftp:.0f}" if t.m_ftp else "—")); col += 1
            # VO2max
            self.tests_table.setItem(row, col, QTableWidgetItem(
                f"{t.vo2max:.1f}" if t.vo2max else "—")); col += 1
            # Fiabilidad
            if t.r_squared is not None:
                rel = reliability_from_r2(t.r_squared)
                item = QTableWidgetItem(f"{rel.emoji} {rel.text}  R² {t.r_squared:.3f}")
                item.setToolTip(rel.text)
            else:
                item = QTableWidgetItem("—")
            self.tests_table.setItem(row, col, item); col += 1

            btn = QPushButton("🗑")
            btn.setFixedSize(34, 34)
            btn.setProperty("class", "ghost")
            btn.setToolTip("Eliminar test")
            btn.clicked.connect(lambda checked=False, tid=t.id: self._on_delete_test(tid))
            self.tests_table.setCellWidget(row, col, btn)

    # ------------------------------------------------------------------
    def _populate_last_model(self, t: PowerTestSet | None) -> None:
        """Rellena la card 'Último modelo' con los datos del test más reciente."""
        # Limpiar contenido anterior
        while self.last_model_grid.count():
            item = self.last_model_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if t is None:
            lbl = QLabel("Aún no hay tests registrados.")
            lbl.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
            self.last_model_grid.addWidget(lbl)
            self.last_model_card.setVisible(False)
            return

        self.last_model_card.setVisible(True)

        _lbl_style = f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg_muted']};"
        _val_style = f"font-size: {FONT_SIZE_LG}; font-weight: 700; color: {COLORS['fg']};"
        _sep_style = (
            f"background-color: {COLORS['border']}; "
            f"max-height: 1px; min-height: 1px;"
        )

        def _row(label: str, value: str) -> QWidget:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(4, 6, 4, 6)
            l = QLabel(label)
            l.setStyleSheet(_lbl_style)
            v = QLabel(value)
            v.setStyleSheet(_val_style)
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_l.addWidget(l)
            row_l.addStretch()
            row_l.addWidget(v)
            return row_w

        def _sep() -> QFrame:
            s = QFrame()
            s.setStyleSheet(_sep_style)
            s.setFixedHeight(1)
            return s

        rows = [
            ("CP", f"{t.cp:.0f} W" if t.cp else "—"),
            ("W'", f"{t.w_prime / 1000:.1f} kJ" if t.w_prime else "—"),
            ("P5MIN", f"{t.p5min:.0f} W" if t.p5min else "—"),
            ("MFTP", f"{t.m_ftp:.0f} W" if t.m_ftp else "—"),
            ("VO2MAX ESTIMADO", f"{t.vo2max:.2f} ml/kg/min" if t.vo2max else "—"),
            ("P MÁX", f"{t.max_power} W" if t.max_power else "—"),
        ]
        for i, (lbl_text, val_text) in enumerate(rows):
            self.last_model_grid.addWidget(_row(lbl_text, val_text))
            if i < len(rows) - 1:
                self.last_model_grid.addWidget(_sep())

        # Fiabilidad
        self.last_model_grid.addWidget(_sep())
        if t.r_squared is not None:
            rel = reliability_from_r2(t.r_squared)
            fiab_text = f"{rel.emoji}  {rel.text}  R² {t.r_squared:.3f}"
        else:
            fiab_text = "—"
        fiab_row = _row("Fiabilidad", fiab_text)
        self.last_model_grid.addWidget(fiab_row)

        # Fecha
        self.last_model_grid.addWidget(_sep())
        date_lbl = QLabel(_fmt_date(t.tested_at))
        date_lbl.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; padding: 4px;")
        self.last_model_grid.addWidget(date_lbl)

    def _get_cp_mftp(self) -> tuple[Optional[int], Optional[int]]:
        """Obtiene CP y mFTP del último test."""
        session = get_session()
        try:
            last = session.query(PowerTestSet).order_by(PowerTestSet.tested_at.desc()).first()
            if last and last.cp:
                cp = round(last.cp)
                mftp = round(last.m_ftp) if last.m_ftp else round(last.cp * 0.96)
                return cp, mftp
        except Exception:
            pass
        finally:
            session.close()
        return None, None

    # ============================================================
    # Tab 5: Strava
    # ============================================================
    def _build_strava_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        card = _make_card("🔗  Strava",
                          "Vincula tu cuenta de Strava para importar actividades de ciclismo.")

        self._strava_status_container = QVBoxLayout()
        self._strava_status_container.setSpacing(12)
        card.layout().addLayout(self._strava_status_container)

        layout.addWidget(card)
        layout.addStretch()

        self._refresh_strava_status()
        return page

    def _refresh_strava_status(self) -> None:
        while self._strava_status_container.count():
            item = self._strava_status_container.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        strava_data = self.profile.config.get("strava")
        is_connected = strava_data is not None and isinstance(strava_data, dict) and strava_data.get("access_token")

        if is_connected:
            athlete_name = strava_data.get("athlete_name", "Atleta de Strava")
            athlete_id = strava_data.get("athlete_id", "—")

            info_row = QHBoxLayout()
            info_row.setSpacing(12)
            icon_lbl = QLabel("🏃")
            icon_lbl.setStyleSheet(f"font-size: 28px; border: none;")
            info_row.addWidget(icon_lbl)
            info_col = QVBoxLayout()
            name_lbl = QLabel(f"<b>{athlete_name}</b>")
            name_lbl.setStyleSheet(f"font-size: {FONT_SIZE_LG}; color: {COLORS['fg']}; border: none;")
            info_col.addWidget(name_lbl)
            id_lbl = QLabel(f"ID: {athlete_id}")
            id_lbl.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; border: none;")
            info_col.addWidget(id_lbl)
            info_row.addLayout(info_col)
            info_row.addStretch()
            info_widget = QWidget()
            info_widget.setLayout(info_row)
            self._strava_status_container.addWidget(info_widget)

            btn_row = QHBoxLayout()
            btn_import = QPushButton("📥  Importar actividades")
            btn_import.setFixedHeight(38)
            btn_import.clicked.connect(self._on_strava_import)
            btn_row.addWidget(btn_import)
            btn_disconnect = QPushButton("🔌  Desvincular")
            btn_disconnect.setProperty("class", "ghost")
            btn_disconnect.setFixedHeight(38)
            btn_disconnect.clicked.connect(self._on_strava_disconnect)
            btn_row.addWidget(btn_disconnect)
            btn_row.addStretch()
            btn_widget = QWidget()
            btn_widget.setLayout(btn_row)
            self._strava_status_container.addWidget(btn_widget)

            note = QLabel(
                "Las actividades importadas desde Strava aparecerán en tu panel "
                "con todos los datos de potencia, FC y cadencia disponibles.\n"
                "Se detectan duplicados automáticamente (por fecha y duración)."
            )
            note.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; border: none;")
            note.setWordWrap(True)
            self._strava_status_container.addWidget(note)
        else:
            desc = QLabel(
                "Al vincular tu cuenta de Strava, podrás importar tus actividades de ciclismo "
                "con todos los datos de potencia, frecuencia cardíaca y cadencia.\n"
                "La subida manual de archivos .fit/.tcx seguirá disponible."
            )
            desc.setStyleSheet(f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg_muted']}; border: none;")
            desc.setWordWrap(True)
            self._strava_status_container.addWidget(desc)

            btn_connect = QPushButton("🔗  Vincular con Strava")
            btn_connect.setFixedHeight(42)
            btn_connect.setFixedWidth(240)
            btn_connect.clicked.connect(self._on_strava_connect)
            self._strava_status_container.addWidget(btn_connect)

            info = QLabel(
                "Se abrirá tu navegador web para autorizar el acceso.\n"
                "Necesitarás un Client ID y Client Secret de la API de Strava. "
                "Puedes obtenerlos en https://www.strava.com/settings/api"
            )
            info.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_dim']}; border: none;")
            info.setWordWrap(True)
            self._strava_status_container.addWidget(info)

    def _on_strava_connect(self) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        from PySide6.QtCore import QTimer
        import threading
        import webbrowser

        dlg = QDialog(self)
        dlg.setWindowTitle("Vincular con Strava")
        dlg.setMinimumWidth(420)
        dlg_lay = QVBoxLayout(dlg)
        dlg_lay.setSpacing(12)
        dlg_lay.addWidget(QLabel(
            "Introduce tus credenciales de la API de Strava.\n"
            "Puedes obtenerlas en: https://www.strava.com/settings/api\n\n"
            "Authorization Callback Domain: localhost"
        ))
        inp_id = QLineEdit()
        inp_id.setPlaceholderText("Client ID")
        dlg_lay.addWidget(inp_id)
        inp_secret = QLineEdit()
        inp_secret.setPlaceholderText("Client Secret")
        inp_secret.setEchoMode(QLineEdit.EchoMode.Password)
        dlg_lay.addWidget(inp_secret)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        dlg_lay.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        client_id = inp_id.text().strip()
        client_secret = inp_secret.text().strip()
        if not client_id or not client_secret:
            QMessageBox.warning(self, "Faltan datos", "Introduce Client ID y Client Secret.")
            return

        # Abrir el navegador en el hilo principal (Windows COM/OLE lo exige)
        from services.strava_service import get_oauth_url
        oauth_url = get_oauth_url(client_id)
        webbrowser.open(oauth_url)

        # Mostrar diálogo de progreso no bloqueante
        self._oauth_progress = QProgressDialog(
            "Esperando autorización de Strava...\n"
            "Autoriza en el navegador y espera.",
            "Cancelar", 0, 0, self
        )
        self._oauth_progress.setWindowTitle("Vincular con Strava")
        self._oauth_progress.setMinimumWidth(400)
        self._oauth_progress.setWindowModality(Qt.WindowModality.WindowModal)

        # Estado compartido con el hilo nativo de Python (no QThread)
        self._oauth_state = {
            "code": None, "error": None, "done": False,
            "client_id": client_id, "client_secret": client_secret,
        }

        def _bg_wait_for_code():
            """Se ejecuta en threading.Thread — solo espera HTTP callback."""
            try:
                from services.strava_service import wait_for_oauth_code
                code, err = wait_for_oauth_code(timeout=120)
                self._oauth_state["code"] = code
                self._oauth_state["error"] = err
            except Exception as e:
                self._oauth_state["error"] = str(e)
            finally:
                self._oauth_state["done"] = True

        bg_thread = threading.Thread(target=_bg_wait_for_code, daemon=True)
        bg_thread.start()
        self._oauth_bg_thread = bg_thread  # evitar GC

        # QTimer sondea desde el hilo principal (seguro para Qt)
        self._oauth_poll_timer = QTimer()
        self._oauth_poll_timer.setInterval(400)  # cada 400 ms
        self._oauth_poll_timer.timeout.connect(self._poll_oauth_result)
        self._oauth_poll_timer.start()

        # Cancelar → detener servidor HTTP + timer
        self._oauth_progress.canceled.connect(self._cancel_oauth)

    def _cancel_oauth(self) -> None:
        from services.strava_service import cancel_oauth_wait
        cancel_oauth_wait()
        if hasattr(self, '_oauth_poll_timer') and self._oauth_poll_timer:
            self._oauth_poll_timer.stop()
            self._oauth_poll_timer = None
        if hasattr(self, '_oauth_progress') and self._oauth_progress:
            self._oauth_progress.close()
            self._oauth_progress = None

    def _poll_oauth_result(self) -> None:
        """Llamado por QTimer en el hilo principal — comprueba si el hilo nativo terminó."""
        state = getattr(self, '_oauth_state', None)
        if not state or not state["done"]:
            return

        # Parar timer
        if self._oauth_poll_timer:
            self._oauth_poll_timer.stop()
            self._oauth_poll_timer = None

        # Cerrar progreso
        if hasattr(self, '_oauth_progress') and self._oauth_progress:
            self._oauth_progress.close()
            self._oauth_progress = None

        if state["error"]:
            QMessageBox.critical(self, "Error", state["error"])
            return

        code = state["code"]
        client_id = state["client_id"]
        client_secret = state["client_secret"]

        # Intercambiar code por tokens (rápido, ~1s, se hace en el hilo principal)
        from services.strava_service import exchange_code_for_tokens
        tokens, err = exchange_code_for_tokens(client_id, client_secret, code)
        if err:
            QMessageBox.critical(self, "Error", err)
            return

        strava_config = {
            "client_id": client_id,
            "client_secret": client_secret,
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": tokens.expires_at,
            "athlete_name": tokens.athlete_name,
            "athlete_id": tokens.athlete_id,
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }
        self.profile.config["strava"] = strava_config
        self.manager.save_config(self.profile)
        self._refresh_strava_status()
        QMessageBox.information(self, "Strava vinculado",
            f"¡Cuenta vinculada correctamente!\nAtleta: {tokens.athlete_name}")

    def _on_strava_disconnect(self) -> None:
        if not confirmar(self, "Desvincular Strava",
                         "¿Desvincular tu cuenta de Strava?\n"
                         "Las actividades ya importadas se mantendrán."):
            return
        self.profile.config["strava"] = None
        self.manager.save_config(self.profile)
        self._refresh_strava_status()
        QMessageBox.information(self, "Desvinculado", "Cuenta de Strava desvinculada.")

    def _on_strava_import(self) -> None:
        """Importar actividades desde Strava API con threading.Thread + barra de progreso."""
        from services.strava_service import _ensure_valid_token, fetch_activities

        strava_data = self.profile.config.get("strava")
        if not strava_data or not strava_data.get("access_token"):
            QMessageBox.warning(self, "Sin conexión", "Vincula primero tu cuenta de Strava.")
            return

        token, err = _ensure_valid_token(self.profile.config)
        if err:
            QMessageBox.critical(self, "Error de autenticación", err)
            return
        self.manager.save_config(self.profile)

        ftp = self.profile.config.get("ftp", 200)
        hr_max = self.profile.config.get("hr_max", 185)

        # Obtener lista de actividades (bloqueante pero rápido)
        activities, err = fetch_activities(token, per_page=50, max_pages=5)
        if err:
            QMessageBox.critical(self, "Error API Strava", err)
            return
        if not activities:
            QMessageBox.information(self, "Sin actividades",
                "No se encontraron actividades de ciclismo en Strava.")
            return

        # Filtrar ya importadas por strava_activity_id
        session = get_session()
        try:
            existing = session.query(Activity.strava_activity_id).filter(
                Activity.strava_activity_id.isnot(None)
            ).all()
            existing_ids = {r[0] for r in existing if r[0]}
        finally:
            session.close()

        new_acts = [a for a in activities if a.strava_id not in existing_ids]
        if not new_acts:
            QMessageBox.information(self, "Al día",
                f"Todas las {len(activities)} actividades ya están importadas.")
            return

        if not confirmar(self, "Importar desde Strava",
            f"Se encontraron {len(new_acts)} actividades nuevas de ciclismo.\n"
            f"¿Importar ahora?"):
            return

        # ── threading.Thread + QTimer polling (evita deadlocks de QThread) ──
        self._progress_dlg = QProgressDialog(
            "Preparando importación...", "Cancelar", 0, len(new_acts), self
        )
        self._progress_dlg.setWindowTitle("Importando desde Strava")
        self._progress_dlg.setMinimumWidth(400)
        self._progress_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress_dlg.setValue(0)

        hr_lthr = self.profile.config.get("hr_lthr")

        # Estado compartido entre hilo worker y main thread
        self._import_state: dict = {
            "status": "running",      # running | done | error
            "progress": (0, len(new_acts), ""),
            "result": None,           # (imported, errors, skipped)
            "cancelled": False,
        }

        self._progress_dlg.canceled.connect(self._cancel_strava_import)

        self._import_thread = threading.Thread(
            target=_run_strava_import,
            args=(self._import_state, token, new_acts, ftp, hr_max,
                  self.profile.config, hr_lthr),
            daemon=True,
        )
        self._import_thread.start()

        # Sondear progreso cada 100ms desde el hilo principal
        self._import_timer = QTimer()
        self._import_timer.timeout.connect(self._poll_strava_import)
        self._import_timer.start(100)

    def _cancel_strava_import(self) -> None:
        """Marca la importación como cancelada (el worker consultará el flag)."""
        if hasattr(self, '_import_state') and self._import_state:
            self._import_state["cancelled"] = True

    def _poll_strava_import(self) -> None:
        """Sondea el estado del hilo de importación (main thread, vía QTimer)."""
        state = getattr(self, '_import_state', None)
        if state is None:
            if hasattr(self, '_import_timer') and self._import_timer:
                self._import_timer.stop()
            return

        # Actualizar barra de progreso
        cur, total, name = state["progress"]
        if hasattr(self, '_progress_dlg') and self._progress_dlg:
            self._progress_dlg.setValue(cur)
            self._progress_dlg.setLabelText(
                f"Importando {cur}/{total}:\n{name}"
            )

        # ¿Terminó?
        if state["status"] != "running":
            self._import_timer.stop()
            self._import_timer = None

            # Cerrar diálogo de progreso
            if hasattr(self, '_progress_dlg') and self._progress_dlg:
                self._progress_dlg.close()
                self._progress_dlg = None

            # El thread ya terminó (daemon), limpiar refs
            self._import_thread = None
            result = state.get("result", (0, 0, []))
            self._import_state = None

            imported, errors, skipped = result

            parts = []
            if imported:
                parts.append(f"✅ {imported} actividad{'es' if imported > 1 else ''} importada{'s' if imported > 1 else ''}")
            if skipped:
                parts.append(f"⚠️ {len(skipped)} duplicada{'s' if len(skipped) > 1 else ''} (ya existían como .fit/.tcx)")
            if errors:
                parts.append(f"❌ {errors} error{'es' if errors > 1 else ''}")
            if not parts:
                parts.append("No se importaron actividades.")

            QMessageBox.information(self, "Strava — Importación", "\n".join(parts))

            # Diferir el refresco pesado para no bloquear el hilo principal
            QTimer.singleShot(200, self.data_changed.emit)

    def _refresh_zones_values(self) -> None:
        """Actualiza los valores en las tarjetas de zona."""
        if not hasattr(self, '_zone_buttons'):
            return
        ftp_val = self.profile.config.get("ftp", 200)
        cp_val, mftp_val = self._get_cp_mftp()
        self._zone_buttons["ftp"].set_value(ftp_val)
        self._zone_buttons["cp"].set_value(cp_val)
        self._zone_buttons["cp"].setEnabled(cp_val is not None)
        self._zone_buttons["mftp"].set_value(mftp_val)
        self._zone_buttons["mftp"].setEnabled(mftp_val is not None)


# ============================================================
# Componentes auxiliares
# ============================================================

def _make_card(title_text: str, description: str = "") -> QFrame:
    card = QFrame()
    card.setProperty("class", "card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    t = QLabel(title_text)
    t.setStyleSheet(
        f"font-size: {FONT_SIZE_LG}; font-weight: 600; color: {COLORS['fg']};"
    )
    layout.addWidget(t)
    if description:
        d = QLabel(description)
        d.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        d.setWordWrap(True)
        layout.addWidget(d)
    return card


# ═══════════════════════════════════════════════════════════════
# Función worker para importación Strava (ejecutada en threading.Thread)
# ═══════════════════════════════════════════════════════════════

def _run_strava_import(
    state: dict,
    token: str,
    activities: list,
    ftp: int,
    hr_max: int,
    config: dict,
    hr_lthr: int | None = None,
) -> None:
    """Importa actividades de Strava en un hilo secundario (threading.Thread).

    Comunica progreso y resultado al hilo principal mediante el dict *state*.
    """
    from services.strava_service import (
        fetch_activity_streams, stream_to_trackpoints,
    )
    from calc.power import calculate_power_metrics
    from calc.zones import bucket_series, POWER_ZONES, HR_ZONES
    from calc.mmp import compute_mmp
    from db.engine import get_session
    from db.models import Activity, PowerTestSet

    imported = 0
    errors = 0
    skipped: list[str] = []
    total = len(activities)

    try:
        for i, act in enumerate(activities):
            if state.get("cancelled"):
                break

            state["progress"] = (i + 1, total, act.name)

            try:
                streams, err = fetch_activity_streams(token, act.strava_id)
                if err or not streams:
                    print(f"[Strava] Error streams {act.name}: {err}")
                    errors += 1
                    continue

                samples = stream_to_trackpoints(act, streams)
                if not samples:
                    errors += 1
                    continue

                # ── Deduplicación robusta: fecha ±10min + (duración o moving_time) ──
                sess = get_session()
                try:
                    from datetime import timedelta
                    from sqlalchemy import or_
                    _sa = act.started_at
                    if _sa.tzinfo is not None:
                        _sa = _sa.replace(tzinfo=None)
                    t_start = _sa - timedelta(minutes=10)
                    t_end = _sa + timedelta(minutes=10)
                    e_lo = int(act.elapsed_time * 0.80)
                    e_hi = int(act.elapsed_time * 1.20)
                    m_lo = int(act.moving_time * 0.80) if act.moving_time else e_lo
                    m_hi = int(act.moving_time * 1.20) if act.moving_time else e_hi
                    dup = sess.query(Activity.id).filter(
                        Activity.started_at.between(t_start, t_end),
                        or_(
                            Activity.duration_sec.between(e_lo, e_hi),
                            Activity.duration_sec.between(m_lo, m_hi),
                            Activity.moving_time_sec.between(e_lo, e_hi),
                            Activity.moving_time_sec.between(m_lo, m_hi),
                        ),
                    ).first()
                    if dup:
                        print(f"[Strava] Duplicado (fecha+dur): {act.name}")
                        skipped.append(act.name)
                        continue
                finally:
                    sess.close()

                # Streams 1Hz
                power_1hz = streams.power if streams.power else []
                hr_1hz = streams.heartrate if streams.heartrate else []

                # Max valid power
                sess = get_session()
                try:
                    last_test = sess.query(PowerTestSet).order_by(
                        PowerTestSet.tested_at.desc()).first()
                    if last_test and last_test.cp and last_test.cp > 0:
                        max_valid = last_test.cp * 3
                    else:
                        max_valid = max(ftp * 5, 1500)
                finally:
                    sess.close()

                clean_power = [p if (p is not None and p <= max_valid) else 0
                               for p in power_1hz]

                duration_sec = act.elapsed_time
                pm = calculate_power_metrics(clean_power, ftp=ftp,
                                              duration_sec=duration_sec)

                zones_power = bucket_series(clean_power, ftp, POWER_ZONES) if power_1hz else None
                hr_ref = hr_lthr if hr_lthr and hr_lthr > 0 else hr_max
                zones_hr = bucket_series(hr_1hz, hr_ref, HR_ZONES) if hr_1hz else None
                mmp_data = compute_mmp(power_1hz, max_valid_power=max_valid) if power_1hz else None

                valid_hr = [v for v in hr_1hz if v and v > 0]
                avg_hr = round(sum(valid_hr) / len(valid_hr)) if valid_hr else None
                max_hr_val = round(max(valid_hr)) if valid_hr else None
                valid_pw = [v for v in power_1hz if v and v > 0]
                max_power = round(max(valid_pw)) if valid_pw else None

                sess = get_session()
                try:
                    activity = Activity(
                        started_at=act.started_at,
                        sport=act.sport_type,
                        source="strava",
                        strava_activity_id=act.strava_id,
                        file_name=act.name,
                        custom_name=act.name,
                        duration_sec=duration_sec,
                        moving_time_sec=act.moving_time,
                        distance_km=round(act.distance_m / 1000, 2) if act.distance_m else 0.0,
                        elevation_gain_m=act.total_elevation,
                        avg_speed_kmh=round(act.distance_m / max(act.moving_time, 1) * 3.6, 1) if act.distance_m and act.moving_time else None,
                        avg_hr=avg_hr,
                        max_hr=max_hr_val,
                        avg_power=pm.avg_power,
                        max_power=max_power,
                        normalized_power=pm.np,
                        intensity_factor=pm.intensity_factor,
                        tss=pm.tss,
                        work_kj=pm.work_kj,
                        ftp_used=ftp,
                    )
                    if zones_power:
                        activity.set_zones_power(zones_power)
                    if zones_hr:
                        activity.set_zones_hr(zones_hr)
                    if samples:
                        activity.set_samples(samples)
                    if mmp_data:
                        activity.set_mmp(mmp_data)
                    sess.add(activity)
                    sess.commit()
                    imported += 1
                    print(f"[Strava] ✓ {act.name} ({act.started_at.date()})")
                except Exception as e:
                    sess.rollback()
                    print(f"[Strava] Error DB {act.name}: {e}")
                    errors += 1
                finally:
                    sess.close()

            except Exception as e:
                print(f"[Strava] Error {act.name}: {e}")
                errors += 1

    finally:
        state["result"] = (imported, errors, skipped)
        state["status"] = "done"


class _ZoneOptionCard(QPushButton):
    """Tarjeta seleccionable para zona de referencia (FTP/CP/mFTP).

    Usa QPushButton como base para tener clicked gratis
    (sin problemas de mousePressEvent en QFrame).
    """

    def __init__(self, key: str, label: str, description: str,
                 value: Optional[int], active: bool = False, enabled: bool = True, parent=None):
        super().__init__(parent)
        self._key = key
        self._active = active
        self.setEnabled(enabled)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(190)
        self.setFixedHeight(120)

        # Layout interno (QPushButton acepta layout)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(5)

        # Header: label + radio indicator
        top = QHBoxLayout()
        self._label_w = QLabel(label)
        self._label_w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top.addWidget(self._label_w)
        top.addStretch()
        self._dot = QLabel()
        self._dot.setFixedSize(14, 14)
        self._dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top.addWidget(self._dot)
        layout.addLayout(top)

        self._desc_w = QLabel(description)
        self._desc_w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._desc_w.setWordWrap(True)
        layout.addWidget(self._desc_w)

        self._value_label = QLabel(f"{value} W" if value is not None else "\u2014")
        self._value_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._value_label)

        layout.addStretch()

        self._apply_style()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_style()

    def set_value(self, value: Optional[int]) -> None:
        self._value_label.setText(f"{value} W" if value is not None else "\u2014")

    def _apply_style(self) -> None:
        if self._active:
            self.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['primary_dim']}; "
                f"border: 2px solid {COLORS['primary']}; border-radius: 8px; "
                f"text-align: left; padding: 0; }}"
                f"QPushButton:hover {{ background-color: {COLORS['primary_dim']}; }}"
            )
            self._label_w.setStyleSheet(
                f"font-size: {FONT_SIZE_LG}; font-weight: 600; "
                f"color: {COLORS['primary']}; background: transparent;"
            )
            self._dot.setStyleSheet(
                f"background-color: {COLORS['primary']}; border-radius: 7px;"
            )
            self._desc_w.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; background: transparent;"
            )
            self._value_label.setStyleSheet(
                f"font-size: {FONT_SIZE_LG}; font-weight: 700; "
                f"color: {COLORS['primary']}; font-family: monospace; background: transparent;"
            )
        else:
            self.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['bg_card']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 8px; "
                f"text-align: left; padding: 0; }}"
                f"QPushButton:hover {{ background-color: {COLORS['bg_hover']}; }}"
            )
            self._label_w.setStyleSheet(
                f"font-size: {FONT_SIZE_LG}; font-weight: 600; "
                f"color: {COLORS['fg']}; background: transparent;"
            )
            self._dot.setStyleSheet(
                f"background-color: transparent; border: 2px solid {COLORS['fg_dim']}; border-radius: 7px;"
            )
            self._desc_w.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; background: transparent;"
            )
            self._value_label.setStyleSheet(
                f"font-size: {FONT_SIZE_LG}; font-weight: 700; "
                f"color: {COLORS['fg']}; font-family: monospace; background: transparent;"
            )