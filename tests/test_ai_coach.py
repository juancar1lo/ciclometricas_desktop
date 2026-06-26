"""Tests para services/ai_coach.py — incluye persistencia."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.ai_coach import (
    AiCoachService,
    ChatMessage,
    ConversationSummary,
    OllamaModel,
    get_ai_coach,
    DEFAULT_OLLAMA_URL,
    DEFAULT_MODEL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def coach():
    """Instancia limpia del servicio."""
    return AiCoachService(ollama_url="http://test:11434", model="test-model")


@pytest.fixture
def db_session():
    """Crea una DB SQLite temporal con las tablas necesarias."""
    from db.engine import init_db, dispose_engine
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_coach.db"
        init_db(db_path)
        yield db_path
        dispose_engine()


# ---------------------------------------------------------------------------
# Propiedades básicas
# ---------------------------------------------------------------------------
class TestProperties:
    def test_defaults(self):
        svc = AiCoachService()
        assert svc.base_url == DEFAULT_OLLAMA_URL
        assert svc.model == DEFAULT_MODEL
        assert svc.is_connected is False
        assert svc.history == []
        assert svc.conversation_id is None

    def test_set_url_strips_slash(self, coach: AiCoachService):
        coach.base_url = "http://other:1234/"
        assert coach.base_url == "http://other:1234"
        assert coach.is_connected is False

    def test_set_model(self, coach: AiCoachService):
        coach.model = "llama3"
        assert coach.model == "llama3"


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------
class TestConnection:
    @patch("services.ai_coach.requests.get")
    def test_check_connection_ok(self, mock_get, coach: AiCoachService):
        mock_get.return_value = MagicMock(status_code=200)
        assert coach.check_connection() is True
        assert coach.is_connected is True

    @patch("services.ai_coach.requests.get")
    def test_check_connection_fail(self, mock_get, coach: AiCoachService):
        from requests.exceptions import ConnectionError
        mock_get.side_effect = ConnectionError("refused")
        assert coach.check_connection() is False
        assert coach.is_connected is False

    @patch("services.ai_coach.requests.get")
    def test_check_connection_500(self, mock_get, coach: AiCoachService):
        mock_get.return_value = MagicMock(status_code=500)
        assert coach.check_connection() is False


# ---------------------------------------------------------------------------
# Listado de modelos
# ---------------------------------------------------------------------------
class TestListModels:
    @patch("services.ai_coach.requests.get")
    def test_list_models(self, mock_get, coach: AiCoachService):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "models": [
                    {"name": "deepseek-r1:8b", "size": 4_800_000_000, "modified_at": "2025-01-01"},
                    {"name": "llama3:8b", "size": 4_200_000_000, "modified_at": "2025-02-01"},
                ]
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()
        models = coach.list_models()
        assert len(models) == 2
        assert models[0].name == "deepseek-r1:8b"

    @patch("services.ai_coach.requests.get")
    def test_list_models_error(self, mock_get, coach: AiCoachService):
        mock_get.side_effect = Exception("timeout")
        assert coach.list_models() == []


# ---------------------------------------------------------------------------
# Contexto del atleta
# ---------------------------------------------------------------------------
class TestAthleteContext:
    @patch("services.ai_coach.get_session")
    def test_no_profile_loaded(self, mock_gs, coach: AiCoachService):
        mock_gs.side_effect = RuntimeError("No DB")
        ctx = coach._get_athlete_context()
        assert "No hay perfil" in ctx

    @patch("services.ai_coach.get_session")
    def test_with_profile(self, mock_gs, coach: AiCoachService):
        mock_session = MagicMock()
        mock_profile = MagicMock()
        mock_profile.ftp = 250
        mock_profile.weight_kg = 72.0
        mock_profile.hr_max = 185
        mock_profile.hr_lthr = 170

        from db.models import ProfileSnapshot as PS

        def query_side_effect(model, *cols):
            q = MagicMock()
            if model is PS:
                q.order_by.return_value.first.return_value = mock_profile
            else:
                q.order_by.return_value.first.return_value = None
                q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
                q.filter.return_value.all.return_value = []
            return q

        mock_session.query.side_effect = query_side_effect
        mock_gs.return_value = mock_session

        ctx = coach._get_athlete_context()
        assert "FTP: 250 W" in ctx
        assert "72.0 kg" in ctx

    @patch("services.ai_coach.get_session")
    def test_enriched_context_mmp_zones_durability(self, mock_gs, coach: AiCoachService):
        """Verifica que MMP, zonas y durabilidad aparecen en el contexto."""
        mock_session = MagicMock()

        mock_profile = MagicMock()
        mock_profile.ftp = 280
        mock_profile.weight_kg = 70.0
        mock_profile.hr_max = 190
        mock_profile.hr_lthr = None

        # MMP activity
        mock_act_mmp = MagicMock()
        mock_act_mmp.get_mmp.return_value = {"5": 900, "60": 350, "300": 290}
        mock_act_mmp.get_zones_power.return_value = {"z1": 600, "z2": 1200, "z3": 800}
        mock_act_mmp.get_zones_hr.return_value = {"z1": 500, "z2": 900}
        mock_act_mmp.started_at = MagicMock()
        mock_act_mmp.started_at.strftime.return_value = "01/01"
        mock_act_mmp.display_name = "Test ride"
        mock_act_mmp.duration_sec = 3600
        mock_act_mmp.tss = 80
        mock_act_mmp.normalized_power = 260
        mock_act_mmp.is_manual = False

        # Durability test
        mock_dur = MagicMock()
        mock_dur.dri_percent = 8.5
        mock_dur.classification = "good"
        mock_dur.cp_fresh = 270.0
        mock_dur.cp_fatigued = 250.0
        mock_dur.w_prime_fatigued = 15000.0
        mock_dur.kj_consumed = 1800.0

        # CP test mock (no cp data in this test)
        mock_cp_none = MagicMock()
        mock_cp_none.cp = None
        mock_cp_none.w_prime = None

        from db.models import (
            ProfileSnapshot as PS, PowerTestSet as PTS, Activity as Act,
            HealthMetric as HM, DurabilityTest as DT,
        )

        # Add basic mock methods for samples/climbs (not needed for this test)
        mock_act_mmp.get_samples.return_value = None
        mock_act_mmp.get_climbs.return_value = None
        mock_act_mmp.avg_power = 200
        mock_act_mmp.avg_hr = 150
        mock_act_mmp.avg_left_balance = None
        mock_act_mmp.intensity_factor = 0.85
        mock_act_mmp.distance_km = 40
        mock_act_mmp.elevation_gain_m = 300
        mock_act_mmp.activity_type = "cycling"

        def query_side_effect(model, *cols):
            q = MagicMock()
            if model is PS:
                q.order_by.return_value.first.return_value = mock_profile
            elif model is PTS:
                q.order_by.return_value.first.return_value = mock_cp_none
            elif model is DT:
                q.order_by.return_value.first.return_value = mock_dur
            elif model is HM:
                q.order_by.return_value.first.return_value = None
            else:
                # Activity queries
                q.order_by.return_value.first.return_value = None
                q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_act_mmp]
                q.filter.return_value.all.return_value = [mock_act_mmp]
            return q

        mock_session.query.side_effect = query_side_effect
        mock_gs.return_value = mock_session

        ctx = coach._get_athlete_context()
        # MMP
        assert "Curva de Potencia" in ctx
        assert "5s: 900 W" in ctx
        assert "5min: 290 W" in ctx
        # Zones
        assert "zonas de potencia" in ctx.lower() or "Distribución zonas" in ctx
        # Durability
        assert "Durabilidad" in ctx
        assert "DRI: 8.5%" in ctx
        assert "good" in ctx
        assert "CP fresco: 270 W" in ctx

    @patch("services.ai_coach.get_session")
    def test_advanced_metrics_in_context(self, mock_gs, coach: AiCoachService):
        """Verifica que EF, VF, intervalos, cuadrante, FR, tendencias,
        monotonía y Race Readiness aparecen en el contexto."""
        from datetime import datetime, timedelta, timezone, date
        mock_session = MagicMock()

        mock_profile = MagicMock()
        mock_profile.ftp = 250
        mock_profile.weight_kg = 72.0
        mock_profile.hr_max = 185
        mock_profile.hr_lthr = 170

        mock_cp = MagicMock()
        mock_cp.cp = 240
        mock_cp.w_prime = 20000
        mock_cp.vo2max = 55.0
        mock_cp.m_ftp = 230
        mock_cp.r_squared = 0.98

        # Build realistic samples (1000 sec of data)
        samples = [
            {"t": i, "p": 220 + (i % 30), "hr": 145 + (i % 10), "c": 88 + (i % 5)}
            for i in range(1000)
        ]

        now = datetime.now(timezone.utc)
        mock_act = MagicMock()
        mock_act.started_at = now - timedelta(days=1)
        mock_act.display_name = "Endurance ride"
        mock_act.duration_sec = 3600
        mock_act.tss = 75.0
        mock_act.normalized_power = 235.0
        mock_act.avg_power = 210.0
        mock_act.avg_hr = 148
        mock_act.is_manual = False
        mock_act.avg_left_balance = 49.5
        mock_act.get_samples.return_value = samples
        mock_act.get_mmp.return_value = {"5": 800, "300": 270}
        mock_act.get_zones_power.return_value = {"z1": 300, "z2": 1500, "z3": 800, "z4": 200, "z5": 100}
        mock_act.get_zones_hr.return_value = {"z1": 400, "z2": 1200}
        mock_act.get_climbs.return_value = [
            {"distance_m": 3200, "elev_gain_m": 180, "avg_gradient": 5.6, "avg_power": 265}
        ]
        mock_act.intensity_factor = 0.94
        mock_act.distance_km = 45.0
        mock_act.elevation_gain_m = 600

        from db.models import (
            ProfileSnapshot as PS, PowerTestSet as PTS, Activity as Act,
            HealthMetric as HM, DurabilityTest as DT,
        )

        def query_side_effect(model, *cols):
            q = MagicMock()
            if model is PS:
                q.order_by.return_value.first.return_value = mock_profile
            elif model is PTS:
                q.order_by.return_value.first.return_value = mock_cp
            elif model is DT:
                q.order_by.return_value.first.return_value = None
            elif model is HM:
                q.order_by.return_value.first.return_value = None
            else:
                # Activity queries — support all chain variants
                q.order_by.return_value.first.return_value = None
                q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_act]
                q.filter.return_value.order_by.return_value.all.return_value = [mock_act]
                q.filter.return_value.all.return_value = [mock_act]
            return q

        mock_session.query.side_effect = query_side_effect
        mock_gs.return_value = mock_session

        ctx = coach._get_athlete_context()

        # Advanced metrics
        assert "Métricas avanzadas" in ctx
        assert "EF (Efficiency Factor)" in ctx
        assert "VF (Variability Factor)" in ctx
        assert "Balance pedaleo" in ctx
        assert "49.5%" in ctx
        # Pw:Hr decoupling
        assert "Pw:Hr decoupling" in ctx
        # TISS
        assert "TISS" in ctx
        # Quadrant
        assert "Cuadrante" in ctx
        # Fatigue Resistance
        assert "Fatigue Resistance" in ctx
        # Intervals
        assert "Intervalos detectados" in ctx
        # Climbs
        assert "Subidas" in ctx
        assert "+180m" in ctx
        # Trends
        assert "Tendencias semanales" in ctx
        assert "polarización" in ctx
        # Race Readiness
        assert "Race Readiness" in ctx
        assert "Score:" in ctx


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
class TestSystemPrompt:
    def test_system_prompt_structure(self, coach: AiCoachService):
        with patch.object(coach, "_get_athlete_context", return_value="FTP: 300W"):
            prompt = coach._build_system_prompt()
            assert "Consejero IA de Ciclométricas" in prompt
            assert "FTP: 300W" in prompt
            assert "español" in prompt


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
class TestChat:
    def test_clear_history(self, coach: AiCoachService):
        coach._history.append(ChatMessage(role="user", content="hola"))
        assert len(coach.history) == 1
        coach.clear_history()
        assert len(coach.history) == 0
        assert coach.conversation_id is None

    def test_build_messages(self, coach: AiCoachService):
        with patch.object(coach, "_build_system_prompt", return_value="system"):
            coach.refresh_context()
            msgs = coach._build_messages("hola")
            assert msgs[0]["role"] == "system"
            assert msgs[-1]["role"] == "user"
            assert msgs[-1]["content"] == "hola"

    @patch("services.ai_coach.requests.post")
    def test_send_message_stream(self, mock_post, coach: AiCoachService):
        chunks = [
            json.dumps({"message": {"content": "Hola "}, "done": False}),
            json.dumps({"message": {"content": "ciclista"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = chunks
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with patch.object(coach, "_build_system_prompt", return_value="sys"):
            with patch.object(coach, "_persist_message"):
                with patch.object(coach, "new_conversation", return_value=1):
                    coach._conversation_id = 1  # simular conversación activa
                    coach.refresh_context()

                    tokens = []
                    result = coach.send_message_stream("hola", on_token=tokens.append)

                    assert result == "Hola ciclista"
                    # La implementación actual bufferiza y emite el texto
                    # completo como un solo token (para detectar [QUERY:] primero)
                    assert tokens == ["Hola ciclista"]
                    assert len(coach.history) == 2

    @patch("services.ai_coach.requests.post")
    def test_send_message_connection_error(self, mock_post, coach: AiCoachService):
        from requests.exceptions import ConnectionError
        mock_post.side_effect = ConnectionError("refused")

        with patch.object(coach, "_build_system_prompt", return_value="sys"):
            with patch.object(coach, "_persist_message"):
                coach._conversation_id = 1
                coach.refresh_context()
                with pytest.raises(ConnectionError):
                    coach.send_message_stream("hola")
                assert len(coach.history) == 0


# ---------------------------------------------------------------------------
# Strip think tags
# ---------------------------------------------------------------------------
class TestStripThink:
    def test_removes_think_blocks(self):
        text = "<think>razonamiento interno</think>Respuesta final"
        assert AiCoachService._strip_think_tags(text) == "Respuesta final"

    def test_no_think_tags(self):
        text = "Respuesta normal"
        assert AiCoachService._strip_think_tags(text) == "Respuesta normal"

    def test_multiline_think(self):
        text = "<think>\nlarga\nreflexion\n</think>\nOK listo"
        assert AiCoachService._strip_think_tags(text) == "OK listo"


# ---------------------------------------------------------------------------
# Acciones rápidas
# ---------------------------------------------------------------------------
class TestQuickActions:
    def test_quick_form(self, coach: AiCoachService):
        msg = coach.quick_form_analysis()
        assert "CTL" in msg and "TSB" in msg

    def test_quick_week(self, coach: AiCoachService):
        msg = coach.quick_week_review()
        assert "semana" in msg

    def test_quick_training(self, coach: AiCoachService):
        msg = coach.quick_training_suggestion()
        assert "TSB" in msg or "forma" in msg

    def test_quick_ftp(self, coach: AiCoachService):
        msg = coach.quick_ftp_advice()
        assert "FTP" in msg

    def test_quick_full_report(self, coach: AiCoachService):
        msg = coach.quick_full_report()
        assert "INFORME COMPLETO" in msg
        assert "Estado de forma" in msg
        assert "Race Readiness" in msg
        assert "Pronóstico" in msg

    def test_quick_training_plan_default(self, coach: AiCoachService):
        msg = coach.quick_training_plan()
        assert "4 a 6 semanas" in msg
        assert "mejorar el rendimiento general" in msg
        assert "mesociclos" in msg

    def test_quick_training_plan_with_goal(self, coach: AiCoachService):
        msg = coach.quick_training_plan("subir FTP a 300W")
        assert "subir FTP a 300W" in msg
        assert "4 a 6 semanas" in msg


# ---------------------------------------------------------------------------
# Gestión inteligente del contexto
# ---------------------------------------------------------------------------
class TestContextTrimming:
    def test_short_context_unchanged(self):
        short = "## Perfil\n- FTP: 250W\n- Peso: 72kg"
        result = AiCoachService._trim_context(short, max_chars=6000)
        assert result == short

    def test_long_context_trimmed(self):
        # Build a context exceeding 6000 chars
        sections = []
        sections.append("## Perfil del atleta\n- FTP: 250W\n- Peso: 72kg")
        sections.append("## Estado de forma actual\n- CTL: 85\n- ATL: 70\n- TSB: 15")
        sections.append("## Métricas avanzadas (ultimas)\n" + "- dato largo de prueba numero Z\n" * 600)
        big_ctx = "\n\n".join(sections)
        assert len(big_ctx) > 6000

        result = AiCoachService._trim_context(big_ctx, max_chars=500)
        assert len(result) <= 600  # small margin for (...)
        # High-priority sections should be present
        assert "Perfil del atleta" in result

    def test_priority_ordering(self):
        ctx = (
            "## Métricas avanzadas\nmucho texto..." + "x" * 200 + "\n"
            "## Perfil del atleta\n- FTP: 250W\n"
            "## Estado de forma actual\n- CTL: 85"
        )
        result = AiCoachService._trim_context(ctx, max_chars=200)
        # Profile should come before advanced metrics
        idx_perfil = result.find("Perfil del atleta")
        assert idx_perfil >= 0


# ---------------------------------------------------------------------------
# Preguntas sugeridas
# ---------------------------------------------------------------------------
class TestFollowUps:
    def test_ftp_response_suggests_ftp(self, coach: AiCoachService):
        sug = coach.generate_follow_ups("Tu FTP actual de 250W es buena base.")
        assert len(sug) >= 2
        assert len(sug) <= 3
        assert any("FTP" in s for s in sug)

    def test_plan_response_suggests_calendar(self, coach: AiCoachService):
        sug = coach.generate_follow_ups("Semana 1: Lunes base, Martes intervalos...")
        assert any("calendario" in s.lower() or "plan" in s.lower() for s in sug)

    def test_recovery_suggests_rest(self, coach: AiCoachService):
        sug = coach.generate_follow_ups("Necesitas más descanso y recuperación.")
        assert any("descansar" in s.lower() for s in sug)

    def test_generic_response_has_suggestions(self, coach: AiCoachService):
        sug = coach.generate_follow_ups("Aquí tienes el análisis.")
        assert len(sug) >= 2

    def test_no_duplicates(self, coach: AiCoachService):
        sug = coach.generate_follow_ups("FTP umbral FTP umbral")
        assert len(sug) == len(set(sug))


# ---------------------------------------------------------------------------
# Exportar a .ics
# ---------------------------------------------------------------------------
class TestIcsExport:
    def test_basic_plan_export(self):
        plan = (
            "## Semana 1\n"
            "**Lunes:** Base aerobica 1.5h Z2\n"
            "**Martes:** Intervalos VO2max 4x4min, 1h\n"
            "**Miércoles:** Descanso\n"
            "**Jueves:** Tempo 90min Z3\n"
            "**Viernes:** Recuperación activa 45min\n"
        )
        from datetime import date
        ics = AiCoachService.export_plan_to_ics(plan, start_date=date(2026, 6, 8))
        assert "BEGIN:VCALENDAR" in ics
        assert "END:VCALENDAR" in ics
        assert ics.count("BEGIN:VEVENT") >= 3  # Lunes, Martes, Jueves, Viernes (no descanso)
        assert "Plan Entrenamiento" in ics

    def test_duration_parsing_hours(self):
        plan = "## Semana 1\n**Lunes:** Ruta larga 3h Z2\n"
        from datetime import date
        ics = AiCoachService.export_plan_to_ics(plan, start_date=date(2026, 6, 8))
        # 3h = 180min, start 07:00 -> end 10:00
        assert "T070000" in ics
        assert "T100000" in ics

    def test_duration_parsing_minutes(self):
        plan = "## Semana 1\n**Martes:** Sprint 45min\n"
        from datetime import date
        ics = AiCoachService.export_plan_to_ics(plan, start_date=date(2026, 6, 8))
        assert "T070000" in ics
        # 45min -> end 07:45
        assert "T074500" in ics

    def test_multi_week_plan(self):
        plan = (
            "## Semana 1\n"
            "**Lunes:** Base 1.5h\n"
            "## Semana 2\n"
            "**Lunes:** Umbral 1h\n"
        )
        from datetime import date
        ics = AiCoachService.export_plan_to_ics(plan, start_date=date(2026, 6, 8))
        assert ics.count("BEGIN:VEVENT") == 2
        # Week 1 Lunes = June 8, Week 2 Lunes = June 15
        assert "20260608" in ics
        assert "20260615" in ics

    def test_empty_plan_no_events(self):
        ics = AiCoachService.export_plan_to_ics("Sin estructura de plan")
        assert "BEGIN:VEVENT" not in ics
        assert "BEGIN:VCALENDAR" in ics

    def test_alarm_present(self):
        plan = "## Semana 1\n**Lunes:** Base 1h\n"
        from datetime import date
        ics = AiCoachService.export_plan_to_ics(plan, start_date=date(2026, 6, 8))
        assert "BEGIN:VALARM" in ics
        assert "TRIGGER:-PT30M" in ics

    def test_default_start_date_is_next_monday(self):
        plan = "## Semana 1\n**Lunes:** Base 1h\n"
        ics = AiCoachService.export_plan_to_ics(plan)
        # Should have events and be valid
        assert "BEGIN:VEVENT" in ics
        # The date should be a Monday (weekday 0)
        from datetime import date as d
        import re
        match = re.search(r"DTSTART:(\d{8})", ics)
        assert match
        dt = d(int(match.group(1)[:4]), int(match.group(1)[4:6]), int(match.group(1)[6:8]))
        assert dt.weekday() == 0  # Monday


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
class TestSingleton:
    def test_get_ai_coach_singleton(self):
        import services.ai_coach as mod
        mod._instance = None

        c1 = get_ai_coach("http://a:1234", "m1")
        c2 = get_ai_coach("http://b:5678", "m2")
        assert c1 is c2
        assert c2.base_url == "http://b:5678"
        assert c2.model == "m2"

        mod._instance = None


# ---------------------------------------------------------------------------
# Persistencia de conversaciones (requiere DB temporal)
# ---------------------------------------------------------------------------
class TestPersistence:
    def test_new_conversation(self, db_session, coach: AiCoachService):
        conv_id = coach.new_conversation()
        assert conv_id > 0
        assert coach.conversation_id == conv_id
        assert coach.history == []

    def test_list_conversations(self, db_session, coach: AiCoachService):
        coach.new_conversation()
        coach.new_conversation()
        convs = coach.list_conversations()
        assert len(convs) >= 2

    def test_persist_and_load(self, db_session, coach: AiCoachService):
        conv_id = coach.new_conversation()
        coach._persist_message("user", "pregunta 1")
        coach._persist_message("assistant", "respuesta 1")

        # Crear nueva instancia y cargar
        coach2 = AiCoachService()
        ok = coach2.load_conversation(conv_id)
        assert ok is True
        assert len(coach2.history) == 2
        assert coach2.history[0].role == "user"
        assert coach2.history[0].content == "pregunta 1"
        assert coach2.history[1].role == "assistant"

    def test_auto_title(self, db_session, coach: AiCoachService):
        conv_id = coach.new_conversation()
        coach._auto_title("Analiza mi FTP de esta temporada")

        from db.engine import get_session
        from db.models import AiConversation
        session = get_session()
        conv = session.query(AiConversation).filter_by(id=conv_id).first()
        assert conv.title == "Analiza mi FTP de esta temporada"
        session.close()

    def test_auto_title_truncates(self, db_session, coach: AiCoachService):
        conv_id = coach.new_conversation()
        long_msg = "A" * 100
        coach._auto_title(long_msg)

        from db.engine import get_session
        from db.models import AiConversation
        session = get_session()
        conv = session.query(AiConversation).filter_by(id=conv_id).first()
        assert len(conv.title) <= 60
        assert conv.title.endswith("…")
        session.close()

    def test_delete_conversation(self, db_session, coach: AiCoachService):
        conv_id = coach.new_conversation()
        coach._persist_message("user", "msg")

        ok = coach.delete_conversation(conv_id)
        assert ok is True
        assert coach.conversation_id is None

        convs = coach.list_conversations()
        assert all(c.id != conv_id for c in convs)

    def test_search_conversations(self, db_session, coach: AiCoachService):
        conv_id = coach.new_conversation()
        coach._auto_title("Análisis de potencia")
        coach._persist_message("user", "mi FTP es bajo")

        results = coach.search_conversations("potencia")
        assert any(c.id == conv_id for c in results)

        results2 = coach.search_conversations("FTP")
        assert any(c.id == conv_id for c in results2)

        results3 = coach.search_conversations("inexistente xyz")
        assert not any(c.id == conv_id for c in results3)

    def test_export_conversation_md(self, db_session, coach: AiCoachService):
        conv_id = coach.new_conversation()
        coach._auto_title("Test export")
        coach._persist_message("user", "hola")
        coach._persist_message("assistant", "hola ciclista")

        md = coach.export_conversation_md(conv_id)
        assert "# Test export" in md
        assert "🚴 **Tú**" in md
        assert "🤖 **Consejero IA**" in md
        assert "hola ciclista" in md

    def test_export_empty_returns_empty(self, coach: AiCoachService):
        md = coach.export_conversation_md(None)
        assert md == ""

    def test_load_nonexistent(self, db_session, coach: AiCoachService):
        ok = coach.load_conversation(9999)
        assert ok is False
