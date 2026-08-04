# Native и plugin SDK

Native plugin нужен для измеренного hot path или существующей native library. Python node остаётся основным способом разработки.

## C/C++ ABI

Plugin должен:

- сообщать ABI version;
- объявлять feature bits: typed ports, memory domains, zero-copy buffers;
- отклонять неподдерживаемый host ABI;
- экспортировать versioned v2 symbols;
- собираться с release optimization и hidden visibility.

Generated project содержит C++20 passthrough example в `native/`.

## Сборка

```bash
cmake -S native -B native/build -DCMAKE_BUILD_TYPE=Release
cmake --build native/build --parallel
```

Headers находятся в compatibility package `nodrix/native` в серии 2.x.

## Isolation

In-process loading используйте только для доверенного и протестированного plugin. Если crash не должен завершить runtime, выбирайте managed external application или process isolation.
