# The Framework Label Reports, It Does Not Gate

**Status:** Accepted
**Date:** 2026-09-09

## Context

`ProjectTypeDetector.detect` returns one `FrameworkType` for a scan root, and `get_required_parsers` turns that label into a mutually exclusive parser list. A root labelled `WEBFORMS` mounts the ASPX parser alone. A root labelled `MVC` mounts the Razor parser alone.

Two problems follow. A scan root that holds both `.aspx` and `.cshtml` files loses one side, and loses it silently — the files are simply never parsed, and nothing reports their absence. The Y-DOCs repository holds eleven project files across five scan roots, so a mixed root is not a hypothetical shape.

The label also never left the scanner. `refresh_cli` cannot see it, and `/refresh` does not carry it. A root detected as `UNKNOWN`, or detected as the wrong framework, produces a scan with missing relations and no explanation for them.

## Decision

Parsers mount by the union of file extensions actually present under the scan root. A root holding `.aspx` mounts the ASPX parser; a root holding `.cshtml` mounts the Razor parser; a root holding both mounts both.

The framework label becomes a reported fact. `/refresh` carries it per scan root, and `refresh_cli` prints it together with the parsers that mounted. A root that detects as `UNKNOWN` fails loudly instead of falling back to a C#-only scan.

## Consequences

- A mixed root reports both frameworks rather than being forced to pick one. The label describes the root; it no longer decides what the scanner reads.
- Existing roots may mount a parser they did not mount before, so their parsed file counts can rise. That is the intended repair of a silent drop, and the Y-DOCs baseline separates it from a regression.
- This follows the same principle as Semantic Binding Availability: a degraded analysis must never look like a confident one. A framework that cannot be identified is now a reported failure, not a quiet default.
