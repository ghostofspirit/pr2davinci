# PR2DAVINCI

**Adobe Premiere Pro → DaVinci Resolve — V2.0 Preview**

<p align="center">
  <img src="premiere_to_resolve/assets/leonardo-prime-minister.png" alt="Leonardo da Vinci as a prime minister — PR2DAVINCI mascot" width="420">
</p>

V2 converts a native Premiere `.prproj` project into a DaVinci Resolve `.drp`
file. It writes the DRP directly, so Resolve does not need to be installed or
running during conversion. The same exporter is available in the desktop GUI
and command line.

V2 is a preview. Its source is on the
[`v2/direct-drp` branch](https://github.com/ghostofspirit/pr2davinci/tree/v2/direct-drp).
Ready-to-download V2 desktop packages have not been published yet.

## What V2 does

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

## Run V2 from source

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

## Linux Flatpak

Build and install the V2 Flatpak using the instructions in
[`flatpak/README.md`](flatpak/README.md). The package includes the GUI and direct
DRP CLI. To export a project from the installed Flatpak:

```bash
flatpak run --user --command=premiere-to-resolve-drp \
  com.serotoninja.PremiereToResolve \
  "$HOME/path/to/input.prproj" -o "$HOME/path/to/output.drp"
```

V2 does not currently provide RPM or DEB packages.

## License

PR2DAVINCI source and materials are dedicated to the public domain under
[CC0 1.0 Universal](LICENSE). Third-party components retain their own licenses;
see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
