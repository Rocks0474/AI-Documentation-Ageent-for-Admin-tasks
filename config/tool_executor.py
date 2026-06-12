"""
Tool executor — dispatches Claude's tool calls to real integrations.

This is the single file you edit to wire up your actual API clients.
Every function returns a plain dict; Claude reads this to decide next steps.

Phase 1 (start here): implement kintone_* and request_human_approval
Phase 2: implement docusign_*
Phase 3+: implement google_workspace_*, gcp_*, slack_*, github_*
"""

import logging
import os

logger = logging.getLogger(__name__)


def execute_tool(tool_name: str, tool_input: dict) -> dict:
    """Dispatcher: maps tool names to implementation functions."""
    handlers = {
        "kintone_create_request_record":   kintone_create_request_record,
        "kintone_update_request_status":   kintone_update_request_status,
        "kintone_get_request":             kintone_get_request,
        "kintone_list_expiring_requests":  kintone_list_expiring_requests,
        "request_human_approval":          request_human_approval,
        "docusign_send_agreement":         docusign_send_agreement,
        "docusign_check_status":           docusign_check_status,
        "google_workspace_create_account": google_workspace_create_account,
        "google_workspace_suspend_account": google_workspace_suspend_account,
        "gcp_grant_project_access":        gcp_grant_project_access,
        "gcp_revoke_project_access":       gcp_revoke_project_access,
        "slack_add_user_to_channels":      slack_add_user_to_channels,
        "slack_send_notification":         slack_send_notification,
        "github_add_to_teams":             github_add_to_teams,
        "github_remove_from_teams":        github_remove_from_teams,
        "offboard_contractor":             offboard_contractor,
    }
    handler = handlers.get(tool_name)
    if not handler:
        return {"error": f"Unknown tool: {tool_name}"}
    logger.info("Executing tool: %s", tool_name)
    return handler(tool_input)


# ── Kintone ───────────────────────────────────────────────────────────────────
# REST API docs: https://kintone.dev/en/docs/kintone/rest-api/
#
# Pattern for all Kintone calls:
#   subdomain = os.environ["KINTONE_SUBDOMAIN"]
#   api_token = os.environ["KINTONE_API_TOKEN"]
#   app_id    = os.environ["KINTONE_APP_ID"]
#   headers   = {"X-Cybozu-API-Token": api_token, "Content-Type": "application/json"}
#   base_url  = f"https://{subdomain}.cybozu.com/k/v1"

def kintone_create_request_record(inp: dict) -> dict:
    # POST {base_url}/record.json
    # Body: {"app": app_id, "record": {field_code: {"value": ...}, ...}}
    # Returns: {"id": "123", "revision": "1"}
    raise NotImplementedError("kintone_create_request_record not yet implemented")


def kintone_update_request_status(inp: dict) -> dict:
    # PUT {base_url}/record.json
    # Body: {"app": app_id, "id": record_id, "record": {field_code: {"value": ...}}}
    raise NotImplementedError("kintone_update_request_status not yet implemented")


def kintone_get_request(inp: dict) -> dict:
    # GET {base_url}/record.json?app={app_id}&id={record_id}
    raise NotImplementedError("kintone_get_request not yet implemented")


def kintone_list_expiring_requests(inp: dict) -> dict:
    # GET {base_url}/records.json?app={app_id}&query=status="ACTIVE" and engagement_end_date <= TODAY()+{days}
    raise NotImplementedError("kintone_list_expiring_requests not yet implemented")


# ── Approval gate ─────────────────────────────────────────────────────────────
# Store pending approvals in a DB table: (record_id, status, approver, decided_at)
# Resolve via Slack button webhook -> update DB row -> agent polls or is woken up

def request_human_approval(inp: dict) -> dict:
    raise NotImplementedError(
        "request_human_approval: implement with a DB-backed pending-approval store "
        "resolved by Slack button webhooks."
    )


# ── DocuSign ──────────────────────────────────────────────────────────────────
# SDK: pip install docusign-esign
# Docs: https://developers.docusign.com/docs/esign-rest-api/

def docusign_send_agreement(inp: dict) -> dict:
    raise NotImplementedError("docusign_send_agreement not yet implemented")


def docusign_check_status(inp: dict) -> dict:
    raise NotImplementedError("docusign_check_status not yet implemented")


# ── Google Workspace ──────────────────────────────────────────────────────────
# SDK: pip install google-api-python-client google-auth
# Docs: https://developers.google.com/admin-sdk/directory/v1/guides/manage-users

def google_workspace_create_account(inp: dict) -> dict:
    raise NotImplementedError("google_workspace_create_account not yet implemented")


def google_workspace_suspend_account(inp: dict) -> dict:
    raise NotImplementedError("google_workspace_suspend_account not yet implemented")


# ── GCP IAM ───────────────────────────────────────────────────────────────────
# Docs: https://cloud.google.com/iam/docs/granting-changing-revoking-access

def gcp_grant_project_access(inp: dict) -> dict:
    raise NotImplementedError("gcp_grant_project_access not yet implemented")


def gcp_revoke_project_access(inp: dict) -> dict:
    raise NotImplementedError("gcp_revoke_project_access not yet implemented")


# ── Slack ─────────────────────────────────────────────────────────────────────
# SDK: pip install slack-sdk
# Pattern: WebClient(token=os.environ["SLACK_BOT_TOKEN"])

def slack_add_user_to_channels(inp: dict) -> dict:
    raise NotImplementedError("slack_add_user_to_channels not yet implemented")


def slack_send_notification(inp: dict) -> dict:
    raise NotImplementedError("slack_send_notification not yet implemented")


# ── GitHub ────────────────────────────────────────────────────────────────────
# SDK: pip install PyGithub
# Docs: https://docs.github.com/en/rest/teams/members

def github_add_to_teams(inp: dict) -> dict:
    raise NotImplementedError("github_add_to_teams not yet implemented")


def github_remove_from_teams(inp: dict) -> dict:
    raise NotImplementedError("github_remove_from_teams not yet implemented")


# ── Offboarding ───────────────────────────────────────────────────────────────

def offboard_contractor(inp: dict) -> dict:
    """Composite: fetches Kintone record and calls individual revocation tools."""
    record = kintone_get_request({"record_id": inp["record_id"]})
    systems = record.get("systems_requested", [])
    results = []

    if "GOOGLE_WORKSPACE_EMAIL" in systems:
        r = google_workspace_suspend_account({
            "record_id": inp["record_id"],
            "user_email": record.get("provisioned_email", ""),
            "reason": inp.get("reason", "END_OF_ENGAGEMENT")
        })
        results.append({"system": "GOOGLE_WORKSPACE", "result": r})

    if "GCP_PROJECT_ACCESS" in systems:
        r = gcp_revoke_project_access({
            "record_id": inp["record_id"],
            "user_email": record.get("provisioned_email", ""),
            "project_ids": [p.strip() for p in record.get("gcp_projects", "").split(",") if p.strip()]
        })
        results.append({"system": "GCP", "result": r})

    if "GITHUB" in systems:
        github_username = record.get("github_username", "")
        if github_username:
            r = github_remove_from_teams({"record_id": inp["record_id"], "github_username": github_username})
            results.append({"system": "GITHUB", "result": r})

    return {"offboarded_systems": results, "record_id": inp["record_id"]}
