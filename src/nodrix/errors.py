class NodrixError(Exception):
    """Base runtime exception under the stable legacy name."""


# An alias, rather than a subclass, keeps exception identity stable for users
# that mix the old and new import paths during the 2.x compatibility window.
PlyctlError = NodrixError


class ManifestError(NodrixError):
    """Invalid pipeline manifest."""


class PluginError(NodrixError):
    """Node plugin cannot be loaded."""


class ProviderError(PluginError):
    """Provider metadata, trust policy, or runtime registration is invalid."""


class RuntimeGraphError(NodrixError):
    """Pipeline graph cannot be executed."""
