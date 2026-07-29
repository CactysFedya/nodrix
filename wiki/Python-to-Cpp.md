# Python to C++

Порты и type names сохраняются. Python node можно заменить ссылкой:

```yaml
uses: native:./build/libnode.so#my.node
```

Для пользовательской структуры сначала выполните `nodrix type build`, затем
подключите сгенерированный `.hpp` к C++ plugin.
