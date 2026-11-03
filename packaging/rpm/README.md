# Fedora RPM package

The V2 RPM targets Fedora 44. It depends on Fedora's PySide6 and zstandard
packages; `py-premiere` is bundled in the RPM because Fedora does not package it.
The RPM is architecture independent, but this build has only been checked on
Fedora 44 x86_64.

Install the downloaded RPM with DNF so it can resolve the GUI dependencies:

```bash
sudo dnf install ./premiere-to-resolve-2.0.0-1.fc44.noarch.rpm
```

Launch the desktop app from the application menu or run
`premiere-to-resolve`. To export a Premiere project directly to DRP:

```bash
premiere-to-resolve-drp input.prproj -o output.drp
```

The package spec is `premiere-to-resolve.spec`. The release workflow builds the
RPM in a Fedora 44 container and attaches it to the V2 GitHub release.
