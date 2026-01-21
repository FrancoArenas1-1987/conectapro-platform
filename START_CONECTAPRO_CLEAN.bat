@echo off
title CONECTAPRO - CLEAN START
color 2F

echo ============================================
echo  🚀 ConectaPro - Reinicio Limpio de Plataforma
echo ============================================
echo.

cd /d %~dp0

echo 🔍 Verificando Docker...
docker info >nul 2>&1
IF ERRORLEVEL 1 (
    echo ❌ Docker no esta corriendo
    pause
    exit /b 1
)
echo ✔ Docker OK

echo.
echo [1/5] Deteniendo contenedores...
docker compose down

echo.
echo [2/5] Eliminando imagenes antiguas...
docker image prune -f

echo.
echo [3/5] Reconstruyendo contenedores (sin cache)...
docker compose build --no-cache

echo.
echo [4/5] Levantando plataforma...
docker compose up -d

echo.
echo [5/5] Exponiendo con Ngrok...
start ngrok http 8000

echo.
echo ============================================
echo   ✅ REINICIO LIMPIO COMPLETADO
echo ============================================
echo.
echo Comandos utiles:
echo  - docker compose logs -f api
echo  - docker compose logs -f worker
echo  - Ngrok dashboard: http://localhost:4040
echo.
pause
