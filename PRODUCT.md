# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

## Stack

delegated: Python with Qt (PySide6) for one maintainable desktop application on Linux, macOS, and Windows.

## Users

Video editors and post-production artists moving an Adobe Premiere Pro edit into DaVinci Resolve.

## Product Purpose

Convert a native Premiere Pro project into a DaVinci Resolve `.drp` project, without requiring Resolve to be installed or running during conversion.

## Positioning

The converter provides a desktop GUI and a command-line entry point for the same direct DRP export workflow. Both include the project's top-level timelines, media pool bins, and offline media references.

## Operating Context

Users work with Premiere projects and local media on Linux, macOS, or Windows. Direct DRP export accepts native `.prproj` files, writes a `.drp` without opening Resolve, and leaves media offline for relinking in Resolve. The existing CLI also supports FCP 7 XML interchange for XML-based Premiere projects.

## Capabilities and Constraints

- Direct DRP export includes all top-level Premiere timelines and media pool bins. GUI and CLI call the same export function.
- Clip timing, tracks, names, and media paths are represented. Native Windows paths are matched against the volume containing the project when possible; unresolved media is retained offline for relinking.
- Synthetic clips without a media file are omitted. Effects, transitions, retiming, nested sequences, multicam, Essential Graphics, and Lumetri may need manual reconstruction or review.
- Resolve is not launched during conversion. The generated DRP must still be opened in Resolve for application-level validation and media relinking.
- The CLI command `premiere-to-resolve-drp` accepts `.prproj` input and `--output` for the resulting `.drp`; `premiere-to-resolve-cli` remains the XML interchange command.
- Linux Flatpak is the packaged Linux distribution. Native RPM and DEB packages are not currently part of the verified release.
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
