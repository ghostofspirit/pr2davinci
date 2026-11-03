# Changelog

## 2.0.0 — Preview

- Builds a DRP archive directly from Premiere projects without requiring Resolve.
- Preserves the project’s sequences, media pool folders, and offline media items.
- Adds the direct DRP workflow to the bilingual desktop GUI; the CLI remains limited to XML interchange.
- Compares generated DRP structure against a Relink reference. Resolve import validation is still pending.

## 1.0.0 — 2026-10-12

- First version of PR2DAVINCI for transferring Adobe Premiere Pro sequences to DaVinci Resolve Studio.
- Creates a Resolve project and exports it as a `.drp` file in one pass through Resolve Studio scripting.
- Aligns imported clip positions with Resolve's default timeline start timecode, so the transferred timeline is visible when opened.
- Includes Russian and English UI, sequence selection, FCPXML export, and Linux Flatpak packaging.
- Effects, transitions, speed changes, nested sequences, and missing media can still require relinking or manual review in Resolve.
