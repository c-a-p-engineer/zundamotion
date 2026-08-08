# C-D-E completion audit

This document records the structural/refactoring and maintenance boundary completed in August 2026.
It is intentionally limited to phases C, D, and E. Later product/release phases are out of scope.

## C. Structural closure

Issue #43 responsibilities are implemented through the following boundaries:

- Clip rendering: input collection, filter policy, background/overlay/subtitle/audio graphs, command generation, execution, and pipeline orchestration are split behind the compatibility renderer facade.
- Subtitle internals: PNG style/draw/metadata/executor and subtitle overlay runtime/graph/execution are separated.
- FFmpeg utilities: background, normalization, concat, transition, capability probes, thread policy, subprocess lifecycle, progress/stall monitoring, and diagnostics are separated behind compatibility facades.
- Finalize: transition planning, cache behavior, and concat are separated from orchestration.
- VideoPhase: scene execution/ordered aggregation/diagnostics are separated from construction and worker policy.
- Markdown: frontmatter render configuration and text layout are separated from parsing/panel rendering.

The refactoring target is responsibility separation, not mechanically eliminating every file over 500 lines.

## D. Compatibility cleanup decision

The active public runtime is modular, while selected historical implementations remain as compatibility bases.
They are retained when physical deletion would change private/public compatibility without improving runtime behavior.

The required dispatch contracts are:

- subtitle burn: `SubtitleOverlayRuntimeMixin` is before the historical overlay implementation in the public `VideoRenderer` MRO;
- wait/image scene base: `WaitClipRuntimeMixin` is before the historical renderer implementation and uses finite PCM WAV input;
- cache: the public `CacheManager` composes lifecycle/media responsibilities over `cache_runtime`, which in turn preserves `cache_base` behavior.

Therefore `overlays.py`, `scene_renderer.py`, and `cache_base.py` may remain source-metric outliers without being active architectural blockers. Future changes to them must preserve the dispatch contracts above.

## E. Maintenance closure

Only observed deprecations were handled; dependency versions were not broadly upgraded.

- Pillow 12.1: deprecated `Image.Image.getdata()` reads used by image color filtering were replaced with `get_flattened_data()`.
- Packaging metadata: the project license was migrated to the PEP 639 SPDX form (`MIT`) with `license-files = ["LICENSE"]` and a compatible Setuptools build requirement.

## Completion gate

Completion requires the current master combination to pass:

- full unit tests;
- FFmpeg integration tests;
- wheel/sdist build and clean wheel installation;
- CPU render smoke;
- no-voice media reproducibility;
- Performance Smoke;
- source metrics audit.

`tests/test_cde_completion_contracts.py` protects the key C/D boundaries from silently regressing.
