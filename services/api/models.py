from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Float, func, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String(64), index=True)
    comuna: Mapped[str] = mapped_column(String(64), index=True)

    name: Mapped[str] = mapped_column(String(120), default="Tecnico")
    whatsapp_e164: Mapped[str] = mapped_column(String(32), default="")  # Ej: 569XXXXXXXX
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Reputación (solo se actualiza cuando hay servicio verificado)
    rating_avg: Mapped[float] = mapped_column(Float, default=0.0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)

    # Bloqueo práctico: si no responde seguimientos, queda bloqueado por X días
    blocked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_wa_id: Mapped[str] = mapped_column(String(64), index=True)
    # Estados sugeridos: OPEN, WAIT_COMUNA, WAIT_OPTIONS, WAIT_CHOICE, WAIT_CONSENT,
    # CONNECTED, CONTACT_CONFIRM_PENDING, SERVICE_CONFIRM_PENDING, RATING_PENDING, CLOSED
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    provider_id: Mapped[Optional[int]] = mapped_column(ForeignKey("providers.id"), nullable=True)

    service: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    comuna: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    problem_type: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    urgency: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # hoy | 1_2_dias | semana
    sector_address: Mapped[Optional[str]] = mapped_column(String(220), nullable=True)

    # Timestamps del flujo
    connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    followup_stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # CONTACT | SERVICE | RATING
    followup_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Doble confirmación
    user_contact_confirmed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    provider_contact_confirmed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    user_service_confirmed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    provider_service_confirmed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Rating (solo se habilita cuando ambos confirman servicio)
    rating_stars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    provider: Mapped[Optional[Provider]] = relationship("Provider", lazy="joined")


class ConversationState(Base):
    __tablename__ = "conversation_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_wa_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    step: Mapped[str] = mapped_column(String(64), default="START", index=True)
    lead_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leads.id"), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    lead: Mapped[Optional[Lead]] = relationship("Lead", lazy="joined")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    blocked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Si tiene un lead pendiente de confirmación (barrera práctica)
    pending_lead_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leads.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    pending_lead: Mapped[Optional[Lead]] = relationship("Lead", lazy="joined")


class LeadOffer(Base):
    __tablename__ = "lead_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..3

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    lead: Mapped[Lead] = relationship("Lead", lazy="joined")
    provider: Mapped[Provider] = relationship("Provider", lazy="joined")

    __table_args__ = (
        UniqueConstraint("lead_id", "provider_id", name="uq_lead_offer"),
        Index("ix_lead_offer_lead_rank", "lead_id", "rank"),
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False, index=True)
    customer_wa_id: Mapped[str] = mapped_column(String(64), index=True)

    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    provider: Mapped[Provider] = relationship("Provider", lazy="joined")
    lead: Mapped[Lead] = relationship("Lead", lazy="joined")

    __table_args__ = (
        Index("ix_reviews_provider_created", "provider_id", "created_at"),
    )


class ProviderState(Base):
    __tablename__ = "provider_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), unique=True, index=True)
    pending_lead_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leads.id"), nullable=True)
    pending_question: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # CONTACT | SERVICE

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    provider: Mapped[Provider] = relationship("Provider", lazy="joined")
    pending_lead: Mapped[Optional[Lead]] = relationship("Lead", lazy="joined")


class InboundMessage(Base):
    """
    Idempotencia: WhatsApp puede reenviar el mismo mensaje (retries).
    Guardamos message_id por wa_id y NO procesamos doble.
    """
    __tablename__ = "inbound_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_wa_id: Mapped[str] = mapped_column(String(64), index=True)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)

    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("customer_wa_id", "message_id", name="uq_inbound_wa_msg"),
        Index("ix_inbound_message_id", "message_id"),
    )
