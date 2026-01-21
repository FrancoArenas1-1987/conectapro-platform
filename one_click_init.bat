@echo off
title CONECTAPRO - INIT (RESET TOTAL)
color 4F

echo ============================================
echo   ⚠  CONECTAPRO - INICIALIZACION TOTAL
echo ============================================
echo.
echo ESTE PROCESO:
echo  - BORRARA la base de datos
echo  - BORRARA los volumenes Docker
echo  - RECREARA todo desde cero
echo.
echo USAR SOLO:
echo  - Primera ejecucion
echo  - Cambios en models.py
echo  - Errores de esquema DB
echo.
pause

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
echo 🧨 Apagando contenedores y BORRANDO volumenes...
docker compose down -v

echo.
echo 🔨 Construyendo imagenes...
docker compose build

echo.
echo 🚀 Levantando ConectaPro desde cero...
docker compose up -d

echo.
echo 🌐 Exponiendo puerto 8000 con Ngrok...
start ngrok http 8000

echo.
echo ============================================
echo   ✅ INICIALIZACION COMPLETA FINALIZADA
echo ============================================
echo.
echo Revisa:
echo  - docker compose ps
echo  - docker compose logs -f api
echo  - docker compose logs -f worker
echo  - Ngrok tunnel: http://localhost:4040
echo.
pause
