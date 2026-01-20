@echo off
title CONECTAPRO - START
color 1F

echo ============================================
echo   🚀 CONECTAPRO - ONE CLICK START
echo ============================================
echo.

echo 🔍 Verificando Docker...
docker info >nul 2>&1
IF ERRORLEVEL 1 (
    echo ❌ Docker no esta corriendo
    pause
    exit /b 1
)
echo ✔ Docker OK

echo.
echo 📴 Deteniendo contenedores previos...
docker compose down

echo.
echo 🔨 Construyendo imagenes (sin borrar datos)...
docker compose build

echo.
echo 🚀 Levantando servicios...
docker compose up -d

echo.
echo ============================================
echo   ✅ CONECTAPRO LEVANTADO CORRECTAMENTE
echo ============================================
echo.
echo Revisa:
echo  - docker compose ps
echo  - docker compose logs -f api
echo  - docker compose logs -f worker
echo.
pause
