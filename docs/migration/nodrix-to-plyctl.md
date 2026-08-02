# Migrating from Nodrix to Plyctl

No flag-day migration is required.

| Before | Canonical now | 2.x status |
| --- | --- | --- |
| `pip install nodrix` | `pip install plyctl` | old distribution moves to a compatibility shim |
| `nodrix validate` | `plyctl validate` | both commands work |
| `import nodrix` | `import plyctl` | both imports share public class identities |
| `nodrix.dev/v2` | `plyctl.dev/v2` | both validate |
| `nodrix.providers` | `plyctl.providers` | both are discovered |
| `nodrix-provider.json` | `plyctl-provider.json` | both are discovered |

Do not mass-rewrite native plugin symbols, `.ndrx` files, `nodrix://` stream
URIs, provider IDs such as `nodrix.ros2`, environment variables, or runtime
artifact paths. Those are stable protocol and ABI names in 2.x.

For new Python code:

```python
from plyctl import Message, Node
```

For new YAML:

```yaml
apiVersion: plyctl.dev/v2
```

Run the existing tests before and after a gradual source rename. Runtime
behavior does not change merely because both spellings are accepted.
