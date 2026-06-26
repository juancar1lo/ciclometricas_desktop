"""Tests para services/embedding_store.py — RAG semántico con embeddings."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from db.engine import init_db, get_session
from db.models import (
    Activity, AiConversation, AiMessage, EmbeddingDoc,
    HealthMetric, ProfileSnapshot,
)
from services.embedding_store import (
    EmbeddingStore,
    SearchResult,
    StoreStats,
    DEFAULT_EMBED_MODEL,
    SIMILARITY_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_db(tmp_path):
    """Crea una DB temporal y la inicializa."""
    db_path = tmp_path / "test_embed.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def session(tmp_db):
    """Sesión SQLAlchemy sobre la DB temporal."""
    s = get_session()
    yield s
    s.close()


def _fake_embedding(dim: int = 768) -> List[float]:
    """Genera un embedding falso normalizado."""
    vec = np.random.randn(dim).astype(float)
    vec = vec / np.linalg.norm(vec)
    return vec.tolist()


def _mock_store(dim: int = 768) -> EmbeddingStore:
    """Crea un EmbeddingStore con embeddings mockeados."""
    store = EmbeddingStore()
    # Mock para generar embeddings determinísticos
    store._generate_embedding = MagicMock(
        side_effect=lambda text: _fake_embedding(dim)
    )
    return store


def _seed_activity(session, **kwargs) -> Activity:
    """Crea una actividad de test."""
    defaults = {
        "started_at": datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
        "sport": "cycling",
        "source": "fit",
        "file_name": "test_ride.fit",
        "duration_sec": 3600,
        "distance_km": 30.0,
        "avg_power": 200.0,
        "normalized_power": 210.0,
        "tss": 80.0,
        "intensity_factor": 0.85,
        "is_manual": False,
    }
    defaults.update(kwargs)
    act = Activity(**defaults)
    session.add(act)
    session.flush()
    return act


def _seed_health(session, **kwargs) -> HealthMetric:
    """Crea un registro de salud de test."""
    defaults = {
        "date": datetime(2025, 6, 1, tzinfo=timezone.utc),
        "weight_kg": 72.5,
        "resting_hr": 48,
        "hrv": 65.0,
        "readiness": 8.0,
    }
    defaults.update(kwargs)
    h = HealthMetric(**defaults)
    session.add(h)
    session.flush()
    return h


def _seed_profile(session, **kwargs) -> ProfileSnapshot:
    """Crea un perfil de test."""
    defaults = {
        "ftp": 250,
        "weight_kg": 72.5,
        "hr_max": 185,
        "hr_lthr": 170,
    }
    defaults.update(kwargs)
    p = ProfileSnapshot(**defaults)
    session.add(p)
    session.flush()
    return p


def _seed_conversation(session) -> tuple:
    """Crea una conversación de test con mensajes."""
    conv = AiConversation(title="Test de forma", model="test")
    session.add(conv)
    session.flush()
    msg1 = AiMessage(
        conversation_id=conv.id, role="user",
        content="¿Cómo está mi forma actual?",
    )
    msg2 = AiMessage(
        conversation_id=conv.id, role="assistant",
        content="Tu CTL está en 65, con TSB de -5.",
    )
    session.add_all([msg1, msg2])
    session.flush()
    return conv, [msg1, msg2]


# ---------------------------------------------------------------------------
# Tests: EmbeddingDoc model
# ---------------------------------------------------------------------------
class TestEmbeddingDocModel:
    """Tests del modelo EmbeddingDoc."""

    def test_create_embedding_doc(self, session):
        vec = [0.1, 0.2, 0.3]
        doc = EmbeddingDoc(
            doc_type="activity",
            source_id=1,
            text="Test activity",
            embedding=json.dumps(vec),
        )
        session.add(doc)
        session.commit()
        assert doc.id is not None

    def test_get_set_embedding(self, session):
        vec = [0.1, 0.2, 0.3, 0.4]
        doc = EmbeddingDoc(
            doc_type="health",
            source_id=1,
            text="Test health",
            embedding="",
        )
        doc.set_embedding(vec)
        session.add(doc)
        session.commit()
        result = doc.get_embedding()
        assert result == vec

    def test_get_set_metadata(self, session):
        meta = {"date": "2025-06-01", "sport": "cycling"}
        doc = EmbeddingDoc(
            doc_type="activity",
            source_id=1,
            text="Test",
            embedding=json.dumps([0.1]),
        )
        doc.set_metadata(meta)
        session.add(doc)
        session.commit()
        assert doc.get_metadata() == meta

    def test_null_metadata(self, session):
        doc = EmbeddingDoc(
            doc_type="activity",
            source_id=1,
            text="Test",
            embedding=json.dumps([0.1]),
        )
        session.add(doc)
        session.commit()
        assert doc.get_metadata() is None

    def test_null_embedding(self, session):
        doc = EmbeddingDoc(
            doc_type="activity",
            source_id=1,
            text="Test",
            embedding="",
        )
        session.add(doc)
        session.commit()
        assert doc.get_embedding() is None


# ---------------------------------------------------------------------------
# Tests: Cosine similarity
# ---------------------------------------------------------------------------
class TestCosineSimilarity:
    """Tests del cálculo de similitud coseno."""

    def test_identical_vectors(self):
        vec = np.array([1.0, 0.0, 0.0])
        docs = np.array([[1.0, 0.0, 0.0]])
        sim = EmbeddingStore.cosine_similarity(vec, docs)
        assert sim[0] == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self):
        vec = np.array([1.0, 0.0, 0.0])
        docs = np.array([[0.0, 1.0, 0.0]])
        sim = EmbeddingStore.cosine_similarity(vec, docs)
        assert sim[0] == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors(self):
        vec = np.array([1.0, 0.0, 0.0])
        docs = np.array([[-1.0, 0.0, 0.0]])
        sim = EmbeddingStore.cosine_similarity(vec, docs)
        assert sim[0] == pytest.approx(-1.0, abs=1e-6)

    def test_multiple_docs(self):
        vec = np.array([1.0, 0.0, 0.0])
        docs = np.array([
            [1.0, 0.0, 0.0],  # identical
            [0.0, 1.0, 0.0],  # orthogonal
            [0.7, 0.7, 0.0],  # similar
        ])
        sim = EmbeddingStore.cosine_similarity(vec, docs)
        assert sim[0] > sim[2] > sim[1]

    def test_zero_query_vector(self):
        vec = np.array([0.0, 0.0, 0.0])
        docs = np.array([[1.0, 0.0, 0.0]])
        sim = EmbeddingStore.cosine_similarity(vec, docs)
        assert sim[0] == 0.0

    def test_1d_doc_vector(self):
        vec = np.array([1.0, 0.0, 0.0])
        docs = np.array([0.5, 0.5, 0.0])  # 1D
        sim = EmbeddingStore.cosine_similarity(vec, docs)
        assert len(sim) == 1


# ---------------------------------------------------------------------------
# Tests: Text builders
# ---------------------------------------------------------------------------
class TestTextBuilders:
    """Tests de los constructores de texto para embedding."""

    def test_activity_text_cycling(self, session):
        act = _seed_activity(session)
        text = EmbeddingStore._build_activity_text(act)
        assert "cycling" in text.lower()
        assert "30.0 km" in text or "30" in text
        assert "200" in text  # avg_power
        assert "TSS" in text

    def test_activity_text_manual(self, session):
        act = _seed_activity(
            session,
            is_manual=True,
            activity_type="strength",
            perceived_if=0.65,
            avg_power=None,
            normalized_power=None,
        )
        text = EmbeddingStore._build_activity_text(act)
        assert "Gimnasio" in text or "Fuerza" in text
        assert "IF percibido" in text

    def test_activity_text_with_climbs(self, session):
        climbs = [
            {"distance_m": 2500, "elev_gain_m": 180, "avg_gradient": 7.2, "avg_power": 280},
        ]
        act = _seed_activity(session)
        act.set_climbs(climbs)
        session.flush()
        text = EmbeddingStore._build_activity_text(act)
        assert "subida" in text.lower()

    def test_activity_text_with_mmp(self, session):
        mmp = {"5": 850, "60": 400, "300": 310, "1200": 270}
        act = _seed_activity(session)
        act.set_mmp(mmp)
        session.flush()
        text = EmbeddingStore._build_activity_text(act)
        assert "MMP" in text
        assert "850" in text

    def test_activity_metadata(self, session):
        act = _seed_activity(session)
        meta = EmbeddingStore._build_activity_metadata(act)
        assert meta["sport"] == "cycling"
        assert meta["has_power"] is True
        assert meta["tss"] == 80.0

    def test_health_text(self, session):
        h = _seed_health(session)
        text = EmbeddingStore._build_health_text(h)
        assert "72.5 kg" in text
        assert "48 ppm" in text
        assert "HRV" in text

    def test_profile_text(self, session):
        p = _seed_profile(session)
        text = EmbeddingStore._build_profile_text(p)
        assert "250 W" in text or "250" in text
        assert "72.5 kg" in text
        assert "FCL" in text

    def test_conversation_text(self, session):
        conv, msgs = _seed_conversation(session)
        text = EmbeddingStore._build_conversation_text(conv, msgs)
        assert "Test de forma" in text
        assert "forma actual" in text
        assert "CTL" in text

    def test_conversation_text_empty(self, session):
        conv = AiConversation(title="Vacía", model="test")
        session.add(conv)
        session.flush()
        text = EmbeddingStore._build_conversation_text(conv, [])
        assert text == ""


# ---------------------------------------------------------------------------
# Tests: Indexación y búsqueda
# ---------------------------------------------------------------------------
class TestIndexAndSearch:
    """Tests de indexación y búsqueda con embeddings mockeados."""

    def test_index_document(self, session):
        store = _mock_store()
        doc_id = store.index_document(
            doc_type="activity",
            source_id=1,
            text="Test ride 30km",
            metadata={"sport": "cycling"},
            session=session,
        )
        session.commit()
        assert doc_id is not None

        # Verificar que se guardó
        doc = session.query(EmbeddingDoc).filter_by(id=doc_id).first()
        assert doc is not None
        assert doc.doc_type == "activity"
        assert doc.source_id == 1
        vec = doc.get_embedding()
        assert vec is not None
        assert len(vec) == 768

    def test_index_document_update(self, session):
        store = _mock_store()
        id1 = store.index_document(
            "activity", 1, "Original text", session=session,
        )
        session.commit()
        id2 = store.index_document(
            "activity", 1, "Updated text", session=session,
        )
        session.commit()
        assert id1 == id2  # mismo doc actualizado
        doc = session.query(EmbeddingDoc).filter_by(id=id1).first()
        assert doc.text == "Updated text"

    def test_delete_document(self, session):
        store = _mock_store()
        store.index_document("activity", 1, "To delete", session=session)
        session.commit()
        count = store.delete_document("activity", 1, session=session)
        session.commit()
        assert count == 1

    def test_search_returns_results(self, tmp_db):
        """Búsqueda semántica devuelve resultados ordenados por similitud."""
        store = EmbeddingStore()

        # Crear embeddings específicos para control de similitud
        query_vec = np.array([1.0, 0.0, 0.0, 0.0])
        similar_vec = np.array([0.9, 0.1, 0.0, 0.0])
        dissimilar_vec = np.array([0.0, 0.0, 0.0, 1.0])

        # Mock: query devuelve query_vec
        call_count = [0]
        def mock_embed(text):
            nonlocal call_count
            call_count[0] += 1
            return query_vec.tolist()

        store._generate_embedding = mock_embed

        session = get_session()
        # Insertar docs con embeddings específicos
        doc1 = EmbeddingDoc(
            doc_type="activity", source_id=1,
            text="Actividad similar",
            embedding=json.dumps(similar_vec.tolist()),
        )
        doc2 = EmbeddingDoc(
            doc_type="activity", source_id=2,
            text="Actividad diferente",
            embedding=json.dumps(dissimilar_vec.tolist()),
        )
        session.add_all([doc1, doc2])
        session.commit()
        session.close()

        results = store.search("test query", top_k=5, threshold=0.0)
        assert len(results) == 2
        assert results[0].text == "Actividad similar"
        assert results[0].similarity > results[1].similarity

    def test_search_with_type_filter(self, tmp_db):
        """Filtro por tipo de documento funciona."""
        store = EmbeddingStore()
        store._generate_embedding = MagicMock(
            return_value=[1.0, 0.0, 0.0]
        )

        session = get_session()
        doc1 = EmbeddingDoc(
            doc_type="activity", source_id=1,
            text="Ride",
            embedding=json.dumps([0.9, 0.1, 0.0]),
        )
        doc2 = EmbeddingDoc(
            doc_type="health", source_id=1,
            text="Health record",
            embedding=json.dumps([0.8, 0.2, 0.0]),
        )
        session.add_all([doc1, doc2])
        session.commit()
        session.close()

        results = store.search("test", doc_types=["health"], threshold=0.0)
        assert len(results) == 1
        assert results[0].doc_type == "health"

    def test_search_threshold_filter(self, tmp_db):
        """Solo devuelve resultados por encima del threshold."""
        store = EmbeddingStore()
        store._generate_embedding = MagicMock(
            return_value=[1.0, 0.0, 0.0]
        )

        session = get_session()
        doc = EmbeddingDoc(
            doc_type="activity", source_id=1,
            text="Muy diferente",
            embedding=json.dumps([0.0, 1.0, 0.0]),  # ortogonal
        )
        session.add(doc)
        session.commit()
        session.close()

        results = store.search("test", threshold=0.5)
        assert len(results) == 0

    def test_search_empty_store(self, tmp_db):
        store = _mock_store()
        results = store.search("test query")
        assert results == []


# ---------------------------------------------------------------------------
# Tests: Indexación individual
# ---------------------------------------------------------------------------
class TestIndividualIndexing:
    """Tests de indexación de registros individuales."""

    def test_index_activity(self, session):
        act = _seed_activity(session)
        session.commit()
        store = _mock_store()
        doc_id = store.index_activity(act.id)
        assert doc_id is not None

    def test_index_health(self, session):
        h = _seed_health(session)
        session.commit()
        store = _mock_store()
        doc_id = store.index_health(h.id)
        assert doc_id is not None

    def test_index_profile(self, session):
        p = _seed_profile(session)
        session.commit()
        store = _mock_store()
        doc_id = store.index_profile(p.id)
        assert doc_id is not None

    def test_index_conversation(self, session):
        conv, _ = _seed_conversation(session)
        session.commit()
        store = _mock_store()
        doc_id = store.index_conversation(conv.id)
        assert doc_id is not None

    def test_index_nonexistent_activity(self, session):
        store = _mock_store()
        doc_id = store.index_activity(99999)
        assert doc_id is None


# ---------------------------------------------------------------------------
# Tests: Reindex masivo
# ---------------------------------------------------------------------------
class TestReindex:
    """Tests de reindexación masiva."""

    def test_reindex_all(self, session):
        _seed_activity(session)
        _seed_activity(
            session,
            started_at=datetime(2025, 6, 2, 10, 0, tzinfo=timezone.utc),
            file_name="ride2.fit",
        )
        _seed_health(session)
        _seed_profile(session)
        _seed_conversation(session)
        session.commit()

        store = _mock_store()
        counts = store.reindex_all()
        assert counts.get("activity", 0) == 2
        assert counts.get("health", 0) == 1
        assert counts.get("profile", 0) == 1
        assert counts.get("conversation", 0) == 1

    def test_reindex_with_progress(self, session):
        _seed_activity(session)
        session.commit()

        progress_calls = []
        store = _mock_store()
        store.reindex_all(on_progress=lambda s, t, m: progress_calls.append((s, t, m)))
        assert len(progress_calls) > 0

    def test_clear_all(self, session):
        store = _mock_store()
        store.index_document("activity", 1, "Test 1", session=session)
        store.index_document("activity", 2, "Test 2", session=session)
        session.commit()

        deleted = store.clear_all()
        assert deleted == 2

        remaining = session.query(EmbeddingDoc).count()
        assert remaining == 0


# ---------------------------------------------------------------------------
# Tests: search_for_context
# ---------------------------------------------------------------------------
class TestSearchForContext:
    """Tests del helper search_for_context para integración con context_engine."""

    def test_search_for_context_format(self, tmp_db):
        store = EmbeddingStore()
        store._generate_embedding = MagicMock(
            return_value=[1.0, 0.0, 0.0, 0.0]
        )

        session = get_session()
        doc = EmbeddingDoc(
            doc_type="activity", source_id=1,
            text="Ruta de 50km por montaña",
            embedding=json.dumps([0.95, 0.05, 0.0, 0.0]),
            metadata_json=json.dumps({"date": "2025-06-01"}),
        )
        session.add(doc)
        session.commit()
        session.close()

        text, sources = store.search_for_context("ruta montaña")
        assert "Datos históricos" in text
        assert "relevancia" in text
        assert len(sources) > 0

    def test_search_for_context_empty(self, tmp_db):
        store = _mock_store()
        text, sources = store.search_for_context("algo")
        assert text == ""
        assert sources == []

    def test_search_for_context_respects_max_chars(self, tmp_db):
        store = EmbeddingStore()
        store._generate_embedding = MagicMock(
            return_value=[1.0, 0.0, 0.0]
        )

        session = get_session()
        for i in range(10):
            doc = EmbeddingDoc(
                doc_type="activity", source_id=i + 1,
                text="A" * 500,
                embedding=json.dumps([0.9, 0.1 * (i + 1) / 10, 0.0]),
            )
            session.add(doc)
        session.commit()
        session.close()

        text, sources = store.search_for_context("test", max_chars=800)
        assert len(text) <= 850  # con pequeño margen


# ---------------------------------------------------------------------------
# Tests: StoreStats
# ---------------------------------------------------------------------------
class TestStoreStats:
    """Tests de estadísticas del store."""

    def test_stats_empty(self, tmp_db):
        store = EmbeddingStore()
        stats = store.get_stats()
        assert stats.total_docs == 0
        assert stats.model == DEFAULT_EMBED_MODEL

    def test_stats_with_docs(self, tmp_db):
        session = get_session()
        for i in range(3):
            session.add(EmbeddingDoc(
                doc_type="activity", source_id=i + 1,
                text=f"Activity {i}",
                embedding=json.dumps([float(i)]),
            ))
        session.add(EmbeddingDoc(
            doc_type="health", source_id=1,
            text="Health",
            embedding=json.dumps([1.0]),
        ))
        session.commit()
        session.close()

        store = EmbeddingStore()
        stats = store.get_stats()
        assert stats.total_docs == 4
        assert stats.by_type["activity"] == 3
        assert stats.by_type["health"] == 1


# ---------------------------------------------------------------------------
# Tests: Embedding generation mock
# ---------------------------------------------------------------------------
class TestEmbeddingGeneration:
    """Tests de la generación de embeddings."""

    def test_empty_text_returns_none(self):
        store = EmbeddingStore()
        result = store._generate_embedding("")
        assert result is None

    def test_whitespace_text_returns_none(self):
        store = EmbeddingStore()
        result = store._generate_embedding("   ")
        assert result is None

    @patch("requests.post")
    def test_successful_embedding(self, mock_post):
        vec = [0.1] * 768
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"embedding": vec}),
            raise_for_status=MagicMock(),
        )
        store = EmbeddingStore()
        result = store._generate_embedding("test text")
        assert result == vec
        assert store._embedding_dim == 768

    @patch("requests.post", side_effect=ConnectionError("No Ollama"))
    def test_connection_error_returns_none(self, mock_post):
        store = EmbeddingStore()
        result = store._generate_embedding("test")
        assert result is None

    @patch("requests.post")
    def test_bad_response_returns_none(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"error": "model not found"}),
            raise_for_status=MagicMock(),
        )
        store = EmbeddingStore()
        result = store._generate_embedding("test")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: is_available
# ---------------------------------------------------------------------------
class TestAvailability:
    """Tests de comprobación de disponibilidad."""

    @patch("requests.get")
    def test_available_with_model(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "models": [{"name": "nomic-embed-text:latest", "size": 274000000}],
            }),
        )
        store = EmbeddingStore()
        assert store.is_available() is True

    @patch("requests.get")
    def test_not_available_without_model(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "models": [{"name": "llama3:latest", "size": 4000000000}],
            }),
        )
        store = EmbeddingStore()
        assert store.is_available() is False

    @patch("requests.get", side_effect=ConnectionError)
    def test_not_available_connection_error(self, mock_get):
        store = EmbeddingStore()
        assert store.is_available() is False


# ---------------------------------------------------------------------------
# Tests: _semantic_doc_types (context_engine integration)
# ---------------------------------------------------------------------------
class TestSemanticDocTypes:
    """Tests del mapeo de categorías a tipos de documento."""

    def test_form_maps_to_activity_health(self):
        from services.context_engine import _semantic_doc_types, QueryCategory
        result = _semantic_doc_types([QueryCategory.FORM])
        assert "activity" in result
        assert "health" in result

    def test_general_returns_none(self):
        from services.context_engine import _semantic_doc_types, QueryCategory
        result = _semantic_doc_types([QueryCategory.GENERAL])
        assert result is None

    def test_multi_category_merge(self):
        from services.context_engine import _semantic_doc_types, QueryCategory
        result = _semantic_doc_types([QueryCategory.PERFORMANCE, QueryCategory.HEALTH])
        assert "activity" in result
        assert "health" in result
        assert "profile" in result
