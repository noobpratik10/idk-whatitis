import json
from unittest.mock import MagicMock, patch

import pytest

from swij.core.intent_parser import IntentParser
from swij.schemas.actions import GitActionPlan


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_parser(monkeypatch):
    """Create an IntentParser with a mocked google.genai Client."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")

    with patch("swij.core.intent_parser.genai") as mock_genai:
        # Mock the Client class and its models attribute
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        # Build parser with mocked internals
        parser = IntentParser.__new__(IntentParser)
        parser._client = mock_client
        parser._model_name = "gemini-2.0-flash"
        parser._confidence_threshold = 0.75

        yield parser, mock_client.models


# ---------------------------------------------------------------------------
# Test: basic intent parsing
# ---------------------------------------------------------------------------

def _setup_response(mock_models, json_text: str):
    """Helper: configure the mock to return given JSON via .text fallback."""
    mock_response = MagicMock()
    mock_response.parsed = None  # Force .text fallback
    mock_response.text = json_text
    mock_models.generate_content.return_value = mock_response


def test_parse_git_status(mock_parser):
    """Parser correctly maps 'show git status' to git_status action."""
    parser, mock_models = mock_parser
    _setup_response(mock_models, '{"action": "git_status", "confidence": 0.98}')
    plan = parser.parse("show git status")
    assert plan.action == "git_status"
    assert plan.confidence == pytest.approx(0.98)
    assert plan.is_safe is True


def test_parse_create_branch(mock_parser):
    """Parser extracts branch name and base branch correctly."""
    parser, mock_models = mock_parser
    _setup_response(
        mock_models,
        '{"action": "create_branch", "branch_name": "fix-login", '
        '"base_branch": "develop", "auto_fetch": true, "confidence": 1.0}',
    )
    plan = parser.parse("create a branch from develop called fix-login")
    assert plan.action == "create_branch"
    assert plan.branch_name == "fix-login"
    assert plan.base_branch == "develop"
    assert plan.auto_fetch is True
    assert plan.risk_level == "yellow"


def test_parse_commit_with_files(mock_parser):
    """Parser extracts specific files and commit message."""
    parser, mock_models = mock_parser
    _setup_response(
        mock_models,
        '{"action": "git_commit", "files_to_add": ["src/auth.py"], '
        '"commit_message": "fix token validation", "confidence": 1.0}',
    )
    plan = parser.parse("commit only src/auth.py with message 'fix token validation'")
    assert plan.action == "git_commit"
    assert plan.files_to_add == ["src/auth.py"]
    assert plan.commit_message == "fix token validation"


def test_parse_hard_reset_sets_needs_confirmation(mock_parser):
    """Parser sets needs_confirmation=True for destructive actions."""
    parser, mock_models = mock_parser
    _setup_response(
        mock_models,
        '{"action": "git_reset", "reset_mode": "hard", '
        '"reset_target": "HEAD~3", "needs_confirmation": true, "confidence": 0.95}',
    )
    plan = parser.parse("hard reset to 3 commits ago")
    assert plan.action == "git_reset"
    assert plan.reset_mode == "hard"
    assert plan.reset_target == "HEAD~3"
    assert plan.needs_confirmation is True
    assert plan.is_destructive is True


def test_parse_unknown_intent(mock_parser):
    """Parser returns action='unknown' with a helpful message for unrecognized requests."""
    parser, mock_models = mock_parser
    _setup_response(
        mock_models,
        '{"action": "unknown", "user_message": "I only help with Git tasks.", "confidence": 1.0}',
    )
    plan = parser.parse("what's the weather?")
    assert plan.action == "unknown"
    assert plan.user_message is not None
    assert len(plan.user_message) > 0


def test_parse_no_auto_fetch_when_local_specified(mock_parser):
    """Parser sets auto_fetch=False when user says 'from my local ...'"""
    parser, mock_models = mock_parser
    _setup_response(
        mock_models,
        '{"action": "create_branch", "branch_name": "my-branch", '
        '"base_branch": "develop", "auto_fetch": false, "confidence": 0.92}',
    )
    plan = parser.parse("create branch from my local develop called my-branch")
    assert plan.auto_fetch is False


# ---------------------------------------------------------------------------
# Test: error handling
# ---------------------------------------------------------------------------

def test_parse_malformed_json_returns_unknown(mock_parser):
    """If Gemini returns invalid JSON, parser returns action='unknown' gracefully."""
    parser, mock_models = mock_parser
    _setup_response(mock_models, "This is not JSON at all!")
    plan = parser.parse("do something")
    assert plan.action == "unknown"
    assert plan.confidence == 0.0
    assert plan.user_message is not None


def test_parse_schema_mismatch_returns_unknown(mock_parser):
    """If Gemini returns JSON with an invalid action, parser returns unknown."""
    parser, mock_models = mock_parser
    _setup_response(mock_models, '{"action": "fly_to_the_moon", "confidence": 1.0}')
    plan = parser.parse("something weird")
    assert plan.action == "unknown"


# ---------------------------------------------------------------------------
# Test: GitActionPlan model helpers
# ---------------------------------------------------------------------------

def test_git_action_plan_risk_level_green():
    plan = GitActionPlan(action="git_status")
    assert plan.risk_level == "green"
    assert plan.is_safe is True
    assert plan.is_destructive is False


def test_git_action_plan_risk_level_red():
    plan = GitActionPlan(action="git_reset")
    assert plan.risk_level == "red"
    assert plan.is_destructive is True
    assert plan.is_safe is False


def test_git_action_plan_confidence_bounds():
    """Confidence must be between 0.0 and 1.0."""
    with pytest.raises(Exception):
        GitActionPlan(action="git_status", confidence=1.5)
    with pytest.raises(Exception):
        GitActionPlan(action="git_status", confidence=-0.1)
