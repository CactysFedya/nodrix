# Python → C++ without changing the pipeline

`node.py:FrameMeanNode` is the permanent node interface used by the manifest.
It initially imports `python_backend.py`. Build the optional native backend:

```bash
cd examples/python_to_cpp
python setup.py build_ext --inplace
```

Run the same unchanged pipeline again. `node.py` now imports
`_frame_mean_native`, which reads the NumPy/OpenCV frame through the Python
buffer protocol without copying it and releases the GIL during the C++ loop.

The same pattern is intended for detector preprocessing, postprocessing,
trackers, filters, Re-ID galleries, and custom camera SDK adapters.
