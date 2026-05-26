@echo off
chcp 65001 >nul
setlocal

echo ============================================================
echo  VoxelBIM — Revisor de Planimetria — Build
echo ============================================================
echo.

cd /d "%~dp0"

REM Ruta al HTML (relativa al script)
set HTML_SRC=..\..\VoxelBIM\app\planimetria.html

if not exist "%HTML_SRC%" (
    echo [ERROR] No se encontro planimetria.html en: %HTML_SRC%
    echo         Ajusta la ruta HTML_SRC en este archivo.
    pause
    exit /b 1
)

echo [1/2] Limpiando build anterior...
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist

echo [2/2] Compilando con PyInstaller ^(--onedir^)...
echo.

pyinstaller ^
    --name "Revisor Planimetria" ^
    --onedir ^
    --windowed ^
    --add-data "%HTML_SRC%;." ^
    --hidden-import "uvicorn.logging" ^
    --hidden-import "uvicorn.loops.auto" ^
    --hidden-import "uvicorn.protocols.http.auto" ^
    --hidden-import "uvicorn.protocols.websockets.auto" ^
    --hidden-import "uvicorn.lifespan.on" ^
    --hidden-import "uvicorn.config" ^
    --hidden-import "fastapi" ^
    --hidden-import "multipart" ^
    --collect-all "fitz" ^
    --collect-all "webview" ^
    --collect-submodules "groq" ^
    --collect-submodules "google.genai" ^
    main.py

echo.
if exist "dist\Revisor Planimetria\Revisor Planimetria.exe" (
    echo [OK] Build exitoso!
    echo      Carpeta: dist\Revisor Planimetria\
    echo.
    echo IMPORTANTE: Copia tu .env dentro de la carpeta antes de distribuir.
    echo             dist\Revisor Planimetria\.env
    echo             El .env debe contener GROQ_API_KEY y/o SLACK_WEBHOOK_URL.
    echo.
    echo Para distribuir: comprime la carpeta dist\Revisor Planimetria\ en un .zip
) else (
    echo [ERROR] El build fallo. Revisa los mensajes arriba.
)

echo.
pause
