# Graph Report - Movie Reccomendation Reels extraction  (2026-10-27)

## Corpus Check
- 39 files · ~130,551 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1322 nodes · 3572 edges · 92 communities (30 shown, 62 thin omitted)
- Extraction: 87% EXTRACTED · 13% INFERRED · 0% AMBIGUOUS · INFERRED: 481 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Core Models & Waterfall Tests
- TMDB Tie-Break Disambiguation
- Subprocess Cancellation Infra
- Vision Chat Backends
- Candidate Extraction & Source Tags
- GUI Workers & CLI Entrypoint
- TMDB Scoring & Search Results
- Candidate Noise Filtering
- Claude-CLI Text Extraction
- Instagram Ingestion
- TMDB HTTP Client
- Config & Env Loading
- Handoff Doc Overview
- Pipeline Rewrite Wave 1
- Whisper.cpp Transcriber
- Claude CLI Subprocess Plumbing
- GUI Deps Wiring
- Perceptual Frame Dedup
- Core Protocols
- GUI Card Formatting Helpers
- Audio Extraction (ffmpeg)
- Waterfall Race Jobs
- Candidate Parsing & Models
- GUI MainWindow State Machine
- Ingest Data Contracts
- yt-dlp Video Ingestion
- Frame & Transcript Protocols
- GUI Results Panel & Cards
- Waterfall Disambiguation Context
- GUI Background Workers
- GUI Entry Point
- GUI API Key Prompt Panel
- GUI Workers Overview
- Signal Source Priority Rationale
- Subprocess Terminate/Kill Helpers
- Execution Flow Steps
- Waterfall Video Prep Job
- Daemon Thread Helper
- Brainstorm & Flow Overview
- Flow Aggregate Step
- Flow Ingest Step
- Flow TMDB Resolution Step
- TMDB Retry Follow-up
- CLI Output Contract
- TMDB Scoring Rationale (brainstorm)
- Known Hard Cases (brainstorm)
- Open Questions (brainstorm)
- Output Shape Draft
- Problem Statement
- v1 Scope
- Error Handling Flow
- Handoff Config Vars
- Handoff File Map
- Handoff CLI Usage
- Suggested GUI Architecture
- What Already Works
- reel2movie root package
- Claude CLI Text Fallback Follow-up
- Drop Unresolved Duplicate Follow-up
- Duration-Probing Fallback Follow-up
- TMDB Query Dilution Fix
- ApiKeyPromptPanel Copy Fix
- Anonymous Instagram Access Follow-up
- Env-Not-Loaded Follow-up
- Project Status Summary
- Subtask 0 Core Models
- Subtask 1 Config
- Subtask 3 Regex Extraction
- Subtask 5 Frame Sampler
- Subtask 6 Vision Detector
- Subtask 8 CLI

## God Nodes (most connected - your core abstractions)
1. `SourceTag` - 120 edges
2. `Candidate` - 114 edges
3. `TMDBSearchResult` - 49 edges
4. `run_pipeline()` - 49 edges
5. `PipelineDeps` - 46 edges
6. `FakeIngestor` - 43 edges
7. `FakeCandidateExtractor` - 43 edges
8. `SubprocessCancelled` - 40 edges
9. `_ingest_result()` - 40 edges
10. `_make_deps()` - 39 edges

## Surprising Connections (you probably didn't know these)
- `Live end-to-end test of streaming wiring (real reel, offscreen Qt)` --references--> `MainWindow`  [EXTRACTED]
  PROGRESS.md → gui/main_window.py
- `GUI Subtask 3: MainWindow, entry point, styling, packaging` --references--> `MainWindow`  [INFERRED]
  PROGRESS.md → gui/main_window.py
- `GUI Subtask 2: presentational widgets (gui/widgets.py)` --references--> `ResultsPanel`  [INFERRED]
  PROGRESS.md → gui/widgets.py
- `GUI Subtask 1: background engine (gui/workers.py)` --references--> `PipelineRunner`  [INFERRED]
  PROGRESS.md → gui/workers.py
- `Bug: WhisperCppTranscriber.transcribe() could return a stale transcript` --rationale_for--> `WhisperCppTranscriber`  [EXTRACTED]
  PROGRESS.md → reel2movie/audio/whisper_cpp_transcriber.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Prioritized signal-source waterfall (caption > creator comment > frame sampling)** — brainstorm_caption_source, brainstorm_creator_comment_source, brainstorm_frame_sampling_source [EXTRACTED 1.00]
- **Caption→comment→visual fallthrough waterfall** — flow_caption_extraction, flow_creator_comment_extraction, flow_visual_frame_extraction, flow_fallthrough_rule [EXTRACTED 1.00]

## Communities (92 total, 62 thin omitted)

### Community 0 - "Core Models & Waterfall Tests"
Cohesion: 0.06
Nodes (54): Candidate, Comment, run_pipeline(), _exact_match_result(), FakeAudioTranscriber, FakeCandidateExtractor, FakeChatClient, FakeIngestor (+46 more)

### Community 1 - "TMDB Tie-Break Disambiguation"
Cohesion: 0.05
Nodes (52): disambiguate_with_context(), resolve_candidate(), resolve_candidate_with_retry(), AlwaysFailingTMDBClient, _candidate(), FakeChatClient, FakeTMDBClient, FlakyThenSucceedsTMDBClient (+44 more)

### Community 2 - "Subprocess Cancellation Infra"
Cohesion: 0.05
Nodes (41): run_cancelable(), _compute_timestamps(), _extract_frame_at(), FrameExtractionError, probe_duration_seconds(), sample_frames(), sample_frames_at_interval(), probe_duration_seconds_fails() (+33 more)

### Community 3 - "Vision Chat Backends"
Cohesion: 0.07
Nodes (17): AnthropicVisionChatClient, ClaudeCodeVisionChatClient, VisionChatClient, VisionLLMPosterDetector, _canned_cli_json(), FakeVisionChatClient, FakeVisionChatClientAcceptingCancelEvent, _frame() (+9 more)

### Community 4 - "Candidate Extraction & Source Tags"
Cohesion: 0.06
Nodes (28): SourceTag, FallbackCandidateExtractor, _claim(), _clean_list_title(), RegexCandidateExtractor, _extract_year_hint(), FakeCandidateExtractor, test_fake_candidate_extractor_satisfies_protocol() (+20 more)

### Community 5 - "GUI Workers & CLI Entrypoint"
Cohesion: 0.05
Nodes (41): _build_parser(), main(), _recommendation_to_dict(), _result_to_dict(), _tmdb_to_dict(), PipelineResult, Platform, Recommendation (+33 more)

### Community 6 - "TMDB Scoring & Search Results"
Cohesion: 0.06
Nodes (31): TMDBSearchResult, _exact_tier_rank(), find_exact_matches(), _is_exact_title_match(), _normalize_apostrophes(), pick_best(), score_result(), test_tmdb_search_result_construction() (+23 more)

### Community 7 - "Candidate Noise Filtering"
Cohesion: 0.08
Nodes (20): parse_movie_candidates(), _parse_reply(), select_primary_candidates(), TextChatClient, _disambiguate_once(), TestParseMovieCandidates, _candidate(), FakeChatClient (+12 more)

### Community 8 - "Claude-CLI Text Extraction"
Cohesion: 0.11
Nodes (13): ClaudeCodeCandidateExtractor, ClaudeCodeTextChatClient, _canned_cli_json(), FakeTextChatClient, TestClaudeCodeCandidateExtractorCancellation, TestClaudeCodeCandidateExtractorEmptyTextShortCircuit, TestClaudeCodeCandidateExtractorMalformedResponse, TestClaudeCodeCandidateExtractorMultiMovie (+5 more)

### Community 9 - "Instagram Ingestion"
Cohesion: 0.14
Nodes (22): IngestError, InstagramIngestor, FakeYtDlpClient, _load_fixture(), test_ensure_video_caches_successful_download_and_does_not_redownload(), test_ensure_video_does_not_cache_failures_and_retries_on_next_call(), test_ensure_video_falls_back_to_filename_key(), test_ensure_video_passes_cookies_file_through_to_client() (+14 more)

### Community 10 - "TMDB HTTP Client"
Cohesion: 0.12
Nodes (16): _parse_year(), TMDBHttpClient, _find_by_id(), _is_retryable_http_error(), _strip_trailing_year(), _mock_get_response(), test_search_exhausts_retries_and_raises_connection_error(), test_search_filters_out_person_and_maps_movie_and_tv_distinctly() (+8 more)

### Community 11 - "Config & Env Loading"
Cohesion: 0.09
Nodes (26): get_anthropic_key(), get_instagram_cookies_file(), get_tmdb_token(), get_vision_backend(), get_whisper_cpp_binary(), get_whisper_cpp_model_path(), test_get_anthropic_key_raises_when_empty(), test_get_anthropic_key_raises_when_unset() (+18 more)

### Community 12 - "Handoff Doc Overview"
Cohesion: 0.08
Nodes (29): Before you start: sanity-check the current state, Performance — this is not a fast, synchronous call, Candidate noise filtering (Problem A) + "Don't Be Shy" reliability follow-up (Problem B), Final live end-to-end confirmation (whole pipeline rewrite, real reel), Fix 3 (MEDIUM) — stale _CANCELLED_EXCEPTIONS tuple, Fix 4 (MEDIUM) — disambiguation's 3-sample majority vote ran sequentially, Fix 6 (LOW) — duplicated 'creator top-level comments' filter, Follow-up finding B — _prepare_audio's cancellation miscategorized as an error (+21 more)

### Community 13 - "Pipeline Rewrite Wave 1"
Cohesion: 0.10
Nodes (16): Follow-up — unify duplicated claude-CLI subprocess/parsing logic, Pipeline Rewrite Wave 1: frame sampling, cancellation infra, audio subpackage, New reel2movie/audio/ subpackage (audio-transcript fallback), Bug: FD leak on cancel/timeout in run_cancelable(), Bug: sample_frames() had no cancel_event parameter, Bug: InstagramIngestor._video_cache race condition, Bug: WhisperCppTranscriber.transcribe() could return a stale transcript, Cancellation infrastructure (cancel_event threaded end-to-end) (+8 more)

### Community 14 - "Whisper.cpp Transcriber"
Cohesion: 0.14
Nodes (7): WhisperCppTranscriber, WhisperCppTranscriberError, _LazyWhisperCppTranscriber, _completed(), TestWhisperCppTranscriber, fake_run_cancelable(), fake_run_cancelable()

### Community 15 - "Claude CLI Subprocess Plumbing"
Cohesion: 0.14
Nodes (5): ClaudeCliCancelled, ClaudeCliError, run_claude_cli(), _canned_cli_json(), TestRunClaudeCli

### Community 16 - "GUI Deps Wiring"
Cohesion: 0.13
Nodes (14): build_deps_or_error(), The real integration point for a GUI: don't shell out, import it, build_default_pipeline_deps(), PipelineDeps, test_anthropic_api_backend_raises_when_key_unset(), test_anthropic_api_backend_succeeds_when_key_set(), test_audio_transcriber_is_none_when_whisper_cpp_model_path_unset(), test_audio_transcriber_is_wired_when_whisper_cpp_model_path_set() (+6 more)

### Community 17 - "Perceptual Frame Dedup"
Cohesion: 0.16
Nodes (11): dedupe_similar_frames(), _fingerprint(), _mean_abs_difference(), _solid_frame(), test_compares_against_last_kept_not_immediately_previous_frame(), test_empty_input_returns_empty_list(), test_run_of_identical_frames_collapses_to_just_the_first(), test_single_frame_returned_unchanged() (+3 more)

### Community 18 - "Core Protocols"
Cohesion: 0.16
Nodes (7): AudioTranscriber, CandidateExtractor, Ingestor, PosterDetector, TMDBClient, test_object_missing_methods_does_not_satisfy_protocol(), test_plain_object_does_not_satisfy_any_protocol()

### Community 19 - "GUI Card Formatting Helpers"
Cohesion: 0.14
Nodes (7): _build_badges_row(), _format_confidence(), _format_media_type(), _format_source(), _get_shared_network_manager(), _make_badge(), RecommendationCard

### Community 20 - "Audio Extraction (ffmpeg)"
Cohesion: 0.17
Nodes (4): SubprocessCancelled, test_cancel_during_transcription_after_successful_extraction(), always_cancelled_extract_audio(), fake_run_cancelable()

### Community 21 - "Waterfall Race Jobs"
Cohesion: 0.19
Nodes (10): _extract_from_audio_transcript(), _extract_from_caption(), _extract_from_creator_comments(), _extract_from_visual(), _is_confident(), _JobOutcome, _prepare_audio(), _race_candidate_jobs() (+2 more)

### Community 24 - "Ingest Data Contracts"
Cohesion: 0.17
Nodes (6): IngestResult, _apply_primary_candidate_filter(), _creator_top_level_comments(), _primary_candidate_source_text(), FakeIngestor, test_fake_ingestor_satisfies_protocol()

### Community 25 - "yt-dlp Video Ingestion"
Cohesion: 0.23
Nodes (8): YtDlpClient, _patched_youtubedl(), test_extract_info_calls_download_with_url_and_download_flag(), test_extract_info_omits_cookies_file_when_none(), test_extract_info_passes_cookies_file_when_given(), test_extract_info_returns_the_raw_dict_yt_dlp_produces(), test_extract_info_sets_getcomments_and_skip_download_when_not_downloading(), test_extract_info_sets_skip_download_false_when_downloading()

### Community 26 - "Frame & Transcript Protocols"
Cohesion: 0.15
Nodes (6): FrameSample, FakePosterDetector, test_fake_poster_detector_satisfies_protocol(), recording_sample_frames_at_interval(), fake_sample_frames_at_interval(), fake_sample_frames_at_interval()

### Community 27 - "GUI Results Panel & Cards"
Cohesion: 0.19
Nodes (6): ResultsPanel, Live end-to-end test of streaming wiring (real reel, offscreen Qt), Review findings on GUI streaming wiring, gui/widgets.py changes: ResultsPanel.add_recommendation incremental add, GUI streaming wiring (consuming run_pipeline_streaming), GUI Subtask 2: presentational widgets (gui/widgets.py)

### Community 28 - "Waterfall Disambiguation Context"
Cohesion: 0.18
Nodes (6): _disambiguation_context(), _fetch_and_race(), _pool_candidates_and_transcript(), _resolve_all(), _resolve_one(), run_pipeline_streaming()

### Community 29 - "GUI Background Workers"
Cohesion: 0.20
Nodes (6): ClaudeCliCheckWorker, PipelineRunner, Fix 5 (MEDIUM) — _dedupe promoted to a public API (dedupe_recommendations), gui/workers.py changes: PipelineRunner consumes run_pipeline_streaming, GUI Subtask 1: background engine (gui/workers.py), _dedupe() (reel2movie/pipeline/waterfall.py, pre-rename)

### Community 33 - "Signal Source Priority Rationale"
Cohesion: 0.40
Nodes (4): Caption signal source, Creator's own top-level comment signal source, Frame sampling (visual) signal source, Signal sources, priority order

### Community 36 - "Execution Flow Steps"
Cohesion: 0.50
Nodes (3): [2] Caption-based extraction, [3] Creator-comment-based extraction, [4] Visual frame extraction (fallback)

## Knowledge Gaps
- **55 isolated node(s):** `reel2movie`, `Brainstorm — Movie Recommendation Reels Extraction`, `Execution Flow — Reel → Movie Recommendations`, `Caption signal source`, `Creator's own top-level comment signal source` (+50 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 503 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **62 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Candidate` connect `Core Models & Waterfall Tests` to `TMDB Tie-Break Disambiguation`, `Vision Chat Backends`, `Candidate Extraction & Source Tags`, `GUI Workers & CLI Entrypoint`, `Candidate Noise Filtering`, `Claude-CLI Text Extraction`, `TMDB HTTP Client`, `Handoff Doc Overview`, `Core Protocols`, `Waterfall Race Jobs`, `Candidate Parsing & Models`, `Ingest Data Contracts`, `Frame & Transcript Protocols`, `Waterfall Disambiguation Context`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Are the 91 inferred relationships involving `SourceTag` (e.g. with `parse_movie_candidates()` and `CandidateExtractor`) actually correct?**
  _`SourceTag` has 91 INFERRED edges - model-reasoned connections that need verification._
- **What connects `reel2movie`, `Brainstorm — Movie Recommendation Reels Extraction`, `Execution Flow — Reel → Movie Recommendations` to the rest of the system?**
  _55 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Core Models & Waterfall Tests` be split into smaller, more focused modules?**
  _Cohesion score 0.05731040916966547 - nodes in this community are weakly interconnected._
- **Why does `SourceTag` connect `Candidate Extraction & Source Tags` to `Core Models & Waterfall Tests`, `TMDB Tie-Break Disambiguation`, `Vision Chat Backends`, `GUI Workers & CLI Entrypoint`, `Candidate Noise Filtering`, `Claude-CLI Text Extraction`, `Core Protocols`, `Waterfall Race Jobs`, `Candidate Parsing & Models`, `Ingest Data Contracts`, `Frame & Transcript Protocols`?**
  _High betweenness centrality (0.080) - this node is a cross-community bridge._
- **Are the 36 inferred relationships involving `Candidate` (e.g. with `CandidateExtractor` and `PosterDetector`) actually correct?**
  _`Candidate` has 36 INFERRED edges - model-reasoned connections that need verification._
- **Should `TMDB Tie-Break Disambiguation` be split into smaller, more focused modules?**
  _Cohesion score 0.05272727272727273 - nodes in this community are weakly interconnected._