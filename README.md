# PR2DAVINCI
Adobe Premiere to DaVinci Resolve Project Converter

<p align="center">
  <img src="premiere_to_resolve/assets/leonardo-prime-minister.png" alt="Leonardo da Vinci as a prime minister — PR2DAVINCI mascot" width="420">
</p>

Эта ветка содержит **PR2DAVINCI 2** — экспериментальную кроссплатформенную
GUI-версию для переноса проектов Adobe Premiere Pro в DaVinci Resolve.
Стабильный релиз **1.0.0** остаётся в `main`.

V2 читает нативный `.prproj` и создаёт `.drp` напрямую, без установленного или
запущенного Resolve. В архив попадают секвенции, папки и медиаобъекты проекта;
медиа может отображаться как `Media Offline`, чтобы монтажёр сделал relink в
Resolve. Интерфейс доступен на русском и английском; Qt/PySide позволяет
собирать приложение для Linux, macOS и Windows.

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

Перетащите `.prproj` в окно или выберите его кнопкой. GUI автоматически выбирает
основную секвенцию для показа, а при сохранении включает в DRP все секвенции и
папки проекта. Укажите папку и имя файла, затем нажмите «Сохранить DRP». Файл
собирается локально — Resolve не запускается и открытый проект не меняется.
После сохранения откройте DRP в Resolve, проверьте таймлайны и сделайте relink
исходников. XML сохраняется отдельно для ручного импорта:
FCPXML для нативных `.prproj` и FCP 7 XML для XML-представления Premiere.
Структура V2 офлайн-сверена с проектом Relink; открытие этой сборки в Resolve
пока ожидает ручной проверки.

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

Готовый пакет для Linux x86_64 можно скачать со страницы [релиза PR2DAVINCI v1.0.0](https://github.com/ghostofspirit/pr2davinci/releases/tag/v1.0.0):
[PR2DAVINCI-1.0.0-x86_64.flatpak](https://github.com/ghostofspirit/pr2davinci/releases/download/v1.0.0/PR2DAVINCI-1.0.0-x86_64.flatpak).

Установка и запуск скачанного пакета:

```sh
flatpak install --user ./PR2DAVINCI-1.0.0-x86_64.flatpak
flatpak run --user com.serotoninja.PremiereToResolve
```

Пакету нужен KDE runtime 6.11 из Flathub. Если Flatpak предложит установить его,
подтвердите установку.

Манифест Flatpak и команды сборки находятся в [`flatpak/README.md`](flatpak/README.md).
Для запуска конвертера в Flatpak ему разрешён доступ к домашней папке, чтобы
открывать проекты Premiere и сохранять DRP-файлы.

## Командная строка

В V2 один и тот же прямой экспорт DRP доступен через GUI и командную строку.
Команда `premiere-to-resolve-drp` принимает нативный `.prproj`, сохраняет все
секвенции и папки проекта и не запускает Resolve:

```bash
premiere-to-resolve-drp input.prproj -o output.drp
```

Если файл с таким именем уже существует, конвертер подберёт свободное имя с
суффиксом `(2)`, `(3)` и так далее. Для просмотра секвенций и экспорта
interchange XML остаётся команда `premiere-to-resolve-cli`:

```bash
premiere-to-resolve-cli input.prproj --list-sequences
premiere-to-resolve-cli input.prproj -o timeline.fcpxml --sequence "Edit v3"
```
