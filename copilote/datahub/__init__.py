"""Accès aux données ERP via le datahub (lecture seule)."""

from __future__ import annotations

from copilote.config import Config, TypeSource

from .base import DataSource
from .cache import SourceEnCache


def creer_source(config: Config) -> DataSource:
    """Instancie la source de données configurée (avec cache pour le datahub réel)."""
    if config.source is TypeSource.MOCK:
        from .mock import MockDataSource

        return MockDataSource(config.chemin_mock)

    from .http import HttpDataSource

    return SourceEnCache(HttpDataSource(config.datahub), config.duree_cache_secondes)


def sans_cache(source: DataSource) -> DataSource:
    """La source réelle derrière un éventuel cache."""
    return source.source if isinstance(source, SourceEnCache) else source


__all__ = ["DataSource", "SourceEnCache", "creer_source", "sans_cache"]
