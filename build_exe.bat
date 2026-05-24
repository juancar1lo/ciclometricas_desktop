@echo off
REM ============================================================
REM  Ciclométricas v2.0 — Construir EXE con PyInstaller
REM  Se puede ejecutar con doble clic o desde cualquier ruta.
REM ============================================================

REM ── Posicionarse en el directorio del .bat ──
cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   Ciclométricas v2.0 — Build EXE        ║
echo  ╚══════════════════════════════════════════╝
echo.

REM ── 1. Verificar Python ──
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.11+ y añádelo al PATH.
    pause
    exit /b 1
)

REM ── 2. Crear entorno virtual (si no existe) ──
if not exist ".venv" (
    echo [1/5] Creando entorno virtual...
    python -m venv .venv
) else (
    echo [1/5] Entorno virtual existente detectado.
)

REM ── 3. Activar entorno virtual ──
call .venv\Scripts\activate.bat

REM ── 4. Instalar dependencias + PyInstaller ──
echo [2/5] Instalando dependencias...
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ERROR] Fallo al instalar dependencias.
    pause
    exit /b 1
)

REM ── 5. Generar icono .ico si no existe ──
if not exist "assets\icon.ico" (
    echo [3/5] Generando icon.ico desde icon.png...
    python -c "from PIL import Image; img=Image.open('assets/icon.png'); img.save('assets/icon.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
    if errorlevel 1 (
        echo [AVISO] No se pudo generar icon.ico. Instala Pillow: pip install Pillow
        echo         Continuando sin icono personalizado...
    )
) else (
    echo [3/5] icon.ico ya existe.
)

REM ── 6. Limpiar builds anteriores ──
echo [4/5] Limpiando builds anteriores...
if exist "build" rmdir /s /q build
if exist "dist\Ciclometricas" rmdir /s /q dist\Ciclometricas

REM ── 7. Ejecutar PyInstaller ──
echo [5/5] Ejecutando PyInstaller...
echo.
pyinstaller ciclometricas.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller falló. Revisa los errores arriba.
    pause
    exit /b 1
)

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║   ¡BUILD COMPLETADO!                            ║
echo  ║                                                 ║
echo  ║   EXE: dist\Ciclometricas\Ciclometricas.exe     ║
echo  ║                                                 ║
echo  ║   Puedes ejecutarlo directamente o usar          ║
echo  ║   Inno Setup para crear el instalador.           ║
echo  ╚══════════════════════════════════════════════════╝
echo.
pause
