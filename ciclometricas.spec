# -*- mode: python ; coding: utf-8 -*-
# Ciclométricas v2.0 — PyInstaller spec
# Ejecutar: pyinstaller ciclometricas.spec

import sys
import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# ── Recoger submódulos ocultos de PySide6 ──
hiddenimports = (
    collect_submodules('PySide6') +
    collect_submodules('scipy') +
    collect_submodules('numpy') +
    collect_submodules('sqlalchemy') +
    collect_submodules('alembic') +
    [
        'pyqtgraph',
        'pyqtgraph.graphicsItems',
        'pyqtgraph.graphicsItems.PlotItem',
        'pyqtgraph.graphicsItems.ViewBox',
        'pyqtgraph.graphicsItems.AxisItem',
        'fitdecode',
        'lxml',
        'lxml.etree',
        'requests',
        'pandas',
        # Módulos internos del proyecto
        'calc',
        'calc.activity_metrics',
        'calc.climbs',
        'calc.cp_model',
        'calc.durability',
        'calc.fatigue_resistance',
        'calc.fitness',
        'calc.ftp_estimator',
        'calc.intervals',
        'calc.mmp',
        'calc.monotony',
        'calc.pdc_fatigue',
        'calc.power',
        'calc.quadrant_analysis',
        'calc.race_readiness',
        'calc.recovery',
        'calc.wbal',
        'calc.zones',
        'db',
        'db.athlete_manager',
        'db.engine',
        'db.models',
        'parsers',
        'parsers.fit_parser',
        'parsers.tcx_parser',
        'parsers.types',
        'services',
        'services.import_service',
        'services.strava_service',
        'ui',
        'ui.athlete_dialog',
        'ui.dialogs',
        'ui.main_window',
        'ui.theme',
        'ui.charts',
        'ui.charts.chart_utils',
        'ui.charts.route_map',
        'ui.charts.time_series_chart',
        'ui.views',
        'ui.views.activities_view',
        'ui.views.activity_detail_view',
        'ui.views.dashboard_view',
        'ui.views.durability_view',
        'ui.views.fatigue_resistance_view',
        'ui.views.health_view',
        'ui.views.import_view',
        'ui.views.monotony_view',
        'ui.views.readiness_view',
        'ui.views.recovery_view',
        'ui.views.settings_view',
        'ui.views.summary_view',
        'ui.widgets',
        'ui.widgets.alert_banner',
        'ui.widgets.stat_card',
        'strava',
    ]
)

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('assets', 'assets'),     # Iconos
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter',    # No necesitamos Tk
        'matplotlib',             # No se usa
        'IPython',
        'notebook',
        'pytest', 'pytest_qt',   # Solo dev
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],                          # NO one-file (más rápido arranque)
    exclude_binaries=True,
    name='Ciclometricas',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,               # Sin ventana de consola
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',      # Icono del EXE
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Ciclometricas',
)
