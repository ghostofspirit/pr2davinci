# Linux Flatpak

The manifest uses KDE's Qt 6.11 runtime and PySide BaseApp, which bundles the
matching Python/Qt bindings. It grants access to the user's home directory so
the app can open Premiere projects and write interchange files there. The
launcher and application window use the Leonardo portrait cutout as their icon.
For one-click DRP transfer, the app uses `flatpak-spawn --host` to invoke the
Resolve Studio scripting runtime installed on the host. This requires external
scripting to be enabled in Resolve Studio and means the Flatpak can launch that
host application when the user requests a transfer.

Install the build tools and runtime SDKs from Flathub, then build and install
the local Flatpak repository:

```bash
flatpak install flathub org.flatpak.Builder org.kde.Sdk//6.11 io.qt.PySide.BaseApp//6.11
flatpak run org.flatpak.Builder --force-clean --repo=flatpak-repo build-dir flatpak/com.serotoninja.PremiereToResolve.yml
flatpak remote-add --user --no-gpg-verify premiere-to-resolve "file://$PWD/flatpak-repo"
flatpak install --user premiere-to-resolve com.serotoninja.PremiereToResolve
flatpak run --user com.serotoninja.PremiereToResolve
```

The first build downloads the SDK and PySide BaseApp. The app is delivered as
an OSTree Flatpak repository in `flatpak-repo/`; installing it requires the
shared KDE runtime and PySide BaseApp, which Flatpak resolves from Flathub.
