Name:           premiere-to-resolve
Version:        2.0.0
Release:        1%{?dist}
Summary:        Convert Adobe Premiere Pro projects to DaVinci Resolve DRP
License:        CC0-1.0 AND MIT
URL:            https://github.com/ghostofspirit/pr2davinci
Source0:        %{name}-%{version}.tar.gz
Source1:        py_premiere-0.1.0-py3-none-any.whl
BuildArch:      noarch
BuildRequires:  python3
BuildRequires:  python3-pip
Requires:       python3
Requires:       python3-pyside6 >= 6.7
Requires:       python3-zstandard >= 0.23
Requires:       hicolor-icon-theme

%description
PR2DAVINCI converts a native Adobe Premiere Pro project into a DaVinci Resolve
DRP archive. The direct exporter includes project timelines and media bins and
does not require DaVinci Resolve to be installed during conversion.

%prep
%autosetup -n %{name}-%{version}

%build

%install
install -d %{buildroot}%{_datadir}/pr2davinci
cp -a premiere_to_resolve %{buildroot}%{_datadir}/pr2davinci/
python3 -m pip install --no-deps --no-index \
  --target %{buildroot}%{_datadir}/pr2davinci/vendor %{SOURCE1}

install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/premiere-to-resolve <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/share/pr2davinci:/usr/share/pr2davinci/vendor${PYTHONPATH:+:$PYTHONPATH}
exec /usr/bin/python3 -c 'from premiere_to_resolve.gui import main; main()' "$@"
EOF
cat > %{buildroot}%{_bindir}/premiere-to-resolve-drp <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/share/pr2davinci:/usr/share/pr2davinci/vendor${PYTHONPATH:+:$PYTHONPATH}
exec /usr/bin/python3 -c 'from premiere_to_resolve.drp_cli import main; main()' "$@"
EOF
cat > %{buildroot}%{_bindir}/premiere-to-resolve-cli <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/share/pr2davinci:/usr/share/pr2davinci/vendor${PYTHONPATH:+:$PYTHONPATH}
exec /usr/bin/python3 -c 'from premiere_to_resolve.cli import main; main()' "$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/premiere-to-resolve*

install -D -m 0644 flatpak/com.serotoninja.PremiereToResolve.desktop \
  %{buildroot}%{_datadir}/applications/com.serotoninja.PremiereToResolve.desktop
install -D -m 0644 premiere_to_resolve/assets/leonardo-icon-512.png \
  %{buildroot}%{_datadir}/icons/hicolor/512x512/apps/com.serotoninja.PremiereToResolve.png

%files
%license LICENSE THIRD_PARTY_NOTICES.md
%{_bindir}/premiere-to-resolve
%{_bindir}/premiere-to-resolve-cli
%{_bindir}/premiere-to-resolve-drp
%{_datadir}/pr2davinci/
%{_datadir}/applications/com.serotoninja.PremiereToResolve.desktop
%{_datadir}/icons/hicolor/512x512/apps/com.serotoninja.PremiereToResolve.png

%changelog
* Wed Nov 04 2026 PR2DAVINCI contributors - 2.0.0-1
- Fedora RPM package for PR2DAVINCI 2.0.0
