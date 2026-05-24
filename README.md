# 🚴 Ciclométricas Desktop

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests: 170](https://img.shields.io/badge/tests-170%20passing-brightgreen.svg)]()
[![Version: 2.0](https://img.shields.io/badge/version-2.0.0-orange.svg)]()

**Análisis avanzado de rendimiento en ciclismo.**

Aplicación de escritorio gratuita, de código abierto y multiplataforma, construida con Python + PySide6 (Qt 6). Analiza potencia, frecuencia cardíaca, cadencia y equilibrio de pedaleo a partir de archivos **FIT** y **TCX**, con integración directa con **Strava**.

---

## ✨ Características principales

### 📊 Modelo de Potencia Crítica (CP)
- Regresión lineal Monod-Scherrer con estimación de **CP**, **W′**, **mFTP**, **VO₂max** y potencia de sprint
- Indicador de fiabilidad **R²** con badge visual
- **TTE** (Tiempo hasta el Agotamiento) con estimaciones detalladas por zona: Sweet Spot (~2–4h), Tempo (~3–5h), Resistencia (>5h)
- Evolución histórica de CP y W′ con gráfico de tendencia

### 📈 Curva de Potencia-Duración (DCP)
- MMP global con suavizado Savitzky-Golay y escala logarítmica (5s → 45min)
- Bandas de targeting para planificación de intervalos
- Tarjetas de rangos sugeridos por duración

### 🔥 Carga y Forma (CTL / ATL / TSB)
- Modelo exponencial de carga crónica y aguda con **previsión a futuro**
- Rampa semanal (ΔCTL pts/semana)
- Gráfico de Forma con bandas: alto riesgo, óptimo, productivo, fresco, transición

### 🎯 Preparación para Competir (RRS)
- Puntuación 0–100 basada en forma, fitness, consistencia y tendencia
- Gauge semicircular con consejo personalizado

### 🧪 Durabilidad (DRI)
- Tests empíricos: CP fresca vs fatigada
- Modelo de decaimiento exponencial con extrapolación
- Gráfico de área entre curvas y clasificación (excelente → limitante)

### ❤️‍🩹 Módulo de Salud *(nuevo en v2.0)*
- FC en reposo, HRV, presión arterial, readiness, peso, grasa corporal, grasa subcutánea
- **3 gráficos interactivos:** cardiovascular (FC + HRV + readiness), presión arterial (candlestick), composición corporal
- Normalización de readiness desde Garmin, Whoop, Oura, COROS, Elite HRV o manual
- Tabla histórica con edición y borrado inline

### 🦶 Balance de Pedaleo *(nuevo en v2.0)*
- Análisis izquierda/derecha con barra visual
- Clasificación: equilibrado, leve asimetría, asimetría notable
- Detección de pierna dominante (requiere potenciómetro dual)

### 📊 Tendencias de Eficiencia *(mejorado en v2.0)*
- EF (NP/FC), VF (NP/Pmedia) y Pw:Hr (desacople potencia/FC)
- **3 ejes Y independientes** con escalas propias para mayor claridad

### 📉 Más análisis
- **Zonas de potencia** — Coggan (8 zonas incluyendo Sweet Spot), referencia configurable: FTP, CP o mFTP
- **Zonas de FC** — Friel (7 zonas basadas en FCL/LTHR) *(actualizado en v2.0)*
- **Resistencia a la fatiga** — Índice FR por actividad con clasificación y tendencia
- **Monotonía (Foster)** — Detección de patrones de carga peligrosos
- **Recuperación** — Gauge de estado actual, proyección TSB a 7 días
- **W′ Balance** — Modelo diferencial de Skiba (2012) en tiempo real
- **Análisis de cuadrantes** — Distribución de pedaleo (Coggan)
- **Detección de intervalos** — Automática con métricas de potencia, FC, cadencia
- **Detección de subidas** — Desnivel, pendiente, potencia y VAM
- **Informe mensual PDF** — Métricas clave, zonas, evolución y resumen

---

## 📱 Detalle de actividad

Cada actividad importada incluye:

| Análisis | Descripción |
|---|---|
| Métricas principales | Duración, distancia, desnivel, TSS, IF, NP, potencia media, FC, cadencia |
| Series temporales | Potencia, FC, cadencia, velocidad, altitud, W′ Balance (toggles individuales) |
| Cuadrantes (Coggan) | Distribución del pedaleo en 4 cuadrantes |
| Balance pedaleo | Simetría izquierda/derecha (potenciómetro dual) |
| Intervalos | Detección automática con recuperación por intervalo |
| Subidas | Detección automática con pendiente, potencia y VAM |
| Records (MMP) | Mejores esfuerzos: 5s, 1min, 5min, 20min, 60min… |
| Mapa de ruta | GPS coloreado por potencia/FC |
| Notas | Campo editable y nombre personalizable |

---

## 🔄 Importación de datos

**Archivos locales:**
- `.FIT` (Garmin, Wahoo, Hammerhead, COROS…) con parsing de balance izq/der nativo
- `.TCX` (Garmin Connect, Strava export…)
- Drag & drop o selección múltiple
- Detección de duplicados

**Strava:**
- Vinculación OAuth 2.0 segura
- Streams completos (potencia, FC, cadencia, altitud, GPS, velocidad)
- Filtrado inteligente: Road, MTB, Gravel, Virtual, E-Bike…
- Hasta 250 actividades con paginación automática
- Arquitectura de threading estable (sin congelaciones)

---

## 🚀 Instalación

### Opción 1 — Desde el .zip

1. Descargar desde el .zip o [Releases](https://github.com/juancar1lo/ciclometricas/releases)
2. | Seguridad del Ejecutable | Verificación |
| :--- | :--- |
| **Análisis Antivirus** | 🟢 [Ver informe en VirusTotal](https://www.virustotal.com/gui/file/f50b3893f238ccbe712389dd05404a5663e19a805d495e0dd635950d1c836a70/detection) |
| **Hash SHA-256** | `f50b3893f238ccbe712389dd05404a5663e19a805d495e0dd635950d1c836a70` |
3. Descomprimir
4. Instalar dependencias:

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
```

4. Ejecutar:

```bash
python main.py
```

### Opción 2 — Desde pyproject.toml

```bash
pip install .
ciclometricas
```

### Requisitos del sistema

- Python 3.11+
- Windows 10/11, macOS 12+, Linux (Ubuntu 22.04+)
- ~200 MB de espacio en disco
- Conexión a internet solo para Strava

---

## 🏗️ Arquitectura

```
ciclométricas/
├── main.py              # Entry point
├── calc/                # CP, MMP, fitness, zonas, W′bal, intervalos, subidas…
├── parsers/             # Lectores de .FIT y .TCX
├── db/                  # SQLAlchemy ORM + gestión de perfiles
├── services/            # Import service + Strava sync
├── ui/
│   ├── charts/          # Widgets de gráficos (pyqtgraph)
│   ├── views/           # Dashboard, salud, durabilidad, recuperación…
│   ├── widgets/         # stat_card, alert_banner, sidebar…
│   ├── theme.py         # QSS tema oscuro
│   └── main_window.py   # Ventana principal
├── assets/              # Iconos
└── tests/               # 170 tests unitarios
```

| Componente | Tecnología |
|---|---|
| Interfaz gráfica | PySide6 (Qt 6) |
| Gráficos interactivos | PyQtGraph + NumPy + SciPy |
| Base de datos local | SQLite + SQLAlchemy ORM |
| Parsing de archivos | fitdecode (FIT) + lxml (TCX) |
| Integración Strava | OAuth 2.0 + API v3 REST |
| Informes | ReportLab (PDF) |
| Tests | pytest (170 tests) |

---

## 📚 Fundamentos científicos

| Métrica | Referencia |
|---|---|
| Critical Power (CP / W′) | Monod & Scherrer (1965) |
| W′ Balance | Skiba et al. (2012) |
| Monotonía / Strain | Foster (1998) |
| Zonas de potencia | Coggan (Training and Racing with a Power Meter) |
| Zonas de FC (FCL) | Friel (The Cyclist’s Training Bible) |
| Análisis de cuadrantes | Coggan (2007) |
| TSS / IF / NP | TrainingPeaks / Coggan |

---

## 🧱 Filosofía

- **100% local** — Tus datos nunca salen de tu ordenador
- **Científicamente riguroso** — Basado en publicaciones revisadas por pares
- **Gratuito y abierto** — Sin suscripciones, sin límites, sin anuncios
- **Open Source** — GPL v3.0

---

## 📄 Licencia

Este proyecto está licenciado bajo la **GNU General Public License v3.0**.  
Consulta el archivo [LICENSE](LICENSE) para más detalles.

---

*🚴 Ciclométricas — Tu laboratorio de rendimiento ciclista, en tu escritorio.*  
*Copyright (C) 2025-2026 Juan Carlos López San Joaquín*
