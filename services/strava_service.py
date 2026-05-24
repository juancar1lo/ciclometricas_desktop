"""Servicio de integración con Strava API v3.

Flujo OAuth desktop:
1. Pedir Client ID/Secret al usuario (primera vez)
2. Abrir browser → authorize → redirect a localhost:5765
3. Servidor HTTP local captura el code
4. Intercambiar code → access_token + refresh_token
5. Guardar tokens en config

Importación:
- GET /athlete/activities → lista de actividades
- GET /activities/{id}/streams → streams (time, power, heartrate, cadence, altitude, latlng)
- Construir TrackPoints → reutilizar import_service
"""
from __future__ import annotations

import http.server
import json
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests

# ── Constants ──
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
LOCAL_PORT = 5765
REDIRECT_URI = f"http://localhost:{LOCAL_PORT}/callback"
SCOPES = "read,activity:read_all"


@dataclass
class StravaTokens:
    access_token: str
    refresh_token: str
    expires_at: int
    athlete_name: str = ""
    athlete_id: int = 0


@dataclass
class StravaActivity:
    strava_id: int
    name: str
    sport_type: str
    started_at: datetime
    elapsed_time: int
    moving_time: int
    distance_m: float
    total_elevation: float
    avg_watts: Optional[float] = None
    max_watts: Optional[float] = None
    avg_heartrate: Optional[float] = None
    max_heartrate: Optional[float] = None
    kilojoules: Optional[float] = None
    has_power: bool = False
    has_heartrate: bool = False


@dataclass
class StravaStream:
    time: List[int] = field(default_factory=list)
    power: List[Optional[float]] = field(default_factory=list)
    heartrate: List[Optional[float]] = field(default_factory=list)
    cadence: List[Optional[float]] = field(default_factory=list)
    altitude: List[Optional[float]] = field(default_factory=list)
    latlng: List[Optional[list]] = field(default_factory=list)
    velocity: List[Optional[float]] = field(default_factory=list)


# ── OAuth Helper: Local HTTP server for callback ──

class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth authorization code."""
    auth_code: Optional[str] = None
    error: Optional[str] = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            _OAuthCallbackHandler.auth_code = params["code"][0]
            html = (
                "<html><body style='font-family:sans-serif;text-align:center;padding:60px;'"
                " bgcolor='#0a0f1e'><h2 style='color:#22d3ee'>✅ Strava vinculado</h2>"
                "<p style='color:#94a3b8'>Puedes cerrar esta ventana y volver a Ciclométricas.</p>"
                "</body></html>"
            )
        elif "error" in params:
            _OAuthCallbackHandler.error = params.get("error", ["unknown"])[0]
            html = (
                "<html><body style='font-family:sans-serif;text-align:center;padding:60px;'"
                " bgcolor='#0a0f1e'><h2 style='color:#ef4444'>❌ Error de autorización</h2>"
                f"<p style='color:#94a3b8'>{_OAuthCallbackHandler.error}</p>"
                "</body></html>"
            )
        else:
            html = "<html><body>Error inesperado</body></html>"

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Silenciar logs del servidor HTTP


# Referencia global al servidor OAuth para poder cerrarlo desde fuera
_oauth_server = None
_oauth_cancelled = False


def cancel_oauth_wait():
    """Cancela la espera del callback OAuth cerrando el servidor HTTP."""
    global _oauth_cancelled, _oauth_server
    _oauth_cancelled = True
    if _oauth_server:
        try:
            _oauth_server.server_close()
        except Exception:
            pass


def _wait_for_oauth_code(timeout: int = 120) -> Tuple[Optional[str], Optional[str]]:
    """Inicia servidor local, espera code OAuth, retorna (code, error).

    Procesa múltiples peticiones (favicon, etc.) hasta recibir el code
    o hasta que expire el timeout.
    """
    global _oauth_server, _oauth_cancelled
    _OAuthCallbackHandler.auth_code = None
    _OAuthCallbackHandler.error = None
    _oauth_cancelled = False

    import socket
    try:
        server = http.server.HTTPServer(("localhost", LOCAL_PORT), _OAuthCallbackHandler)
        server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except (OSError, socket.error) as e:
        return None, f"No se pudo iniciar el servidor de callback en puerto {LOCAL_PORT}: {e}"

    _oauth_server = server
    server.timeout = 2  # timeout por petición individual

    try:
        deadline = time.time() + timeout
        while time.time() < deadline and not _oauth_cancelled:
            try:
                server.handle_request()
            except Exception:
                break
            if _OAuthCallbackHandler.auth_code or _OAuthCallbackHandler.error:
                break
    finally:
        try:
            server.server_close()
        except Exception:
            pass
        _oauth_server = None

    if _oauth_cancelled:
        return None, "Cancelado por el usuario."

    return _OAuthCallbackHandler.auth_code, _OAuthCallbackHandler.error


# ── Strava API Client ──

def get_oauth_url(client_id: str) -> str:
    """Genera la URL de autorización OAuth de Strava (sin abrir navegador)."""
    return (
        f"{STRAVA_AUTH_URL}?"
        f"client_id={client_id}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"response_type=code&"
        f"approval_prompt=auto&"
        f"scope={SCOPES}"
    )


def wait_for_oauth_code(timeout: int = 120) -> Tuple[Optional[str], Optional[str]]:
    """Espera el callback OAuth en el servidor local (sin abrir navegador).

    Returns: (auth_code, error_message)
    """
    code, error = _wait_for_oauth_code(timeout=timeout)
    if error:
        return None, f"Error de autorización: {error}"
    if not code:
        return None, "Timeout: no se recibió autorización en 2 minutos."
    return code, None


def start_oauth_flow(client_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Abre el browser para autorización y espera el callback.

    Returns: (auth_code, error_message)
    NOTA: Bloquea el hilo — usar get_oauth_url + wait_for_oauth_code por separado
    para no bloquear la GUI.
    """
    url = get_oauth_url(client_id)
    webbrowser.open(url)
    return wait_for_oauth_code(timeout=120)


def exchange_code_for_tokens(
    client_id: str, client_secret: str, code: str
) -> Tuple[Optional[StravaTokens], Optional[str]]:
    """Intercambia authorization code por access/refresh tokens."""
    try:
        resp = requests.post(STRAVA_TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }, timeout=15)
        if resp.status_code != 200:
            return None, f"Error {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        athlete = data.get("athlete", {})
        tokens = StravaTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
            athlete_name=f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip(),
            athlete_id=athlete.get("id", 0),
        )
        return tokens, None
    except Exception as e:
        return None, str(e)


def refresh_access_token(
    client_id: str, client_secret: str, refresh_token: str
) -> Tuple[Optional[StravaTokens], Optional[str]]:
    """Renueva el access token usando refresh token."""
    try:
        resp = requests.post(STRAVA_TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=15)
        if resp.status_code != 200:
            return None, f"Error {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        tokens = StravaTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
        )
        return tokens, None
    except Exception as e:
        return None, str(e)


def _ensure_valid_token(config: dict) -> Tuple[Optional[str], Optional[str]]:
    """Devuelve access_token válido, renovando si hace falta.

    Returns: (access_token, error)
    """
    strava = config.get("strava")
    if not strava or not strava.get("access_token"):
        return None, "No hay cuenta de Strava vinculada."

    expires_at = strava.get("expires_at", 0)
    now = int(time.time())

    if now < expires_at - 60:  # aún válido (1 min margen)
        return strava["access_token"], None

    # Renovar
    client_id = strava.get("client_id", "")
    client_secret = strava.get("client_secret", "")
    refresh_tok = strava.get("refresh_token", "")
    if not client_id or not client_secret or not refresh_tok:
        return None, "Faltan credenciales de Strava. Desvincular y volver a vincular."

    new_tokens, err = refresh_access_token(client_id, client_secret, refresh_tok)
    if err:
        return None, f"Error al renovar token: {err}"

    # Actualizar config (el caller debe persistir)
    strava["access_token"] = new_tokens.access_token
    strava["refresh_token"] = new_tokens.refresh_token
    strava["expires_at"] = new_tokens.expires_at
    return new_tokens.access_token, None


def _api_get(access_token: str, endpoint: str, params: dict = None) -> Tuple[Any, Optional[str]]:
    """GET genérico a la API de Strava."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = requests.get(
            f"{STRAVA_API_BASE}{endpoint}",
            headers=headers,
            params=params or {},
            timeout=30,
        )
        if resp.status_code == 401:
            return None, "Token expirado o revocado. Desvincular y vincular de nuevo."
        if resp.status_code == 429:
            return None, "Límite de peticiones de Strava alcanzado. Inténtalo en 15 minutos."
        if resp.status_code != 200:
            return None, f"Error API Strava {resp.status_code}: {resp.text[:200]}"
        return resp.json(), None
    except requests.exceptions.Timeout:
        return None, "Timeout al contactar con Strava."
    except Exception as e:
        return None, str(e)


_CYCLING_KEYWORDS = (
    "ride", "cycling", "velodrome", "gravel", "mountain",
    "virtual", "e_bike", "ebike", "handcycle", "recumbent",
)


def fetch_activities(
    access_token: str,
    after: Optional[datetime] = None,
    per_page: int = 50,
    max_pages: int = 5,
) -> Tuple[List[StravaActivity], Optional[str]]:
    """Obtiene lista de actividades del atleta (paginación automática)."""
    all_activities: List[StravaActivity] = []

    for page in range(1, max_pages + 1):
        params: Dict[str, Any] = {"per_page": per_page, "page": page}
        if after:
            params["after"] = int(after.astimezone(timezone.utc).timestamp() if after.tzinfo else after.replace(tzinfo=timezone.utc).timestamp())

        data, err = _api_get(access_token, "/athlete/activities", params)
        if err:
            # Si ya tenemos algunas, devolvemos lo que tenemos + warning
            if all_activities:
                print(f"[Strava] Warning pág {page}: {err}")
                break
            return [], err

        if not data:
            break  # No hay más páginas

        for a in data:
            sport = a.get("sport_type", a.get("type", "Ride"))
            # Solo actividades de ciclismo
            if not any(kw in sport.lower() for kw in _CYCLING_KEYWORDS):
                print(f"[Strava] Ignorada (no ciclismo): {a.get('name', '?')} tipo={sport}")
                continue
            try:
                started = datetime.fromisoformat(a["start_date"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue

            all_activities.append(StravaActivity(
                strava_id=a["id"],
                name=a.get("name", "Actividad"),
                sport_type=sport,
                started_at=started,
                elapsed_time=a.get("elapsed_time", 0),
                moving_time=a.get("moving_time", 0),
                distance_m=a.get("distance", 0),
                total_elevation=a.get("total_elevation_gain", 0),
                avg_watts=a.get("average_watts"),
                max_watts=a.get("max_watts"),
                avg_heartrate=a.get("average_heartrate"),
                max_heartrate=a.get("max_heartrate"),
                kilojoules=a.get("kilojoules"),
                has_power=a.get("device_watts", False),
                has_heartrate=a.get("has_heartrate", False),
            ))

        if len(data) < per_page:
            break  # Última página

    print(f"[Strava] Total actividades de ciclismo encontradas: {len(all_activities)}")
    return all_activities, None


def fetch_activity_streams(
    access_token: str, activity_id: int
) -> Tuple[Optional[StravaStream], Optional[str]]:
    """Descarga streams completos de una actividad."""
    keys = "time,watts,heartrate,cadence,altitude,latlng,velocity_smooth"
    data, err = _api_get(
        access_token,
        f"/activities/{activity_id}/streams",
        {"keys": keys, "key_by_type": True},
    )
    if err:
        return None, err
    if not data:
        return None, "No se recibieron streams."

    # La API puede devolver dict (key_by_type=true) o lista de objetos
    if isinstance(data, list):
        # Convertir lista [{type: "time", data: [...]}, ...] → dict
        keyed: Dict[str, Any] = {}
        for item in data:
            if isinstance(item, dict) and "type" in item:
                keyed[item["type"]] = item
        data = keyed
    elif not isinstance(data, dict):
        return None, f"Formato inesperado de streams: {type(data).__name__}"

    stream = StravaStream()
    stream.time = data.get("time", {}).get("data", [])
    stream.power = data.get("watts", {}).get("data", [])
    stream.heartrate = data.get("heartrate", {}).get("data", [])
    stream.cadence = data.get("cadence", {}).get("data", [])
    stream.altitude = data.get("altitude", {}).get("data", [])
    stream.latlng = data.get("latlng", {}).get("data", [])
    stream.velocity = data.get("velocity_smooth", {}).get("data", [])

    if not stream.time:
        return None, "Sin datos de tiempo en los streams."

    print(f"[Strava] Streams OK id={activity_id}: {len(stream.time)} pts, "
          f"power={len(stream.power)}, hr={len(stream.heartrate)}")
    return stream, None


def stream_to_trackpoints(
    activity: StravaActivity, stream: StravaStream
) -> list:
    """Convierte StravaStream a lista de dicts compatibles con import_service samples."""
    n = len(stream.time)
    samples = []
    for i in range(n):
        t = stream.time[i]
        sample: dict = {"t": t}
        sample["p"] = stream.power[i] if i < len(stream.power) else None
        sample["hr"] = stream.heartrate[i] if i < len(stream.heartrate) else None
        sample["c"] = stream.cadence[i] if i < len(stream.cadence) else None
        sample["alt"] = stream.altitude[i] if i < len(stream.altitude) else None
        if i < len(stream.latlng) and stream.latlng[i]:
            sample["lat"] = round(stream.latlng[i][0], 6)
            sample["lng"] = round(stream.latlng[i][1], 6)
        if i < len(stream.velocity) and stream.velocity[i]:
            sample["s"] = round(stream.velocity[i], 2)
        samples.append(sample)

    # Downsample a ~5s
    if len(samples) > 100:
        downsampled = []
        last_t = -5
        for s in samples:
            if s["t"] - last_t >= 5:
                downsampled.append(s)
                last_t = s["t"]
        if samples and (not downsampled or downsampled[-1]["t"] != samples[-1]["t"]):
            downsampled.append(samples[-1])
        samples = downsampled

    return samples
