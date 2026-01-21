@echo off
title CONECTAPRO - CLEAN ALL (NUCLEAR)
color 4F

echo ===============================================
echo   ☢  CONECTAPRO - LIMPIEZA TOTAL (PELIGRO)
echo ===============================================
echo.
echo ESTE PROCESO:
echo  - ELIMINA contenedores
echo  - ELIMINA volumenes
echo  - ELIMINA imagenes
echo  - ELIMINA networks
echo  - ELIMINA cache Docker
echo.
echo SOLO USAR SI:
echo  - Docker quedo corrupto
echo  - Imagenes inconsistentes
echo  - Nada levanta
echo.
echo NO HAY FORMA DE DESHACER ESTO
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
echo 🧹 Deteniendo contenedores ConectaPro...
docker compose down -v --remove-orphans

echo.
echo 🗑 Eliminando imagenes ConectaPro...
FOR /F %%i IN ('docker images -q conectapro*') DO docker rmi -f %%i

echo.
echo 🧨 Limpiando sistema Docker...
docker system prune -f
docker volume prune -f
docker network prune -f

echo.
echo ===============================================
echo   ✅ LIMPIEZA TOTAL COMPLETADA
echo ===============================================
echo.
echo Ahora puedes usar one_click_init.bat para reconstruir desde cero.
echo.
pause

echo.
echo 🌐 Eliminando network ConectaPro...
docker network prune -f

echo.
echo 📦 Eliminando volumenes huérfanos...
docker volume prune -f

echo.
echo 🧽 Limpieza de sistema Docker...
docker system prune -a -f

echo.
echo ===============================================
echo   ✅ LIMPIEZA TOTAL FINALIZADA
echo ===============================================
echo.
echo Ahora debes ejecutar:
echo   1) one_click_init.bat
echo   2) luego one_click_start.bat
echo.
pause
