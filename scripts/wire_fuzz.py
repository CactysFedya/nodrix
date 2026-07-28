from __future__ import annotations

import os
import random
import struct

from nodrix.wire import decode_packet_parts, WireProtocolError


def main(iterations: int = 5000) -> None:
    accepted = 0
    rejected = 0
    for _ in range(iterations):
        header = os.urandom(random.randint(0, 80))
        type_part = os.urandom(random.randint(0, 32))
        metadata = os.urandom(random.randint(0, 128))
        payload = os.urandom(random.randint(0, 512))
        try:
            decode_packet_parts(header, type_part, metadata, payload)
            accepted += 1
        except (WireProtocolError, ValueError, TypeError, UnicodeDecodeError, KeyError, struct.error):
            rejected += 1
    print({"iterations": iterations, "accepted": accepted, "rejected": rejected})


if __name__ == "__main__":
    main()
