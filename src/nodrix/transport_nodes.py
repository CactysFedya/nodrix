"""Built-in data-plane nodes for System transports."""

from __future__ import annotations

import socket
import time

from .node import SinkNode, SourceNode
from .registry import register_builtin
from .wire import encode_message, recv_message, send_packet


@register_builtin("core.transport_tcp_sink")
class TcpTransportSink(SinkNode):
    """Send Nodrix Messages to one TCP transport receiver."""

    input_types = {"input": "core.any"}

    def open(self, context):
        super().open(context)
        self.host = str(self.parameters["host"])
        self.port = int(self.parameters["port"])
        self.connect_timeout_seconds = float(
            self.parameters.get("connect_timeout_seconds", 10.0)
        )
        self.retry_interval_seconds = float(
            self.parameters.get("retry_interval_seconds", 0.05)
        )
        self.sock: socket.socket | None = None

    def _connect(self) -> socket.socket:
        if self.sock is not None:
            return self.sock

        deadline = time.monotonic() + self.connect_timeout_seconds
        last_error: OSError | None = None
        while time.monotonic() < deadline:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.settimeout(min(1.0, self.connect_timeout_seconds))
                sock.connect((self.host, self.port))
                sock.settimeout(None)
                self.sock = sock
                return sock
            except OSError as exc:
                last_error = exc
                sock.close()
                time.sleep(self.retry_interval_seconds)

        raise ConnectionError(
            f"TCP transport could not connect to {self.host}:{self.port}: {last_error}"
        )

    def process(self, inputs):
        message = inputs["input"]
        send_packet(self._connect(), encode_message(message))
        return None

    def close(self):
        sock = self.sock
        self.sock = None
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()


@register_builtin("core.transport_tcp_source")
class TcpTransportSource(SourceNode):
    """Receive Nodrix Messages from one TCP transport sender."""

    output_types = {"output": "core.any"}

    def open(self, context):
        super().open(context)
        self.bind_host = str(self.parameters.get("bind_host", "0.0.0.0"))
        self.port = int(self.parameters["port"])
        self.max_message_bytes = int(
            self.parameters.get("max_message_bytes", 256 * 1024 * 1024)
        )
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.bind_host, self.port))
        listener.listen(1)
        self.listener: socket.socket | None = listener
        self.connection: socket.socket | None = None

    def produce(self):
        listener = self.listener
        if listener is None:
            return
        connection, _peer = listener.accept()
        self.connection = connection
        try:
            while True:
                try:
                    message = recv_message(
                        connection,
                        max_message_bytes=self.max_message_bytes,
                    )
                except EOFError:
                    return
                yield {"output": message}
        finally:
            try:
                connection.close()
            finally:
                self.connection = None

    def close(self):
        connection = self.connection
        self.connection = None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

        listener = self.listener
        self.listener = None
        if listener is not None:
            listener.close()


__all__ = ["TcpTransportSink", "TcpTransportSource"]
