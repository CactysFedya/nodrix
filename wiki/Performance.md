# Performance

- синхронный `Node.process()` вызывается напрямую;
- native bounded queues;
- payload references внутри процесса;
- network serialization вынесена в transport worker;
- независимая очередь каждого stream;
- `sendmsg` scatter/gather на Unix;
- generated custom types используют фиксированный binary layout.

Для измерений:

```bash
nodrix benchmark --warmup 2 --repeat 5
```
