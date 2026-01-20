@echo off
echo ============================================
echo  ConectaPro - Reinicio Limpio de Plataforma
echo ============================================
echo.

cd /d %~dp0

echo [1/6] Deteniendo contenedores...
docker compose down

echo.
echo [2/6] Eliminando imagenes antiguas...
docker image prune -f

echo.
echo [3/6] Reconstruyendo contenedores (sin cache)...
docker compose build --no-cache

echo.
echo [4/6] Levantando plataforma...
docker compose up -d

echo.
echo [5/6] Mostrando logs del API...
echo (Presiona CTRL+C para salir de logs)
docker logs -f conectapro-platform-api-1

echo.
echo [6/6] Finalizado.
pause
