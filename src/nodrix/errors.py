class NodrixError(Exception):
    """Base Nodrix exception."""


class ManifestError(NodrixError):
    """Invalid pipeline manifest."""


class PluginError(NodrixError):
    """Node plugin cannot be loaded."""


class RuntimeGraphError(NodrixError):
    """Pipeline graph cannot be executed."""
