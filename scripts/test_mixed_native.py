from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
env = dict(os.environ)
env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
cli = [sys.executable, "-m", "nodrix.cli"]

subprocess.run([*cli, "native", "build"], cwd=ROOT, env=env, check=True)
subprocess.run([sys.executable, "examples/video_passthrough/generate_demo_video.py"], cwd=ROOT, env=env, check=True)
subprocess.run([*cli, "run", "examples/unified_native/pipeline.yaml"], cwd=ROOT, env=env, check=True)
