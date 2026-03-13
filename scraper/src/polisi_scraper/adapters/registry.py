"""Auto-discovery and registration of site adapters."""

from __future__ import annotations

from typing import Type

from polisi_scraper.adapters.base import BaseSiteAdapter

# Registry: slug → adapter class
_ADAPTER_REGISTRY: dict[str, Type[BaseSiteAdapter]] = {}


def register_adapter(cls: Type[BaseSiteAdapter]) -> Type[BaseSiteAdapter]:
    """Class decorator to register an adapter."""
    if cls.slug:
        _ADAPTER_REGISTRY[cls.slug] = cls
    return cls


def get_adapter_registry() -> dict[str, Type[BaseSiteAdapter]]:
    """Return the current adapter registry. Triggers import of all adapter modules."""
    # Import all adapter modules to trigger registration
    from polisi_scraper.adapters import (  # noqa: F401
        bheuu,
        dewan_johor,
        dewan_selangor,
        idfr,
        kpkt,
        mcmc,
        moe,
        moh,
        mohe,
        perpaduan,
        rmp,
    )
    return dict(_ADAPTER_REGISTRY)


def get_adapter_class(slug: str) -> Type[BaseSiteAdapter]:
    """Get adapter class by slug."""
    registry = get_adapter_registry()
    if slug not in registry:
        available = ", ".join(sorted(registry.keys()))
        raise ValueError(f"Unknown adapter slug: {slug!r}. Available: {available}")
    return registry[slug]
