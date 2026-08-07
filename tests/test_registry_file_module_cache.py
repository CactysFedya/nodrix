from __future__ import annotations

from pathlib import Path
import sys

import pytest

from nodrix.registry import load_node_class, reset_file_module_cache


MODULE = '''from dataclasses import dataclass
from nodrix.node import Node

@dataclass
class Payload:
    value: int

class Producer(Node):
    def process(self, inputs):
        return None

class Consumer(Node):
    def process(self, inputs):
        return None
'''


def test_local_file_is_loaded_once_and_registered(tmp_path: Path) -> None:
    module_path = tmp_path / "nodes.py"
    module_path.write_text(MODULE, encoding="utf-8")

    reset_file_module_cache()
    producer = load_node_class(f"{module_path}:Producer")
    consumer = load_node_class(f"{module_path}:Consumer")
    producer_again = load_node_class(f"{module_path}:Producer")

    assert producer_again is producer
    assert producer.__module__ == consumer.__module__
    assert producer.__module__ in sys.modules

    module = sys.modules[producer.__module__]
    payload = module.Payload(7)
    assert isinstance(payload, module.Payload)


def test_failed_local_import_is_not_cached(tmp_path: Path) -> None:
    module_path = tmp_path / "recoverable.py"
    module_path.write_text("raise RuntimeError('broken import')\n", encoding="utf-8")

    reset_file_module_cache()
    with pytest.raises(Exception, match="broken import"):
        load_node_class(f"{module_path}:Recovered")

    module_path.write_text(
        "from nodrix.node import Node\n"
        "class Recovered(Node):\n"
        "    def process(self, inputs):\n"
        "        return None\n",
        encoding="utf-8",
    )

    recovered = load_node_class(f"{module_path}:Recovered")
    assert recovered.__name__ == "Recovered"
