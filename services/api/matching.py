from __future__ import annotations

from datetime import datetime


from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from .models import Provider, ProviderCoverage


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def is_provider_blocked(p: Provider) -> bool:
    """Bloqueo práctico: mientras blocked_until > now, no se ofrece ni asigna."""
    if not p.blocked_until:
        return False
    return p.blocked_until.replace(tzinfo=None) > datetime.utcnow()


def _matches_comuna(provider: Provider, comuna_n: str) -> bool:
    if not comuna_n:
        return True
    if provider.coverage_areas:
        return any(_norm(cov.comuna) == comuna_n for cov in provider.coverage_areas)
    return _norm(provider.comuna) == comuna_n


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
    if not service_n or not comuna_n:
        return []

    query = (
        db.query(Provider)
        .outerjoin(ProviderCoverage, ProviderCoverage.provider_id == Provider.id)
        .filter(Provider.active == True)
        .filter(func.lower(Provider.service) == service_n)
        .filter(
            or_(
                func.lower(ProviderCoverage.comuna) == comuna_n,
                and_(ProviderCoverage.id.is_(None), func.lower(Provider.comuna) == comuna_n),
            )
        )

        .order_by(Provider.rating_avg.desc(), Provider.rating_count.desc(), Provider.id.asc())
    )

    if limit > 0:
        query = query.limit(limit * 3)  # traemos extra para poder filtrar bloqueados

    providers = query.all()

    out: list[Provider] = []
    for p in providers:
        if is_provider_blocked(p):
            continue
        if service_n and _norm(p.service) != service_n:
            continue
        if comuna_n and not _matches_comuna(p, comuna_n):
            continue
        out.append(p)
        if limit > 0 and len(out) >= limit:
            break
    return out
