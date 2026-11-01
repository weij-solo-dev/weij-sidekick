"""sidekick.log — logging façade."""

from .log import Log, configure_logging, mask_secret

__all__ = ["Log", "configure_logging", "mask_secret"]
