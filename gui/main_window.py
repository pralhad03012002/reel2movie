"""The GUI's single top-level window.

One ``MainWindow`` class holds the entire one-screen app: a URL input row
(always visible) plus a content area below it that switches between four
states (idle / running / results / top-level error), with the inline
``ApiKeyPromptPanel`` shown only when the claude-CLI fallback is needed.

This module is the only place allowed to wire ``gui.workers`` (threads,
env-var fallback, dependency construction) to ``gui.widgets``
(presentation). Both of those modules have fixed public interfaces that are
used here exactly as documented in their own docstrings -- this file does
not reach into their internals.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.widgets import ApiKeyPromptPanel, ResultsPanel
from gui.workers import (
    ClaudeCliCheckWorker,
    PipelineRunner,
    apply_anthropic_api_fallback,
    build_deps_or_error,
)

# Real timing data from handoff.md's "Performance" section: caption/comment
# hits are 10-60s, visual-fallback hits range ~50s to ~24 minutes -- so the
# honest overall range to show the user is ~10 seconds to ~24 minutes.
_PIPELINE_RUNNING_TEXT = (
    "Analyzing reel… this can take anywhere from ~10 seconds to ~24 minutes"
)
_CLI_CHECK_RUNNING_TEXT = "Checking environment…"
_EMPTY_URL_MESSAGE = "Please enter a reel URL."


class MainWindow(QMainWindow):
    """The entire desktop app: input row + a four-state content area."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("reel2movie")
        self.resize(720, 560)

        # -- session state (persists across Run clicks within this process) --
        self._claude_cli_checked = False
        self._claude_cli_usable = False
        self._api_key_supplied = False
        self._pending_url: str | None = None

        # Keep running QThread instances referenced on self so Python never
        # garbage-collects a thread object out from under itself mid-run.
        self._cli_check_worker: ClaudeCliCheckWorker | None = None
        self._pipeline_runner: PipelineRunner | None = None

        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(12)

        # -- input row (always visible) --
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.url_input = QLineEdit()
        self.url_input.setObjectName("urlInput")
        self.url_input.setPlaceholderText("Paste an Instagram Reel URL…")
        self.url_input.returnPressed.connect(self._on_run_clicked)
        input_row.addWidget(self.url_input, 1)

        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self._on_run_clicked)
        input_row.addWidget(self.run_button, 0)

        root_layout.addLayout(input_row)

        self.validation_label = QLabel("")
        self.validation_label.setObjectName("validationLabel")
        self.validation_label.setVisible(False)
        root_layout.addWidget(self.validation_label)

        # -- inline API key panel (hidden unless the claude-CLI fallback
        # path needs it) --
        self._api_key_panel = ApiKeyPromptPanel()
        self._api_key_panel.setVisible(False)
        self._api_key_panel.key_submitted.connect(self._on_api_key_submitted)
        root_layout.addWidget(self._api_key_panel)

        # -- four-state content area --
        self.stacked_widget = QStackedWidget()
        root_layout.addWidget(self.stacked_widget, 1)

        self.idle_page = QWidget()
        self.stacked_widget.addWidget(self.idle_page)

        self.running_page = self._build_running_page()
        self.stacked_widget.addWidget(self.running_page)

        self.results_panel = ResultsPanel()
        self.stacked_widget.addWidget(self.results_panel)

        self.error_label = QLabel("")
        self.error_label.setObjectName("errorBanner")
        self.error_label.setWordWrap(True)
        self.stacked_widget.addWidget(self.error_label)

        self.stacked_widget.setCurrentWidget(self.idle_page)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Refuse to close while a background `QThread` is still running.

        Neither worker is Qt-parented to this window (both are constructed
        with the default `parent=None`), so closing the window would not
        automatically stop them -- and tearing down the process while one
        is still executing risks Qt's "QThread: Destroyed while thread is
        still running" crash. Simplest safe behavior: just don't allow the
        close until the in-flight check/run finishes on its own.
        """
        runner = self._pipeline_runner
        checker = self._cli_check_worker
        if (runner is not None and runner.isRunning()) or (
            checker is not None and checker.isRunning()
        ):
            event.ignore()
            return
        super().closeEvent(event)

    def _build_running_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 24, 0, 0)
        layout.setSpacing(12)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("progressBar")
        self.progress_bar.setRange(0, 0)  # indeterminate
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addStretch(1)
        return page

    # -- content-area state helpers -----------------------------------------

    def _show_idle(self) -> None:
        self.stacked_widget.setCurrentWidget(self.idle_page)

    def _show_running(self, text: str) -> None:
        self.status_label.setText(text)
        self.stacked_widget.setCurrentWidget(self.running_page)

    def _show_results(self) -> None:
        self.stacked_widget.setCurrentWidget(self.results_panel)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.stacked_widget.setCurrentWidget(self.error_label)

    def _show_validation_message(self, text: str) -> None:
        self.validation_label.setText(text)
        self.validation_label.setVisible(True)

    def _hide_validation_message(self) -> None:
        self.validation_label.setVisible(False)

    # -- Run click / state machine -------------------------------------------

    def _on_run_clicked(self) -> None:
        # Guards against re-entrancy: `run_button` is disabled for the
        # entire duration of any in-flight CLI check or pipeline run, but
        # `url_input.returnPressed` (wired above) fires regardless of the
        # button's enabled state, so without this check pressing Enter
        # mid-run would start a second worker and overwrite the
        # still-running one's `self._cli_check_worker`/`self._pipeline_runner`
        # reference.
        if not self.run_button.isEnabled():
            return
        url = self.url_input.text().strip()
        if not url:
            self._show_validation_message(_EMPTY_URL_MESSAGE)
            return

        self._hide_validation_message()
        self._api_key_panel.setVisible(False)
        self._pending_url = url
        self._begin_flow(url)

    def _begin_flow(self, url: str) -> None:
        if not self._claude_cli_checked:
            self.run_button.setEnabled(False)
            self._show_running(_CLI_CHECK_RUNNING_TEXT)
            self._cli_check_worker = ClaudeCliCheckWorker()
            self._cli_check_worker.finished_check.connect(self._on_cli_check_finished)
            self._cli_check_worker.start()
            return
        self._continue_after_cli_check(url)

    def _on_cli_check_finished(self, usable: bool) -> None:
        self._claude_cli_checked = True
        self._claude_cli_usable = usable
        if self._pending_url is None:
            return
        self._continue_after_cli_check(self._pending_url)

    def _continue_after_cli_check(self, url: str) -> None:
        if self._claude_cli_usable or self._api_key_supplied:
            self._launch_pipeline(url)
            return

        # claude CLI isn't usable and no API key has been supplied yet this
        # session -- pause here and ask for one inline.
        self.run_button.setEnabled(True)
        self._show_idle()
        self._api_key_panel.setVisible(True)

    def _on_api_key_submitted(self, key: str) -> None:
        apply_anthropic_api_fallback(key)
        self._api_key_supplied = True
        self._api_key_panel.setVisible(False)
        if self._pending_url is None:
            return
        self._launch_pipeline(self._pending_url)

    def _launch_pipeline(self, url: str) -> None:
        deps, error = build_deps_or_error()
        if error is not None:
            self.run_button.setEnabled(True)
            self._show_error(error)
            return

        # Reset the results panel before this run's first streamed result
        # arrives, so `_on_recommendation_ready` always starts trickling
        # cards into a clean panel rather than appending onto whatever an
        # earlier run left behind (the panel itself is long-lived across
        # Run clicks, not recreated per run).
        self.results_panel.clear()

        self.run_button.setEnabled(False)
        self._show_running(_PIPELINE_RUNNING_TEXT)

        self._pipeline_runner = PipelineRunner(url, deps)
        self._pipeline_runner.recommendation_ready.connect(self._on_recommendation_ready)
        self._pipeline_runner.succeeded.connect(self._on_pipeline_succeeded)
        self._pipeline_runner.failed.connect(self._on_pipeline_failed)
        self._pipeline_runner.start()

    def _on_recommendation_ready(self, rec: object) -> None:
        """One `Recommendation` streamed in early, ahead of the run's final
        `succeeded` signal -- trickle it into the results panel immediately
        and switch to the results page right away (on the very FIRST one),
        rather than waiting for the whole pipeline to finish. `succeeded`'s
        existing handler still does one full, authoritative re-render at
        the end, which naturally corrects/replaces these incrementally
        trickled-in cards with the final deduped set.
        """
        card_data = self._recommendation_to_card_data(rec)
        self.results_panel.add_recommendation(card_data)
        if self.stacked_widget.currentWidget() is not self.results_panel:
            self._show_results()

    def _on_pipeline_succeeded(self, result: object) -> None:
        cards_data = [
            self._recommendation_to_card_data(rec) for rec in result.recommendations
        ]
        self.results_panel.set_recommendations(cards_data)
        self._show_results()
        self.run_button.setEnabled(True)

    def _on_pipeline_failed(self, message: str) -> None:
        self._show_error(message)
        self.run_button.setEnabled(True)

    @staticmethod
    def _recommendation_to_card_data(rec: object) -> dict:
        tmdb = rec.tmdb
        if tmdb is not None:
            title = tmdb.title
            year = tmdb.year
            overview = tmdb.overview
            media_type = tmdb.media_type
            poster_path = tmdb.poster_path
        else:
            title = year = overview = media_type = poster_path = None

        return {
            "title": title,
            "year": year,
            "overview": overview,
            "media_type": media_type,
            "poster_path": poster_path,
            "source": rec.source.value,
            "confidence": rec.confidence,
            "query": rec.query,
        }
