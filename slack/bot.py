"""
Slack Bolt application entry point for the Account Request bot.

Handles:
  /request-access    -> opens the intake modal
  modal submission   -> triggers the orchestration agent
  button clicks      -> approve / reject actions
"""

import logging
import os

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .modals import account_request_modal, rejection_reason_modal
from .handlers import (
    handle_form_submission,
    handle_approve_click,
    handle_rejection_reason_submit,
)

logger = logging.getLogger(__name__)

app = App(token=os.environ["SLACK_BOT_TOKEN"])


@app.command("/request-access")
def open_request_modal(ack, body, client):
    """Open the account request intake modal."""
    ack()
    client.views_open(**account_request_modal(body["trigger_id"]))


@app.view("account_request_submit")
def on_form_submit(ack, body, client, logger):
    ack()
    handle_form_submission(body, client, logger)


@app.action("approve_request")
def on_approve(ack, body, client, logger):
    ack()
    handle_approve_click(body, client, logger)


@app.action("reject_request")
def on_reject(ack, body, client, logger):
    ack()
    record_id = int(body["actions"][0]["value"])
    client.views_open(**rejection_reason_modal(body["trigger_id"], record_id))


@app.view("rejection_submit")
def on_rejection_reason(ack, body, client, logger):
    ack()
    handle_rejection_reason_submit(body, client, logger)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
