"""Presentation-layer widgets for the reel2movie desktop GUI.

This module is deliberately ignorant of ``reel2movie``, threading, env vars,
or the pipeline. Every widget here is constructed from plain Python values
(str/int/float/None/dict/list) and communicates upward only through plain Qt
signals carrying plain values. A background-engine module and a main-window
module (built elsewhere) are expected to import exactly the three classes
below and wire them up.

Design system
--------------
Colors and spacing are centralized as module-level constants and woven into
one QSS template (``_STYLESHEET``) rather than scattered as inline hex
strings across widget code. Every widget in this module applies the same
stylesheet to itself; QSS rules are scoped by object name, so sharing one
sheet across independent widget instances is harmless.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Design tokens: spacing scale
# ---------------------------------------------------------------------------

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 20
SPACE_6 = 28

# ---------------------------------------------------------------------------
# Design tokens: color system
# ---------------------------------------------------------------------------

COLOR_PANEL_BG = "#F3F4F8"
COLOR_CARD_BG = "#FFFFFF"
COLOR_CARD_BORDER = "#E3E5EC"
COLOR_CARD_HOVER_BORDER = "#C9CDFB"

COLOR_TEXT_PRIMARY = "#1A1D29"
COLOR_TEXT_SECONDARY = "#5B6072"
COLOR_TEXT_TERTIARY = "#8A8F9C"

COLOR_ACCENT = "#4F5DFF"
COLOR_ACCENT_SOFT_BG = "#EEF0FF"
COLOR_ACCENT_SOFT_TEXT = "#4047C4"

COLOR_BADGE_BG = "#F0F1F6"
COLOR_BADGE_TEXT = "#5B6072"

COLOR_UNRESOLVED_BG = "#FAFAFC"
COLOR_UNRESOLVED_BORDER = "#C9CDD6"
COLOR_UNRESOLVED_TEXT = "#767C8A"
COLOR_UNRESOLVED_HEADLINE = "#42465A"

COLOR_DANGER = "#C0392B"
COLOR_DANGER_SOFT_BG = "#FDECEC"

# ---------------------------------------------------------------------------
# Design tokens: typography
# ---------------------------------------------------------------------------

FONT_FAMILY = '"Segoe UI", -apple-system, "Helvetica Neue", Arial, sans-serif'

# Poster placeholder dimensions (roughly TMDB's 2:3 poster aspect ratio).
POSTER_WIDTH = 112
POSTER_HEIGHT = 168

TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"


_STYLESHEET = f"""
QWidget {{
    font-family: {FONT_FAMILY};
}}

/* ---------------- RecommendationCard ---------------- */

QWidget#recommendationCard {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_CARD_BORDER};
    border-radius: 10px;
}}

QWidget#recommendationCard[unresolved="true"] {{
    background-color: {COLOR_UNRESOLVED_BG};
    border: 1px dashed {COLOR_UNRESOLVED_BORDER};
}}

QLabel#cardTitle {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 17px;
    font-weight: 600;
}}

QLabel#cardYearType {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 12px;
    font-weight: 500;
}}

QLabel#cardQuery {{
    color: {COLOR_TEXT_TERTIARY};
    font-size: 11px;
    font-style: italic;
}}

QLabel#cardOverview {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 13px;
}}

QLabel#cardBadge {{
    background-color: {COLOR_BADGE_BG};
    color: {COLOR_BADGE_TEXT};
    font-size: 11px;
    font-weight: 600;
    border-radius: 9px;
    padding: 3px 10px;
}}

QLabel#cardPoster {{
    background-color: {COLOR_ACCENT_SOFT_BG};
    color: {COLOR_TEXT_TERTIARY};
    border-radius: 8px;
    font-size: 11px;
}}

QLabel#unresolvedPoster {{
    background-color: {COLOR_UNRESOLVED_BG};
    color: {COLOR_UNRESOLVED_BORDER};
    border: 1px dashed {COLOR_UNRESOLVED_BORDER};
    border-radius: 8px;
    font-size: 28px;
}}

QLabel#unresolvedHeadline {{
    color: {COLOR_UNRESOLVED_HEADLINE};
    font-size: 15px;
    font-weight: 600;
}}

QLabel#unresolvedExplanation {{
    color: {COLOR_UNRESOLVED_TEXT};
    font-size: 12px;
}}

/* ---------------- ApiKeyPromptPanel ---------------- */

QWidget#apiKeyPromptPanel {{
    background-color: {COLOR_ACCENT_SOFT_BG};
    border: 1px solid {COLOR_CARD_BORDER};
    border-radius: 10px;
}}

QLabel#apiKeyTitle {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 15px;
    font-weight: 600;
}}

QLabel#apiKeyExplanation {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 12px;
}}

QLineEdit#apiKeyInput {{
    background-color: {COLOR_CARD_BG};
    border: 1px solid {COLOR_CARD_BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 13px;
    color: {COLOR_TEXT_PRIMARY};
}}

QLineEdit#apiKeyInput:focus {{
    border: 1px solid {COLOR_ACCENT};
}}

QPushButton#apiKeySubmit {{
    background-color: {COLOR_ACCENT};
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 600;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
}}

QPushButton#apiKeySubmit:hover {{
    background-color: {COLOR_ACCENT_SOFT_TEXT};
}}

QPushButton#apiKeySubmit:pressed {{
    background-color: {COLOR_ACCENT_SOFT_TEXT};
}}

QLabel#validationHint {{
    color: {COLOR_DANGER};
    font-size: 11px;
}}

/* ---------------- ResultsPanel ---------------- */

QWidget#resultsPanel, QWidget#resultsPanelContent {{
    background-color: {COLOR_PANEL_BG};
    border: none;
}}

QScrollArea#resultsScrollArea {{
    background-color: {COLOR_PANEL_BG};
    border: none;
}}

QLabel#emptyStateLabel {{
    color: {COLOR_TEXT_TERTIARY};
    font-size: 14px;
}}
"""


def _format_confidence(confidence: float) -> str:
    try:
        return f"{confidence:.0%}"
    except (TypeError, ValueError):
        return "--"


def _format_source(source: str) -> str:
    return source.replace("_", " ").strip().title()


def _format_media_type(media_type: str | None) -> str | None:
    if media_type == "movie":
        return "Movie"
    if media_type == "tv":
        return "TV Show"
    return None


def _make_badge(text: str) -> QLabel:
    badge = QLabel(text)
    badge.setObjectName("cardBadge")
    badge.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    return badge


def _build_badges_row(source: str, confidence: float) -> QHBoxLayout:
    """Shared source/confidence badge row used by both the resolved and
    unresolved card layouts."""
    row = QHBoxLayout()
    row.setSpacing(SPACE_2)
    row.addWidget(_make_badge(_format_source(source)))
    row.addWidget(_make_badge(f"Confidence {_format_confidence(confidence)}"))
    row.addStretch(1)
    return row


# One process-wide QNetworkAccessManager shared by every RecommendationCard's
# poster fetch, rather than each card opening its own connection pool.
_shared_network_manager: QNetworkAccessManager | None = None


def _get_shared_network_manager() -> QNetworkAccessManager:
    global _shared_network_manager
    if _shared_network_manager is None:
        _shared_network_manager = QNetworkAccessManager()
    return _shared_network_manager


class RecommendationCard(QWidget):
    """One result card. Construct with plain fields:

        RecommendationCard(
            title: str | None,       # None means unresolved (tmdb was null)
            year: int | None,
            overview: str | None,
            media_type: str | None,  # "movie" | "tv" | None
            source: str,             # e.g. "caption" (already a plain string)
            confidence: float,
            poster_path: str | None, # TMDB relative path, or None
            query: str,              # raw candidate string, always shown
            parent=None,
        )

    If ``poster_path`` is not None, the poster is fetched asynchronously via
    ``QNetworkAccessManager`` (never blocking the GUI thread) and swapped in
    once it arrives; a failed fetch just leaves the placeholder, silently.

    When ``title`` is None the card is marked via the ``unresolved`` dynamic
    property (so external QSS using ``[unresolved="true"]`` can also style
    it) and renders a visually distinct placeholder: no poster fetch, no
    year/overview, instead explanatory copy plus the always-known
    source/confidence.
    """

    def __init__(
        self,
        title: str | None,
        year: int | None,
        overview: str | None,
        media_type: str | None,
        source: str,
        confidence: float,
        poster_path: str | None,
        query: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._poster_label: QLabel | None = None

        unresolved = title is None

        self.setObjectName("recommendationCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("unresolved", bool(unresolved))
        self.setStyleSheet(_STYLESHEET)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(SPACE_4, SPACE_4, SPACE_4, SPACE_4)
        outer.setSpacing(SPACE_4)

        if unresolved:
            self._build_unresolved_content(outer, query, source, confidence)
        else:
            self._build_resolved_content(
                outer, title, year, overview, media_type, source, confidence, query, poster_path
            )

        # Force the dynamic-property-based QSS selector to re-evaluate now
        # that the property is set, rather than waiting for the next
        # implicit style event.
        self.style().unpolish(self)
        self.style().polish(self)

    # -- resolved state -----------------------------------------------------

    def _build_resolved_content(
        self,
        outer: QHBoxLayout,
        title: str,
        year: int | None,
        overview: str | None,
        media_type: str | None,
        source: str,
        confidence: float,
        query: str,
        poster_path: str | None,
    ) -> None:
        poster = QLabel("No Poster")
        poster.setObjectName("cardPoster")
        poster.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        poster.setFixedSize(POSTER_WIDTH, POSTER_HEIGHT)
        poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        poster.setWordWrap(True)
        outer.addWidget(poster, 0, Qt.AlignmentFlag.AlignTop)
        self._poster_label = poster

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(SPACE_2)

        header = QHBoxLayout()
        header.setSpacing(SPACE_2)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        title_label.setWordWrap(True)
        header.addWidget(title_label, 1)
        body.addLayout(header)

        meta_bits = []
        if year is not None:
            meta_bits.append(str(year))
        media_type_text = _format_media_type(media_type)
        if media_type_text is not None:
            meta_bits.append(media_type_text)
        if meta_bits:
            meta_label = QLabel(" · ".join(meta_bits))
            meta_label.setObjectName("cardYearType")
            body.addWidget(meta_label)

        query_label = QLabel(f'Detected as "{query}"')
        query_label.setObjectName("cardQuery")
        query_label.setWordWrap(True)
        body.addWidget(query_label)

        if overview:
            overview_label = QLabel(overview)
            overview_label.setObjectName("cardOverview")
            overview_label.setWordWrap(True)
            body.addWidget(overview_label)

        body.addLayout(_build_badges_row(source, confidence))

        outer.addLayout(body, 1)

        if poster_path:
            self._start_poster_fetch(poster_path)

    # -- unresolved state -----------------------------------------------------

    def _build_unresolved_content(
        self, outer: QHBoxLayout, query: str, source: str, confidence: float
    ) -> None:
        placeholder = QLabel("?")
        placeholder.setObjectName("unresolvedPoster")
        placeholder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        placeholder.setFixedSize(POSTER_WIDTH, POSTER_HEIGHT)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(placeholder, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(SPACE_2)

        headline = QLabel(f'Detected "{query}" but could not verify on TMDB')
        headline.setObjectName("unresolvedHeadline")
        headline.setWordWrap(True)
        body.addWidget(headline)

        explanation = QLabel(
            "This usually means the TMDB lookup failed or the title couldn't be "
            "confirmed -- it isn't an extraction error."
        )
        explanation.setObjectName("unresolvedExplanation")
        explanation.setWordWrap(True)
        body.addWidget(explanation)

        body.addLayout(_build_badges_row(source, confidence))
        body.addStretch(1)

        outer.addLayout(body, 1)

    # -- async poster fetch -----------------------------------------------------

    def _start_poster_fetch(self, poster_path: str) -> None:
        manager = _get_shared_network_manager()
        url = QUrl(f"{TMDB_IMAGE_BASE_URL}{poster_path}")
        request = QNetworkRequest(url)
        reply = manager.get(request)
        reply.finished.connect(lambda reply=reply: self._on_poster_reply_finished(reply))

    def _on_poster_reply_finished(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError and self._poster_label is not None:
                data = reply.readAll()
                pixmap = QPixmap()
                if pixmap.loadFromData(data) and not pixmap.isNull():
                    scaled = pixmap.scaled(
                        self._poster_label.width(),
                        self._poster_label.height(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self._poster_label.setText("")
                    self._poster_label.setPixmap(scaled)
            # Any error (network failure, bad path, timeout, non-2xx status)
            # is intentionally swallowed here: the placeholder simply stays.
        except RuntimeError:
            # The card (and its poster label) may already have been torn
            # down -- e.g. ResultsPanel.clear() ran while this reply was
            # still in flight -- in which case the underlying Qt C++ object
            # is gone. Nothing to update in that case.
            pass
        finally:
            reply.deleteLater()


class ApiKeyPromptPanel(QWidget):
    """Inline (not a popup/separate window) prompt for an API key: a short
    explanation, a password-mode QLineEdit, and a submit button, with
    Enter-to-submit support.
    """

    key_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("apiKeyPromptPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_5, SPACE_5, SPACE_5, SPACE_5)
        layout.setSpacing(SPACE_3)

        title = QLabel("Anthropic API Key Needed")
        title.setObjectName("apiKeyTitle")
        layout.addWidget(title)

        explanation = QLabel(
            "The local claude CLI isn't available or isn't logged in. An "
            "Anthropic API key is needed to run the vision-based detection "
            "step instead. Paste your key below to continue -- it is kept "
            "only in memory for this session."
        )
        explanation.setObjectName("apiKeyExplanation")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        input_row = QHBoxLayout()
        input_row.setSpacing(SPACE_2)

        self._line_edit = QLineEdit()
        self._line_edit.setObjectName("apiKeyInput")
        self._line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._line_edit.setPlaceholderText("Paste your Anthropic API key")
        self._line_edit.returnPressed.connect(self._try_submit)
        input_row.addWidget(self._line_edit, 1)

        self._submit_button = QPushButton("Submit")
        self._submit_button.setObjectName("apiKeySubmit")
        self._submit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._submit_button.clicked.connect(self._try_submit)
        input_row.addWidget(self._submit_button, 0)

        layout.addLayout(input_row)

        self._hint_label = QLabel("Please enter a key before submitting.")
        self._hint_label.setObjectName("validationHint")
        self._hint_label.setVisible(False)
        layout.addWidget(self._hint_label)

    def _try_submit(self) -> None:
        text = self._line_edit.text().strip()
        if not text:
            self._hint_label.setVisible(True)
            return
        self._hint_label.setVisible(False)
        self.key_submitted.emit(text)


class ResultsPanel(QWidget):
    """Scrollable container of ``RecommendationCard`` widgets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("resultsPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_STYLESHEET)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("resultsScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._content = QWidget()
        self._content.setObjectName("resultsPanelContent")
        self._content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(SPACE_5, SPACE_5, SPACE_5, SPACE_5)
        self._content_layout.setSpacing(SPACE_4)

        self._scroll_area.setWidget(self._content)
        outer.addWidget(self._scroll_area)

        self._empty_label: QLabel | None = None

    def set_recommendations(self, cards_data: list[dict]) -> None:
        """Clears any existing cards, creates one ``RecommendationCard`` per
        dict. Each dict has exactly the keys matching
        ``RecommendationCard``'s constructor kwargs (title, year, overview,
        media_type, source, confidence, poster_path, query). If
        ``cards_data`` is empty, shows a plain centered "no recommendations
        found" message instead of an empty blank panel.
        """
        self.clear()

        if not cards_data:
            self._content_layout.addStretch(1)
            self._empty_label = QLabel("No recommendations found.")
            self._empty_label.setObjectName("emptyStateLabel")
            self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._content_layout.addWidget(self._empty_label)
            self._content_layout.addStretch(1)
            return

        for card_data in cards_data:
            card = RecommendationCard(parent=self._content, **card_data)
            self._content_layout.addWidget(card)

        self._content_layout.addStretch(1)

    def clear(self) -> None:
        """Removes all cards and any empty-state message, resetting to a
        truly empty container ready for the next ``set_recommendations``
        call.
        """
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._empty_label = None
