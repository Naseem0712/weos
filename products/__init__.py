"""Product generator protocol and registry for reusable window/door systems."""

from __future__ import annotations

from abc import ABC, abstractmethod

from cad_engine.types import DrawingModel


class ProductGenerator(ABC):
    """
    Extension point for future systems:
      2 Track, 3 Track, Casement, Fixed, French, Folding, Top Hung, Ventilator, ...
    Each product implements formula-based geometry from named parameters.
    """

    product_id: str
    display_name: str

    @abstractmethod
    def default_params(self) -> dict[str, float]:
        """Named configurable profile parameters and defaults (mm)."""

    @abstractmethod
    def generate(self, width: float, height: float, params: dict[str, float] | None = None) -> DrawingModel:
        """Build a complete parametric drawing for the given overall size."""


_REGISTRY: dict[str, ProductGenerator] = {}


def register(cls: type[ProductGenerator]) -> type[ProductGenerator]:
    """Class decorator: instantiate once and register by product_id."""
    instance = cls()
    _REGISTRY[instance.product_id] = instance
    return cls


def get_product(product_id: str) -> ProductGenerator:
    if product_id not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown product '{product_id}'. Known: {known}")
    return _REGISTRY[product_id]


def list_products() -> list[tuple[str, str]]:
    return [(gid, g.display_name) for gid, g in _REGISTRY.items()]


def ensure_builtin_products() -> None:
    """Import built-in products so they self-register."""
    from products import two_track_sliding as _two  # noqa: F401


__all__ = [
    "ProductGenerator",
    "register",
    "get_product",
    "list_products",
    "ensure_builtin_products",
]
