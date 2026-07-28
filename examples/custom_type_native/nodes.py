from nodrix import Message, SinkNode, SourceNode
from generated import Telemetry


class Source(SourceNode):
    output_types = {"output": "demo.Telemetry"}

    def produce(self):
        for sequence in range(10):
            yield {
                "output": Message(
                    type="demo.Telemetry",
                    payload=Telemetry(sequence, 20.0, (1.0, 2.0, 3.0)),
                    sequence=sequence,
                )
            }


class PrintSink(SinkNode):
    input_types = {"input": "demo.Telemetry"}

    def process(self, inputs):
        print(inputs["input"].payload)
