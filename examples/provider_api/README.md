# Provider API 1 example

Build and install the provider:

```bash
python -m build
python -m pip install dist/nodrix_example_provider-1.0.0-py3-none-any.whl
nodrix provider info example.echo
nodrix doctor --provider example.echo
```

`provider list` and `provider info` read `nodrix-provider.json` from wheel
metadata without importing `nodrix_example_provider`. The entry point is loaded
only after compatibility, feature, signature, and trust checks.

For a production package, generate `nodrix-provider.sig` before building:

```python
from nodrix.providers import sign_provider_metadata

sign_provider_metadata(
    "nodrix_example_provider/nodrix-provider.json",
    "publisher-private.pem",
)
```

Install the matching public key into the provider trust store and add
`example.echo` to the production allowlist. Private keys never belong in the
wheel or trust store.
