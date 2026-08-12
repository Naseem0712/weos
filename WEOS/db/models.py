"""SQLAlchemy models for the WEOS persistent quote system (Part 1).

Tables: customers, projects, quotes, quote_items, quote_versions,
quote_calculations, quote_bom, quote_agent_events, quote_suggestions,
quote_documents.

JSON columns use SQLAlchemy's portable ``JSON`` type so the same models work on
PostgreSQL (production) and sqlite (dev fallback).

This module is only imported lazily (via ``init_db`` / ``quote_store``) so a
missing SQLAlchemy install never breaks ``import WEOS``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Mobile number is the login identity (Part: mobile-number login, no OTP).
    mobile: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    gst_no: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(String(80))
    state_code: Mapped[str | None] = mapped_column(String(10))
    contact_person: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    quotes: Mapped[list["Quote"]] = relationship(back_populates="customer")
    projects: Mapped[list["Project"]] = relationship(back_populates="customer")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "mobile": self.mobile,
            "name": self.name,
            "email": self.email,
            "gstNo": self.gst_no,
            "address": self.address,
            "state": self.state,
            "stateCode": self.state_code,
            "contactPerson": self.contact_person,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_number: Mapped[str | None] = mapped_column(String(40), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    customer: Mapped["Customer | None"] = relationship(back_populates="projects")
    quotes: Mapped[list["Quote"]] = relationship(back_populates="project")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "projectNumber": self.project_number,
            "customerId": self.customer_id,
            "name": self.name,
            "status": self.status,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    quote_number: Mapped[str | None] = mapped_column(String(40), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)

    product: Mapped[str | None] = mapped_column(String(80))
    series: Mapped[str | None] = mapped_column(String(80))
    width_mm: Mapped[float | None] = mapped_column(Float)
    height_mm: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    track_count: Mapped[float | None] = mapped_column(Float)
    shutter_count: Mapped[int | None] = mapped_column(Integer)

    colour: Mapped[str | None] = mapped_column(String(80))
    glass: Mapped[Any] = mapped_column(JSON, nullable=True)
    hardware: Mapped[Any] = mapped_column(JSON, nullable=True)
    materials: Mapped[Any] = mapped_column(JSON, nullable=True)
    bom: Mapped[Any] = mapped_column(JSON, nullable=True)
    rates: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Full editable line payload(s) — mirrors legacy project "lines" shape.
    lines: Mapped[Any] = mapped_column(JSON, nullable=True)

    selling_price: Mapped[float | None] = mapped_column(Float)
    gst_percent: Mapped[float | None] = mapped_column(Float)
    gst_amount: Mapped[float | None] = mapped_column(Float)
    grand_total: Mapped[float | None] = mapped_column(Float)

    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped["Customer | None"] = relationship(back_populates="quotes")
    project: Mapped["Project | None"] = relationship(back_populates="quotes")
    items: Mapped[list["QuoteItem"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    versions: Mapped[list["QuoteVersion"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    calculations: Mapped[list["QuoteCalculation"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    bom_rows: Mapped[list["QuoteBom"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    events: Mapped[list["QuoteAgentEvent"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    suggestions: Mapped[list["QuoteSuggestion"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    documents: Mapped[list["QuoteDocument"]] = relationship(back_populates="quote", cascade="all, delete-orphan")

    def to_dict(self, *, include_children: bool = False) -> dict:
        data = {
            "id": self.id,
            "quoteId": self.quote_id,
            "quoteNumber": self.quote_number,
            "customerId": self.customer_id,
            "projectId": self.project_id,
            "product": self.product,
            "series": self.series,
            "width": self.width_mm,
            "height": self.height_mm,
            "quantity": self.quantity,
            "trackCount": self.track_count,
            "shutterCount": self.shutter_count,
            "colour": self.colour,
            "glass": self.glass,
            "hardware": self.hardware,
            "materials": self.materials,
            "bom": self.bom,
            "rates": self.rates,
            "lines": self.lines,
            "sellingPrice": self.selling_price,
            "gstPercent": self.gst_percent,
            "gstAmount": self.gst_amount,
            "grandTotal": self.grand_total,
            "status": self.status,
            "version": self.version,
            "createdBy": self.created_by,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
            "finalizedAt": _iso(self.finalized_at),
        }
        if self.customer is not None:
            data["customer"] = self.customer.to_dict()
        if include_children:
            data["items"] = [i.to_dict() for i in self.items]
            data["events"] = [e.to_dict() for e in sorted(self.events, key=lambda x: x.id or 0)]
            data["suggestions"] = [s.to_dict() for s in self.suggestions]
            data["documents"] = [d.to_dict() for d in self.documents]
        return data


class QuoteItem(Base):
    __tablename__ = "quote_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer, default=0)
    product: Mapped[str | None] = mapped_column(String(80))
    width_mm: Mapped[float | None] = mapped_column(Float)
    height_mm: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    line_total: Mapped[float | None] = mapped_column(Float)

    quote: Mapped["Quote"] = relationship(back_populates="items")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "lineNo": self.line_no,
            "product": self.product,
            "width": self.width_mm,
            "height": self.height_mm,
            "quantity": self.quantity,
            "payload": self.payload,
            "lineTotal": self.line_total,
        }


class QuoteVersion(Base):
    __tablename__ = "quote_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    snapshot: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    quote: Mapped["Quote"] = relationship(back_populates="versions")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "createdBy": self.created_by,
            "createdAt": _iso(self.created_at),
            "snapshot": self.snapshot,
        }


class QuoteCalculation(Base):
    __tablename__ = "quote_calculations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    result: Mapped[Any] = mapped_column(JSON, nullable=True)
    grand_total: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    quote: Mapped["Quote"] = relationship(back_populates="calculations")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "grandTotal": self.grand_total,
            "createdAt": _iso(self.created_at),
            "result": self.result,
        }


class QuoteBom(Base):
    __tablename__ = "quote_bom"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    bom: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    quote: Mapped["Quote"] = relationship(back_populates="bom_rows")

    def to_dict(self) -> dict:
        return {"id": self.id, "bom": self.bom, "createdAt": _iso(self.created_at)}


class QuoteAgentEvent(Base):
    """Per-quote activity audit trail (Part 8)."""

    __tablename__ = "quote_agent_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    message: Mapped[str | None] = mapped_column(Text)
    data: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    quote: Mapped["Quote"] = relationship(back_populates="events")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "eventType": self.event_type,
            "message": self.message,
            "data": self.data,
            "createdBy": self.created_by,
            "createdAt": _iso(self.created_at),
        }


class QuoteSuggestion(Base):
    """Persisted live Agent suggestions (Part 4)."""

    __tablename__ = "quote_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    suggestion_key: Mapped[str | None] = mapped_column(String(80), index=True)
    type: Mapped[str] = mapped_column(String(30), default="info")
    message: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(120))
    confidence: Mapped[float | None] = mapped_column(Float)
    action: Mapped[str | None] = mapped_column(String(120))
    why: Mapped[Any] = mapped_column(JSON, nullable=True)
    data: Mapped[Any] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    quote: Mapped["Quote"] = relationship(back_populates="suggestions")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.suggestion_key,
            "type": self.type,
            "message": self.message,
            "reason": self.reason,
            "source": self.source,
            "confidence": self.confidence,
            "action": self.action,
            "why": self.why,
            "data": self.data,
            "status": self.status,
            "createdAt": _iso(self.created_at),
        }


class QuoteDocument(Base):
    __tablename__ = "quote_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="customer_pdf")
    filename: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    quote: Mapped["Quote"] = relationship(back_populates="documents")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "filename": self.filename,
            "url": self.url,
            "meta": self.meta,
            "createdAt": _iso(self.created_at),
        }


class LibraryFile(Base):
    """Durable mirror of Product Library JSON files (products + section catalogue).

    On Railway the container filesystem is ephemeral, so product folders written
    under ``products_dir()`` are lost on every redeploy. Each JSON file in the
    library is mirrored here (keyed by its path relative to ``products_dir()``) so
    the library survives redeploys. On boot the app rehydrates the filesystem from
    these rows; edits/imports write through to this table.
    """

    __tablename__ = "library_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rel_path: Mapped[str] = mapped_column(String(400), unique=True, index=True, nullable=False)
    product_id: Mapped[str | None] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="product")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "relPath": self.rel_path,
            "productId": self.product_id,
            "kind": self.kind,
            "updatedAt": _iso(self.updated_at),
        }


class DurableRecord(Base):
    """Ephemeral-filesystem escape hatch for company / customer / project JSON.

    Railway containers lose ``data_dir()`` on every redeploy. Anything the UI
    treats as "setup" (company identity, customer bill-to profiles, PRJ-* project
    documents, project counters) is mirrored here keyed by a stable string so
    boot can rehydrate the filesystem from Postgres.
    """

    __tablename__ = "durable_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(400), unique=True, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), default="json", index=True)
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    blob_content_type: Mapped[str | None] = mapped_column(String(80))
    blob_filename: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def to_dict(self, *, include_blob: bool = False) -> dict:
        data = {
            "id": self.id,
            "key": self.key,
            "kind": self.kind,
            "payload": self.payload,
            "blobContentType": self.blob_content_type,
            "blobFilename": self.blob_filename,
            "hasBlob": bool(self.blob),
            "updatedAt": _iso(self.updated_at),
        }
        if include_blob and self.blob is not None:
            data["blob"] = self.blob
        return data


class CustomerAdvance(Base):
    """Payment received against a customer account (ledger advances)."""

    __tablename__ = "customer_advances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_key: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_mode: Mapped[str] = mapped_column(String(40), default="cash")
    reference: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[str | None] = mapped_column(String(60), index=True)
    quote_id: Mapped[str | None] = mapped_column(String(60), index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customerKey": self.customer_key,
            "customerName": self.customer_name,
            "amount": self.amount,
            "paymentMode": self.payment_mode,
            "reference": self.reference,
            "note": self.note,
            "projectId": self.project_id,
            "quoteId": self.quote_id,
            "paidAt": _iso(self.paid_at),
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
