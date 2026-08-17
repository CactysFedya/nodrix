# Pipeline OS — 2.x compatibility model

Pipeline OS was the original Nodrix/Plyctl 2.x execution model.

The canonical architecture model is now `System`. A Pipeline remains supported
as a specialized dataflow Definition and compatibility surface, but it is no
longer the universal conceptual model for new Nodrix systems.

Existing Pipeline manifests, runtime APIs, providers, blocks, fragments, and
execution paths remain supported throughout the compatibility transition.

The 2.x Pipeline architecture separates a stable runtime core from independently
versioned domain and platform packages.

```{mermaid}
flowchart LR
  YAML["Typed YAML manifest"] --> Core["Plyctl Core"]
  Core --> Nodes["Python / C++ nodes"]
  Core --> Apps["Managed applications"]
  Core --> Sessions["Provider sessions"]
  Core --> Edges["Logical edges"]
  Edges --> Transport["Local, shared memory, ROS 2, LAN"]
  Providers["Independent provider packages"] --> Core
```

Within the 2.x Pipeline compatibility architecture, the runtime core owns
manifest validation, lifecycle, scheduling, queues, memory planning,
observability, security policy, and reproducible run artifacts. Packages own
platform-specific nodes, sessions, resources, applications, transports, probes,
and templates.

This boundary keeps ROS 2 optional and makes the same model usable for MQTT,
GStreamer, industrial protocols, cloud services, or a custom hardware SDK.
Providers are discovered from metadata and imported only when selected.

Protocol identifiers from Nodrix releases remain stable inside 2.x. They are
compatibility contracts, not evidence that the public rebrand is incomplete.
