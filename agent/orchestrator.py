"""
Account Request Orchestration Agent
====================================
Uses Claude claude-opus-4-6 with tool use to orchestrate the full lifecycle of
external contractor account requests:

  Intake -> Approval -> Agreement (DocuSign) -> Provisioning -> Active -> Offboarding

The agent is invoked in two ways:
  1. Event-driven: a Slack form submission triggers handle_new_request()
  2. Scheduled:    a cron job triggers check_expiring_contracts() daily
"""

import json
import logging
from typing import Any

import anthropic

from .tools import TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-6"

SYSTEM_PROMPT = """You are an IT administration agent for a Japanese company.
Your role is to orchestrate the full lifecycle of system account requests
for external contractors: advisors, engineering outsourcers, and business outsourcers.

## Your responsibilities
1. Process new account requests submitted via Slack
2. Validate that all required information is present; ask for clarification if not
3. Create a Kintone tracking record for every request
4. Route requests to the correct approver and wait for their decision
5. Send DocuSign agreements after approval
6. Provision accounts in the requested systems after the agreement is signed
7. Notify all parties of status changes via Slack
8. Handle scheduled offboarding when engagements end

## Key rules — never violate these
- NEVER provision any account without a human approval on record (use request_human_approval)
- NEVER provision any account before the DocuSign agreement is signed
  (exception: agreement_type = EXISTING or NONE, confirmed by the approver)
- GCP access: never grant roles/editor or roles/owner unless allow_editor_override=true
  was explicitly set by the approver
- Always update Kintone status BEFORE sending Slack notifications
- Log every action in the Kintone record's provisioned_systems field
- If any provisioning step fails, mark that system as FAILED in the log,
  continue with remaining systems, and alert the sponsor via Slack

## Tone
- Responses to users should be professional and concise
- Use Japanese honorifics when addressing Japanese-named contractors if appropriate
- Status messages should be clear about what happened and what comes next
"""


class AccountRequestAgent:
    """
    Thin orchestration wrapper around Claude.

    Your application (e.g. Slack bot) calls the public methods.
    This class manages the tool-use loop; you supply a `tool_executor`
    callable that actually runs each tool against real APIs.
    """

    def __init__(self, tool_executor: callable):
        """
        Args:
            tool_executor: callable(tool_name: str, tool_input: dict) -> dict
                           Implement this to call your real integrations.
                           Raise an exception on hard errors; return {"error": "..."} for soft errors.
        """
        self.client = anthropic.Anthropic()
        self.tool_executor = tool_executor

    def handle_new_request(self, form_data: dict, slack_context: dict) -> str:
        """
        Process a new account request from a Slack form submission.

        Args:
            form_data:     Parsed Slack modal submission values
            slack_context: {channel_id, user_id, user_email, thread_ts}

        Returns:
            Final text response to surface to the user.
        """
        prompt = _build_new_request_prompt(form_data, slack_context)
        return self._run(prompt)

    def handle_approval_decision(self, record_id: int, approved: bool,
                                  approver_slack_id: str, reason: str = "") -> str:
        """Called when an approver clicks Approve or Reject in Slack."""
        decision = "APPROVED" if approved else "REJECTED"
        prompt = (
            f"The approver <@{approver_slack_id}> has {decision} request record #{record_id}. "
            + (f"Rejection reason: {reason}" if not approved else "")
            + "\n\nPlease update the Kintone record and continue the workflow accordingly."
        )
        return self._run(prompt)

    def handle_docusign_webhook(self, envelope_id: str, new_status: str) -> str:
        """Called when DocuSign sends a status update webhook."""
        prompt = (
            f"DocuSign envelope {envelope_id} status changed to '{new_status}'. "
            "Look up the associated Kintone record, update its DocuSign status, "
            "and proceed with the next workflow step."
        )
        return self._run(prompt)

    def check_expiring_contracts(self, days_ahead: int = 30) -> str:
        """Scheduled job: find contracts expiring soon and send reminders. Run daily."""
        prompt = (
            f"Check for all active contractor engagements expiring within "
            f"the next {days_ahead} days. "
            "For each, send a Slack reminder to the internal sponsor. "
            "For engagements ending today or already past their end date, "
            "trigger the offboarding workflow immediately."
        )
        return self._run(prompt)

    def offboard_by_record(self, record_id: int, reason: str = "END_OF_ENGAGEMENT") -> str:
        """Manually trigger offboarding for a specific record."""
        prompt = (
            f"Please offboard the contractor in Kintone record #{record_id}. "
            f"Reason: {reason}. "
            "Revoke all system access and update Kintone and Slack accordingly."
        )
        return self._run(prompt)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self, user_prompt: str) -> str:
        """Core agentic loop: keep calling Claude until stop_reason is 'end_turn'."""
        messages = [{"role": "user", "content": user_prompt}]

        while True:
            with self.client.messages.stream(
                model=MODEL,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            ) as stream:
                response = stream.get_final_message()

            logger.debug("Claude stop_reason=%s", response.stop_reason)
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if block.type == "text":
                        return block.text
                return ""

            if response.stop_reason != "tool_use":
                logger.warning("Unexpected stop_reason: %s", response.stop_reason)
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                logger.info("Tool call: %s  input=%s", block.name, json.dumps(block.input))
                try:
                    result = self.tool_executor(block.name, block.input)
                except Exception as exc:
                    logger.exception("Tool %s raised an exception", block.name)
                    result = {"error": str(exc), "tool": block.name}
                logger.info("Tool result: %s", json.dumps(result))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })

            messages.append({"role": "user", "content": tool_results})

        return "An unexpected error occurred in the agent loop."


def _build_new_request_prompt(form_data: dict, slack_context: dict) -> str:
    return f"""A new account request has been submitted via Slack.

## Form Data
{json.dumps(form_data, ensure_ascii=False, indent=2)}

## Slack Context
- Submitted by (Slack user ID): {slack_context.get('user_id')}
- Submitter email: {slack_context.get('user_email')}
- Channel ID: {slack_context.get('channel_id')}
- Thread timestamp: {slack_context.get('thread_ts')}

## Instructions
1. Validate the form data. If anything critical is missing, ask the submitter
   via Slack (in-thread) before proceeding.
2. Create a Kintone record to track this request.
3. Send an approval request to the IT admin approval channel.
4. Reply in the Slack thread to confirm the request was received and is pending approval.
"""
