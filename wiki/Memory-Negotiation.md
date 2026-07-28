# Memory Negotiation

Ports declare accepted/preferred memory. Edges may choose `auto` or force a domain.

```yaml
memory:
  domain: cuda
  allow_copy: false
```

`nodrix inspect --memory` shows the selected domain, copies, transfers and adapter before the graph runs. Unsupported conversions fail validation.
