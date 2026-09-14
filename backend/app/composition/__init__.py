"""The composition root: the only package permitted to import adapters."""

from app.adapters.prometheus.metrics import build_metrics
from app.composition.container import Container, StartupConfigurationError, build_container

__all__ = ["Container", "StartupConfigurationError", "build_container", "build_metrics"]
