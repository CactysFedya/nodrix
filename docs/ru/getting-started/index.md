# Начало работы

Этот раздел проводит нового пользователя от чистой системы до проверенного и запущенного workspace Plyctl.

## Последовательность

1. [Установите Plyctl 2.3.0a1](installation.md).
2. [Создайте и изучите workspace](first-workspace.md).
3. [Запустите и измените pipeline](first-pipeline.md).
4. Выберите дальнейший путь в разделе [Что изучать дальше](next-steps.md).

После прохождения раздела должно быть понятно:

- где находятся `nodrix.yaml`, manifests, environments, profiles и views;
- как context выбирает окружение, профиль и вид мониторинга;
- зачем запускать `plyctl prepare` до `run` или `up`;
- как `uses` разрешается в builtin, provider или локальный Python-класс;
- где хранятся логи и состояние supervisor.
