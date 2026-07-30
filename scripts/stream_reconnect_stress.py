from __future__ import annotations


from nodrix import Message
from nodrix.streams import StreamClient, StreamServer


def main(iterations: int = 200) -> None:
    server = StreamServer(host="127.0.0.1", port=0)
    server.register("/stress", "core.object", access_mode="token", token="stress-token")
    server.start()
    uri = f"nodrix://127.0.0.1:{server.port}/stress"
    try:
        for sequence in range(iterations):
            client = StreamClient(uri, token="stress-token")
            client.connect()
            server.publish("/stress", Message("core.object", {"sequence": sequence}, sequence=sequence))
            received = client.receive()
            if received.sequence != sequence:
                raise RuntimeError(f"sequence mismatch: {received.sequence} != {sequence}")
            client.close()
    finally:
        server.close()
    print({"connections": iterations, "status": "ok"})


if __name__ == "__main__":
    main()
