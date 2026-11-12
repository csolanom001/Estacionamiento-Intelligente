@echo off
chcp 65001 > nul
title Subir Proyecto a GitHub - Estacionamiento Inteligente ESP32
cls

echo ======================================================================
echo    🚀 SUBIENDO PROYECTO A GITHUB: Estacionamiento-Intelligente
echo    Repositorio: https://github.com/csolanom001/Estacionamiento-Intelligente
echo ======================================================================
echo.

cd /d "%~dp0"

if not exist ".git" (
    echo [1/5] Inicializando repositorio Git local en esta carpeta...
    git init -b main
) else (
    echo [1/5] Repositorio Git local detectado...
    git branch -M main
)

echo [2/5] Configurando enlace remoto con GitHub...
git remote remove origin 2>nul
git remote add origin https://github.com/csolanom001/Estacionamiento-Intelligente.git

echo [3/5] Agregando archivos del proyecto...
git add .

echo [4/5] Creando commit del proyecto...
git commit -m "Sistema de Estacionamiento Inteligente con ESP32, RFID RC522, Doble HC-SR04 y Plataforma Web FastAPI"

echo [5/5] Subiendo archivos a GitHub (rama main)...
git push -u origin main

echo.
echo ======================================================================
echo    ✅ PROCESO COMPLETADO
echo    Revisa tu repositorio en:
echo    https://github.com/csolanom001/Estacionamiento-Intelligente
echo ======================================================================
pause
