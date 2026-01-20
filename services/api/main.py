from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import time
from sqlalchemy.exc import OperationalError

from services.common.logging_config import setup_logging
from .db import Base, engine
from .whatsapp_webhook import router as whatsapp_router

logger = setup_logging("api")

app = FastAPI(title="ConectaPro API", version="0.1.0")


@app.on_event("startup")
def startup():
    # Espera DB (Postgres en Docker puede tardar)
    max_wait_s = 45
    start = time.time()

    while True:
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("✅ DB OK y tablas listas")
            break
        except OperationalError:
            if time.time() - start > max_wait_s:
                logger.error("❌ DB no disponible tras %ss. API seguirá viva pero sin DB", max_wait_s)
                break
            logger.warning("⏳ Esperando DB...")
            time.sleep(2)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception | %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"ok": False})


app.include_router(whatsapp_router)


@app.get("/health")
def health():
    return {"ok": True}
