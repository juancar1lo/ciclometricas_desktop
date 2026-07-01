
<img width="247" height="166" alt="16 (redimensionado)" src="https://github.com/user-attachments/assets/1a5e3c67-f5b4-43cf-81c3-2372864e5d94" />
<img width="297" height="159" alt="15 (redimensionado)" src="https://github.com/user-attachments/assets/96404b7c-60cb-4de5-af02-750d6b68ade4" />
<img width="297" height="158" alt="14 (redimensionado)" src="https://github.com/user-attachments/assets/480803ba-97ca-4ddb-90bc-fb60b9e206a6" />
<img width="317" height="168" alt="13 (redimensionado)" src="https://github.com/user-attachments/assets/07e73c0d-46ca-418e-9333-65c0611a337d" />
<img width="297" height="159" alt="12 (redimensionado)" src="https://github.com/user-attachments/assets/08f28c95-3ff9-47b5-a63f-341bbd1fb98e" />
<img width="277" height="147" alt="11 (redimensionado)" src="https://github.com/user-attachments/assets/360f16cb-eb06-49d6-999a-ba92e03d9a12" />
<img width="277" height="148" alt="10 (redimensionado)" src="https://github.com/user-attachments/assets/78d15e17-d666-4d3f-95ce-e3807328d4ca" />
<img width="277" height="148" alt="9 (redimensionado)" src="https://github.com/user-attachments/assets/2a32424e-c3e1-45bf-b0a8-de397c170378" />
<img width="440" height="234" alt="8 (redimensionado)" src="https://github.com/user-attachments/assets/2f9b6478-462d-459f-ae3a-a8db79c1abc4" />
<img width="460" height="245" alt="7 (redimensionado)" src="https://github.com/user-attachments/assets/836f5573-a47e-4ac7-a9c0-0c9c72f4036d" />
<img width="460" height="242" alt="6 (redimensionado)" src="https://github.com/user-attachments/assets/67fd82a3-c2fc-4c46-9479-2a77fc892e9b" />
<img width="477" height="253" alt="5 (redimensionado)" src="https://github.com/user-attachments/assets/8ad5227b-d3d0-483a-a300-c5fd2f9e1dbf" />
<img width="435" height="197" alt="4 (redimensionado)" src="https://github.com/user-attachments/assets/b507658b-e74d-4ad0-9d57-782f9ff33d6f" />
<img width="419" height="190" alt="3 (redimensionado)" src="https://github.com/user-attachments/assets/1a594022-edbb-41c8-a8b5-7756cbe16882" />
<img width="338" height="181" alt="2 (redimensionado)" src="https://github.com/user-attachments/assets/2d781934-9b4e-430b-91e9-7d00c8c8d091" />
<img width="253" height="134" alt="1 (redimensionado)" src="https://github.com/user-attachments/assets/209f945a-2a18-42e0-8933-861ec198b0c1" />
<img width="134" height="178" alt="0 (redimensionado)" src="https://github.com/user-attachments/assets/dfa344cc-6d5a-4d58-bab4-808b6d99cbec" />
<img width="360" height="154" alt="19 (redimensionado)" src="https://github.com/user-attachments/assets/022d9189-2ddd-40a5-973a-56d45cd5059b" />



# Ciclométricas_v3.0.0

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests: 170](https://img.shields.io/badge/tests-170%20passing-brightgreen.svg)]()
[![Version: 2.0](https://img.shields.io/badge/version-2.0.0-orange.svg)]()

**Análisis avanzado de rendimiento en ciclismo.**

Aplicación de escritorio gratuita, de código abierto y multiplataforma, construida con Python + PySide6 (Qt 6). Analiza datos de potencia, frecuencia cardíaca, cadencia y equilibrio de pedaleo a partir de archivos **FIT** y **TCX**, con integración directa con **Strava**.

**Advanced cycling performance analysis.**
Free, open-source, cross-platform desktop application built with Python + PySide6 (Qt 6). Analyzes power, heart rate, cadence, and pedaling balance data from FIT and TCX files, with direct Strava integration.


---

## Características principales
## Main Features

### Consejero IA con RAG (nuevo en v3.0.0)
Ciclométricas integra un consejero de inteligencia artificial local que analiza tu entrenamiento y responde preguntas en lenguaje natural. Todo se ejecuta en tu ordenador mediante Ollama, sin enviar datos a la nube.

Motor de contexto inteligente: 
El sistema clasifica automáticamente la pregunta del usuario (perfil, fitness, actividades, zonas, CP, salud, MMP, monotonía, rendimiento…) y selecciona solo los datos relevantes para incluir en el contexto del modelo. Esto permite respuestas precisas sin sobrecargar el LLM con información innecesaria.

RAG semántico con embeddings: 
Un almacén de embeddings vectoriales (nomic-embed-text) indexa automáticamente cada actividad y perfil. Cuando el usuario hace una pregunta, el sistema busca los documentos más similares semánticamente y los incluye en el contexto. Esto permite preguntas como "¿Cuál fue mi mejor subida del mes pasado?" o "¿Cómo ha evolucionado mi fitness?".

Funciones de consulta estructurada: 
El Consejero tiene acceso a funciones de consulta que puede ejecutar automáticamente:
•	Buscar actividades por fecha, tipo o nombre
•	Consultar MMP para duraciones específicas
•	Resumen de período (TSS, horas, distancia…)
•	Fitness en fecha concreta (CTL/ATL/TSB)

### AI Advisor with RAG (New in v3.0.0)
Ciclométricas integrates a local artificial intelligence advisor that analyzes your training and answers questions in natural language. Everything runs on your computer via Ollama, without sending data to the cloud.
•	Smart Context Engine: 
The system automatically classifies the user's question (profile, fitness, activities, zones, CP, health, MMP, monotony, performance...) and selects only the relevant data to include in the model's context. This allows for accurate responses without overloading the LLM with unnecessary information.
•	Semantic RAG with Embeddings: 
A vector embedding store (nomic-embed-text) automatically indexes each activity and profile. When the user asks a question, the system searches for the most semantically similar documents and includes them in the context. This enables questions like "What was my best climb last month?" or "How has my fitness evolved?".
•	Structured Query Functions: 
The AI Advisor has access to query functions that it can execute automatically:
o	Search activities by date, type, or name
o	Query MMP for specific durations
o	Period summary (TSS, hours, distance...)
o	Fitness on a specific date (CTL/ATL/TSB)


### Editor de picos de potencia
Vista híbrida para detección y corrección de picos aberrantes de potencia en archivos .FIT y .TCX. Flujo guiado:
•	1. Abrir archivo .FIT o .TCX.
•	2. Auto-detectar picos con 4 algoritmos combinados: umbral absoluto, umbral relativo (W/kg), tasa de cambio (ΔP/Δt) y Z-score en ventana deslizante.
•	3. Revisar cada spike con contexto multi-canal (potencia, FC, cadencia, velocidad).
•	4. Aceptar o rechazar cada corrección individualmente.
•	5. Exportar archivo corregido (.FIT o .TCX) sin perder los datos originales.
Tres métodos de corrección disponibles: interpolación lineal entre vecinos válidos, recorte al umbral máximo y reemplazo por media local.

### Power Spike Editor
Hybrid view for detecting and correcting anomalous power spikes in .FIT and .TCX files. Guided workflow:
•	1. Open a .FIT or .TCX file.
•	2. Auto-detect spikes using 4 combined algorithms: absolute threshold, relative threshold ($W/kg$), rate of change ($\Delta P/\Delta t$), and Z-score in a sliding window.
•	3. Review each spike with multi-channel context (power, HR, cadence, speed).
•	4. Accept or reject each correction individually.
•	5. Export the corrected file (.FIT or .TCX) without losing the original data.
•	Three correction methods available: linear interpolation between valid neighbors, clipping to the maximum threshold, and replacement by local average.


### Sesiones manuales
Diálogo para registrar actividades no ciclistas que contribuyen a la carga de entrenamiento:
•	Tipos: fuerza (🏋️), caminata (🚶) y otro (🏃).
•	Presets de intensidad percibida por tipo: mantenimiento, hipertrofia, fuerza máxima; paseo, caminata rápida, marcha intensa.
•	TSS calculado con la fórmula: TSS = horas × IF² × 100.
•	Campos: fecha, hora, duración, tipo, intensidad, notas.
•	Se integran automáticamente en CTL/ATL/TSB, monotonía, preparación para competir y calendario.

### Manual Sessions
Dialog to log non-cycling activities that contribute to training load:
•	Types: strength (🏋️), walking (🚶), and other (🏃).
•	Perceived intensity presets by type: maintenance, hypertrophy, maximum strength; stroll, brisk walk, intense walking.
•	TSS calculated with the formula:
$$TSS = \text{hours} \times IF^2 \times 100$$
•	Fields: date, time, duration, type, intensity, notes.
•	They automatically integrate into CTL/ATL/TSB, monotony, readiness to race, and the calendar.


### Objetivos de entrenamiento
Sistema de planificación de metas de entrenamiento:
•	Tipos de objetivo: subir CTL (fitness), subir FTP, preparar un evento.
•	Cálculo de plan: basado en carga actual con rampa segura (3-7 pts CTL/semana, Coggan).
•	Proyección: estimación de TSS semanal necesario y fecha estimada de consecución.

### Training Goals
Training goal planning system:
•	Goal types: increase CTL (fitness), increase FTP, prepare for an event.
•	Plan calculation: based on current load with a safe ramp rate (3–7 CTL pts/week, Coggan).
•	Projection: estimation of required weekly TSS and estimated completion date.


###  Copia de seguridad
Pestaña dedicada en Configuración para la gestión de copias de seguridad:
•	Crear copia de seguridad completa de la base de datos SQLite del atleta.
•	Restaurar desde archivo .db con confirmación para evitar pérdida de datos.
•	Ruta configurable para la exportación.

### Backup
Dedicated tab in Settings for backup management:
•	Create a full backup of the athlete's SQLite database.
•	Restore from a .db file with confirmation to prevent data loss.
•	Configurable export path.


### Lectura en voz alta (TTS)
Servicio de Text-to-Speech integrado con QTextToSpeech (PySide6):
•	Disponible en el consejero IA y en el detalle de actividad.
•	Preprocesamiento inteligente de Markdown para lectura fluida.
•	Selección automática de idioma según la configuración (español/inglés).
•	Controles: reproducir, pausar, reanudar y detener.
•	Compatible con Windows (SAPI5/WinRT) y Linux.

### Read Aloud (TTS)
Text-to-Speech service integrated with QTextToSpeech (PySide6):
•	Available in the AI advisor and activity details.
•	Smart Markdown preprocessing for fluent reading.
•	Automatic language selection based on settings (Spanish/English).
•	Controls: play, pause, resume, and stop.
•	Compatible with Windows (SAPI5/WinRT) and Linux.


Ya presentes en v2.0 / Already Present in v2.0:
###  Modelo de Potencia Crítica (CP)
- Regresión lineal Monod-Scherrer con estimación de **CP**, **W′**, **mFTP**, **VO₂max** y potencia de sprint
- Indicador de fiabilidad **R²** con badge visual
- **TTE** (Tiempo hasta el Agotamiento) con estimaciones detalladas por zona: Sweet Spot (~2–4h), Tempo (~3–5h), Resistencia (>5h)
- Evolución histórica de CP y W′ con gráfico de tendencia

### Critical Power (CP) Model
•	Monod-Scherrer linear regression with estimations of $CP$, $W^\prime$, $mFTP$, $VO_2max$, and sprint power.
•	$R^2$ reliability indicator with a visual badge.
•	TTE (Time to Exhaustion) with detailed estimations per zone: Sweet Spot (~2–4h), Tempo (~3–5h), Endurance (>5h).
•	Historical evolution of $CP$ and $W^\prime$ with a trend chart.


###  Curva de Potencia-Duración (DCP)
- MMP global con suavizado Savitzky-Golay y escala logarítmica (5s → 45min)
- Bandas de targeting para planificación de intervalos
- Tarjetas de rangos sugeridos por duración

### Power-Duration Curve (DCP)
•	Global MMP with Savitzky-Golay smoothing and logarithmic scale (5s $\rightarrow$ 45min).
•	Targeting bands for interval planning.
•	Suggested range cards by duration.


###  Carga y Forma (CTL / ATL / TSB)
- Modelo exponencial de carga crónica y aguda con **previsión a futuro**
- Rampa semanal (ΔCTL pts/semana)
- Gráfico de Forma con bandas: alto riesgo, óptimo, productivo, fresco, transición

### Load and Form (CTL / ATL / TSB)
•	Exponential model of chronic and acute load with future forecasting.
•	Weekly ramp ($\Delta\text{CTL}$ pts/week).
•	Form chart with bands: high risk, optimal, productive, fresh, transition.


###  Preparación para Competir (RRS)
- Puntuación 0–100 basada en forma, fitness, consistencia y tendencia
- Gauge semicircular con consejo personalizado

### Readiness to Race (RRS)
•	0–100 score based on form, fitness, consistency, and trend.
•	Semicircular gauge with personalized advice.


###  Durabilidad (DRI)
- Tests empíricos: CP fresca vs fatigada
- Modelo de decaimiento exponencial con extrapolación
- Gráfico de área entre curvas y clasificación (excelente → limitante)

### Durability (DRI)
•	Empirical tests: fresh vs. fatigued CP.
•	Exponential decay model with extrapolation.
•	Area chart between curves and classification (excellent $\rightarrow$ limiting).


###  Módulo de Salud *(nuevo en v2.0)*
- FC en reposo, HRV, presión arterial, readiness, peso, grasa corporal, grasa subcutánea
- **3 gráficos interactivos:** cardiovascular (FC + HRV + readiness), presión arterial (candlestick), composición corporal
- Normalización de readiness desde Garmin, Whoop, Oura, COROS, Elite HRV o manual
- Tabla histórica con edición y borrado inline

### Health Module (New in v2.0)
•	Resting HR, HRV, blood pressure, readiness, weight, body fat, subcutaneous fat.
•	3 interactive charts: cardiovascular (HR + HRV + readiness), blood pressure (candlestick), body composition.
•	Readiness normalization from Garmin, Whoop, Oura, COROS, Elite HRV, or manual input.
•	Historical table with inline editing and deletion.


###  Balance de Pedaleo *(nuevo en v2.0)*
- Análisis izquierda/derecha con barra visual
- Clasificación: equilibrado, leve asimetría, asimetría notable
- Detección de pierna dominante (requiere potenciómetro dual)

### Pedaling Balance (New in v2.0)
•	Left/right analysis with a visual bar.
•	Classification: balanced, minor asymmetry, significant asymmetry.
•	Dominant leg detection (requires a dual power meter).


###  Tendencias de Eficiencia *(mejorado en v2.0)*
- EF (NP/FC), VF (NP/Pmedia) y Pw:Hr (desacople potencia/FC)
- **3 ejes Y independientes** con escalas propias para mayor claridad

### Efficiency Trends (Improved in v2.0)
•	EF (NP/HR), VF (NP/Average Power), and Pw:Hr (power/HR decoupling).
•	3 independent Y-axes with their own scales for greater clarity.


###  Más análisis
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

### More Analysis
•	Power zones — Coggan (8 zones including Sweet Spot), configurable reference: FTP, CP, or mFTP.
•	HR zones — Friel (7 zones based on FTHR/LTHR) (updated in v2.0).
•	Fatigue resistance — FR index per activity with classification and trend.
•	Monotony (Foster) — Detection of dangerous loading patterns.
•	Recovery — Current status gauge, 7-day TSB projection.
•	$W^\prime$ Balance — Skiba (2012) differential model in real-time.
•	Quadrant analysis — Pedaling distribution (Coggan).
•	Interval detection — Automatic, featuring power, HR, and cadence metrics.
•	Climb detection — Elevation gain, grade, power, and VAM.
•	Monthly PDF report — Key metrics, zones, evolution, and summary.


---

## Detalle de actividad

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

## Activity Details
Each imported activity includes:
| Analysis | Description |
|---|---|
| Main metrics | Duration, distance, elevation gain, TSS, IF, NP, average power, HR, cadence |
| Time series |	Power, HR, cadence, speed, altitude, $W^\prime$ Balance (individual toggles) |
| Quadrants (Coggan)	| Pedaling distribution across 4 quadrants |
| Pedaling balance	| Left/right symmetry (dual power meter) |
| Intervals	Automatic | detection with recovery per interval |
| Climbs	| Automatic detection with grade, power, and VAM |
| Records (MMP)	| Best efforts: 5s, 1min, 5min, 20min, 60min… |
| Route map	| GPS colored by power/HR |
| Notes	| Editable field and customizable name |


---

##  Importación de datos / Data Import

**Archivos locales:**
- `.FIT` (Garmin, Wahoo, Hammerhead, COROS…) con parsing de balance izq/der nativo
- `.TCX` (Garmin Connect, Strava export…)
- Drag & drop o selección múltiple
- Detección de duplicados

**Local Files:**

**Strava:**
- Vinculación OAuth 2.0 segura
- Streams completos (potencia, FC, cadencia, altitud, GPS, velocidad)
- Filtrado inteligente: Road, MTB, Gravel, Virtual, E-Bike…
- Hasta 250 actividades con paginación automática
- Arquitectura de threading estable (sin congelaciones)

**Strava:**
- .FIT (Garmin, Wahoo, Hammerhead, COROS…) with native left/right balance parsing.
- .TCX (Garmin Connect, Strava export…).
- Drag & drop or multiple selection.
- Duplicate detection.


---

##  Instalación

### Opción 1 — Desde el .zip

1. Descargar desde el .zip o [Releases][(https://github.com/juancar1lo/ciclometricas_desktop/releases)]
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
### Option 1 — From the .zip
1. Download from the .zip or [Releases](https://github.com/juancar1lo/ciclometricas/releases)
2. | Executable Security	| Verification |
| :--- | :--- |
Antivirus Scan	🟢 [View report on VirusTotal]
(https://www.virustotal.com/gui/file/f50b3893f238ccbe712389dd05404a5663e19a805d495e0dd635950d1c836a70/detection) |
| **Hash SHA-256** | `f50b3893f238ccbe712389dd05404a5663e19a805d495e0dd635950d1c836a70` |
3. Unzip the file.
4. Install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
```
3.	Run:
```bash
python main.py
```

### Opción 2 — Desde pyproject.toml
---
Bash
pip install .
ciclometricas
---

### Option 2 — From pyproject.toml
---
Bash
pip install .
ciclometricas
---

### Requisitos del sistema

•	Python 3.11 o superior
•	Windows 10/11, Linux (Ubuntu 22.04+, Fedora 38+, etc.)
•	~800 MB de espacio en disco
•	16 GB RAM, mínimo aconsejable (8 GB para usarlo SIN consejero IA)
•	Si queremos una buena velocidad del modelo LLM, GPU potente
•	Conexión a internet, solo para la integración con Strava
•	Ollama para el Consejero IA — se instala por separado, LLM “a gusto” del usuario

### System Requirements
•	Python 3.11 or higher.
•	Windows 10/11, Linux (Ubuntu 22.04+, Fedora 38+, etc.).
•	~800 MB of disk space.
•	16 GB RAM recommended minimum (8 GB to use it WITHOUT the AI advisor).
•	A powerful GPU is recommended for good LLM execution speed.
•	Internet connection required only for Strava integration.
•	Ollama for the AI Advisor — installed separately, LLM of the user's choice.


### Consejero IA

Instalación de Ollama (para el Consejero IA):
¿Qué es Ollama? Ollama es un cliente de modelos LLM que permite usar IA de manera local en el ordenador del usuario. Todos sus datos quedan a salvo y no son compartidos con ninguna nube. El usuario selecciona el LLM más apropiado para su ordenador y ejecuta el modelo sin conexión a Internet, salvo para la descarga del mismo. Cualquier LLM descargado el usuario lo puede utilizar para lo que desee de manera absolutamente privada.
•	1. Descargar Ollama desde ollama.com
•	2. Instalar y ejecutar: ollama serve
•	3. Descargar algún/os modelo/s (desde CMD/PowerShell/terminal: ollama pull [nombre y versión de cualquiera de los LLM disponibles: Deepseek, Llama, Qwen… y según las características del ordenador del usuario]
•	4. Descargar embeddings: ollama pull nomic-embed-text
•	5. Para saber los LLM instalados en Ollama: ollama list
•	6. Para desinstalar modelos LLM: ollama rm [nombre y versión del LLM]
•	7. Las respuestas que obtenga el usuario van a ser tanto más estructuradas y de mejor calidad cuanto más parámetros tenga el modelo LLM (pueden ser varios), lo cual dependerá de las limitaciones de hardware del ordenador del usuario.
El Consejero IA es completamente opcional, el resto de la aplicación funciona sin Ollama.

### AI Advisor
Ollama Installation (for the AI Advisor):
What is Ollama? Ollama is an LLM client that allows you to run AI locally on the user's computer. All your data remains safe and is never shared with any cloud. The user selects the most appropriate LLM for their computer and runs the model offline, except for the initial download. Any downloaded LLM can be used for any purpose in absolute privacy.
•	1. Download Ollama from ollama.com.
•	2. Install and run: ollama serve.
•	3. Download one or more models from the CMD/PowerShell/terminal: ollama pull [name and version of any available LLM: Deepseek, Llama, Qwen… based on the user's computer specifications].
•	4. Download embeddings: ollama pull nomic-embed-text.
•	5. To see installed LLMs in Ollama: ollama list.
•	6. To uninstall LLM models: ollama rm [LLM_name_and_version].
•	7. The answers obtained by the user will be more structured and higher quality the more parameters the LLM model has (it can be several), which will depend on the hardware limitations of the user's computer.
Note: The AI Advisor is completely optional; the rest of the application functions perfectly without Ollama.

---

##  Arquitectura / Architecture

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
| Interfaz gráfica / Graphical Interface | PySide6 (Qt 6) |
| Gráficos interactivos / Interactive Charts | PyQtGraph + NumPy + SciPy |
| Base de datos local / Local Database | SQLite + SQLAlchemy ORM |
| Parsing de archivos / File Parsing | fitdecode (FIT) + lxml (TCX) |
| Integración Strava / Strava Integration | OAuth 2.0 + API v3 REST |
| Informes / Reports | ReportLab (PDF) |
| Tests / Tests | pytest (170 tests) |

---

##  Fundamentos científicos / Scientific Foundations

| Métrica / Metric | Referencia / Reference |
|---|---|
| Critical Power (CP / W′) | Monod & Scherrer (1965) |
| W′ Balance | Skiba et al. (2012) |
| Monotonía / Monotony | Foster (1998) |
| Zonas de potencia / Power Zones | Coggan (Training and Racing with a Power Meter) |
| Zonas de FC (FCL) / HR Zones (FTHR) | Friel (The Cyclist’s Training Bible) |
| Análisis de cuadrantes / Quadrant Analysis |
| TSS / IF / NP |

---

## Filosofía

- **100% local** — Tus datos nunca salen de tu ordenador
- **Científicamente riguroso** — Basado en publicaciones revisadas por pares
- **Gratuito y abierto** — Sin suscripciones, sin límites, sin anuncios
- **Open Source** — GPL v3.0

## Philosophy
•	100% Local — Your data never leaves your computer.
•	Scientifically Rigorous — Based on peer-reviewed publications.
•	Free and Open — No subscriptions, no limits, no ads.


---

##  Licencia / License

Este proyecto está licenciado bajo la **GNU General Public License v3.0**.  
Consulta el archivo [LICENSE](LICENSE) para más detalles.
This project is licensed under the GNU General Public License v3.0.
See the LICENSE file for more details.


---

* Ciclométricas — Tu laboratorio de rendimiento ciclista, en tu escritorio.*
* Ciclométricas — Your cycling performance laboratory, on your desktop.*
*Copyright (C) 2025-2026 Juan Carlos López San Joaquín*



[Ciclometricas_Presentacion_v3.pdf](https://github.com/juancar1lo/ciclometricas_desktop/blob/main/Ciclometricas_Presentacion_v3.pdf)
[Ciclometricas_Presentation_v3_EN.pdf](https://github.com/juancar1lo/ciclometricas_desktop/blob/main/Ciclometricas_Presentation_v3_EN.pdf).

