from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .models import Provider


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def is_provider_blocked(p: Provider) -> bool:
    """Bloqueo práctico: mientras blocked_until > now, no se ofrece ni asigna."""
    if not p.blocked_until:
        return False
    return p.blocked_until.replace(tzinfo=None) > datetime.utcnow()


def list_available_services(db: Session) -> list[str]:
    """Servicios disponibles según providers activos."""
    rows = (
        db.query(Provider.service)
        .filter(Provider.active == True)
        .distinct()
        .order_by(Provider.service.asc())
        .all()
    )
    return [r[0] for r in rows if r and r[0]]


def find_top_providers(db: Session, service: str, comuna: str, limit: int = 3) -> list[Provider]:
    """Top providers por rating (y cantidad) para servicio+comuna, excluyendo bloqueados."""
    service_n = _norm(service)
    comuna_n = _norm(comuna)

    providers = (
        db.query(Provider)
        .filter(Provider.active == True)
        .filter(Provider.service == service)
        .filter(Provider.comuna == comuna)
        .order_by(Provider.rating_avg.desc(), Provider.rating_count.desc(), Provider.id.asc())
        .limit(limit * 3)  # traemos extra para poder filtrar bloqueados
        .all()
    )

    out: list[Provider] = []
    for p in providers:
        if is_provider_blocked(p):
            continue
        # sanity normalize on DB side (si hay diferencias de mayúsculas, no matchea; se recomienda guardar normalizado)
        if service_n and _norm(p.service) != service_n:
            continue
        if comuna_n and _norm(p.comuna) != comuna_n:
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return out
