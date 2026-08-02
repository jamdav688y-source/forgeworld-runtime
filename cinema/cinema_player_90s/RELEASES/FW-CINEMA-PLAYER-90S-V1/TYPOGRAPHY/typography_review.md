# Typography Review

## Font

DejaVu Sans Bold (`/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`),
a standard Linux system font. No custom or licensed font asset is
bundled with this release.

## Placement and safety

- Scene title is horizontally centered, bottom-anchored with a margin of
  6% of frame height -- this stays inside the title-safe area for both
  16:9 (1920x1080) and 4:5 (1080x1350) natively, since the margin is
  computed as a fraction of each output's own height, not a fixed pixel
  offset copied from one aspect to the other.
- Font size is 3.2% of `min(width, height)`, so text scales
  proportionally between the two masters rather than becoming
  disproportionately large/small on the narrower 4:5 frame.
- A one-line subtitle (`scene N / 9`) sits just above the title.

## Fade behavior

Each scene's title fades in over the first 15% of the scene and fades out
over the last 15% (`genome/typography.py:_fade_alpha`), so there is never
a hard text cut-in/cut-out. Visible in the contact sheet
(`contact_sheet_16x9.jpg`): compare frames near a scene's start/end vs.
its middle.

## What was NOT done

No kerning/tracking refinement, no custom typeface, no animated text
entrance beyond the opacity fade, and no localized/multi-language text.
This is a functional, safe-margined title system, not a typographic
design pass.

## Verdict

PASS for the stated scope (legible, safe-margined, fading, proportional
across both aspect ratios). Not evaluated against any higher bar of
typographic craft, because none was attempted.
