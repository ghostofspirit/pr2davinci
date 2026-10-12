# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

## Stack

delegated: Python with Qt (PySide6) for one maintainable desktop application on Linux, macOS, and Windows.

## Users

Video editors and post-production artists moving an Adobe Premiere Pro edit into DaVinci Resolve.

## Product Purpose

Transfer Premiere project timelines into DaVinci Resolve Studio and export a native Resolve project in one desktop workflow.

## Positioning

The converter provides a focused local desktop workflow around project selection, sequence selection, transfer to Resolve Studio, and native DRP export.

## Operating Context

Users work with Premiere projects and local media on Linux, macOS, or Windows. The desktop app creates FCP 7 XML for XML-based Premiere projects and FCPXML 1.9 for native `.prproj` projects, then uses Resolve Studio's local scripting API to import the timeline and export a `.drp` in one action.

## Capabilities and Constraints

- Current converter handles one selected Premiere sequence. Native `.prproj` parsing uses py-premiere and exports FCPXML; XML-based projects export FCP 7 XML.
- Clip timing, tracks, names, and media paths are represented. Native Windows paths are matched against the volume containing the project when possible; unresolved media is retained offline for relinking.
- Synthetic clips without a media file are omitted. Effects, transitions, retiming, nested sequences, multicam, Essential Graphics, and Lumetri may need manual reconstruction or review.
- Native `.drp` packaging is delegated to the installed Resolve Studio scripting API; the app does not write undocumented DRP files itself.
- External scripting must be enabled in Resolve Studio. The first release requires ResolvePython (DaVinci Resolve 21.1+).
- If a project is already open in Resolve, transfer is refused to protect the user's active project and possible unsaved changes.
- Linux Flatpak launches the host Resolve installation through `flatpak-spawn`; this capability must be declared in the manifest.
- The desktop UI should offer Russian and English.

## Brand Commitments

The user supplied a dark conversion-workflow screenshot as a visual reference for the desktop application.

## Evidence on Hand

The converter and its tests are in `premiere_to_resolve/` and `tests/`. The supplied screenshot depicts a conversion status, log, report, and output actions; those are reference elements, not proof of currently implemented conversion capabilities.

## Product Principles

- Keep source media local and make output paths visible.
- Preserve timeline structure the converter actually supports.
- Make unsupported translation limits and next steps understandable.
- Keep the workflow usable across desktop operating systems.
