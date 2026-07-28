# DLPack interoperability

Nodrix tensors implement the Python array API DLPack protocol:

```python
Tensor.__dlpack__
Tensor.__dlpack_device__
Tensor.to_dlpack()
Tensor.from_dlpack(...)
```

## Import

```python
from nodrix.vision import Tensor

tensor = Tensor.from_dlpack(torch_tensor, layout="nchw")
```

Shape and dtype are inferred when the provider exposes them. They can be supplied explicitly for opaque providers.

## Export

```python
model_input = torch.utils.dlpack.from_dlpack(tensor)
```

The consumer receives the existing allocation. Nodrix does not create an intermediate NumPy array.

## Synchronisation

DLPack stream negotiation is passed to the provider when supported. Device backends remain responsible for correct stream/event semantics.

## CPU conversion

```python
tensor.numpy(copy=False)
```

is rejected for device-only tensors. `copy=True` requests an explicit host copy through a DLPack-capable backend.
