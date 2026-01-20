Write-Host "Inicializando estructura ConectaPro..."

# Carpetas base
New-Item -ItemType Directory -Force -Path `
services\api, `
services\worker, `
infra\nginx | Out-Null

# Archivos raiz
New-Item -ItemType File -Force -Path `
docker-compose.yml, `
.env.example, `
.gitignore, `
README.md | Out-Null

# API service
New-Item -ItemType File -Force -Path `
services\api\main.py, `
services\api\settings.py, `
services\api\db.py, `
services\api\models.py, `
services\api\schemas.py, `
services\api\leads_flow.py, `
services\api\matching.py, `
services\api\whatsapp_cloud.py, `
services\api\requirements.txt, `
services\api\Dockerfile | Out-Null

# Worker service
New-Item -ItemType File -Force -Path `
services\worker\worker.py, `
services\worker\requirements.txt, `
services\worker\Dockerfile | Out-Null

# Infra
New-Item -ItemType File -Force -Path `
infra\nginx\nginx.conf | Out-Null

Write-Host "Estructura ConectaPro creada correctamente."
Write-Host ""
Write-Host "Arbol generado:"
Get-ChildItem -Recurse | Select-Object FullName
