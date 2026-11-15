# FW-VIDEO-CAPABILITY-HARVESTER-001
## Architecture and first implementation cycle

Status: proposed implementation contract
Target repository: `jamdav688y-source/forgeworld-runtime`
Branch: `codex/video-capability-harvester-v0-1`
Purpose: guide a source-grounded video research and creation plugin that produces local video files and can prepare a user-authorized YouTube upload.

## 1. Existing system facts

The repository already has a governed content path:

`cognition/cycle.py` creates evidence-aware cycle artifacts.
`cognition/episode.py` creates and reviews episode candidates.
`cognition/production.py` assembles a deterministic production package with citations, uncertainty disclosures, and source lineage.

The production module intentionally stops before generating media. Packages remain `DRAFT_PACKAGE`; publication authorization is false. Preserve this boundary. Media production must consume an approved, exact package revision and create a separately reviewable media artifact. It must never reinterpret production approval as permission to publish.

The mobile research companion indexes local screenshots and stores OCR, tags, notes, prompts, and append-only processing events in SQLite. It does not yet harvest web sources or represent video mechanisms. Extend its provenance model or create a narrow adapter into the existing exchange; do not create a second unlinked research database.

## 2. System objective

Create an original ForgeWorld plugin that:

1. Discovers useful, publicly accessible video engineering and production knowledge.
2. Preserves source provenance, licensing facts, retrieval dates, uncertainty, and contradictions.
3. Converts claims into mechanisms, algorithms, experiments, and capability specifications.
4. Implements selected capabilities in an inspectable local video pipeline.
5. Measures output quality, resource use, reliability, and reuse.
6. Feeds observed results back into the source graph, capability registry, and bounded adaptive policies.
7. Exports downloadable videos and supports an official, explicitly user-authorized YouTube upload path.

“Harvest the internet” means continuous, prioritized discovery through compliant, bounded source adapters. It does not mean indiscriminate crawling, copying entire copyrighted works, or claiming complete coverage.

## 3. Integration design

Use one linked evidence and production lineage:

`public source -> source record -> claim -> mechanism -> hypothesis -> experiment -> capability specification -> implementation -> media recipe -> rendered artifact -> validation receipt`

Every transition retains identifiers for its upstream records. Derived conclusions never replace original source evidence. Model-generated extraction is labeled as an interpretation until checked against the cited source.

Use the existing ForgeWorld exchange and event conventions where they fit. A new module may own video-specific schemas and rendering, but it must link to the existing episode candidate, production package, capability registry, and evidence lineage rather than creating a parallel lifecycle.

### Knowledge records

Each source record should include a stable ID, canonical URL, title, publisher or author, publication date when known, retrieval timestamp, content hash, source type, license or usage note, and retrieval method.

Each claim should include its source span or locator, a normalized statement, evidence type, confidence, and review status.

Each mechanism should explain the causal or mathematical relationship, assumptions, parameters, failure modes, dependencies, workload fit, compute cost, and measurable effects.

Each experiment should identify the baseline, input fixture, changed variables, expected result, actual result, environment, and reproducible command or procedure.

Each capability specification should name its interface, inputs, outputs, resource requirements, evidence basis, validation contract, version, and rollback target.

Store only the material needed to establish provenance and support implementation. Keep short source excerpts where permitted; prefer links, hashes, metadata, and original-source locators over mirrored full texts.

## 4. Knowledge domains and experiment families

Organize discovery into connected domains rather than a flat reading list.

### Image formation and camera

Lens and perspective behavior, exposure, focus, depth cues, camera motion, shutter and motion blur, stabilization, and sensor or image-processing limits.

### Motion and time

Frame rate, sampling, easing, interpolation, motion paths, acceleration, collisions, temporal coherence, transitions, rhythm, and scene continuity.

### Visual construction

Composition, lighting, color, tone mapping, typography, compositing, masks, keying, effects, image transforms, and story structure.

### Sound and speech

Waveform handling, voice recording, local speech synthesis where licensed, synchronization, loudness, mixing, sound effects, transcription, captions, and accessibility.

### Media engineering

Container and codec behavior, pixel formats, color metadata, bitrates, scaling, aspect ratios, hardware encoders, render scheduling, corruption checks, and export interoperability.

### Generative methods

Public research and open implementations for image-to-video, text-to-video, tracking, segmentation, depth, optical flow, and motion synthesis. Treat these as optional adapters. Record model license, hardware requirements, memory demands, limitations, and whether operation incurs a third-party fee. The core pipeline must remain useful without these models.

### Production grammar

Shot size, camera movement, cuts, pacing, hooks, captions, titles, lower thirds, transitions, and platform-specific structure. Treat creative rules as hypotheses until tested on an explicit set of examples and goals.

## 5. Source discovery and synthesis loop

1. Maintain a ranked source queue by expected capability gain, evidence quality, novelty, relevance to current builds, reuse potential, effort, and access constraints.
2. Retrieve only from approved public sources through documented adapters. Respect site terms, robots directives where applicable, rate limits, copyright, privacy, and API rules.
3. Normalize metadata, retain the canonical locator, compute a content hash, detect duplicates, and append a retrieval event.
4. Extract claims and mechanisms with precise locators. Keep quotations short and distinguish source text from system inference.
5. Link related records and flag contradictions, missing assumptions, stale facts, and unclear licensing.
6. Generate the smallest experiment that can distinguish the mechanism from its baseline.
7. Run experiments only in a bounded local environment using declared fixtures and resource limits.
8. Record outputs, failures, timing, compute usage, and human review. Preserve failed trials.
9. Promote only mechanisms that meet their validation contract into reusable capabilities.
10. Revisit promoted capabilities when source facts, dependencies, hardware, or platform requirements change.

Discovery itself must be measurable: source classes covered, deduplication rate, claim locator completeness, unresolved conflict count, experiment yield, implementation yield, and capability reuse.

## 6. Video project and render pipeline

Define a versioned project graph with source assets, scene order, timeline intervals, transforms, motion curves, text, captions, audio tracks, color settings, export profile, and YouTube metadata draft. Every node must have a stable ID and explicit units, timing base, and coordinate space.

Compile the project graph into an inspectable render plan. The renderer should support deterministic local operations first: stills and video clips, trimming, scaling, cropping or padding, compositing, titles, captions, transitions, audio mix, and encoding.

Use a replaceable media backend. Before integrating any backend, record its license, bundled codec configuration, platform support, and redistribution obligations. Keep backend-specific commands behind a typed adapter.

Preserve the exact project recipe, input hashes, backend and version, selected parameters, output hash, and validation receipt for each render. A re-render from unchanged inputs and settings should be reproducible to the extent the chosen codec and hardware allow; state any nondeterminism.

## 7. First end-to-end vertical slice

Build the smallest useful demonstration before expanding the feature surface:

Create a short, vertical video locally from user-provided or clearly licensed stills, a title, timed text or captions, and an optional audio track. Render a preview first, then a final MP4. Verify duration, dimensions, frame rate, audio stream, codec/container metadata, and file readability. Save the project graph, render plan, input hashes, output hash, timing, and validation receipt.

The first slice passes when a user can repeat the same recipe, download the result, inspect its provenance, and produce it without paid generation credits. Local compute, storage, electricity, optional model downloads, and YouTube quotas remain real resource constraints.

## 8. Substrate dynamics integration

### Telemetry bus

Append structured events for source discovery, fetch outcomes, extraction, experiments, capability changes, preview and final renders, validation, export, and upload. Include timing, status, capability version, relevant resource measurements, and lineage IDs. Avoid collecting unnecessary personal or private media data.

### Attention economy

Schedule work by expected gain, evidence quality, reuse, user priority, effort, and risk. Prefer inexpensive discriminating experiments over broad collection. Deduplicate sources and skip unchanged work.

### Compute history

Measure CPU and GPU utilization when available, peak memory, render time, encode speed, output size, dropped or missing frames, and failure categories. Use history to choose bounded preview quality, batch size, encoder, and scheduling policy.

### Behavioral genome

Store proven versioned production recipes such as motion curves, title systems, shot patterns, transitions, caption layouts, and export profiles. Each recipe records provenance, suitable use cases, parameter ranges, test coverage, observed quality, and known failures.

### Adaptive policy

The policy may select technical settings within declared bounds and recommend experiments. It may not change source meaning, governance rules, rights declarations, approval state, upload destination, visibility, or publication intent. Human review is required to promote an experimental policy.

### Architecture evolution

After each completed cycle, report the highest-value gap, evidence, affected modules, dependencies, expected benefit, validation plan, resource cost, and rollback path. No self-editing production code or autonomous capability promotion.

## 9. YouTube integration boundary

Use the YouTube Data API and OAuth. Never collect Google passwords or reuse another service’s credentials. Store tokens using the host platform’s protected credential store, with the narrowest necessary scope.

The upload flow must identify the selected channel, show editable title and required metadata, expose the visibility choice, disclose the user’s upload certification, handle audience designation, and require an explicit final user action. Preserve resumable upload state and recover safely from interruptions. Report upload status and returned video ID.

Do not upload, schedule, publish, change visibility, or claim success without the user’s explicit action and an API-confirmed result. Do not create additional Google Cloud projects to evade quota limits.

Current official documentation describes `videos.insert` as using a separate video-upload quota bucket; its current method cost and project allocation must be checked at implementation time. API quota is not a per-generation credit charge, but it is still a platform limit. Official references:

- https://developers.google.com/youtube/data/reference/rest/v3/videos/insert
- https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol
- https://developers.google.com/youtube/terms/api-services-terms-of-service/
- https://developers.google.com/youtube/terms/required-minimum-functionality

## 10. Delivery sequence

### Cycle A: Integration and evidence contracts

Map the current CXP, episode, production, capability, and research schemas. Define video-specific records and state transitions. Confirm that production approval can authorize media preparation without authorizing publication.

### Cycle B: First local render

Implement the project graph, render-plan compiler, local media backend adapter, preview path, final export, and validation receipt for the vertical slice.

### Cycle C: Source harvesting

Add bounded public-source adapters, source ledger, claim and mechanism schemas, duplicate detection, provenance links, and search. Begin with authoritative technical references and open implementations relevant to the current renderer.

### Cycle D: Experiments and promotion

Add benchmark fixtures for timing, motion, text rendering, audio sync, codec outputs, quality checks, resource tracking, and failure preservation. Promote only verified capabilities.

### Cycle E: YouTube upload

Implement OAuth, compliant metadata controls, explicit user authorization, resumable transfer, and API-confirmed status.

### Cycle F: Dynamics and expansion

Connect telemetry, attention scheduling, compute history, reusable production recipes, and evidence-based architecture evolution. Expand into optional local AI models only after measuring actual capability gain against cost and hardware limits.

## 11. Completion standard

A capability is not complete because code exists or one demo worked. It is complete only when:

- Its source and dependency lineage are recorded.
- Its assumptions, limits, and rights constraints are explicit.
- Its inputs and outputs have stable documented schemas.
- Its validation contract passes against a representative fixture set.
- Its failure modes are observable and recoverable.
- Its resource cost and measured benefit are recorded.
- Its prior version can be restored.
- External actions remain behind the required user authorization.

The operating cycle is: identify the highest-value gap, gather relevant evidence, formulate a discriminating experiment, implement the smallest reusable mechanism, compare it with a baseline, preserve the outcome, and select the next improvement from measured results.
