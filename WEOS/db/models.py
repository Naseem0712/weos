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
    UniqueConstraint,
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
    share_token: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    company_gst: Mapped[str | None] = mapped_column(String(40), index=True)
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
            "shareToken": self.share_token,
            "companyGst": self.company_gst,
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
    item_snapshot: Mapped[Any] = mapped_column(JSON, nullable=True)
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
            "itemSnapshot": self.item_snapshot,
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
    quote_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_type: Mapped[str | None] = mapped_column(String(20), default="advance")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    company_gst: Mapped[str | None] = mapped_column(String(40), index=True)
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
            "quoteVersion": self.quote_version,
            "entryType": self.entry_type or ("refund" if (self.amount or 0) < 0 else "advance"),
            "paidAt": _iso(self.paid_at),
            "companyGst": self.company_gst or "",
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


# ── WEOS V2 canonical identity (additive — does not replace Agent `customers`) ─


class CanonicalCustomer(Base):
    """Company-scoped customer master with immutable ``customer_id`` PK.

    Discovery fields (mobile / GST / name) live in ``CustomerIdentity`` rows —
    they are never foreign keys into quotes/projects.
    """

    __tablename__ = "canonical_customers"

    customer_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(200))
    contact_person: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str | None] = mapped_column(String(80))
    state_code: Mapped[str | None] = mapped_column(String(10))
    site: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    legacy_slug: Mapped[str | None] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    identities: Mapped[list["CustomerIdentity"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    projects: Mapped[list["CanonicalProject"]] = relationship(back_populates="customer")

    def to_dict(self, *, include_identities: bool = False) -> dict:
        data = {
            "customerId": self.customer_id,
            "companyGst": self.company_gst,
            "displayName": self.display_name,
            "address": self.address,
            "email": self.email,
            "contactPerson": self.contact_person,
            "state": self.state,
            "stateCode": self.state_code,
            "site": self.site,
            "notes": self.notes,
            "legacySlug": self.legacy_slug,
            "status": self.status,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }
        if include_identities:
            data["identities"] = [i.to_dict() for i in (self.identities or [])]
        return data


class CustomerIdentity(Base):
    """Searchable identity for a canonical customer — unique per company + kind."""

    __tablename__ = "customer_identities"
    __table_args__ = (
        UniqueConstraint(
            "company_gst",
            "kind",
            "normalized_value",
            name="uq_customer_identity_company_kind_value",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("canonical_customers.customer_id"), index=True, nullable=False
    )
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), index=True, nullable=False)  # mobile|gst|email|name_key
    raw_value: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    customer: Mapped["CanonicalCustomer"] = relationship(back_populates="identities")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customerId": self.customer_id,
            "companyGst": self.company_gst,
            "kind": self.kind,
            "rawValue": self.raw_value,
            "normalizedValue": self.normalized_value,
            "createdAt": _iso(self.created_at),
        }


class CanonicalProject(Base):
    """Company → Customer → Project spine with immutable ``project_id`` (PRJ-…)."""

    __tablename__ = "canonical_projects"

    project_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("canonical_customers.customer_id"), index=True, nullable=False
    )
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    normalized_name: Mapped[str] = mapped_column(String(200), index=True, nullable=False, default="")
    site_address: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    quotation_id: Mapped[str | None] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    customer: Mapped["CanonicalCustomer"] = relationship(back_populates="projects")

    def to_dict(self) -> dict:
        return {
            "projectId": self.project_id,
            "customerId": self.customer_id,
            "companyGst": self.company_gst,
            "name": self.name,
            "normalizedName": self.normalized_name,
            "siteAddress": self.site_address,
            "status": self.status,
            "quotationId": self.quotation_id,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


# ── WEOS V2 design hierarchy (Batch 5) — Floor → Location → DesignDocument ──


class Floor(Base):
    """Project-owned floor. Arbitrary names; system ``Unassigned`` for legacy mapping."""

    __tablename__ = "floors"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_floor_project_code"),
    )

    floor_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("canonical_projects.project_id"), index=True, nullable=False
    )
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(80), index=True)
    level_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    elevation_mm: Mapped[float | None] = mapped_column(Float)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    meta: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    locations: Mapped[list["Location"]] = relationship(back_populates="floor")

    def to_dict(self) -> dict:
        return {
            "floorId": self.floor_id,
            "projectId": self.project_id,
            "companyGst": self.company_gst,
            "name": self.name,
            "code": self.code,
            "levelIndex": self.level_index,
            "elevationMm": self.elevation_mm,
            "isSystem": bool(self.is_system),
            "status": self.status,
            "meta": self.meta,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


class Location(Base):
    """Structured location under a Floor — not free-text ``locationName`` alone."""

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("floor_id", "normalized_name", name="uq_location_floor_normalized_name"),
    )

    location_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    floor_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("floors.floor_id"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), index=True, nullable=False, default="")
    code: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    legacy_location_name: Mapped[str | None] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    floor: Mapped["Floor"] = relationship(back_populates="locations")

    def to_dict(self) -> dict:
        return {
            "locationId": self.location_id,
            "floorId": self.floor_id,
            "projectId": self.project_id,
            "companyGst": self.company_gst,
            "name": self.name,
            "normalizedName": self.normalized_name,
            "code": self.code,
            "notes": self.notes,
            "sortOrder": self.sort_order,
            "legacyLocationName": self.legacy_location_name,
            "status": self.status,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


class DesignDocument(Base):
    """SQL SoT for a project engineering scene — not SVG/browser storage."""

    __tablename__ = "design_documents"

    design_document_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("canonical_projects.project_id"), index=True, nullable=False
    )
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="Main Design")
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    current_revision_id: Mapped[str | None] = mapped_column(String(60), index=True)
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    revisions: Mapped[list["GeometryRevision"]] = relationship(
        back_populates="design_document", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "designDocumentId": self.design_document_id,
            "projectId": self.project_id,
            "companyGst": self.company_gst,
            "name": self.name,
            "status": self.status,
            "currentRevisionId": self.current_revision_id,
            "payload": self.payload,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


class GeometryRevision(Base):
    """Immutable snapshot of DesignDocument content once explicitly created."""

    __tablename__ = "geometry_revisions"
    __table_args__ = (
        UniqueConstraint(
            "design_document_id",
            "revision_number",
            name="uq_geometry_revision_doc_number",
        ),
    )

    revision_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    design_document_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("design_documents.design_document_id"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))
    content_hash: Mapped[str | None] = mapped_column(String(80), index=True)
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    immutable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    design_document: Mapped["DesignDocument"] = relationship(back_populates="revisions")

    def to_dict(self) -> dict:
        return {
            "revisionId": self.revision_id,
            "designDocumentId": self.design_document_id,
            "projectId": self.project_id,
            "companyGst": self.company_gst,
            "revisionNumber": self.revision_number,
            "label": self.label,
            "contentHash": self.content_hash,
            "payload": self.payload,
            "immutable": bool(self.immutable),
            "createdAt": _iso(self.created_at),
        }


# ── WEOS V2 design scene (Batch 6) — Assembly → Element + Connection ────────


CONNECTION_TYPES = (
    "adjacent_independent",
    "frame_to_frame",
    "coupler",
    "shared_mullion",
    "shared_transom",
    "top_bottom_join",
    "corner",
    "custom",
)


class Assembly(Base):
    """First-class grouping of Elements + Connections under a DesignDocument/Location."""

    __tablename__ = "assemblies"
    __table_args__ = (
        UniqueConstraint(
            "design_document_id",
            "display_code",
            name="uq_assembly_doc_display_code",
        ),
    )

    assembly_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    design_document_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("design_documents.design_document_id"), index=True, nullable=False
    )
    location_id: Mapped[str | None] = mapped_column(
        String(60), ForeignKey("locations.location_id"), index=True
    )
    project_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    display_code: Mapped[str] = mapped_column(String(40), nullable=False, default="A-01")
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    bounds: Mapped[Any] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    legacy_line_id: Mapped[str | None] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    elements: Mapped[list["DesignElement"]] = relationship(
        back_populates="assembly", cascade="all, delete-orphan"
    )
    connections: Mapped[list["Connection"]] = relationship(
        back_populates="assembly", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "assemblyId": self.assembly_id,
            "designDocumentId": self.design_document_id,
            "locationId": self.location_id,
            "projectId": self.project_id,
            "companyGst": self.company_gst,
            "displayCode": self.display_code,
            "name": self.name,
            "bounds": self.bounds,
            "sortOrder": self.sort_order,
            "status": self.status,
            "legacyLineId": self.legacy_line_id,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


class DesignElement(Base):
    """Typed leaf geometry under an Assembly — product identity preserved; geometry ≠ series."""

    __tablename__ = "design_elements"
    __table_args__ = (
        UniqueConstraint(
            "assembly_id",
            "display_code",
            name="uq_element_assembly_display_code",
        ),
    )

    element_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    assembly_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("assemblies.assembly_id"), index=True, nullable=False
    )
    design_document_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    display_code: Mapped[str] = mapped_column(String(40), nullable=False, default="W-01")
    product_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    product_id: Mapped[str | None] = mapped_column(String(120), index=True)
    width_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    height_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    x_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    y_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    orientation: Mapped[str | None] = mapped_column(String(40))
    sill_height_mm: Mapped[float | None] = mapped_column(Float)
    parent_element_id: Mapped[str | None] = mapped_column(String(60), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    geometry_payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    config_payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    legacy_line_id: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    assembly: Mapped["Assembly"] = relationship(back_populates="elements")

    def to_dict(self) -> dict:
        return {
            "elementId": self.element_id,
            "assemblyId": self.assembly_id,
            "designDocumentId": self.design_document_id,
            "projectId": self.project_id,
            "companyGst": self.company_gst,
            "displayCode": self.display_code,
            "productType": self.product_type,
            "productId": self.product_id,
            "widthMm": self.width_mm,
            "heightMm": self.height_mm,
            "xMm": self.x_mm,
            "yMm": self.y_mm,
            "orientation": self.orientation,
            "sillHeightMm": self.sill_height_mm,
            "parentElementId": self.parent_element_id,
            "quantity": self.quantity,
            "geometryPayload": self.geometry_payload,
            "configPayload": self.config_payload,
            "legacyLineId": self.legacy_line_id,
            "status": self.status,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


class Connection(Base):
    """Explicit engineered join between two Elements — never implied by touching geometry."""

    __tablename__ = "connections"

    connection_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    assembly_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("assemblies.assembly_id"), index=True, nullable=False
    )
    design_document_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    element_a_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("design_elements.element_id"), index=True, nullable=False
    )
    element_b_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("design_elements.element_id"), index=True, nullable=False
    )
    side_a: Mapped[str | None] = mapped_column(String(40))
    side_b: Mapped[str | None] = mapped_column(String(40))
    connection_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    parameters: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    assembly: Mapped["Assembly"] = relationship(back_populates="connections")

    def to_dict(self) -> dict:
        return {
            "connectionId": self.connection_id,
            "assemblyId": self.assembly_id,
            "designDocumentId": self.design_document_id,
            "projectId": self.project_id,
            "companyGst": self.company_gst,
            "elementAId": self.element_a_id,
            "elementBId": self.element_b_id,
            "sideA": self.side_a,
            "sideB": self.side_b,
            "connectionType": self.connection_type,
            "parameters": self.parameters,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


# ── WEOS V2 Canvas Batch E — FrameMember + DesignCell (structural topology) ──


MEMBER_ORIENTATIONS = ("V", "H")
MEMBER_TYPES = (
    "OUTER_FRAME",
    "MULLION",
    "TRANSOM",
    "COUPLER",
    "MEETING_MEMBER",
    "CUSTOM",
)
SIZE_CHANGE_RULES = ("KEEP_OFFSETS", "SCALE", "CANCEL")


class FrameMember(Base):
    """Real structural member inside an opening — not decorative SVG.

    Coordinates are element-local engineering mm (origin = element top-left).
    World mm = element.xMm/yMm + local. Distinct from DesignElement / Connection.
    """

    __tablename__ = "frame_members"
    __table_args__ = (
        UniqueConstraint(
            "element_id",
            "display_code",
            name="uq_frame_member_element_display_code",
        ),
    )

    member_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    element_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("design_elements.element_id"), index=True, nullable=False
    )
    assembly_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    design_document_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    display_code: Mapped[str] = mapped_column(String(40), nullable=False, default="M-01")
    orientation: Mapped[str] = mapped_column(String(8), index=True, nullable=False)  # V | H
    member_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="MULLION")
    position_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    x1_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    y1_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    x2_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    y2_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    span_cell_id: Mapped[str | None] = mapped_column(String(60), index=True)
    parent_member_id: Mapped[str | None] = mapped_column(String(60), index=True)
    profile_role: Mapped[str | None] = mapped_column(String(80))
    thickness_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    meta: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def to_dict(self) -> dict:
        return {
            "memberId": self.member_id,
            "elementId": self.element_id,
            "assemblyId": self.assembly_id,
            "designDocumentId": self.design_document_id,
            "projectId": self.project_id,
            "companyGst": self.company_gst,
            "displayCode": self.display_code,
            "orientation": self.orientation,
            "memberType": self.member_type,
            "positionMm": self.position_mm,
            "x1Mm": self.x1_mm,
            "y1Mm": self.y1_mm,
            "x2Mm": self.x2_mm,
            "y2Mm": self.y2_mm,
            "spanCellId": self.span_cell_id,
            "parentMemberId": self.parent_member_id,
            "profileRole": self.profile_role,
            "thicknessMm": self.thickness_mm,
            "sortOrder": self.sort_order,
            "status": self.status,
            "meta": self.meta,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }


class DesignCell(Base):
    """Stable-ID panel region produced by FrameMember subdivision.

    Batch E: geometry + lineage only — NO product assignment (Batch F).
    """

    __tablename__ = "design_cells"
    __table_args__ = (
        UniqueConstraint(
            "element_id",
            "display_code",
            name="uq_design_cell_element_display_code",
        ),
    )

    cell_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    element_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("design_elements.element_id"), index=True, nullable=False
    )
    assembly_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    design_document_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    company_gst: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    display_code: Mapped[str] = mapped_column(String(40), nullable=False, default="C-01")
    parent_cell_id: Mapped[str | None] = mapped_column(String(60), index=True)
    x_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    y_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    width_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    height_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_root: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_leaf: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    split_by_member_id: Mapped[str | None] = mapped_column(String(60), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    # Reserved for Batch F — must stay null / unused in Batch E
    product_assignment: Mapped[Any] = mapped_column(JSON, nullable=True)
    meta: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def to_dict(self) -> dict:
        return {
            "cellId": self.cell_id,
            "elementId": self.element_id,
            "assemblyId": self.assembly_id,
            "designDocumentId": self.design_document_id,
            "projectId": self.project_id,
            "companyGst": self.company_gst,
            "displayCode": self.display_code,
            "parentCellId": self.parent_cell_id,
            "xMm": self.x_mm,
            "yMm": self.y_mm,
            "widthMm": self.width_mm,
            "heightMm": self.height_mm,
            "isRoot": bool(self.is_root),
            "isLeaf": bool(self.is_leaf),
            "splitByMemberId": self.split_by_member_id,
            "sortOrder": self.sort_order,
            "status": self.status,
            "productAssignment": None,  # Batch F — never expose assignment in E
            "meta": self.meta,
            "createdAt": _iso(self.created_at),
            "updatedAt": _iso(self.updated_at),
        }
