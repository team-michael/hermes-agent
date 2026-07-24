"""Requester-aware approval policy tests for shared gateway profiles."""

from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from gateway.session_context import clear_session_vars, set_session_vars
from tools import approval


@contextmanager
def _slack_request(user_id: str):
    session_key = f"agent:main:slack:group:C1:{user_id}"
    session_tokens = set_session_vars(
        platform="slack",
        user_id=user_id,
        session_key=session_key,
    )
    approval_token = approval.set_current_session_key(session_key)
    try:
        yield session_key
    finally:
        approval.reset_current_session_key(approval_token)
        clear_session_vars(session_tokens)
        approval.clear_session(session_key)


@pytest.fixture
def approval_config(monkeypatch):
    config = {
        "mode": "manual",
        "require": [
            "*git push*",
            "*gh pr merge*",
            "*gh api * -f *",
        ],
        "exempt_users": {"slack": ["U_OWNER"]},
        "approver_users": {"slack": ["U_OWNER"]},
    }
    monkeypatch.setattr(approval, "_get_approval_config", lambda: config)
    monkeypatch.setattr(
        "tools.tirith_security.check_command_security",
        lambda _command: {"action": "allow", "findings": [], "summary": ""},
    )
    return config


def test_configured_require_rule_marks_github_write_as_dangerous(approval_config):
    dangerous, pattern_key, description = approval.detect_dangerous_command(
        "gh pr merge 42 --squash"
    )

    assert dangerous is True
    assert pattern_key == "configured:*gh pr merge*"
    assert "approvals.require" in description


def test_owner_is_exempt_from_recoverable_github_write_approval(approval_config):
    with _slack_request("U_OWNER"):
        result = approval.check_all_command_guards(
            "git push origin HEAD", "local"
        )

    assert result["approved"] is True
    assert result["requester_exempt"] is True


def test_owner_exemption_never_bypasses_hardline_floor(approval_config):
    with _slack_request("U_OWNER"):
        result = approval.check_all_command_guards("rm -rf /", "local")

    assert result["approved"] is False
    assert result["hardline"] is True


def test_non_owner_github_write_requires_one_operation_approval(
    approval_config, monkeypatch
):
    monkeypatch.setattr(approval, "_command_matches_permanent_allowlist", lambda _cmd: True)

    with _slack_request("U_COWORKER"):
        result = approval.check_all_command_guards(
            "gh api repos/acme/app/issues -f title=hello", "local"
        )

    assert result["approved"] is False
    assert result["approval_pending"] is True
    assert result["allow_session"] is False
    assert result["allow_permanent"] is False


def test_shared_thread_yolo_does_not_bypass_non_owner_approval(approval_config):
    with _slack_request("U_COWORKER") as session_key:
        approval.enable_session_yolo(session_key)
        result = approval.check_all_command_guards(
            "git push origin HEAD", "local"
        )

    assert result["approved"] is False
    assert result["approval_pending"] is True


def test_shared_thread_cached_approval_does_not_bypass_non_owner(
    approval_config,
):
    with _slack_request("U_COWORKER") as session_key:
        approval.approve_session(session_key, "execute_code")
        result = approval.check_execute_code_guard("print('ok')", "local")

    assert result["approved"] is False
    assert result["approval_pending"] is True


def test_permanent_allowlist_does_not_bypass_non_owner_dangerous_command(
    approval_config, monkeypatch
):
    monkeypatch.setattr(approval, "_command_matches_permanent_allowlist", lambda _cmd: True)

    with _slack_request("U_COWORKER"):
        result = approval.check_all_command_guards(
            "systemctl restart app.service", "local"
        )

    assert result["approved"] is False
    assert result["approval_pending"] is True


def test_non_owner_read_only_github_command_does_not_require_approval(approval_config):
    with _slack_request("U_COWORKER"):
        result = approval.check_all_command_guards("gh pr list", "local")

    assert result["approved"] is True


def test_smart_mode_cannot_autoapprove_non_owner_github_write(
    approval_config, monkeypatch
):
    approval_config["mode"] = "smart"
    monkeypatch.setattr(approval, "_smart_approve", lambda *_args: "approve")

    with _slack_request("U_COWORKER"):
        result = approval.check_all_command_guards(
            "git push origin HEAD", "local"
        )

    assert result["approved"] is False
    assert result["approval_pending"] is True


def test_smart_mode_cannot_autoapprove_non_owner_execute_code(
    approval_config, monkeypatch
):
    approval_config["mode"] = "smart"
    monkeypatch.setattr(approval, "_smart_approve", lambda *_args: "approve")

    with _slack_request("U_COWORKER"):
        result = approval.check_execute_code_guard("print('ok')", "local")

    assert result["approved"] is False
    assert result["approval_pending"] is True


def test_owner_is_exempt_from_execute_code_approval(approval_config):
    with _slack_request("U_OWNER"):
        result = approval.check_execute_code_guard("print('ok')", "local")

    assert result["approved"] is True
    assert result["requester_exempt"] is True


def test_only_configured_approver_can_resolve_approval(approval_config):
    assert approval.can_user_resolve_approval("slack", "U_OWNER") is True
    assert approval.can_user_resolve_approval("slack", "U_COWORKER") is False


def test_resolver_is_backward_compatible_without_approver_config(
    approval_config,
):
    approval_config.pop("approver_users")
    assert approval.can_user_resolve_approval("slack", "U_ANYONE") is True


@pytest.mark.parametrize(
    "command",
    [
        "git push origin HEAD",
        "gh pr create --title test --body body",
        "gh issue close 42",
        "gh api repos/acme/app -X PATCH -f archived=true",
        "curl -X POST https://api.github.com/repos/acme/app/issues",
    ],
)
def test_bg_overlay_requires_approval_for_github_mutations(command, monkeypatch):
    overlay_path = (
        Path(__file__).resolve().parents[2]
        / "ignored/local/profiles/bg/config.overlay.yaml"
    )
    overlay = yaml.safe_load(overlay_path.read_text())
    monkeypatch.setattr(
        approval,
        "_get_approval_config",
        lambda: overlay["approvals"],
    )

    dangerous, pattern_key, _description = approval.detect_dangerous_command(command)

    assert dangerous is True
    assert pattern_key.startswith("configured:")


def test_bg_overlay_keeps_kelly_style_shared_threads():
    overlay_path = (
        Path(__file__).resolve().parents[2]
        / "ignored/local/profiles/bg/config.overlay.yaml"
    )
    overlay = yaml.safe_load(overlay_path.read_text())

    assert overlay["thread_sessions_per_user"] is False
    assert overlay["slack"]["require_mention"] is True
    assert overlay["slack"]["strict_mention"] is False
