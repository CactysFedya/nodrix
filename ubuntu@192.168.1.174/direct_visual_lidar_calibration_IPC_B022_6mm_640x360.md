# Калибровка HiWatch IPC-B022-G2/U 6 мм и Livox Mid‑360S

## `direct_visual_lidar_calibration` + ROS 2 Jazzy + исправленный RTSP-скрипт

Инструкция рассчитана на следующую конфигурацию:

- ноутбук с Ubuntu 24.04;
- ROS 2 Jazzy;
- Livox Mid‑360S;
- IP-камера HiWatch `IPC-B022-G2/U`;
- объектив камеры: **6 мм**;
- используемый RTSP-поток: **640×360**;
- применяется подготовленный приближённый YAML внутренних параметров;
- внешний щит FAST-Calib не используется;
- применяется targetless-метод `direct_visual_lidar_calibration`.

Используемый скрипт:

```text
rtsp_camera_ros2_fixed.py
```

Новый скрипт:

- не использует `cv_bridge`;
- открывает RTSP через OpenCV/FFmpeg по TCP;
- автоматически переподключается при обрыве;
- по умолчанию публикует только сжатое изображение;
- может публиковать `CameraInfo` из готового YAML;
- показывает полный traceback вместо сообщения вида `fatal error 16`.

> **Важно:** YAML для камеры рассчитан приближённо по заявленному углу обзора объектива 6 мм. Он предназначен для первого запуска и оценки результата. Коэффициенты дисторсии неизвестны и установлены в ноль.

---

# 1. Что калибруем

`direct_visual_lidar_calibration` определяет внешнее преобразование между камерой и LiDAR:

```text
камера → LiDAR
```

Для работы алгоритму также нужны внутренние параметры камеры:

```text
fx, fy, cx, cy
k1, k2, p1, p2, k3
```

Для вашей камеры используется подготовленный **приближённый** YAML:

```text
HiWatch IPC-B022-G2/U
объектив: 6 мм
RTSP-разрешение: 640×360
```

Заданные значения:

```text
fx = 628.035361762
fy = 696.008357082
cx = 319.5
cy = 179.5
```

Поскольку точные заводские коэффициенты дисторсии конкретного экземпляра неизвестны, временно используются:

```text
k1 = 0
k2 = 0
p1 = 0
p2 = 0
k3 = 0
```

Это позволяет:

- проверить весь пайплайн;
- записать ROS bags;
- запустить preprocessing;
- получить предварительную внешнюю калибровку;
- проверить, достаточно ли результата для вашего эксперимента.

Это **не заменяет точную внутреннюю калибровку камеры**. Если совмещение будет расходиться по краям изображения, потребуется один раз откалибровать саму камеру.

Итог внешней калибровки сохраняется в:

```text
~/lidar_camera_calib/preprocessed/calib.json
```

Поле результата:

```json
"T_lidar_camera": [x, y, z, qx, qy, qz, qw]
```

Оно задаёт:

```text
p_lidar = T_lidar_camera × p_camera
```

---

# 2. Главное условие

Камера и LiDAR должны быть жёстко закреплены относительно друг друга.

После начала сбора данных нельзя:

- поворачивать камеру отдельно от LiDAR;
- перемещать LiDAR отдельно от камеры;
- менять объектив, фокус или оптический зум;
- менять цифровой зум;
- менять разрешение RTSP-потока;
- включать другой режим кадрирования;
- менять программное исправление дисторсии.

Между сценами можно перемещать только всю конструкцию целиком.

---

# 3. Подготовка каталогов

```bash
mkdir -p ~/lidar_camera_calib/tools
mkdir -p ~/lidar_camera_calib/camera
mkdir -p ~/lidar_camera_calib/bags
mkdir -p ~/lidar_camera_calib/preprocessed
```

Скопируйте скачанный файл:

```bash
cp ~/Downloads/rtsp_camera_ros2_fixed.py \
  ~/lidar_camera_calib/tools/rtsp_camera_ros2.py

chmod +x ~/lidar_camera_calib/tools/rtsp_camera_ros2.py
```

Проверьте:

```bash
ls -l ~/lidar_camera_calib/tools/rtsp_camera_ros2.py
```

---

# 4. Установка зависимостей

```bash
sudo apt update

sudo apt install -y \
  ffmpeg \
  docker.io \
  python3-opencv \
  python3-numpy \
  python3-yaml \
  ros-jazzy-rclpy \
  ros-jazzy-sensor-msgs \
  ros-jazzy-image-view
```

Новый скрипт не использует `cv_bridge`, поэтому пакет `ros-jazzy-cv-bridge` для него не требуется.

Запустите Docker:

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Примените новую группу:

```bash
newgrp docker
```

Проверьте:

```bash
docker version
```

---

# 5. Проверка нового скрипта

```bash
source /opt/ros/jazzy/setup.bash

python3 -m py_compile \
  ~/lidar_camera_calib/tools/rtsp_camera_ros2.py
```

Покажите справку:

```bash
python3 ~/lidar_camera_calib/tools/rtsp_camera_ros2.py --help
```

Основные параметры:

```text
--url             RTSP-ссылка
--fps             частота публикации
--frame-id        имя системы координат камеры
--camera-yaml     готовый YAML внутренней калибровки
--jpeg-quality    качество JPEG
--publish-raw     дополнительно публиковать /camera/image_raw
```

Для внешней калибровки рекомендуется не использовать `--publish-raw`, чтобы не увеличивать ROS bag.

---

# 6. RTSP-ссылка

Укажите фактический адрес камеры:

```bash
export RTSP_URL='rtsp://USER:PASSWORD@CAMERA_IP:554/STREAM_PATH'
```

Пример структуры:

```bash
export RTSP_URL='rtsp://admin:password@192.168.2.195:554/Streaming/Channels/101'
```

Это только пример. Используйте реальный путь потока вашей камеры.

Если пароль содержит специальные символы, их нужно URL-кодировать.

Проверка переменной:

```bash
printf '%s\n' "$RTSP_URL"
```

---

# 7. Проверка RTSP до запуска ROS 2

Сначала убедитесь, что поток действительно открывается:

```bash
ffprobe \
  -rtsp_transport tcp \
  -v error \
  -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate \
  -of default=noprint_wrappers=1 \
  "$RTSP_URL"
```

Пример:

```text
codec_name=h264
width=1920
height=1080
r_frame_rate=25/1
```

Запомните разрешение:

```text
WIDTH × HEIGHT
```

Откройте поток:

```bash
ffplay \
  -rtsp_transport tcp \
  -fflags nobuffer \
  -flags low_delay \
  "$RTSP_URL"
```

Для выхода нажмите:

```text
q
```

После проверки обязательно закройте `ffplay`, чтобы он не занимал RTSP-подключение:

```bash
pkill -f ffplay
```

---

# 8. Установка готового YAML для камеры 6 мм

Используйте файл:

```text
camera_ipc_b022_g2u_640x360_6mm_approx.yaml
```

Скопируйте его в рабочий каталог:

```bash
cp ~/Downloads/camera_ipc_b022_g2u_640x360_6mm_approx.yaml \
  ~/lidar_camera_calib/camera/camera.yaml
```

Проверьте содержимое:

```bash
cat ~/lidar_camera_calib/camera/camera.yaml
```

Ожидаемый YAML:

```yaml
image_width: 640
image_height: 360
camera_name: ipc_b022_g2u_6mm_approx

camera_matrix:
  rows: 3
  cols: 3
  data: [628.035361762, 0.0, 319.500000000,
         0.0, 696.008357082, 179.500000000,
         0.0, 0.0, 1.0]

distortion_model: plumb_bob

distortion_coefficients:
  rows: 1
  cols: 5
  data: [0.0, 0.0, 0.0, 0.0, 0.0]

rectification_matrix:
  rows: 3
  cols: 3
  data: [1.0, 0.0, 0.0,
         0.0, 1.0, 0.0,
         0.0, 0.0, 1.0]

projection_matrix:
  rows: 3
  cols: 4
  data: [628.035361762, 0.0, 319.500000000, 0.0,
         0.0, 696.008357082, 179.500000000, 0.0,
         0.0, 0.0, 1.0, 0.0]
```

Проверьте, что используемый RTSP-поток действительно имеет разрешение `640×360`:

```bash
ffprobe \
  -rtsp_transport tcp \
  -v error \
  -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate \
  -of default=noprint_wrappers=1 \
  "$RTSP_URL"
```

Ожидается:

```text
width=640
height=360
```

Если вывод показывает другое разрешение, этот YAML использовать нельзя. Сначала переключите дополнительный поток камеры на `640×360`.

---

# 9. Окружение ROS 2

В каждом новом терминале выполняйте:

```bash
source /opt/ros/jazzy/setup.bash

export ROS_DOMAIN_ID=26
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

Для Livox дополнительно:

```bash
source ~/livox_ws/install/setup.bash
```

---

# 10. Запуск RTSP → ROS 2

Закройте старые процессы:

```bash
pkill -f rtsp_camera_ros2.py || true
pkill -f ffplay || true
```

Задайте переменные:

```bash
source /opt/ros/jazzy/setup.bash

export ROS_DOMAIN_ID=26
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

export RTSP_URL='rtsp://USER:PASSWORD@CAMERA_IP:554/STREAM_PATH'

export CAMERA_YAML=~/lidar_camera_calib/camera/camera.yaml
```

Запустите исправленный скрипт:

```bash
python3 -u ~/lidar_camera_calib/tools/rtsp_camera_ros2.py \
  --fps 2 \
  --jpeg-quality 90 \
  --frame-id camera_optical_frame \
  --camera-yaml "$CAMERA_YAML"
```

Не добавляйте:

```text
--publish-raw
```

Для `direct_visual_lidar_calibration` достаточно сжатого изображения.

Ожидаемые сообщения:

```text
RTSP stream opened
RTSP frame: WIDTHxHEIGHT
Published frames: 1
```

Нормальный набор топиков:

```text
/camera/image/compressed
/camera/camera_info
```

---

# 11. Проверка топиков камеры

Откройте второй терминал:

```bash
source /opt/ros/jazzy/setup.bash

export ROS_DOMAIN_ID=26
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

Проверьте:

```bash
ros2 topic list -t | grep camera
```

Ожидается:

```text
/camera/image/compressed [sensor_msgs/msg/CompressedImage]
/camera/camera_info [sensor_msgs/msg/CameraInfo]
```

Проверьте частоту:

```bash
ros2 topic hz /camera/image/compressed
```

Ожидаемая частота:

```text
около 2 Hz
```

Проверьте `CameraInfo`:

```bash
ros2 topic echo /camera/camera_info --once
```

Проверьте разрешение и матрицу:

```text
width
height
distortion_model
d
k
r
p
```

---

# 12. Просмотр сжатого изображения

Пакет `image_view` может подписаться на базовое имя транспорта:

```bash
ros2 run image_view image_view \
  --ros-args \
  -r image:=/camera/image
```

Если изображение не открылось, проверьте поток через ROS 2:

```bash
ros2 topic echo /camera/image/compressed --once
```

Для временного просмотра сырого изображения можно перезапустить скрипт:

```bash
python3 -u ~/lidar_camera_calib/tools/rtsp_camera_ros2.py \
  --fps 5 \
  --jpeg-quality 90 \
  --camera-yaml "$CAMERA_YAML" \
  --publish-raw
```

Тогда появится:

```text
/camera/image_raw
```

После проверки вернитесь к запуску без `--publish-raw`.

---

# 13. Если снова появляется ошибка

Новый скрипт должен выводить:

```text
FATAL: ТипОшибки: описание
Traceback ...
```

Скопируйте весь блок, начиная с:

```text
FATAL:
```

Проверка RTSP отдельно:

```bash
ffprobe \
  -rtsp_transport tcp \
  -v error \
  "$RTSP_URL"
```

Проверка зависимостей:

```bash
python3 - <<'PY'
import cv2
import numpy
import yaml
import rclpy
from sensor_msgs.msg import CameraInfo, CompressedImage, Image

print("OpenCV:", cv2.__version__)
print("NumPy:", numpy.__version__)
print("Dependencies: OK")
PY
```

---

# 14. Запуск Livox Mid‑360S как PointCloud2

`direct_visual_lidar_calibration` нужен тип:

```text
sensor_msgs/msg/PointCloud2
```

Нельзя записывать только:

```text
livox_interfaces/msg/CustomMsg
```

Откройте отдельный терминал:

```bash
source /opt/ros/jazzy/setup.bash
source ~/livox_ws/install/setup.bash

export ROS_DOMAIN_ID=26
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

Запустите драйвер:

```bash
ros2 launch livox_ros_driver2 rviz_MID360_launch.py
```

Если используется ваш launch-файл, установите:

```python
xfer_format = 0
```

Значения:

```text
xfer_format = 0 → Livox PointCloud2
xfer_format = 1 → Livox CustomMsg
xfer_format = 2 → стандартный PointXYZI для ROS
```

Для текущей инструкции используйте:

```text
xfer_format = 0
```

---

# 15. Найти фактический LiDAR-топик

```bash
ros2 topic list -t | grep PointCloud2
```

Возможный результат:

```text
/livox/lidar [sensor_msgs/msg/PointCloud2]
```

Задайте переменную:

```bash
export POINTS_TOPIC=/livox/lidar
```

Используйте имя из фактического вывода, а не обязательно `/livox/lidar`.

Проверка:

```bash
ros2 topic type "$POINTS_TOPIC"
```

Ожидается:

```text
sensor_msgs/msg/PointCloud2
```

Частота:

```bash
ros2 topic hz "$POINTS_TOPIC"
```

Поля:

```bash
ros2 topic echo "$POINTS_TOPIC" --once
```

В `fields` должно присутствовать:

```text
intensity
```

---

# 16. Финальная проверка перед записью

В терминале записи:

```bash
source /opt/ros/jazzy/setup.bash
source ~/livox_ws/install/setup.bash

export ROS_DOMAIN_ID=26
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

export IMAGE_TOPIC=/camera/image/compressed
export CAMERA_INFO_TOPIC=/camera/camera_info
export POINTS_TOPIC=/livox/lidar
```

Проверьте типы:

```bash
ros2 topic type "$IMAGE_TOPIC"
ros2 topic type "$CAMERA_INFO_TOPIC"
ros2 topic type "$POINTS_TOPIC"
```

Должно быть:

```text
sensor_msgs/msg/CompressedImage
sensor_msgs/msg/CameraInfo
sensor_msgs/msg/PointCloud2
```

Проверьте частоты:

```bash
ros2 topic hz "$IMAGE_TOPIC"
ros2 topic hz "$POINTS_TOPIC"
```

---

# 17. Подходящая сцена

Нужна обычная неподвижная сцена с геометрией и текстурой.

Хорошо подходят:

- стены, пол и потолок;
- дверные проёмы;
- окна без сильных бликов;
- шкафы;
- стеллажи;
- столы;
- надписи;
- контрастные поверхности;
- объекты на разных расстояниях;
- вертикальные и горизонтальные границы.

Плохо подходят:

- одна пустая белая стена;
- тёмная комната;
- стеклянные стены;
- движущиеся люди;
- автомобили в движении;
- листья на ветру;
- сильный солнечный свет;
- сцена без заметных углов;
- все объекты на одном расстоянии.

---

# 18. Запись калибровочных ROS bags

Рекомендуется записать:

```text
5–10 сцен
```

Одна запись:

```text
15 секунд
```

Во время каждой отдельной записи камера и LiDAR должны быть неподвижны.

Между записями:

1. остановите запись;
2. переместите всю конструкцию;
3. выберите другую сцену или другой ракурс;
4. снова полностью остановите конструкцию;
5. начните следующую запись.

## Сцена 1

```bash
ros2 bag record \
  -o ~/lidar_camera_calib/bags/scene_01 \
  "$IMAGE_TOPIC" \
  "$CAMERA_INFO_TOPIC" \
  "$POINTS_TOPIC"
```

Через 15 секунд:

```text
Ctrl+C
```

## Сцена 2

```bash
ros2 bag record \
  -o ~/lidar_camera_calib/bags/scene_02 \
  "$IMAGE_TOPIC" \
  "$CAMERA_INFO_TOPIC" \
  "$POINTS_TOPIC"
```

Аналогично создайте:

```text
scene_03
scene_04
scene_05
```

Лучше:

```text
scene_01 ... scene_08
```

---

# 19. Проверка записей

```bash
ros2 bag info ~/lidar_camera_calib/bags/scene_01
```

Должны присутствовать:

```text
/camera/image/compressed
/camera/camera_info
/livox/lidar
```

И типы:

```text
sensor_msgs/msg/CompressedImage
sensor_msgs/msg/CameraInfo
sensor_msgs/msg/PointCloud2
```

Проверьте все bags:

```bash
for bag in ~/lidar_camera_calib/bags/scene_*; do
  echo
  echo "===== $bag ====="
  ros2 bag info "$bag"
done
```

Не переходите дальше, если хотя бы в одной записи отсутствуют изображения или облака точек.

---

# 20. Установка Docker-образа калибратора

```bash
docker pull koide3/direct_visual_lidar_calibration:jazzy
```

Подготовьте выходной каталог:

```bash
rm -rf ~/lidar_camera_calib/preprocessed/*
mkdir -p ~/lidar_camera_calib/preprocessed
```

Разрешите контейнеру открыть графическое окно:

```bash
xhost +si:localuser:root
```

Задайте пути:

```bash
export CALIB_BAGS="$(realpath ~/lidar_camera_calib/bags)"
export CALIB_OUT="$(realpath ~/lidar_camera_calib/preprocessed)"
```

Проверка:

```bash
printf 'BAGS: %s\nOUT:  %s\n' \
  "$CALIB_BAGS" \
  "$CALIB_OUT"
```

---

# 21. Функция запуска Docker

Добавьте в текущий терминал:

```bash
dvlc() {
  local dri_args=()

  if [ -e /dev/dri ]; then
    dri_args+=(--device=/dev/dri)
  fi

  docker run --rm -it \
    --net host \
    "${dri_args[@]}" \
    -e DISPLAY="$DISPLAY" \
    -e QT_X11_NO_MITSHM=1 \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    -v "$CALIB_BAGS":/tmp/input_bags:ro \
    -v "$CALIB_OUT":/tmp/preprocessed \
    koide3/direct_visual_lidar_calibration:jazzy \
    "$@"
}
```

Проверьте:

```bash
type dvlc
```

Если используется NVIDIA и установлен NVIDIA Container Toolkit, в функцию вместо `/dev/dri` можно добавить:

```text
--gpus all
```

---

# 22. Preprocessing с готовым приближённым CameraInfo

Скрипт публикует `CameraInfo` из готового YAML для `IPC-B022-G2/U`, 6 мм, 640×360. Если в каждом bag записаны один image-топик, один `CameraInfo` и один `PointCloud2`, используйте автоматический выбор:

```bash
dvlc \
  ros2 run direct_visual_lidar_calibration preprocess \
  /tmp/input_bags \
  /tmp/preprocessed \
  -a \
  -v \
  -i intensity
```

Параметры:

```text
-a             автоматически выбрать image, CameraInfo и PointCloud2
-v             показать накопление облака
-i intensity   использовать поле интенсивности Livox
```

Если автоматический выбор не сработал, укажите топики явно:

```bash
dvlc \
  ros2 run direct_visual_lidar_calibration preprocess \
  /tmp/input_bags \
  /tmp/preprocessed \
  --image_topic /camera/image/compressed \
  --camera_info_topic /camera/camera_info \
  --points_topic /livox/lidar \
  --intensity_channel intensity \
  -v
```

Если ваш фактический LiDAR-топик отличается, замените:

```text
/livox/lidar
```

---

# 23. Резервный preprocessing без CameraInfo

Этот раздел нужен только в том случае, если вы записали bags без `/camera/camera_info`.

Задайте реальные параметры:

```bash
export CAMERA_MODEL='plumb_bob'
export CAMERA_INTRINSIC='FX,FY,CX,CY'
export CAMERA_DISTORTION='K1,K2,P1,P2,K3'
```

Пример формата, а не реальные параметры:

```bash
export CAMERA_INTRINSIC='1430.2,1428.7,960.5,540.1'
export CAMERA_DISTORTION='-0.12,0.08,0.0003,-0.0002,0.0'
```

Запуск:

```bash
dvlc \
  ros2 run direct_visual_lidar_calibration preprocess \
  /tmp/input_bags \
  /tmp/preprocessed \
  --image_topic /camera/image/compressed \
  --points_topic /livox/lidar \
  --camera_model "$CAMERA_MODEL" \
  --camera_intrinsic "$CAMERA_INTRINSIC" \
  --camera_distortion_coeffs "$CAMERA_DISTORTION" \
  --intensity_channel intensity \
  -v
```

Не используйте вымышленные значения из примера.

---

# 24. Проверка preprocessing

```bash
find ~/lidar_camera_calib/preprocessed \
  -maxdepth 1 \
  -type f \
  -printf '%f\n' \
  | sort
```

Ожидаются файлы вида:

```text
calib.json
scene_01.png
scene_01.ply
scene_01_lidar_indices.png
scene_01_lidar_intensities.png
...
```

Если Docker создал файлы от `root`:

```bash
sudo chown -R "$USER:$USER" \
  ~/lidar_camera_calib
```

Если изображение или облако пустое, не переходите к следующему этапу.

---

# 25. Ручное начальное приближение

Официальный Docker-образ не содержит SuperGlue, поэтому используйте ручной вариант:

```bash
dvlc \
  ros2 run direct_visual_lidar_calibration \
  initial_guess_manual \
  /tmp/preprocessed
```

В открывшемся окне:

1. выберите правой кнопкой точку в облаке;
2. выберите соответствующую точку на изображении;
3. нажмите `Add picked points`;
4. повторите для других точек;
5. нажмите `Estimate`;
6. измените `blend_weight`;
7. проверьте приблизительное совмещение;
8. нажмите `Save`.

Минимум:

```text
3 соответствия
```

Практически лучше:

```text
6–12 соответствий
```

Выбирайте точки:

- по всему изображению;
- слева и справа;
- сверху и снизу;
- на ближних и дальних объектах;
- на однозначных геометрических углах.

Не выбирайте:

- людей;
- движущиеся объекты;
- стекло;
- блики;
- листву;
- неоднозначные поверхности.

---

# 26. Точная калибровка

```bash
dvlc \
  ros2 run direct_visual_lidar_calibration \
  calibrate \
  /tmp/preprocessed
```

Стандартный метод:

```text
nid_bfgs
```

При необходимости укажите явно:

```bash
dvlc \
  ros2 run direct_visual_lidar_calibration \
  calibrate \
  /tmp/preprocessed \
  --registration_type nid_bfgs
```

Не закрывайте окно до завершения оптимизации.

---

# 27. Просмотр результата

```bash
dvlc \
  ros2 run direct_visual_lidar_calibration \
  viewer \
  /tmp/preprocessed
```

Изменяйте параметр:

```text
blend_weight
```

Хороший результат:

- точки стен совпадают с изображением стен;
- дверные и оконные проёмы не раздваиваются;
- вертикальные границы совпадают;
- результат корректен в центре и по краям;
- близкие и дальние объекты совмещены;
- результат устойчив на всех записанных сценах.

Плохой результат:

- постоянное смещение;
- неверный поворот;
- совпадает только центр;
- края расходятся;
- ближняя часть совпадает, дальняя нет;
- разные сцены дают разный результат.

Для используемого приближённого YAML особенно важна проверка краёв изображения. Если центр совмещён, а края систематически расходятся, причина, скорее всего, в неизвестных коэффициентах дисторсии камеры. В этом случае внешнюю калибровку нельзя считать окончательной.

---

# 28. Получение результата

```bash
python3 -m json.tool \
  ~/lidar_camera_calib/preprocessed/calib.json \
  | less
```

Найдите:

```bash
grep -A 8 '"T_lidar_camera"' \
  ~/lidar_camera_calib/preprocessed/calib.json
```

Формат:

```text
[x, y, z, qx, qy, qz, qw]
```

Направление преобразования:

```text
camera frame → LiDAR frame
```

Формула:

```text
p_lidar = T_lidar_camera × p_camera
```

Для FAST-LIVO2 может потребоваться обратное преобразование. Нельзя без проверки просто копировать `T_lidar_camera` в `Rcl/Pcl`.

---

# 29. Очистка разрешения X11

После завершения:

```bash
xhost -si:localuser:root
```

---

# 30. Быстрый порядок действий

## Терминал 1 — камера

```bash
source /opt/ros/jazzy/setup.bash

export ROS_DOMAIN_ID=26
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

export RTSP_URL='rtsp://USER:PASSWORD@CAMERA_IP:554/STREAM_PATH'
export CAMERA_YAML=~/lidar_camera_calib/camera/camera.yaml

python3 -u ~/lidar_camera_calib/tools/rtsp_camera_ros2.py \
  --fps 2 \
  --jpeg-quality 90 \
  --camera-yaml "$CAMERA_YAML"
```

## Терминал 2 — Livox

```bash
source /opt/ros/jazzy/setup.bash
source ~/livox_ws/install/setup.bash

export ROS_DOMAIN_ID=26
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

ros2 launch livox_ros_driver2 rviz_MID360_launch.py
```

## Терминал 3 — проверка

```bash
source /opt/ros/jazzy/setup.bash
source ~/livox_ws/install/setup.bash

export ROS_DOMAIN_ID=26
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

ros2 topic list -t | grep -E 'CameraInfo|CompressedImage|PointCloud2'
```

## Терминал 3 — запись

```bash
export IMAGE_TOPIC=/camera/image/compressed
export CAMERA_INFO_TOPIC=/camera/camera_info
export POINTS_TOPIC=/livox/lidar

ros2 bag record \
  -o ~/lidar_camera_calib/bags/scene_01 \
  "$IMAGE_TOPIC" \
  "$CAMERA_INFO_TOPIC" \
  "$POINTS_TOPIC"
```

## После записи всех сцен

```bash
docker pull koide3/direct_visual_lidar_calibration:jazzy
xhost +si:localuser:root

export CALIB_BAGS="$(realpath ~/lidar_camera_calib/bags)"
export CALIB_OUT="$(realpath ~/lidar_camera_calib/preprocessed)"
```

Затем последовательно:

```text
preprocess
initial_guess_manual
calibrate
viewer
```

---

# 31. Контрольный список

Перед записью:

- [ ] RTSP открывается через `ffprobe`.
- [ ] RTSP открывается через новый скрипт.
- [ ] Нет сообщения `fatal error 16`.
- [ ] Публикуется `/camera/image/compressed`.
- [ ] Публикуется `/camera/camera_info`.
- [ ] Камера имеет объектив 6 мм.
- [ ] RTSP-поток имеет разрешение ровно 640×360.
- [ ] Используется YAML `camera_ipc_b022_g2u_640x360_6mm_approx.yaml`.
- [ ] Публикуется Livox `PointCloud2`.
- [ ] В облаке есть поле `intensity`.
- [ ] Камера и LiDAR жёстко закреплены.

Перед калибровкой:

- [ ] Записано минимум пять сцен.
- [ ] В каждой сцене конструкция была неподвижна.
- [ ] В каждом bag есть изображение, `CameraInfo` и облако.
- [ ] Сцены содержат геометрию и текстуру.
- [ ] Выходной каталог очищен.

После калибровки:

- [ ] Наложение проверено в центре и по краям.
- [ ] Проверены ближние и дальние объекты.
- [ ] Результат проверен на нескольких сценах.
- [ ] Отдельно проверены края кадра из-за нулевых коэффициентов дисторсии.
- [ ] Сохранён `calib.json`.
- [ ] Проверено направление преобразования перед FAST-LIVO2.

---

# Официальные источники

- https://github.com/koide3/direct_visual_lidar_calibration
- https://koide3.github.io/direct_visual_lidar_calibration/
- https://koide3.github.io/direct_visual_lidar_calibration/collection/
- https://koide3.github.io/direct_visual_lidar_calibration/programs/
- https://koide3.github.io/direct_visual_lidar_calibration/docker/
- https://koide3.github.io/direct_visual_lidar_calibration/example/
- https://github.com/Livox-SDK/livox_ros_driver2
