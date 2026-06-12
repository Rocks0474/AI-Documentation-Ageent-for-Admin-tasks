"""
Slack event handlers — parse Slack payloads and hand off to the agent.

Each handler:
  1. Parses the Slack payload into clean dicts
  2. Sends an immediate acknowledgement (never block the Slack thread)
  3. Invokes the orchestration agent in a background thread
"""

import logging
import os
import threading

from agent import AccountRequestAgent
from config.tool_executor import execute_tool

logger = logging.getLogger(__name__)

_agent = AccountRequestAgent(tool_executor=execute_tool)
APPROVAL_CHANNEL = os.environ.get("SLACK_APPROVAL_CHANNEL", "#it-admin-approvals")


def handle_form_submission(body: dict, client, log) -> None:
    """Parse modal submission and kick off the new request workflow."""
    values = body["view"]["state"]["values"]
    user = body["user"]

    user_info = client.users_info(user=user["id"])
    user_email = user_info["user"]["profile"].get("email", "")

    form_data = _parse_modal_values(values)
    slack_context = {
        "user_id":    user["id"],
        "user_email": user_email,
        "channel_id": APPROVAL_CHANNEL,
        "thread_ts":  None,
    }

    client.chat_postMessage(
        channel=user["id"],
        text=(
            f":white_check_mark: Your access request for *{form_data.get('contractor_full_name')}* "
            "has been received and is being processed. You'll be notified once it's reviewed."
        )
    )

    threading.Thread(
        target=lambda: _agent.handle_new_request(form_data, slack_context),
        daemon=True
    ).start()


def handle_approve_click(body: dict, client, log) -> None:
    action = body["actions"][0]
    record_id = int(action["value"])
    approver = body["user"]

    client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f":white_check_mark: Approved by <@{approver['id']}>. Processing...",
        blocks=[]
    )

    threading.Thread(
        target=lambda: _agent.handle_approval_decision(
            record_id=record_id, approved=True, approver_slack_id=approver["id"]
        ),
        daemon=True
    ).start()


def handle_rejection_reason_submit(body: dict, client, log) -> None:
    record_id = int(body["view"]["private_metadata"])
    values = body["view"]["state"]["values"]
    reason = values["rejection_reason"]["value"]["value"]
    approver = body["user"]

    threading.Thread(
        target=lambda: _agent.handle_approval_decision(
            record_id=record_id, approved=False,
            approver_slack_id=approver["id"], reason=reason
        ),
        daemon=True
    ).start()


def _parse_modal_values(values: dict) -> dict:
    """Flatten Slack's nested state.values into a clean dict."""
    result = {}
    for block_id, block in values.items():
        for action_id, element in block.items():
            t = element.get("type")
            if t == "plain_text_input":
                result[block_id] = element.get("value")
            elif t in ("static_select", "external_select"):
                sel = element.get("selected_option")
                result[block_id] = sel["value"] if sel else None
            elif t == "datepicker":
                result[block_id] = element.get("selected_date")
            elif t == "checkboxes":
                result[block_id] = [o["value"] for o in element.get("selected_options", [])]
            elif t == "users_select":
                result[block_id] = element.get("selected_user")
    return result
