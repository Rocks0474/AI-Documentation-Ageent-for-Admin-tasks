"""
Slack modal definitions for the Account Request intake form.
Uses Block Kit: https://api.slack.com/block-kit
"""


def account_request_modal(trigger_id: str) -> dict:
    """Main intake modal presented via /request-access slash command."""
    return {
        "trigger_id": trigger_id,
        "view": {
            "type": "modal",
            "callback_id": "account_request_submit",
            "title": {"type": "plain_text", "text": "Request System Access"},
            "submit": {"type": "plain_text", "text": "Submit Request"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": "Contractor Information"}},
                {
                    "type": "input", "block_id": "contractor_full_name",
                    "label": {"type": "plain_text", "text": "Contractor Full Name"},
                    "element": {"type": "plain_text_input", "action_id": "value",
                                "placeholder": {"type": "plain_text", "text": "e.g. Taro Yamada"}}
                },
                {
                    "type": "input", "block_id": "contractor_name_kana", "optional": True,
                    "label": {"type": "plain_text", "text": "Name (フリガナ / Kana)"},
                    "element": {"type": "plain_text_input", "action_id": "value",
                                "placeholder": {"type": "plain_text", "text": "ヤマダ タロウ"}}
                },
                {
                    "type": "input", "block_id": "contractor_email",
                    "label": {"type": "plain_text", "text": "Contractor Personal Email"},
                    "element": {"type": "plain_text_input", "action_id": "value",
                                "placeholder": {"type": "plain_text", "text": "taro@example.com"}}
                },
                {
                    "type": "input", "block_id": "contractor_company", "optional": True,
                    "label": {"type": "plain_text", "text": "Company / Organization"},
                    "element": {"type": "plain_text_input", "action_id": "value"}
                },
                {
                    "type": "input", "block_id": "contractor_type",
                    "label": {"type": "plain_text", "text": "Contractor Type"},
                    "element": {
                        "type": "static_select", "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "Select type..."},
                        "options": [
                            {"text": {"type": "plain_text", "text": "External Advisor"},       "value": "EXTERNAL_ADVISOR"},
                            {"text": {"type": "plain_text", "text": "Engineering Outsourcer"}, "value": "ENGINEERING_OUTSOURCER"},
                            {"text": {"type": "plain_text", "text": "Business Outsourcer"},    "value": "BUSINESS_OUTSOURCER"},
                            {"text": {"type": "plain_text", "text": "Vendor"},                 "value": "VENDOR"},
                            {"text": {"type": "plain_text", "text": "Temporary Staff"},        "value": "TEMP_STAFF"}
                        ]
                    }
                },
                {"type": "divider"},
                {"type": "header", "text": {"type": "plain_text", "text": "Engagement Details"}},
                {
                    "type": "input", "block_id": "project_name",
                    "label": {"type": "plain_text", "text": "Project / Engagement Name"},
                    "element": {"type": "plain_text_input", "action_id": "value",
                                "placeholder": {"type": "plain_text", "text": "e.g. Analytics Platform v2"}}
                },
                {
                    "type": "input", "block_id": "department",
                    "label": {"type": "plain_text", "text": "Your Department"},
                    "element": {
                        "type": "static_select", "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "Select department..."},
                        "options": [
                            {"text": {"type": "plain_text", "text": "Engineering"},  "value": "ENGINEERING"},
                            {"text": {"type": "plain_text", "text": "Product"},      "value": "PRODUCT"},
                            {"text": {"type": "plain_text", "text": "Sales"},        "value": "SALES"},
                            {"text": {"type": "plain_text", "text": "Marketing"},    "value": "MARKETING"},
                            {"text": {"type": "plain_text", "text": "Finance"},      "value": "FINANCE"},
                            {"text": {"type": "plain_text", "text": "HR"},           "value": "HR"},
                            {"text": {"type": "plain_text", "text": "Legal"},        "value": "LEGAL"},
                            {"text": {"type": "plain_text", "text": "Operations"},   "value": "OPERATIONS"}
                        ]
                    }
                },
                {
                    "type": "input", "block_id": "purpose",
                    "label": {"type": "plain_text", "text": "Purpose / Business Justification"},
                    "element": {"type": "plain_text_input", "action_id": "value", "multiline": True,
                                "placeholder": {"type": "plain_text",
                                                "text": "Describe why this contractor needs access and what they will do."}}
                },
                {
                    "type": "input", "block_id": "engagement_start_date",
                    "label": {"type": "plain_text", "text": "Engagement Start Date"},
                    "element": {"type": "datepicker", "action_id": "value",
                                "placeholder": {"type": "plain_text", "text": "Start date"}}
                },
                {
                    "type": "input", "block_id": "engagement_end_date",
                    "label": {"type": "plain_text", "text": "Engagement End Date"},
                    "element": {"type": "datepicker", "action_id": "value",
                                "placeholder": {"type": "plain_text", "text": "End date"}}
                },
                {"type": "divider"},
                {"type": "header", "text": {"type": "plain_text", "text": "Systems & Access Required"}},
                {
                    "type": "input", "block_id": "systems_requested",
                    "label": {"type": "plain_text", "text": "Systems to Grant Access"},
                    "element": {
                        "type": "checkboxes", "action_id": "value",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Google Workspace Email (@yourcompany.com)"}, "value": "GOOGLE_WORKSPACE_EMAIL"},
                            {"text": {"type": "plain_text", "text": "GCP Project Access"},  "value": "GCP_PROJECT_ACCESS"},
                            {"text": {"type": "plain_text", "text": "Slack"},               "value": "SLACK"},
                            {"text": {"type": "plain_text", "text": "Kintone"},             "value": "KINTONE"},
                            {"text": {"type": "plain_text", "text": "GitHub"},              "value": "GITHUB"},
                            {"text": {"type": "plain_text", "text": "Jira"},               "value": "JIRA"},
                            {"text": {"type": "plain_text", "text": "Confluence"},          "value": "CONFLUENCE"},
                            {"text": {"type": "plain_text", "text": "VPN"},                "value": "VPN"},
                            {"text": {"type": "plain_text", "text": "Other (describe in notes)"}, "value": "OTHER"}
                        ]
                    }
                },
                {
                    "type": "input", "block_id": "gcp_projects", "optional": True,
                    "label": {"type": "plain_text", "text": "GCP Project IDs (if applicable)"},
                    "hint": {"type": "plain_text", "text": "Comma-separated, e.g.: my-project-123, analytics-prod"},
                    "element": {"type": "plain_text_input", "action_id": "value"}
                },
                {
                    "type": "input", "block_id": "gcp_role", "optional": True,
                    "label": {"type": "plain_text", "text": "GCP Access Level (if applicable)"},
                    "element": {
                        "type": "static_select", "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "Select role..."},
                        "options": [
                            {"text": {"type": "plain_text", "text": "Viewer (read-only)"},         "value": "VIEWER"},
                            {"text": {"type": "plain_text", "text": "Editor"},                    "value": "EDITOR"},
                            {"text": {"type": "plain_text", "text": "Developer (custom)"},         "value": "DEVELOPER"},
                            {"text": {"type": "plain_text", "text": "Custom (specify in notes)"}, "value": "CUSTOM"}
                        ]
                    }
                },
                {
                    "type": "input", "block_id": "slack_channels", "optional": True,
                    "label": {"type": "plain_text", "text": "Slack Channels to Add"},
                    "hint": {"type": "plain_text", "text": "Comma-separated, e.g.: engineering, project-alpha"},
                    "element": {"type": "plain_text_input", "action_id": "value"}
                },
                {
                    "type": "input", "block_id": "kintone_apps", "optional": True,
                    "label": {"type": "plain_text", "text": "Kintone Apps / Spaces"},
                    "element": {"type": "plain_text_input", "action_id": "value"}
                },
                {
                    "type": "input", "block_id": "github_teams", "optional": True,
                    "label": {"type": "plain_text", "text": "GitHub Teams / Repos"},
                    "element": {"type": "plain_text_input", "action_id": "value"}
                },
                {"type": "divider"},
                {"type": "header", "text": {"type": "plain_text", "text": "Agreement"}},
                {
                    "type": "input", "block_id": "agreement_type",
                    "label": {"type": "plain_text", "text": "Agreement Required"},
                    "element": {
                        "type": "static_select", "action_id": "value",
                        "initial_option": {"text": {"type": "plain_text", "text": "NDA Only"}, "value": "NDA"},
                        "options": [
                            {"text": {"type": "plain_text", "text": "NDA Only"},                   "value": "NDA"},
                            {"text": {"type": "plain_text", "text": "NDA + Contractor Agreement"}, "value": "NDA_AND_CONTRACT"},
                            {"text": {"type": "plain_text", "text": "Existing Agreement on File"}, "value": "EXISTING"},
                            {"text": {"type": "plain_text", "text": "None Required"},               "value": "NONE"}
                        ]
                    }
                },
                {
                    "type": "input", "block_id": "notes", "optional": True,
                    "label": {"type": "plain_text", "text": "Additional Notes"},
                    "element": {"type": "plain_text_input", "action_id": "value", "multiline": True}
                }
            ]
        }
    }


def approval_message(request: dict) -> list:
    """Slack message blocks sent to the approver with Approve / Reject buttons."""
    systems = ", ".join(request.get("systems_requested", []))
    return [
        {"type": "header", "text": {"type": "plain_text", "text": ":bell: New Access Request — Approval Required"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Contractor:*\n{request['contractor_full_name']}"},
                {"type": "mrkdwn", "text": f"*Type:*\n{request['contractor_type'].replace('_', ' ').title()}"},
                {"type": "mrkdwn", "text": f"*Sponsor:*\n<@{request['sponsor_slack_id']}>"},
                {"type": "mrkdwn", "text": f"*Department:*\n{request['department'].title()}"},
                {"type": "mrkdwn", "text": f"*Project:*\n{request['project_name']}"},
                {"type": "mrkdwn", "text": f"*Period:*\n{request['engagement_start_date']} → {request['engagement_end_date']}"}
            ]
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Systems Requested:*\n{systems}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Purpose:*\n{request['purpose']}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Agreement:*\n{request['agreement_type'].replace('_', ' ').title()}"}},
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": f"approval_{request['kintone_record_id']}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":white_check_mark: Approve"},
                    "style": "primary",
                    "action_id": "approve_request",
                    "value": str(request["kintone_record_id"]),
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Approve this request?"},
                        "text": {"type": "mrkdwn", "text": f"This will trigger DocuSign and system provisioning for *{request['contractor_full_name']}*."},
                        "confirm": {"type": "plain_text", "text": "Yes, Approve"},
                        "deny": {"type": "plain_text", "text": "Cancel"}
                    }
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":x: Reject"},
                    "style": "danger",
                    "action_id": "reject_request",
                    "value": str(request["kintone_record_id"])
                }
            ]
        }
    ]


def rejection_reason_modal(trigger_id: str, record_id: int) -> dict:
    """Modal to collect a rejection reason."""
    return {
        "trigger_id": trigger_id,
        "view": {
            "type": "modal",
            "callback_id": "rejection_submit",
            "private_metadata": str(record_id),
            "title": {"type": "plain_text", "text": "Reject Request"},
            "submit": {"type": "plain_text", "text": "Confirm Rejection"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [{
                "type": "input", "block_id": "rejection_reason",
                "label": {"type": "plain_text", "text": "Reason for Rejection"},
                "element": {
                    "type": "plain_text_input", "action_id": "value", "multiline": True,
                    "placeholder": {"type": "plain_text",
                                    "text": "Provide a reason that will be shared with the requester."}
                }
            }]
        }
    }


def status_update_message(contractor_name: str, status: str, detail: str = "") -> list:
    """Generic status update message posted to the request thread."""
    emoji = {
        "APPROVED": ":white_check_mark:", "REJECTED": ":x:",
        "PENDING_SIGNATURE": ":pencil:", "SIGNED": ":memo:",
        "PROVISIONING": ":gear:", "ACTIVE": ":tada:",
        "OFFBOARDED": ":wave:", "SUSPENDED": ":pause_button:"
    }.get(status, ":information_source:")
    label = status.replace("_", " ").title()
    blocks = [{
        "type": "section",
        "text": {"type": "mrkdwn",
                 "text": f"{emoji} *Status Update:* Request for *{contractor_name}* is now *{label}*"}
    }]
    if detail:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": detail}})
    return blocks
