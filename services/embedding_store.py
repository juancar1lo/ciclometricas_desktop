"""Almacén de embeddings vectoriales para RAG semántico.

Usa Ollama como backend de embeddings (modelo nomic-embed-text)
y SQLite + numpy para almacenamiento y búsqueda por similitud coseno.

Todo el procesamiento es 100% local.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import requests
from requests.exceptions import ConnectionError, Timeout
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import (
    Activity, AiConversation, AiMessage, EmbeddingDoc,
    HealthMetric, ProfileSnapshot,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
EMBED_TIMEOUT = 30  # segundos por request
MAX_CHUNK_CHARS = 1500  # máximo de caracteres por chunk de texto
DEFAULT_TOP_K = 5  # resultados por búsqueda
SIMILARITY_THRESHOLD = 0.35  # mínimo de similitud para incluir


# ---------------------------------------------------------------------------
# Resultado de búsqueda
# ---------------------------------------------------------------------------
@dataclass
class SearchResult:
    """Un resultado de búsqueda semántica."""
    doc_id: int
    doc_type: str
    source_id: int
    text: str
    similarity: float
    metadata: Optional[dict] = None


# ---------------------------------------------------------------------------
# Estado del store
# ---------------------------------------------------------------------------
@dataclass
class StoreStats:
    """Estadísticas del almacén de embeddings."""
    total_docs: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    model: str = ""
    is_available: bool = False


# ---------------------------------------------------------------------------
# Servicio principal
# ---------------------------------------------------------------------------
class EmbeddingStore:
    """Gestiona la indexación y búsqueda de documentos vectorizados.

    Usa Ollama para generar embeddings y SQLite para almacenarlos.
    La búsqueda se realiza por similitud coseno con numpy.
    """

    def __init__(
        self,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_EMBED_MODEL,
    ):
        self._base_url = ollama_url.rstrip("/")
        self._model = model
        self._embedding_dim: Optional[int] = None

    # ---- Propiedades -------------------------------------------------------

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, name: str) -> None:
        self._model = name
        self._embedding_dim = None

    @property
    def base_url(self) -> str:
        return self._base_url

    @base_url.setter
    def base_url(self, url: str) -> None:
        self._base_url = url.rstrip("/")

    # ---- Comunicación con Ollama -------------------------------------------

    def is_available(self) -> bool:
        """Comprueba si Ollama está accesible y el modelo de embeddings está instalado."""
        try:
            r = requests.get(
                f"{self._base_url}/api/tags",
                timeout=5,
            )
            if r.status_code != 200:
                return False
            models = [m.get("name", "") for m in r.json().get("models", [])]
            # Comprobar si el modelo está disponible (nombre exacto o con :latest)
            for m in models:
                base = m.split(":")[0]
                if base == self._model or m == self._model:
                    return True
            return False
        except (ConnectionError, Timeout, Exception):
            return False

    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """Genera un embedding para un texto usando Ollama.

        Returns:
            Lista de floats con el vector, o None si falla.
        """
        if not text.strip():
            return None
        try:
            r = requests.post(
                f"{self._base_url}/api/embeddings",
                json={
                    "model": self._model,
                    "prompt": text.strip(),
                },
                timeout=EMBED_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            vec = data.get("embedding")
            if vec and isinstance(vec, list):
                if self._embedding_dim is None:
                    self._embedding_dim = len(vec)
                return vec
            return None
        except (ConnectionError, Timeout) as exc:
            log.warning("Ollama no accesible para embeddings: %s", exc)
            return None
        except Exception as exc:
            log.error("Error generando embedding: %s", exc)
            return None

    def _generate_embeddings_batch(
        self, texts: List[str]
    ) -> List[Optional[List[float]]]:
        """Genera embeddings para un lote de textos.

        Procesa uno a uno (la API de Ollama no soporta batch nativo)
        pero lo envuelve para un uso más limpio.
        """
        results: List[Optional[List[float]]] = []
        for text in texts:
            vec = self._generate_embedding(text)
            results.append(vec)
        return results

    # ---- Similitud ---------------------------------------------------------

    @staticmethod
    def cosine_similarity(
        query_vec: np.ndarray,
        doc_vecs: np.ndarray,
    ) -> np.ndarray:
        """Calcula similitud coseno entre un query y múltiples documentos.

        Args:
            query_vec: Vector 1D (dim,)
            doc_vecs: Matriz 2D (n_docs, dim)

        Returns:
            Array 1D (n_docs,) con similitudes.
        """
        if doc_vecs.ndim == 1:
            doc_vecs = doc_vecs.reshape(1, -1)

        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return np.zeros(doc_vecs.shape[0])

        doc_norms = np.linalg.norm(doc_vecs, axis=1)
        # Evitar división por cero
        doc_norms = np.where(doc_norms == 0, 1e-10, doc_norms)

        return np.dot(doc_vecs, query_vec) / (doc_norms * query_norm)

    # ---- CRUD de documentos ------------------------------------------------

    def index_document(
        self,
        doc_type: str,
        source_id: int,
        text: str,
        metadata: Optional[dict] = None,
        chunk_index: int = 0,
        session: Optional[Session] = None,
    ) -> Optional[int]:
        """Indexa un documento generando su embedding.

        Si ya existe un doc con el mismo (doc_type, source_id, chunk_index),
        lo actualiza.

        Returns:
            ID del documento, o None si falla.
        """
        vec = self._generate_embedding(text)
        if vec is None:
            return None

        own_session = session is None
        if own_session:
            try:
                session = get_session()
            except RuntimeError:
                return None

        try:
            # Buscar existente
            existing = (
                session.query(EmbeddingDoc)
                .filter_by(
                    doc_type=doc_type,
                    source_id=source_id,
                    chunk_index=chunk_index,
                )
                .first()
            )

            if existing:
                existing.text = text
                existing.set_embedding(vec)
                if metadata is not None:
                    existing.set_metadata(metadata)
                existing.updated_at = datetime.now(timezone.utc)
                doc_id = existing.id
            else:
                doc = EmbeddingDoc(
                    doc_type=doc_type,
                    source_id=source_id,
                    chunk_index=chunk_index,
                    text=text,
                    embedding=json.dumps(vec),
                    metadata_json=json.dumps(metadata) if metadata else None,
                )
                session.add(doc)
                session.flush()
                doc_id = doc.id

            if own_session:
                session.commit()
            return doc_id

        except Exception as exc:
            log.error("Error indexando documento: %s", exc)
            if own_session:
                session.rollback()
            return None
        finally:
            if own_session:
                session.close()

    def delete_document(
        self,
        doc_type: str,
        source_id: int,
        session: Optional[Session] = None,
    ) -> int:
        """Elimina todos los chunks de un documento.

        Returns:
            Número de filas eliminadas.
        """
        own_session = session is None
        if own_session:
            try:
                session = get_session()
            except RuntimeError:
                return 0

        try:
            count = (
                session.query(EmbeddingDoc)
                .filter_by(doc_type=doc_type, source_id=source_id)
                .delete()
            )
            if own_session:
                session.commit()
            return count
        except Exception as exc:
            log.error("Error eliminando documento: %s", exc)
            if own_session:
                session.rollback()
            return 0
        finally:
            if own_session:
                session.close()

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        doc_types: Optional[List[str]] = None,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> List[SearchResult]:
        """Búsqueda semántica por similitud coseno.

        Args:
            query: Texto de búsqueda.
            top_k: Máximo de resultados.
            doc_types: Filtrar por tipos de documento (None = todos).
            threshold: Similitud mínima para incluir.

        Returns:
            Lista de SearchResult ordenada por similitud descendente.
        """
        query_vec = self._generate_embedding(query)
        if query_vec is None:
            return []

        try:
            session = get_session()
        except RuntimeError:
            return []

        try:
            q = session.query(EmbeddingDoc)
            if doc_types:
                q = q.filter(EmbeddingDoc.doc_type.in_(doc_types))
            docs = q.all()

            if not docs:
                return []

            # Construir matriz de embeddings
            valid_docs: List[EmbeddingDoc] = []
            vectors: List[List[float]] = []
            for doc in docs:
                vec = doc.get_embedding()
                if vec:
                    valid_docs.append(doc)
                    vectors.append(vec)

            if not valid_docs:
                return []

            query_np = np.array(query_vec, dtype=np.float32)
            docs_np = np.array(vectors, dtype=np.float32)

            similarities = self.cosine_similarity(query_np, docs_np)

            # Filtrar y ordenar
            results: List[SearchResult] = []
            indices = np.argsort(similarities)[::-1]  # descendente

            for idx in indices[:top_k * 2]:  # mirar un poco más por si el threshold filtra
                sim = float(similarities[idx])
                if sim < threshold:
                    continue
                doc = valid_docs[idx]
                results.append(SearchResult(
                    doc_id=doc.id,
                    doc_type=doc.doc_type,
                    source_id=doc.source_id,
                    text=doc.text,
                    similarity=round(sim, 4),
                    metadata=doc.get_metadata(),
                ))
                if len(results) >= top_k:
                    break

            return results

        except Exception as exc:
            log.error("Error en búsqueda semántica: %s", exc)
            return []
        finally:
            session.close()

    def get_stats(self) -> StoreStats:
        """Devuelve estadísticas del almacén."""
        stats = StoreStats(
            model=self._model,
            is_available=self.is_available(),
        )
        try:
            session = get_session()
            docs = session.query(EmbeddingDoc.doc_type).all()
            stats.total_docs = len(docs)
            for (dt,) in docs:
                stats.by_type[dt] = stats.by_type.get(dt, 0) + 1
            session.close()
        except Exception:
            pass
        return stats

    # ---- Indexación masiva -------------------------------------------------

    def reindex_all(
        self,
        on_progress: Optional[callable] = None,
    ) -> Dict[str, int]:
        """Reindexar todos los documentos de la base de datos.

        Args:
            on_progress: Callback(step: int, total: int, msg: str)

        Returns:
            Dict con contadores {doc_type: n_indexed}.
        """
        counts: Dict[str, int] = {}

        try:
            session = get_session()
        except RuntimeError:
            return counts

        try:
            # 1. Actividades
            activities = session.query(Activity).all()
            total = len(activities)
            for i, act in enumerate(activities):
                text = self._build_activity_text(act)
                if text:
                    meta = self._build_activity_metadata(act)
                    doc_id = self.index_document(
                        "activity", act.id, text, meta, session=session,
                    )
                    if doc_id:
                        counts["activity"] = counts.get("activity", 0) + 1
                if on_progress:
                    on_progress(i + 1, total, f"Actividades: {i + 1}/{total}")

            # 2. Salud
            health_records = session.query(HealthMetric).all()
            total_h = len(health_records)
            for i, h in enumerate(health_records):
                text = self._build_health_text(h)
                if text:
                    meta = {"date": h.date.isoformat() if h.date else None}
                    doc_id = self.index_document(
                        "health", h.id, text, meta, session=session,
                    )
                    if doc_id:
                        counts["health"] = counts.get("health", 0) + 1
                if on_progress:
                    on_progress(i + 1, total_h, f"Salud: {i + 1}/{total_h}")

            # 3. Perfiles
            profiles = session.query(ProfileSnapshot).all()
            for p in profiles:
                text = self._build_profile_text(p)
                if text:
                    meta = {"date": p.effective_at.isoformat() if p.effective_at else None}
                    doc_id = self.index_document(
                        "profile", p.id, text, meta, session=session,
                    )
                    if doc_id:
                        counts["profile"] = counts.get("profile", 0) + 1

            # 4. Conversaciones del coach
            conversations = session.query(AiConversation).all()
            for conv in conversations:
                messages = (
                    session.query(AiMessage)
                    .filter_by(conversation_id=conv.id)
                    .order_by(AiMessage.created_at)
                    .all()
                )
                text = self._build_conversation_text(conv, messages)
                if text:
                    meta = {
                        "title": conv.title,
                        "date": conv.created_at.isoformat() if conv.created_at else None,
                        "n_messages": len(messages),
                    }
                    doc_id = self.index_document(
                        "conversation", conv.id, text, meta, session=session,
                    )
                    if doc_id:
                        counts["conversation"] = counts.get("conversation", 0) + 1

            session.commit()
        except Exception as exc:
            log.error("Error en reindexación: %s", exc)
            session.rollback()
        finally:
            session.close()

        return counts

    def clear_all(self) -> int:
        """Elimina todos los embeddings. Devuelve filas eliminadas."""
        try:
            session = get_session()
            count = session.query(EmbeddingDoc).delete()
            session.commit()
            session.close()
            return count
        except Exception:
            return 0

    # ---- Indexación individual ---------------------------------------------

    def index_activity(self, activity_id: int) -> Optional[int]:
        """Indexa una actividad por su ID."""
        try:
            session = get_session()
            act = session.query(Activity).filter_by(id=activity_id).first()
            if not act:
                session.close()
                return None
            text = self._build_activity_text(act)
            if not text:
                session.close()
                return None
            meta = self._build_activity_metadata(act)
            doc_id = self.index_document(
                "activity", act.id, text, meta, session=session,
            )
            session.commit()
            session.close()
            return doc_id
        except Exception as exc:
            log.error("Error indexando actividad %d: %s", activity_id, exc)
            return None

    def index_health(self, health_id: int) -> Optional[int]:
        """Indexa un registro de salud por su ID."""
        try:
            session = get_session()
            h = session.query(HealthMetric).filter_by(id=health_id).first()
            if not h:
                session.close()
                return None
            text = self._build_health_text(h)
            if not text:
                session.close()
                return None
            meta = {"date": h.date.isoformat() if h.date else None}
            doc_id = self.index_document(
                "health", h.id, text, meta, session=session,
            )
            session.commit()
            session.close()
            return doc_id
        except Exception as exc:
            log.error("Error indexando salud %d: %s", health_id, exc)
            return None

    def index_conversation(self, conv_id: int) -> Optional[int]:
        """Indexa una conversación del AI Coach."""
        try:
            session = get_session()
            conv = session.query(AiConversation).filter_by(id=conv_id).first()
            if not conv:
                session.close()
                return None
            messages = (
                session.query(AiMessage)
                .filter_by(conversation_id=conv_id)
                .order_by(AiMessage.created_at)
                .all()
            )
            text = self._build_conversation_text(conv, messages)
            if not text:
                session.close()
                return None
            meta = {
                "title": conv.title,
                "date": conv.created_at.isoformat() if conv.created_at else None,
                "n_messages": len(messages),
            }
            doc_id = self.index_document(
                "conversation", conv.id, text, meta, session=session,
            )
            session.commit()
            session.close()
            return doc_id
        except Exception as exc:
            log.error("Error indexando conversación %d: %s", conv_id, exc)
            return None

    def index_profile(self, profile_id: int) -> Optional[int]:
        """Indexa un snapshot de perfil."""
        try:
            session = get_session()
            p = session.query(ProfileSnapshot).filter_by(id=profile_id).first()
            if not p:
                session.close()
                return None
            text = self._build_profile_text(p)
            if not text:
                session.close()
                return None
            meta = {"date": p.effective_at.isoformat() if p.effective_at else None}
            doc_id = self.index_document(
                "profile", p.id, text, meta, session=session,
            )
            session.commit()
            session.close()
            return doc_id
        except Exception as exc:
            log.error("Error indexando perfil %d: %s", profile_id, exc)
            return None

    # ---- Constructores de texto para indexación ----------------------------

    @staticmethod
    def _build_activity_text(act: Activity) -> str:
        """Genera texto descriptivo de una actividad para embedding."""
        parts: List[str] = []

        date_str = act.started_at.strftime("%d/%m/%Y") if act.started_at else "?"
        name = act.display_name

        # Tipo de actividad
        if act.is_manual:
            type_label = {
                "strength": "Gimnasio/Fuerza",
                "walk": "Caminata",
                "other": "Otro",
            }.get(act.activity_type or "", "Manual")
            parts.append(f"Sesión {type_label} del {date_str}: {name}")
        else:
            sport = act.sport or "cycling"
            parts.append(f"Actividad de {sport} del {date_str}: {name}")

        # Duración
        if act.duration_sec:
            dur_min = round(act.duration_sec / 60)
            dur_h = round(act.duration_sec / 3600, 1)
            if dur_h >= 1:
                parts.append(f"Duración: {dur_h}h ({dur_min} minutos)")
            else:
                parts.append(f"Duración: {dur_min} minutos")

        # Distancia y desnivel
        if act.distance_km:
            parts.append(f"Distancia: {round(act.distance_km, 1)} km")
        if act.elevation_gain_m:
            parts.append(f"Desnivel positivo: {round(act.elevation_gain_m)} m")

        # Potencia
        if act.avg_power:
            parts.append(f"Potencia media: {round(act.avg_power)} W")
        if act.normalized_power:
            parts.append(f"NP: {round(act.normalized_power)} W")
        if act.max_power:
            parts.append(f"Potencia máxima: {act.max_power} W")

        # Métricas de carga
        if act.tss:
            parts.append(f"TSS: {round(act.tss)}")
        if act.intensity_factor:
            parts.append(f"IF: {round(act.intensity_factor, 2)}")
        if act.work_kj:
            parts.append(f"Trabajo: {round(act.work_kj)} kJ")

        # FC
        if act.avg_hr:
            parts.append(f"FC media: {act.avg_hr} ppm")
        if act.max_hr:
            parts.append(f"FC máxima: {act.max_hr} ppm")

        # Cadencia
        if act.avg_cadence:
            parts.append(f"Cadencia media: {round(act.avg_cadence)} rpm")

        # Velocidad
        if act.avg_speed_kmh:
            parts.append(f"Velocidad media: {round(act.avg_speed_kmh, 1)} km/h")

        # Balance pedaleo
        if act.avg_left_balance is not None:
            lb = round(act.avg_left_balance, 1)
            parts.append(f"Balance pedaleo: {lb}% izq / {round(100 - lb, 1)}% der")

        # FTP de referencia
        if act.ftp_used:
            parts.append(f"FTP referencia: {act.ftp_used} W")

        # Zonas de potencia (resumen)
        zones_p = act.get_zones_power()
        if zones_p:
            total_z = sum(zones_p.values()) or 1
            z_summary = []
            for zk in sorted(zones_p.keys()):
                pct = round(zones_p[zk] / total_z * 100)
                if pct >= 5:  # solo zonas significativas
                    z_summary.append(f"{zk.upper()}={pct}%")
            if z_summary:
                parts.append(f"Zonas potencia: {', '.join(z_summary)}")

        # Subidas
        climbs = act.get_climbs()
        if climbs:
            parts.append(f"{len(climbs)} subidas detectadas")
            for cl in sorted(climbs, key=lambda c: c.get("elev_gain_m", 0), reverse=True)[:3]:
                cl_text = (
                    f"Subida: {round(cl.get('distance_m', 0))}m, "
                    f"+{round(cl.get('elev_gain_m', 0))}m, "
                    f"{round(cl.get('avg_gradient', 0), 1)}% pendiente"
                )
                if cl.get("avg_power"):
                    cl_text += f", {cl['avg_power']}W"
                parts.append(cl_text)

        # Sesión manual: IF percibido
        if act.is_manual and act.perceived_if:
            parts.append(f"IF percibido: {round(act.perceived_if, 2)}")

        # Notas
        if act.notes:
            parts.append(f"Notas: {act.notes[:200]}")

        # MMP highlights
        mmp_data = act.get_mmp()
        if mmp_data:
            mmp_highlights = []
            for dur_sec, label in [(5, "5s"), (60, "1min"), (300, "5min"), (1200, "20min")]:
                val = mmp_data.get(str(dur_sec))
                if val:
                    mmp_highlights.append(f"{label}={round(val)}W")
            if mmp_highlights:
                parts.append(f"MMP: {', '.join(mmp_highlights)}")

        return ". ".join(parts)

    @staticmethod
    def _build_activity_metadata(act: Activity) -> dict:
        """Metadatos para filtrado rápido."""
        return {
            "date": act.started_at.isoformat() if act.started_at else None,
            "sport": act.sport,
            "is_manual": act.is_manual,
            "activity_type": act.activity_type,
            "tss": act.tss,
            "duration_sec": act.duration_sec,
            "distance_km": act.distance_km,
            "has_power": act.avg_power is not None,
        }

    @staticmethod
    def _build_health_text(h: HealthMetric) -> str:
        """Genera texto descriptivo de un registro de salud."""
        parts: List[str] = []
        date_str = h.date.strftime("%d/%m/%Y") if h.date else "?"
        parts.append(f"Registro de salud del {date_str}")

        if h.weight_kg:
            parts.append(f"Peso: {h.weight_kg} kg")
        if h.body_fat_pct:
            parts.append(f"Grasa corporal: {h.body_fat_pct}%")
        if h.resting_hr:
            parts.append(f"FC reposo: {h.resting_hr} ppm")
        if h.hrv:
            parts.append(f"HRV (RMSSD): {h.hrv} ms")
        if h.readiness:
            parts.append(f"Readiness: {h.readiness}/10")
        if h.bp_systolic and h.bp_diastolic:
            parts.append(f"Presión arterial: {h.bp_systolic}/{h.bp_diastolic} mmHg")
        if h.notes:
            parts.append(f"Notas: {h.notes[:200]}")

        return ". ".join(parts)

    @staticmethod
    def _build_profile_text(p: ProfileSnapshot) -> str:
        """Genera texto descriptivo de un perfil."""
        parts: List[str] = []
        date_str = p.effective_at.strftime("%d/%m/%Y") if p.effective_at else "?"
        parts.append(f"Perfil del atleta actualizado el {date_str}")
        parts.append(f"FTP: {p.ftp} W")
        parts.append(f"Peso: {p.weight_kg} kg")
        if p.weight_kg and p.ftp:
            parts.append(f"W/kg: {round(p.ftp / p.weight_kg, 2)}")
        parts.append(f"FC máxima: {p.hr_max} ppm")
        if p.hr_lthr:
            parts.append(f"FCL (umbral): {p.hr_lthr} ppm")
        if p.notes:
            parts.append(f"Notas: {p.notes[:200]}")
        return ". ".join(parts)

    @staticmethod
    def _build_conversation_text(
        conv: AiConversation,
        messages: List[AiMessage],
    ) -> str:
        """Genera texto de una conversación para embedding.

        Extrae los temas principales sin incluir todo el detalle.
        """
        if not messages:
            return ""

        parts: List[str] = []
        title = conv.title or "Sin título"
        date_str = conv.created_at.strftime("%d/%m/%Y") if conv.created_at else "?"
        parts.append(f"Conversación con AI Coach ({date_str}): {title}")

        # Solo incluir mensajes del usuario (preguntas = semántica del tema)
        # y un resumen compacto de las respuestas
        user_msgs = [m for m in messages if m.role == "user"]
        for um in user_msgs[:5]:  # máximo 5 preguntas por conversación
            content = um.content.strip()[:300]
            parts.append(f"Pregunta: {content}")

        # Temas clave de respuestas del asistente
        assistant_msgs = [m for m in messages if m.role == "assistant"]
        if assistant_msgs:
            # Primer y último mensaje del asistente (resumen)
            first_resp = assistant_msgs[0].content.strip()[:200]
            parts.append(f"Respuesta inicial: {first_resp}")
            if len(assistant_msgs) > 1:
                last_resp = assistant_msgs[-1].content.strip()[:200]
                parts.append(f"Última respuesta: {last_resp}")

        text = ". ".join(parts)
        # Truncar si excede
        if len(text) > MAX_CHUNK_CHARS:
            text = text[:MAX_CHUNK_CHARS]
        return text

    # ---- Helpers para la integración con context_engine --------------------

    def search_for_context(
        self,
        query: str,
        max_chars: int = 2000,
        doc_types: Optional[List[str]] = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> Tuple[str, List[str]]:
        """Busca documentos relevantes y devuelve texto formateado para el prompt.

        Returns:
            (texto_para_prompt, lista_de_fuentes_para_summary)
        """
        results = self.search(
            query=query,
            top_k=top_k,
            doc_types=doc_types,
        )
        if not results:
            return "", []

        lines: List[str] = []
        sources: List[str] = []
        total_chars = 0

        lines.append("## Datos históricos relevantes (búsqueda semántica)")
        total_chars += len(lines[0]) + 2

        type_labels = {
            "activity": "📊 Actividad",
            "health": "❤️ Salud",
            "conversation": "💬 Coach",
            "profile": "👤 Perfil",
        }

        for r in results:
            label = type_labels.get(r.doc_type, r.doc_type)
            sim_pct = round(r.similarity * 100)
            entry = f"\n### {label} (relevancia {sim_pct}%)\n{r.text}"

            if total_chars + len(entry) > max_chars:
                remaining = max_chars - total_chars - 10
                if remaining > 80:
                    entry = entry[:remaining] + "\n(...)"
                    lines.append(entry)
                break

            lines.append(entry)
            total_chars += len(entry)

            # Info para summary
            meta = r.metadata or {}
            date_info = meta.get("date", "")[:10] if meta.get("date") else ""
            source_label = label
            if date_info:
                source_label += f" {date_info}"
            sources.append(source_label)

        return "\n".join(lines), sources
