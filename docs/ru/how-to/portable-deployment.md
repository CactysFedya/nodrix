# Перенос проекта на другое устройство

Здесь описан безопасный процесс для версии 2.3. Команды `plyctl setup` и
`plyctl verify` являются целевым интерфейсом следующих версий, а не заявлением
о текущем CLI.

## Что переносить

Предпочтительный порядок:

1. Git commit, точный source lock и project-local configuration.
2. Проверенный wheelhouse для нужной ОС и архитектуры.
3. Source archive с checksums для offline-устройства.

Нельзя переносить `.venv`, `build/` и native wheels между macOS и Linux ARM64.

## Перенос через Git

На ноутбуке:

```bash
git status --short
git commit -am "Prepare 2.3.0b1"
git push -u origin release/2.3.0b1-stabilization
```

На целевом устройстве:

```bash
git fetch origin
git switch --track origin/release/2.3.0b1-stabilization

python3 -m venv ~/.venvs/plyctl-230b1
source ~/.venvs/plyctl-230b1/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install . --no-build-isolation
python -m pip install \
  ./packages/nodrix-spatial \
  ./packages/nodrix-mapping \
  ./packages/nodrix-ros2 \
  ./packages/nodrix-spatial-ros2
```

ROS 2 остаётся системной зависимостью и не устанавливается из PyPI.

## Offline wheelhouse

Wheelhouse обязан содержать wheel `plyctl`, все нужные provider wheels и
Python dependencies. Перед переносом проверяются hashes.

```bash
python -m pip install \
  --no-index \
  --find-links ./wheelhouse \
  "plyctl==2.3.0b1"
```

Wheelhouse, собранный на macOS, не является Linux ARM64 wheelhouse.

## Локальные параметры устройства

IP-адреса, RTSP credentials, ROS domain ID и device paths хранятся в
исключённом из Git каталоге `local/`. В Git попадают templates и schemas, но
не secrets.

## Проверка до замены рабочего окружения

```bash
plyctl --version
plyctl provider list
python -m pytest \
  tests/test_registry_file_module_cache.py \
  tests/test_release_metadata_consistency.py -q
```

Для робота дополнительно проверяются ROS packages, topic types, rates, frames,
QoS и корректный shutdown.

## Откат

Старое virtual environment сохраняется до завершения qualification. Откат
должен выполняться выбором предыдущего environment и commit, а не ручным
восстановлением изменённого рабочего окружения.
