# Troubleshooting

## Stream не виден

1. Убедитесь, что он указан в `streams.exports`.
2. Проверьте, что publisher продолжает работать.
3. Увеличьте `nodrix stream list --timeout 3`.
4. Проверьте multicast/firewall.
5. Используйте явный `nodrix://IP:PORT/name` URI.

## Native extension не загружена

Установите пакет из wheel или выполните:

```bash
python setup.py build_ext --inplace
```

## C++ plugin ABI mismatch

Пересоберите plugin с headers Nodrix 0.6.0. ABI версии 0.6.0 остаётся 2.
