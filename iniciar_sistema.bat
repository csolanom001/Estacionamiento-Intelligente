@echo off
chcp 65001 > nul
title Sistema de Estacionamiento Inteligente ESP32 - UAEMEX
cls

echo ======================================================================
echo    🚗 SISTEMA DE ESTACIONAMIENTO INTELIGENTE CON ESP32 - UAEMEX
echo    Plataforma Web, App Móvil PWA, Base de Datos y Gemelo Digital
echo ======================================================================
echo.

cd /d "%~dp0plataforma_web"

:: Obtener la IP local de la computadora para abrir desde el celular
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    set IP_LOCAL=%%a
    goto :ip_encontrada
)
:ip_encontrada
set IP_LOCAL=%IP_LOCAL: =%

echo [INFO] Servidor iniciando en el puerto 8085 (sin conflicto con otros proyectos):
echo    • Desde esta computadora:   http://localhost:8085
echo    • Desde tu celular (Wi-Fi): http://%IP_LOCAL%:8085
echo    • Documentación API REST:   http://localhost:8085/docs
echo.
echo [INFO] Abriendo Dashboard en el navegador en 2 segundos...
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8085"

echo.
echo Presiona Ctrl+C para detener el servidor cuando termines.
echo ======================================================================
echo.

python -m uvicorn app:app --host 0.0.0.0 --port 8085 --reload
pause
