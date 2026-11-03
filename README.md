# PR2DAVINCI

**Adobe Premiere Pro → DaVinci Resolve — V2.0 Preview**

<p align="center">
  <img src="premiere_to_resolve/assets/leonardo-prime-minister.png" alt="Leonardo da Vinci as a prime minister — PR2DAVINCI mascot" width="420">
</p>

**[English](#english) | [Русский](#русский)**

## English

V2 converts a native Premiere `.prproj` project into a DaVinci Resolve `.drp`
file. It writes the DRP directly, so Resolve does not need to be installed or
running during conversion. The same exporter is available in the desktop GUI
and command line.

V2 is a preview. Its source is on the
[`v2/direct-drp` branch](https://github.com/ghostofspirit/pr2davinci/tree/v2/direct-drp).
Download the Linux x86_64 Flatpak from the
[PR2DAVINCI V2.0 Preview release](https://github.com/ghostofspirit/pr2davinci/releases/download/v2.0.0-preview.3/PR2DAVINCI-v2.0.0-preview.3-linux-x86_64.flatpak).

### What V2 does

- Includes the project's timelines, media pool bins, and media references in
  the DRP.
- Leaves source media offline when it is not available, so it can be relinked
  in Resolve later.
- Offers the same DRP export through the GUI and the `premiere-to-resolve-drp`
  command.
- Does not launch Resolve or modify a project already open there.

The generated archive has been compared offline with a Relink-created DRP.
Opening the V2-generated file in Resolve still needs manual validation. Effects,
transitions, retiming, multicam, Essential Graphics, and Lumetri may need review
or reconstruction.

### Run V2 from source

Python 3.10 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
premiere-to-resolve
```

On Windows, activate the environment with `.venv\\Scripts\\activate`.

To create a DRP from the whole Premiere project:

```bash
premiere-to-resolve-drp input.prproj -o output.drp
```

The command saves all project timelines and bins without launching Resolve. If
the output name already exists, it chooses the next available name, such as
`output (2).drp`. The older `premiere-to-resolve-cli` command remains available
for FCP 7 XML interchange.

### Linux Flatpak

Install the downloaded bundle (it includes the GUI and direct DRP CLI):

```bash
flatpak install --user ./PR2DAVINCI-v2.0.0-preview.3-linux-x86_64.flatpak
```

Launch the GUI with `flatpak run --user com.serotoninja.PremiereToResolve`.
To export a project from the command line:

```bash
flatpak run --user --command=premiere-to-resolve-drp \
  com.serotoninja.PremiereToResolve \
  "$HOME/path/to/input.prproj" -o "$HOME/path/to/output.drp"
```

V2 does not currently provide RPM or DEB packages.

### License

PR2DAVINCI source and materials are dedicated to the public domain under
[CC0 1.0 Universal](LICENSE). Third-party components retain their own licenses;
see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

---

## Русский

V2 преобразует нативный проект Premiere `.prproj` в проект DaVinci Resolve
`.drp`. DRP создаётся напрямую: устанавливать или запускать Resolve во время
конвертации не нужно. Один и тот же экспорт доступен в графическом интерфейсе и
командной строке.

V2 пока находится в статусе Preview. Исходный код — в ветке
[`v2/direct-drp`](https://github.com/ghostofspirit/pr2davinci/tree/v2/direct-drp).
Скачать Flatpak для Linux x86_64 можно со страницы
[релиза PR2DAVINCI V2.0 Preview](https://github.com/ghostofspirit/pr2davinci/releases/download/v2.0.0-preview.3/PR2DAVINCI-v2.0.0-preview.3-linux-x86_64.flatpak).

### Что умеет V2

- Переносит в DRP секвенции, папки Media Pool и ссылки на медиа проекта.
- Если исходники недоступны, они остаются Offline — монтажёр может сделать
  relink в Resolve.
- Создаёт DRP одинаковым экспортом из GUI и командой
  `premiere-to-resolve-drp`.
- Не запускает Resolve и не меняет открытый в нём проект.

Структура архива офлайн сравнивалась с DRP, созданным Relink. Открытие DRP в
самом Resolve ещё нужно проверить вручную. Эффекты, переходы, изменение
скорости, multicam, Essential Graphics и Lumetri могут потребовать проверки
или ручного восстановления.

### Запуск V2 из исходников

Нужен Python 3.10 или новее.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
premiere-to-resolve
```

В Windows активируйте окружение командой `.venv\\Scripts\\activate`.

Чтобы сохранить весь проект Premiere в DRP:

```bash
premiere-to-resolve-drp input.prproj -o output.drp
```

Команда включает все секвенции и папки проекта и не запускает Resolve. Если
указанное имя файла уже занято, будет выбрано следующее свободное, например
`output (2).drp`. Для обмена через FCP 7 XML остаётся команда
`premiere-to-resolve-cli`.

### Linux Flatpak

Установите скачанный bundle. В него входят GUI и прямая CLI-команда экспорта DRP:

```bash
flatpak install --user ./PR2DAVINCI-v2.0.0-preview.3-linux-x86_64.flatpak
```

Запустить GUI можно командой `flatpak run --user com.serotoninja.PremiereToResolve`.
Чтобы создать DRP из командной строки:

```bash
flatpak run --user --command=premiere-to-resolve-drp \
  com.serotoninja.PremiereToResolve \
  "$HOME/path/to/input.prproj" -o "$HOME/path/to/output.drp"
```

Пакеты RPM и DEB для V2 пока не подготовлены.

### Лицензия

Исходный код и материалы PR2DAVINCI посвящены общественному достоянию по
[лицензии CC0 1.0 Universal](LICENSE). У сторонних компонентов свои лицензии;
см. [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
