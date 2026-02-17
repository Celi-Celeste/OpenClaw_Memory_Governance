# Architecture

## Design Goal

Improve long-horizon memory quality while preserving upstream OpenClaw compatibility.

## System Split

```mermaid
flowchart TD
    A["OpenClaw Runtime"] --> B["Config Profile (documented keys)"]
    A --> C["Memory Search + Compaction + Sessions"]
    D["Skill Package"] --> E["Hourly Semantic Extract"]
    D --> F["Daily Consolidate + Transcript Mirror"]
    D --> G["Weekly Identity Promotion"]
    D --> H["Weekly Drift Review"]
    D --> I["Confidence Gate"]
    D --> J["On-demand Transcript Lookup"]
    C --> K["Workspace Memory Files"]
    C --> I
    E --> K
    F --> K
    G --> K
    H --> K
    I --> J
    J --> K
```

## Memory Layers

1. Identity memory: stable user/project truths
2. Semantic memory: distilled medium-term knowledge
3. Episodic memory: short-horizon event memory
4. Transcript mirror: 7-day precision archive for manual recall (`archive/transcripts/`, default `sanitized` mode)

Identity sub-files:

1. `memory/identity/identity.md`
2. `memory/identity/preferences.md`
3. `memory/identity/decisions.md`

Identity recall priority:

1. `identity.md`
2. `preferences.md`
3. `decisions.md`

## Hard Boundaries

1. No OpenClaw core patching
2. No transcript auto-mix into default retrieval
3. No gateway session format modifications
4. No memory plugin forking for cadence
