"""Vista del Consejero IA — interfaz de chat con Ollama.

Chat con burbujas, panel lateral de conversaciones, búsqueda,
acciones rápidas, exportar a Markdown e indicador de conexión.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDateEdit, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QDate

from i18n import tr
from services.ai_coach import get_ai_coach, AiCoachService, ConversationSummary
from ui.dialogs import confirmar
from ui.theme import (
    COLORS, FONT_SIZE_SM, FONT_SIZE_BASE, FONT_SIZE_MD,
    FONT_SIZE_LG, FONT_SIZE_XS, RADIUS, RADIUS_LG,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de estilo
# ---------------------------------------------------------------------------
_USER_BUBBLE_BG = COLORS["primary_dim"]
_USER_BUBBLE_BORDER = COLORS["primary"]
_ASSISTANT_BUBBLE_BG = COLORS["bg_secondary"]
_ASSISTANT_BUBBLE_BORDER = COLORS["border"]
_STATUS_CONNECTED = COLORS["success"]
_STATUS_DISCONNECTED = COLORS["destructive"]
_STATUS_CHECKING = COLORS["warning"]
_SIDEBAR_WIDTH = 260


# ---------------------------------------------------------------------------
# Worker thread para streaming
# ---------------------------------------------------------------------------
class _StreamWorker(QThread):
    """Ejecuta el streaming en hilo secundario para no bloquear la UI."""
    token_received = Signal(str)
    finished_ok = Signal(str)
    finished_error = Signal(str)

    def __init__(self, coach: AiCoachService, message: str, parent=None):
        super().__init__(parent)
        self._coach = coach
        self._message = message

    def run(self):
        try:
            full = self._coach.send_message_stream(
                self._message,
                on_token=lambda tok: self.token_received.emit(tok),
            )
            self.finished_ok.emit(full)
        except Exception as exc:
            self.finished_error.emit(str(exc))


# ---------------------------------------------------------------------------
# Burbuja de mensaje
# ---------------------------------------------------------------------------
class _MessageBubble(QFrame):
    """Widget de burbuja de chat."""

    def __init__(self, role: str, text: str = "", parent=None):
        super().__init__(parent)
        self._role = role
        is_user = role == "user"

        bg = _USER_BUBBLE_BG if is_user else _ASSISTANT_BUBBLE_BG
        border = _USER_BUBBLE_BORDER if is_user else _ASSISTANT_BUBBLE_BORDER
        margin_l = "60px" if is_user else "0px"
        margin_r = "0px" if is_user else "60px"
        icon = "🚴" if is_user else "🤖"

        self.setStyleSheet(f"""
            _MessageBubble {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {RADIUS_LG};
                margin-left: {margin_l};
                margin-right: {margin_r};
                padding: 0px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        # Cabecera
        header = QHBoxLayout()
        role_label = QLabel(f"{icon} {tr('Tú') if is_user else tr('Consejero IA')}")
        role_label.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; font-weight: 600; "
            f"color: {COLORS['primary'] if is_user else COLORS['accent']}; "
            "background: transparent;"
        )
        header.addWidget(role_label)
        header.addStretch()

        time_label = QLabel(datetime.now().strftime("%H:%M"))
        time_label.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']}; background: transparent;"
        )
        header.addWidget(time_label)
        layout.addLayout(header)

        # Contenido
        self._content = QLabel(text)
        self._content.setWordWrap(True)
        self._content.setTextFormat(Qt.TextFormat.MarkdownText)
        self._content.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._content.setStyleSheet(
            f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg']}; "
            f"line-height: 1.5; background: transparent; padding: 0;"
        )
        layout.addWidget(self._content)

    def append_text(self, token: str) -> None:
        current = self._content.text()
        self._content.setText(current + token)

    def set_text(self, text: str) -> None:
        self._content.setText(text)


# ---------------------------------------------------------------------------
# Campo de entrada
# ---------------------------------------------------------------------------
class _ChatInput(QTextEdit):
    """Campo de texto multi-línea. Enter envía, Shift+Enter nueva línea."""
    submit = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(tr("Escribe tu pregunta..."))
        self.setMaximumHeight(100)
        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_input']};
                border: 2px solid {COLORS['border']};
                border-radius: {RADIUS};
                padding: 8px 12px;
                color: {COLORS['fg']};
                font-size: {FONT_SIZE_BASE};
            }}
            QTextEdit:focus {{
                border-color: {COLORS['border_focus']};
            }}
        """)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.submit.emit()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Vista principal
# ---------------------------------------------------------------------------
class AiCoachView(QWidget):
    """Vista completa del Consejero IA con panel lateral de conversaciones."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[_StreamWorker] = None
        self._current_bubble: Optional[_MessageBubble] = None
        self._coach = get_ai_coach()
        self._setup_ui()
        self._check_connection()
        self._refresh_conversation_list()

    def refresh(self) -> None:
        """Refresca estado de conexión y modelo (llamado al navegar a esta vista)."""
        # Re-leer el singleton por si el usuario cambió modelo en Configuración
        self._coach = get_ai_coach()
        self._check_connection()

    def _apply_model_from_settings(self) -> None:
        """Lee el modelo guardado en perfil y lo aplica al singleton.

        Esto cubre el caso en que la app arrancó con un DEFAULT_MODEL
        pero el perfil ya tiene otro modelo guardado.
        """
        try:
            from ui.main_window import MainWindow
            mw = self.window()
            if isinstance(mw, MainWindow) and hasattr(mw, 'profile'):
                saved_model = mw.profile.config.get('ollama_model', '')
                saved_url = mw.profile.config.get('ollama_url', '')
                if saved_model and saved_model != self._coach.model:
                    self._coach.model = saved_model
                if saved_url and saved_url != self._coach.base_url:
                    self._coach.base_url = saved_url
        except Exception:
            pass

    # ---- Construcción de UI -------------------------------------------------

    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # === Panel lateral de conversaciones ===
        sidebar = self._build_sidebar()
        root.addWidget(sidebar)

        # === Área principal de chat ===
        chat_area = QWidget()
        main_layout = QVBoxLayout(chat_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Barra superior
        top_bar = self._build_top_bar()
        main_layout.addWidget(top_bar)

        # Área de mensajes
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )

        self._messages_container = QWidget()
        self._messages_layout = QVBoxLayout(self._messages_container)
        self._messages_layout.setContentsMargins(20, 16, 20, 16)
        self._messages_layout.setSpacing(12)
        self._messages_layout.addStretch()

        self._scroll.setWidget(self._messages_container)
        main_layout.addWidget(self._scroll, 1)

        # Acciones rápidas
        quick_bar = self._build_quick_actions()
        main_layout.addWidget(quick_bar)

        # Barra de entrada
        input_bar = self._build_input_bar()
        main_layout.addWidget(input_bar)

        root.addWidget(chat_area, 1)

        # Mensaje de bienvenida
        self._add_welcome_message()

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setFixedWidth(_SIDEBAR_WIDTH)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border-right: 1px solid {COLORS['border']};
            }}
        """)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Botón nueva conversación
        btn_new = QPushButton(f"➕ {tr('Nueva conversación')}")
        btn_new.setFixedHeight(36)
        btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_new.clicked.connect(self._on_new_conversation)
        layout.addWidget(btn_new)

        # Campo de búsqueda
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(f"🔍 {tr('Buscar conversaciones...')}")
        self._search_input.setFixedHeight(32)
        self._search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search_input)

        # Lista de conversaciones
        self._conv_list = QListWidget()
        self._conv_list.setStyleSheet(f"""
            QListWidget {{
                background-color: transparent;
                border: none;
                font-size: {FONT_SIZE_SM};
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-radius: 4px;
                color: {COLORS['fg_muted']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['primary_dim']};
                color: {COLORS['primary']};
            }}
            QListWidget::item:hover:!selected {{
                background-color: {COLORS['bg_hover']};
                color: {COLORS['fg']};
            }}
        """)
        self._conv_list.itemClicked.connect(self._on_conversation_selected)
        layout.addWidget(self._conv_list, 1)

        # Botones de acción — dos filas para evitar truncado
        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(4)
        btn_export = QPushButton(f"💾 {tr('Exportar')}")
        btn_export.setProperty("class", "ghost")
        btn_export.setFixedHeight(28)
        btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_export.setToolTip(tr("Exportar conversación a Markdown"))
        btn_export.clicked.connect(self._on_export)
        btn_row1.addWidget(btn_export)

        btn_ics = QPushButton(f"📆 {tr('.ics')}")
        btn_ics.setProperty("class", "ghost")
        btn_ics.setFixedHeight(28)
        btn_ics.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ics.setToolTip(tr("Exportar plan a calendario (.ics)"))
        btn_ics.clicked.connect(self._on_export_ics)
        btn_row1.addWidget(btn_ics)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(4)
        btn_pdf = QPushButton(f"📄 {tr('Informe PDF')}")
        btn_pdf.setProperty("class", "ghost")
        btn_pdf.setFixedHeight(28)
        btn_pdf.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_pdf.setToolTip(tr("Generar informe completo en PDF"))
        btn_pdf.clicked.connect(self._on_export_pdf)
        btn_row2.addWidget(btn_pdf)

        btn_delete = QPushButton(f"🗑 {tr('Eliminar')}")
        btn_delete.setProperty("class", "ghost")
        btn_delete.setFixedHeight(28)
        btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_delete.setToolTip(tr("Eliminar conversación seleccionada"))
        btn_delete.clicked.connect(self._on_delete_conversation)
        btn_row2.addWidget(btn_delete)

        layout.addLayout(btn_row1)
        layout.addLayout(btn_row2)

        return sidebar

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border-bottom: 1px solid {COLORS['border']};
                padding: 12px 20px;
            }}
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 10, 20, 10)

        title = QLabel(f"🤖 {tr('Consejero IA')}")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: 700; "
            f"color: {COLORS['fg']}; background: transparent;"
        )
        layout.addWidget(title)
        layout.addStretch()

        # Indicador de conexión
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(
            f"font-size: 14px; color: {_STATUS_CHECKING}; background: transparent;"
        )
        layout.addWidget(self._status_dot)

        self._status_label = QLabel(tr("Verificando..."))
        self._status_label.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        layout.addWidget(self._status_label)

        btn_reconnect = QPushButton(tr("↻"))
        btn_reconnect.setToolTip(tr("Reconectar con Ollama"))
        btn_reconnect.setFixedSize(32, 32)
        btn_reconnect.setProperty("class", "ghost")
        btn_reconnect.clicked.connect(self._check_connection)
        layout.addWidget(btn_reconnect)

        return bar

    def _build_quick_actions(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border-top: 1px solid {COLORS['border']};
            }}
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(8)

        actions = [
            ("📊", tr("Análisis de forma"), self._coach.quick_form_analysis),
            ("📅", tr("Resumen semanal"), self._coach.quick_week_review),
            ("🎯", tr("Entreno de hoy"), self._coach.quick_training_suggestion),
            ("⚡", tr("Consejo FTP"), self._coach.quick_ftp_advice),
            ("📝", tr("Informe completo"), self._coach.quick_full_report),
            ("🗓️", tr("Plan 4-6 semanas"), None),  # special: needs goal input
        ]

        for icon, label, action_fn in actions:
            btn = QPushButton(f"{icon} {label}")
            btn.setProperty("class", "ghost")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_secondary']};
                    color: {COLORS['fg_muted']};
                    border: 1px solid {COLORS['border']};
                    border-radius: {RADIUS};
                    padding: 6px 12px;
                    font-size: {FONT_SIZE_SM};
                }}
                QPushButton:hover {{
                    background-color: {COLORS['bg_hover']};
                    color: {COLORS['fg']};
                    border-color: {COLORS['primary']};
                }}
            """)
            btn.clicked.connect(partial(self._send_quick_action, action_fn))
            layout.addWidget(btn)

        layout.addStretch()
        return bar

    def _build_input_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border-top: 1px solid {COLORS['border']};
            }}
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(10)

        self._input = _ChatInput()
        self._input.submit.connect(self._on_send)
        layout.addWidget(self._input, 1)

        self._send_btn = QPushButton(tr("Enviar"))
        self._send_btn.setFixedHeight(40)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send)
        layout.addWidget(self._send_btn)

        return bar

    # ---- Mensajes -----------------------------------------------------------

    def _add_welcome_message(self):
        from i18n import get_language
        if get_language() == "en":
            welcome = (
                "**Hi! I'm your Ciclométricas AI Coach** 🚴\n\n"
                "I can help you with:\n"
                "- 📊 **Form analysis** — CTL, ATL, TSB and current status\n"
                "- 📅 **Weekly summary** — load, polarization, trends\n"
                "- 🎯 **Workout suggestions** — ideal session for today\n"
                "- 📝 **Full report** — comprehensive analysis of all your data\n"
                "- 🗓️ **4-6 week plan** — exportable to your calendar (.ics)\n\n"
                "After each response you'll see **suggested questions** to go deeper. "
                "Everything is processed **100% locally** with Ollama."
            )
        else:
            welcome = (
                "**¡Hola! Soy tu Consejero IA de Ciclométricas** 🚴\n\n"
                "Puedo ayudarte con:\n"
                "- 📊 **Análisis de forma** — CTL, ATL, TSB y estado actual\n"
                "- 📅 **Resumen semanal** — carga, polarización, tendencias\n"
                "- 🎯 **Sugerencias de entreno** — sesión ideal para hoy\n"
                "- 📝 **Informe completo** — análisis exhaustivo de todos tus datos\n"
                "- 🗓️ **Plan de 4-6 semanas** — exportable a tu calendario (.ics)\n\n"
                "Tras cada respuesta verás **preguntas sugeridas** para profundizar. "
                "Todo se procesa **100% local** con Ollama."
            )
        self._add_bubble("assistant", welcome)

    def _add_bubble(self, role: str, text: str = "") -> _MessageBubble:
        bubble = _MessageBubble(role, text)
        count = self._messages_layout.count()
        self._messages_layout.insertWidget(count - 1, bubble)
        self._scroll_to_bottom(force=True)
        return bubble

    def _clear_bubbles(self):
        """Elimina todas las burbujas de la UI."""
        while self._messages_layout.count() > 1:
            item = self._messages_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _is_near_bottom(self, threshold: int = 60) -> bool:
        """Devuelve True si el scroll está cerca del final."""
        sb = self._scroll.verticalScrollBar()
        return sb.value() >= sb.maximum() - threshold

    def _scroll_to_bottom(self, force: bool = False):
        """Hace scroll al final solo si el usuario no ha scrolleado arriba.

        Args:
            force: Si True, scrollea siempre (ej. al enviar un mensaje).
        """
        if not force and not self._is_near_bottom():
            return
        sb = self._scroll.verticalScrollBar()
        QTimer.singleShot(50, lambda: sb.setValue(sb.maximum()))

    # ---- Enviar mensaje ----------------------------------------------------

    def _on_send(self):
        text = self._input.toPlainText().strip()
        if not text or self._worker is not None:
            return
        self._input.clear()
        self._do_send(text)

    def _send_quick_action(self, action_fn):
        if self._worker is not None:
            return
        if action_fn is None:
            # Special case: training plan needs a goal
            goal, ok = QInputDialog.getText(
                self,
                tr("Plan de entrenamiento"),
                tr("Define tu objetivo (ej: 'subir FTP a 300W', 'preparar granfondo 150km', 'mejorar VO2max'):"),
            )
            if not ok:
                return
            prompt = self._coach.quick_training_plan(goal)
        else:
            prompt = action_fn()
        self._do_send(prompt)

    def _do_send(self, text: str):
        if not self._coach.is_connected:
            self._add_bubble(
                "assistant",
                "⚠️ **No hay conexión con Ollama.** "
                "Verifica que está ejecutándose y pulsa ↻ para reconectar."
            )
            return

        self._coach.refresh_context()
        self._add_bubble("user", text)
        self._current_bubble = self._add_bubble("assistant", f"✨ {tr('Pensando...')}")
        self._set_input_enabled(False)

        self._worker = _StreamWorker(self._coach, text, parent=self)
        self._worker.token_received.connect(self._on_token)
        self._worker.finished_ok.connect(self._on_stream_done)
        self._worker.finished_error.connect(self._on_stream_error)
        self._worker.start()

    def _on_token(self, token: str):
        if self._current_bubble is None:
            return
        if self._current_bubble._content.text() in ("✨ Pensando...", f"✨ {tr('Pensando...')}"):
            self._current_bubble.set_text("")
        self._current_bubble.append_text(token)
        self._scroll_to_bottom()

    def _on_stream_done(self, full_text: str):
        if self._current_bubble:
            self._current_bubble.set_text(full_text)
        self._cleanup_worker()
        # Refrescar lista (el título puede haber cambiado)
        self._refresh_conversation_list()
        # Mostrar preguntas sugeridas
        self._show_follow_ups(full_text)

    def _on_stream_error(self, error_msg: str):
        if self._current_bubble:
            self._current_bubble.set_text(
                f"❌ **Error:** {error_msg}\n\n"
                "Verifica que Ollama está ejecutándose y que el modelo está descargado."
            )
        self._cleanup_worker()

    def _cleanup_worker(self):
        self._worker = None
        self._current_bubble = None
        self._set_input_enabled(True)
        self._input.setFocus()

    def _set_input_enabled(self, enabled: bool):
        self._input.setEnabled(enabled)
        self._send_btn.setEnabled(enabled)

    # ---- Conexión ----------------------------------------------------------

    def _check_connection(self):
        self._status_dot.setStyleSheet(
            f"font-size: 14px; color: {_STATUS_CHECKING}; background: transparent;"
        )
        self._status_label.setText(tr("Verificando..."))

        # Asegurar que el singleton tiene el modelo del perfil
        self._apply_model_from_settings()

        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        ok = self._coach.check_connection()
        if ok:
            models = self._coach.list_models()
            model_names = [m.name for m in models]
            model_name = self._coach.model

            # Verificar que el modelo configurado existe en Ollama
            if model_name and model_names and model_name not in model_names:
                # Modelo no encontrado — auto-seleccionar el primero disponible
                old_name = model_name
                model_name = model_names[0]
                self._coach.model = model_name
                # Persistir el cambio en el perfil
                self._save_model_to_profile(model_name)
                self._status_dot.setStyleSheet(
                    f"font-size: 14px; color: #fbbf24; background: transparent;"
                )
                self._status_label.setText(
                    f"⚠️ {old_name} {tr('no encontrado')} → {tr('usando')} {model_name}"
                )
            else:
                self._status_dot.setStyleSheet(
                    f"font-size: 14px; color: {_STATUS_CONNECTED}; background: transparent;"
                )
                self._status_label.setText(
                    f"{tr('Conectado')} · {model_name} · {len(models)} {tr('modelo(s)')}"
                )
        else:
            self._status_dot.setStyleSheet(
                f"font-size: 14px; color: {_STATUS_DISCONNECTED}; background: transparent;"
            )
            self._status_label.setText(tr("Desconectado — Ollama no responde"))

    def _save_model_to_profile(self, model_name: str) -> None:
        """Persiste el modelo seleccionado en el perfil del atleta."""
        try:
            from ui.main_window import MainWindow
            mw = self.window()
            if isinstance(mw, MainWindow) and hasattr(mw, 'profile'):
                mw.profile.config['ollama_model'] = model_name
                if hasattr(mw, 'manager'):
                    mw.manager.save_profiles()
        except Exception:
            pass

    # ---- Gestión de conversaciones en UI -----------------------------------

    def _refresh_conversation_list(self, select_id: Optional[int] = None):
        """Recarga la lista del panel lateral."""
        query = self._search_input.text().strip() if hasattr(self, '_search_input') else ""
        if query:
            convs = self._coach.search_conversations(query)
        else:
            convs = self._coach.list_conversations()

        self._conv_list.blockSignals(True)
        self._conv_list.clear()
        target_id = select_id or self._coach.conversation_id

        for c in convs:
            date_str = c.updated_at.strftime("%d/%m %H:%M") if c.updated_at else ""
            item = QListWidgetItem(f"{c.title}\n{c.model} · {c.message_count} msgs · {date_str}")
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            self._conv_list.addItem(item)
            if c.id == target_id:
                item.setSelected(True)
                self._conv_list.setCurrentItem(item)

        self._conv_list.blockSignals(False)

    def _on_search_changed(self, text: str):
        self._refresh_conversation_list()

    def _on_new_conversation(self):
        """Crea una nueva conversación."""
        self._coach.clear_history()
        conv_id = self._coach.new_conversation()
        self._clear_bubbles()
        self._add_welcome_message()
        self._refresh_conversation_list(select_id=conv_id)

    def _on_conversation_selected(self, item: QListWidgetItem):
        """Carga una conversación seleccionada."""
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        if conv_id == self._coach.conversation_id:
            return

        ok = self._coach.load_conversation(conv_id)
        if not ok:
            return

        # Reconstruir burbujas desde el historial cargado
        self._clear_bubbles()
        history = self._coach.history
        if not history:
            self._add_welcome_message()
        else:
            for msg in history:
                self._add_bubble(msg.role, msg.content)

        self._scroll_to_bottom()

    def _on_delete_conversation(self):
        """Elimina la conversación seleccionada."""
        item = self._conv_list.currentItem()
        if item is None:
            return
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        if not confirmar(self, tr("Eliminar conversación"),
                        tr("¿Eliminar esta conversación y todos sus mensajes?")):
            return

        self._coach.delete_conversation(conv_id)
        if conv_id == self._coach.conversation_id:
            self._clear_bubbles()
            self._add_welcome_message()
        self._refresh_conversation_list()

    # ---- Preguntas sugeridas -----------------------------------------------

    def _show_follow_ups(self, assistant_text: str):
        """Muestra botones de preguntas sugeridas bajo la última respuesta."""
        # Limpiar follow-ups anteriores si existen
        self._clear_follow_ups()

        suggestions = self._coach.generate_follow_ups(assistant_text)
        if not suggestions:
            return

        self._follow_up_frame = QFrame()
        self._follow_up_frame.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: none;
                margin-left: 60px;
            }}
        """)
        fu_layout = QHBoxLayout(self._follow_up_frame)
        fu_layout.setContentsMargins(0, 0, 0, 4)
        fu_layout.setSpacing(6)

        for suggestion in suggestions:
            btn = QPushButton(f"💡 {suggestion}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_secondary']};
                    color: {COLORS['accent']};
                    border: 1px solid {COLORS['border']};
                    border-radius: {RADIUS};
                    padding: 4px 10px;
                    font-size: {FONT_SIZE_SM};
                    text-align: left;
                }}
                QPushButton:hover {{
                    background-color: {COLORS['bg_hover']};
                    border-color: {COLORS['accent']};
                    color: {COLORS['fg']};
                }}
            """)
            btn.clicked.connect(partial(self._on_follow_up_clicked, suggestion))
            fu_layout.addWidget(btn)

        fu_layout.addStretch()

        # Insertar justo antes del stretch final
        count = self._messages_layout.count()
        self._messages_layout.insertWidget(count - 1, self._follow_up_frame)
        self._scroll_to_bottom()

    def _clear_follow_ups(self):
        """Elimina los botones de follow-up si existen."""
        if hasattr(self, '_follow_up_frame') and self._follow_up_frame:
            self._follow_up_frame.deleteLater()
            self._follow_up_frame = None

    def _on_follow_up_clicked(self, text: str):
        """Envía la pregunta sugerida como mensaje del usuario."""
        self._clear_follow_ups()
        self._do_send(text)

    # ---- Exportar a calendario .ics ----------------------------------------

    def _on_export_pdf(self):
        """Genera informe completo del atleta en PDF."""
        from services.report_generator import generate_report, collect_report_data, _ensure_pdf_deps

        # Verificar dependencias antes de nada
        try:
            _ensure_pdf_deps()
        except ImportError as exc:
            QMessageBox.critical(
                self, tr("Error"),
                f"{tr('No se pudo cargar el generador de informes.')}\n\n{exc}",
            )
            return

        try:
            data = collect_report_data()
        except Exception as exc:
            QMessageBox.critical(
                self, tr("Error"),
                f"{tr('No se pudieron recopilar los datos del atleta.')}\n{exc}",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Guardar informe PDF"),
            str(Path.home() / "ciclometricas_informe.pdf"),
            "PDF (*.pdf);;All files (*)",
        )
        if not path:
            return

        try:
            generate_report(path, data)
            QMessageBox.information(
                self,
                tr("Informe PDF"),
                f"{tr('Informe generado correctamente.')}\n{path}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self, tr("Error"), f"{tr('No se pudo generar el PDF.')}\n{exc}"
            )

    def _on_export_ics(self):
        """Busca el último plan de entrenamiento en el historial y lo exporta a .ics."""
        # Buscar la última respuesta que parezca un plan
        plan_text = None
        for msg in reversed(self._coach.history):
            if msg.role == "assistant":
                text_lower = msg.content.lower()
                if (("semana" in text_lower or "week" in text_lower) and
                    ("plan" in text_lower or "día" in text_lower or "day" in text_lower
                     or "lunes" in text_lower or "monday" in text_lower)):
                    plan_text = msg.content
                    break

        if not plan_text:
            QMessageBox.information(
                self,
                tr("Exportar calendario"),
                tr("No se encontró un plan de entrenamiento en la conversación actual.\n"
                   "Primero pide al Consejero IA que genere un plan de 4-6 semanas."),
            )
            return

        # Preguntar fecha de inicio
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Fecha de inicio del plan"))
        dlg_layout = QVBoxLayout(dialog)

        dlg_layout.addWidget(QLabel(tr("Selecciona la fecha de inicio (lunes recomendado):")))

        date_edit = QDateEdit()
        # Próximo lunes
        from datetime import date as date_cls, timedelta
        today = date_cls.today()
        days_to_monday = (7 - today.weekday()) % 7
        if days_to_monday == 0:
            days_to_monday = 7
        next_monday = today + timedelta(days=days_to_monday)
        date_edit.setDate(QDate(next_monday.year, next_monday.month, next_monday.day))
        date_edit.setCalendarPopup(True)
        dlg_layout.addWidget(date_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dlg_layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        qd = date_edit.date()
        start = date_cls(qd.year(), qd.month(), qd.day())

        ics_content = self._coach.export_plan_to_ics(plan_text, start)

        # Contar eventos generados
        event_count = ics_content.count("BEGIN:VEVENT")
        if event_count == 0:
            QMessageBox.warning(
                self,
                tr("Exportar calendario"),
                tr("No se pudieron detectar sesiones en el plan.\n"
                   "Asegúrate de que el plan incluye días de la semana o números de día."),
            )
            return

        # Guardar archivo
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Guardar plan como calendario"),
            str(Path.home() / "plan_entrenamiento.ics"),
            "iCalendar (*.ics);;All files (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(ics_content, encoding="utf-8")
            QMessageBox.information(
                self,
                tr("Exportar calendario"),
                f"{tr('Plan exportado con')} {event_count} {tr('sesiones.')}\n"
                f"{tr('Abre el archivo .ics con tu app de calendario')}"
                f" (Google Calendar, Apple Calendar, Outlook...)",
            )
        except Exception as exc:
            QMessageBox.critical(
                self, tr("Error"), f"{tr('No se pudo exportar.')}\n{exc}"
            )

    # ---- Exportar conversación a MD -----------------------------------------

    def _on_export(self):
        """Exporta la conversación seleccionada a .md."""
        item = self._conv_list.currentItem()
        if item is None:
            QMessageBox.information(
                self, tr("Exportar"), tr("Selecciona una conversación para exportar.")
            )
            return
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        md = self._coach.export_conversation_md(conv_id)
        if not md:
            QMessageBox.warning(self, tr("Exportar"), tr("No hay contenido para exportar."))
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Guardar conversación"),
            str(Path.home() / "consejero_ia_chat.md"),
            "Markdown (*.md);;Texto (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(md, encoding="utf-8")
            QMessageBox.information(
                self, tr("Exportar"), tr("Conversación exportada correctamente.")
            )
        except Exception as exc:
            QMessageBox.critical(
                self, tr("Error"), f"{tr('No se pudo exportar.')}\n{exc}"
            )
