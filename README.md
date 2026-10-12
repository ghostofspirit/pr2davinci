# PR2DAVINCI
Adobe Premiere to DaVinci Resolve Project Converter

<p align="center">
  <img src="premiere_to_resolve/assets/leonardo-prime-minister.png" alt="Leonardo da Vinci as a prime minister — PR2DAVINCI mascot" width="420">
</p>

Первая версия — **1.0.0**. История изменений: [`CHANGELOG.md`](CHANGELOG.md).

Кроссплатформенный desktop-конвертер Adobe Premiere Pro в DaVinci Resolve.
Приложение читает обычные и gzip-сжатые `.prproj`, переносит выбранную секвенцию
в DaVinci Resolve Studio и автоматически экспортирует проект в `.drp`.

## Запуск

Нужен Python 3.10 или новее.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
premiere-to-resolve
```

На Windows активируйте окружение командой `.venv\\Scripts\\activate`.
При первом запуске окно можно переключить между русским и английским.

## Конвертация

Перетащите `.prproj` в окно или выберите его кнопкой. Укажите секвенцию,
папку и имя файла. «Передать проект в Resolve Studio» автоматически создаёт
DRP, а «Сохранить XML» экспортирует interchange-файл для ручного импорта:
FCPXML для нативных `.prproj` и FCP 7 XML для XML-представления Premiere.
Список содержит только секвенции проекта (без вложенных ссылок), поддерживает
поиск по имени и различает одноимённые секвенции по их ID.
Если Resolve не найден автоматически, укажите исполняемый файл Resolve Studio.

Для локальной передачи нужна DaVinci Resolve Studio с включённым внешним
scripting (**Preferences → System → General → External scripting using → Local**).
Если Resolve не запущен, PR2DAVINCI запустит его. Перед передачей закройте
открытый в Resolve проект; если в нём есть изменения, сначала сохраните их.
Импортированный таймлайн сохраняется в DRP автоматически; временный проект
удаляется из базы Resolve.

Нативные `.prproj` разбираются библиотекой py-premiere и экспортируются в
FCPXML 1.9 — формат, который Resolve импортирует напрямую. Клиповые точки,
дорожки, тайминг и доступные ссылки на медиа переносятся; если Windows-пути
можно сопоставить с подключённым диском проекта, приложение делает это
автоматически. Несопоставленные файлы потребуют relink в Resolve, а в журнале
будут отмечены пропущенные синтетические клипы и неподдержанные эффекты,
переходы или изменение скорости. Вложенные и multicam-секвенции,
Essential Graphics и Lumetri могут требовать ручной проверки.

Разбор Premiere использует стороннюю библиотеку [py-premiere](https://github.com/Pouf/py-premiere)
(MIT License); её лицензия распространяется вместе с установленным пакетом.

Исходный код и материалы PR2DAVINCI посвящены общественному достоянию по
CC0 1.0 Universal; см. [`LICENSE`](LICENSE). Лицензии сторонних компонентов
и ограничения на права третьих лиц остаются в силе.

## Сборка desktop-приложения

PySide6 поддерживает desktop на Linux, macOS и Windows. Создавайте отдельную
сборку на каждой целевой ОС: запустите следующие команды на компьютере с этой
системой. Qt for Python рекомендует `pyside6-deploy` для сборки приложения.

```bash
python -m pip install .
pyside6-deploy launch_gui.py
```

Готовый standalone-бандл и промежуточные файлы сборки появятся в папках,
указанных в `pysidedeploy.spec` и конфигурации Qt. Первый запуск `pyside6-deploy`
создаёт `pysidedeploy.spec`; после проверки параметров его удобно хранить
вместе с проектом.

Сборка и запуск проверены только в текущем Linux-окружении. Для готовых
артефактов Windows и macOS нужны сборочные машины или CI runners этих систем.

### Flatpak для Linux

Манифест Flatpak и команды сборки находятся в [`flatpak/README.md`](flatpak/README.md).
Для запуска конвертера в Flatpak ему разрешён доступ к домашней папке, чтобы
открывать проекты Premiere и сохранять DRP-файлы. Для связи с Resolve Flatpak
использует `flatpak-spawn --host` и запускает ResolvePython на хосте.

## CLI

GUI — основной способ запуска. Для командной строки установите проект и
используйте отдельную команду, чтобы отдельно создать XML:

```bash
premiere-to-resolve-cli input.prproj --list-sequences
premiere-to-resolve-cli input.prproj -o timeline.fcpxml --sequence "Edit v3"
```

