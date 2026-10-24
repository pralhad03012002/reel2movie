# Graph Report - Movie Reccomendation Reels extraction  (2026-10-24)

## Corpus Check
- 5 files · ~96,977 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 915 nodes · 2426 edges · 55 communities (26 shown, 29 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 367 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Shared Candidate Parsing
- Pipeline Waterfall Orchestration
- Vision Chat Backends
- Chat Client Protocol
- Visual Frame Extraction
- Instagram Ingestion
- Config & Env Loading
- TMDB Exact-Match Scoring
- Flow & Vision Backend Overview
- TMDB HTTP Client & Retry
- GUI Card Formatting Helpers
- Core Models & Disambiguation Fixes
- GUI Background Engine (workers.py)
- GUI MainWindow State Machine
- Ingestor Protocol & Results
- CLI Entrypoint
- Visual Protocols & Frame Sampling
- Ingest Data Contracts
- PipelineResult Contract & Tests
- Perceptual Frame Dedup
- Claude-CLI Text Chat Client
- GUI API Key Prompt Panel
- Brainstorm & Handoff Docs
- GUI Results Panel & Cards
- Recommendation & ResolvedMovie Contracts
- GUI Entry Point (main.py/main_window.py)
- Frame Dedup Internals
- Waterfall Dedup Follow-ups
- Signal Source Priority Rationale
- Execution Flow Steps 2-4
- TMDB Scoring Rationale
- Known Hard Cases (brainstorm)
- Open Questions (brainstorm)
- Output Shape Draft
- Problem Statement
- v1 Scope
- Error Handling Flow
- reel2movie root package
- Duration-Probing Fallback Follow-up
- Anonymous Instagram Access Follow-up

## God Nodes (most connected - your core abstractions)
1. `SourceTag` - 94 edges
2. `Candidate` - 86 edges
3. `resolve_candidate()` - 37 edges
4. `TMDBSearchResult` - 36 edges
5. `FrameSample` - 33 edges
6. `run_pipeline()` - 33 edges
7. `ClaudeCodeCandidateExtractor` - 31 edges
8. `IngestResult` - 30 edges
9. `InstagramIngestor` - 29 edges
10. `VisionLLMPosterDetector` - 28 edges

## Surprising Connections (you probably didn't know these)
- `Output contract (if going through the CLI/subprocess route)` --references--> `PipelineResult`  [INFERRED]
  handoff.md → reel2movie/core/models.py
- `The real integration point for a GUI: don't shell out, import it` --references--> `run_pipeline()`  [INFERRED]
  handoff.md → reel2movie/pipeline/waterfall.py
- `Output contract (if going through the CLI/subprocess route)` --references--> `_result_to_dict()`  [INFERRED]
  handoff.md → reel2movie/cli.py
- `The real integration point for a GUI: don't shell out, import it` --references--> `build_default_pipeline_deps()`  [INFERRED]
  handoff.md → reel2movie/pipeline/deps.py
- `MainWindow(QMainWindow) — one-screen app state machine` --references--> `MainWindow`  [EXTRACTED]
  PROGRESS.md → gui/main_window.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Prioritized signal-source waterfall (caption > creator comment > frame sampling)** — brainstorm_caption_source, brainstorm_creator_comment_source, brainstorm_frame_sampling_source [EXTRACTED 1.00]
- **Caption→comment→visual fallthrough waterfall** — flow_caption_extraction, flow_creator_comment_extraction, flow_visual_frame_extraction, flow_fallthrough_rule [EXTRACTED 1.00]
- **VISION_BACKEND selection mechanism (decision -> implementation -> GUI consequence)** — handoff_vision_backend_design_constraint [INFERRED 0.85]

## Communities (55 total, 29 thin omitted)

### Community 0 - "Shared Candidate Parsing"
Cohesion: 0.05
Nodes (34): parse_movie_candidates(), Candidate, SourceTag, _extract_from_creator_comments(), ClaudeCodeCandidateExtractor, FallbackCandidateExtractor, _extract_year_hint(), TestParseMovieCandidates (+26 more)

### Community 1 - "Pipeline Waterfall Orchestration"
Cohesion: 0.09
Nodes (34): _dedupe(), run_pipeline(), _exact_match_result(), FakeCandidateExtractor, FakeChatClient, FakeIngestor, FakePosterDetector, FakeTMDBClient (+26 more)

### Community 2 - "Vision Chat Backends"
Cohesion: 0.08
Nodes (15): AnthropicVisionChatClient, ClaudeCodeVisionChatClient, VisionChatClient, VisionLLMPosterDetector, _canned_cli_json(), FakeVisionChatClient, _frame(), TestAnthropicVisionChatClient (+7 more)

### Community 3 - "Chat Client Protocol"
Cohesion: 0.09
Nodes (34): TextChatClient, disambiguate_with_context(), resolve_candidate(), _candidate(), FakeChatClient, FakeTMDBClient, _search_result(), test_disambiguate_with_context_prompt_includes_context_and_overviews() (+26 more)

### Community 4 - "Visual Frame Extraction"
Cohesion: 0.09
Nodes (31): _extract_from_visual(), _compute_timestamps(), _extract_frame_at(), FrameExtractionError, probe_duration_seconds(), sample_frames(), sample_frames_at_interval(), probe_duration_seconds_fails() (+23 more)

### Community 5 - "Instagram Ingestion"
Cohesion: 0.09
Nodes (28): IngestError, InstagramIngestor, YtDlpClient, FakeYtDlpClient, _load_fixture(), test_ensure_video_falls_back_to_filename_key(), test_ensure_video_passes_cookies_file_through_to_client(), test_ensure_video_raises_ingest_error_when_no_path_available() (+20 more)

### Community 6 - "Config & Env Loading"
Cohesion: 0.06
Nodes (32): Post-ship follow-up — .env was never actually loaded, Subtask 1 — config.py — status: done, get_anthropic_key(), get_instagram_cookies_file(), get_tmdb_token(), get_vision_backend(), build_default_pipeline_deps(), PipelineDeps (+24 more)

### Community 7 - "TMDB Exact-Match Scoring"
Cohesion: 0.09
Nodes (25): _exact_tier_rank(), find_exact_matches(), _is_exact_title_match(), _normalize_apostrophes(), pick_best(), score_result(), _result(), test_exact_title_match_scores_highest() (+17 more)

### Community 8 - "Flow & Vision Backend Overview"
Cohesion: 0.07
Nodes (17): [6] Aggregate + de-duplicate, [1] Platform detect + ingest, [5] TMDB resolution, Project status, Subtask 0 — core/ (models.py, protocols.py) — status: done, Subtask 2 — tmdb/ — status: done, Subtask 3 — text_extraction/regex_extractor.py — status: done, Subtask 4 — ingest/ — status: done (+9 more)

### Community 9 - "TMDB HTTP Client & Retry"
Cohesion: 0.18
Nodes (13): _parse_year(), TMDBHttpClient, _mock_get_response(), test_search_exhausts_retries_and_raises_connection_error(), test_search_filters_out_person_and_maps_movie_and_tv_distinctly(), test_search_hits_search_multi_endpoint(), test_search_maps_fields_and_rank(), test_search_passes_query_param() (+5 more)

### Community 10 - "GUI Card Formatting Helpers"
Cohesion: 0.15
Nodes (7): _build_badges_row(), _format_confidence(), _format_media_type(), _format_source(), _get_shared_network_manager(), _make_badge(), RecommendationCard

### Community 11 - "Core Models & Disambiguation Fixes"
Cohesion: 0.13
Nodes (4): Follow-up — fix TMDB query dilution from embedded year — status: done, TMDBSearchResult, TMDBClient, _strip_trailing_year()

### Community 12 - "GUI Background Engine (workers.py)"
Cohesion: 0.11
Nodes (6): apply_anthropic_api_fallback(), build_deps_or_error(), check_claude_cli_usable(), ClaudeCliCheckWorker, PipelineRunner, GUI Subtask 1: background engine (gui/workers.py)

### Community 14 - "Ingestor Protocol & Results"
Cohesion: 0.14
Nodes (5): IngestResult, Ingestor, FakeIngestor, test_fake_ingestor_satisfies_protocol(), test_object_missing_methods_does_not_satisfy_protocol()

### Community 15 - "CLI Entrypoint"
Cohesion: 0.17
Nodes (7): _build_parser(), main(), _recommendation_to_dict(), _result_to_dict(), _tmdb_to_dict(), test_live_pipeline_end_to_end(), test_missing_api_key_prints_clear_error_on_stderr_and_returns_nonzero()

### Community 16 - "Visual Protocols & Frame Sampling"
Cohesion: 0.18
Nodes (12): FrameSample, CandidateExtractor, PosterDetector, FakeCandidateExtractor, FakePosterDetector, FakeTMDBClient, test_fake_candidate_extractor_satisfies_protocol(), test_fake_poster_detector_satisfies_protocol() (+4 more)

### Community 17 - "Ingest Data Contracts"
Cohesion: 0.16
Nodes (12): Comment, Platform, test_candidate_construction(), test_comment_construction_and_defaults(), test_comment_is_immutable(), test_frame_sample_construction_and_equality(), test_ingest_result_is_immutable(), test_ingest_result_video_path_defaults_to_none() (+4 more)

### Community 18 - "PipelineResult Contract & Tests"
Cohesion: 0.21
Nodes (12): PipelineResult, test_pipeline_result_defaults_to_empty_recommendations(), test_pipeline_result_with_recommendations_and_equality(), _canned_result(), _fake_deps(), test_fatal_pipeline_error_prints_clear_error_on_stderr_and_returns_nonzero(), test_frame_interval_seconds_override_reaches_pipeline_deps(), fake_run_pipeline() (+4 more)

### Community 19 - "Perceptual Frame Dedup"
Cohesion: 0.26
Nodes (9): dedupe_similar_frames(), _solid_frame(), test_compares_against_last_kept_not_immediately_previous_frame(), test_empty_input_returns_empty_list(), test_run_of_identical_frames_collapses_to_just_the_first(), test_single_frame_returned_unchanged(), test_substantially_different_frame_is_kept(), test_threshold_boundary_frame_just_above_threshold_is_kept() (+1 more)

### Community 20 - "Claude-CLI Text Chat Client"
Cohesion: 0.31
Nodes (3): ClaudeCodeTextChatClient, _canned_cli_json(), TestClaudeCodeTextChatClient

### Community 21 - "GUI API Key Prompt Panel"
Cohesion: 0.19
Nodes (6): ApiKeyPromptPanel, GUI Subtask 2: presentational widgets (gui/widgets.py), MainWindow(QMainWindow) — one-screen app state machine, GUI Subtask 3: MainWindow, entry point, styling, packaging (gui/main_window.py, gui/main.py, gui/styles.qss, pyproject.toml), pyproject.toml — 'gui' optional-dependency group (PySide6), gui/styles.qss — window chrome styling

### Community 22 - "Brainstorm & Handoff Docs"
Cohesion: 0.25
Nodes (4): Brainstorm — Movie Recommendation Reels Extraction, Execution Flow — Reel → Movie Recommendations, The real integration point for a GUI: don't shell out, import it, Performance -- this is not a fast, synchronous call

### Community 24 - "Recommendation & ResolvedMovie Contracts"
Cohesion: 0.20
Nodes (9): Output contract (if going through the CLI/subprocess route), Recommendation, ResolvedMovie, test_pipeline_result_default_factory_does_not_share_list_between_instances(), test_recommendation_defaults_tmdb_to_none(), test_recommendation_is_immutable(), test_recommendation_unresolved_candidate_is_kept_not_dropped(), test_recommendation_with_resolved_tmdb() (+1 more)

### Community 27 - "Waterfall Dedup Follow-ups"
Cohesion: 0.25
Nodes (4): Follow-up — drop unresolved duplicate when same-query candidate already resolved — status: DONE, _extract_from_caption(), _is_confident(), _resolve_all()

### Community 28 - "Signal Source Priority Rationale"
Cohesion: 0.40
Nodes (4): Caption signal source, Creator's own top-level comment signal source, Frame sampling (visual) signal source, Signal sources, priority order

### Community 29 - "Execution Flow Steps 2-4"
Cohesion: 0.50
Nodes (3): [2] Caption-based extraction, [3] Creator-comment-based extraction, [4] Visual frame extraction (fallback)

## Knowledge Gaps
- **25 isolated node(s):** `Caption signal source`, `Creator's own top-level comment signal source`, `Frame sampling (visual) signal source`, `Candidate resolution via TMDB scoring`, `Open questions (not yet decided)` (+20 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 329 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **29 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SourceTag` connect `Shared Candidate Parsing` to `Pipeline Waterfall Orchestration`, `Vision Chat Backends`, `Chat Client Protocol`, `Config & Env Loading`, `Flow & Vision Backend Overview`, `Core Models & Disambiguation Fixes`, `Visual Protocols & Frame Sampling`, `Ingest Data Contracts`, `PipelineResult Contract & Tests`, `Recommendation & ResolvedMovie Contracts`, `Waterfall Dedup Follow-ups`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Are the 67 inferred relationships involving `SourceTag` (e.g. with `parse_movie_candidates()` and `CandidateExtractor`) actually correct?**
  _`SourceTag` has 67 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Caption signal source`, `Creator's own top-level comment signal source`, `Frame sampling (visual) signal source` to the rest of the system?**
  _25 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Shared Candidate Parsing` be split into smaller, more focused modules?**
  _Cohesion score 0.05207920792079208 - nodes in this community are weakly interconnected._
- **Why does `Candidate` connect `Shared Candidate Parsing` to `Pipeline Waterfall Orchestration`, `Vision Chat Backends`, `Chat Client Protocol`, `Visual Frame Extraction`, `Config & Env Loading`, `Flow & Vision Backend Overview`, `Core Models & Disambiguation Fixes`, `Visual Protocols & Frame Sampling`, `Ingest Data Contracts`, `Waterfall Dedup Follow-ups`?**
  _High betweenness centrality (0.090) - this node is a cross-community bridge._
- **Are the 29 inferred relationships involving `Candidate` (e.g. with `CandidateExtractor` and `PosterDetector`) actually correct?**
  _`Candidate` has 29 INFERRED edges - model-reasoned connections that need verification._
- **Should `Pipeline Waterfall Orchestration` be split into smaller, more focused modules?**
  _Cohesion score 0.08737060041407868 - nodes in this community are weakly interconnected._