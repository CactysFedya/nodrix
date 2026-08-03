# Руководства

## Базовый рабочий процесс

1. Создайте проект командой `plyctl init`.
2. Опишите узлы и связи в `pipeline.yaml`.
3. Проверьте граф через `plyctl validate`.
4. Посмотрите итоговый план через `plyctl inspect`.
5. Запустите pipeline через `plyctl run`.
6. Контролируйте выполнение через `plyctl top`.

## ROS 2

Установите модульные пакеты:

```bash
python -m pip install plyctl plyctl-spatial plyctl-ros2 plyctl-spatial-ros2
plyctl init my-robot --template ros2
plyctl validate my-robot/pipeline.yaml
plyctl run my-robot/pipeline.yaml
```

ROS 2 добавляет приложения, сессии и транспорты, но не создаёт отдельный тип
pipeline и не заменяет ядро Plyctl.
