"""
Claude tool definitions for the Account Request orchestration agent.

Each tool corresponds to one action the agent can take. The agent decides
which tools to call and in what order based on the request context.

Design principles:
- Tools are narrow and specific (one action per tool)
- Write operations require a prior human approval gate
- All tools return structured JSON so the agent can reason about results
"""

TOOL_DEFINITIONS = [

    # ── Kintone ───────────────────────────────────────────────────────────────

    {
        "name": "kintone_create_request_record",
        "description": (
            "Create a new account request record in Kintone. "
            "Call this immediately after a Slack form submission to persist the request "
            "and obtain a record ID for all subsequent tracking. "
            "Returns the new record ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contractor_full_name":  {"type": "string", "description": "Full name of the contractor"},
                "contractor_name_kana":  {"type": "string", "description": "Name in katakana (optional)"},
                "contractor_email":      {"type": "string", "description": "Contractor's personal email address"},
                "contractor_company":    {"type": "string", "description": "Contractor's company or organization"},
                "contractor_type": {
                    "type": "string",
                    "enum": ["EXTERNAL_ADVISOR", "ENGINEERING_OUTSOURCER", "BUSINESS_OUTSOURCER", "VENDOR", "TEMP_STAFF"],
                    "description": "Category of contractor"
                },
                "internal_sponsor_email": {"type": "string", "description": "Email of the internal employee sponsoring this request"},
                "department":            {"type": "string", "description": "Sponsoring department"},
                "project_name":          {"type": "string", "description": "Name of the project or engagement"},
                "purpose":               {"type": "string", "description": "Business justification for access"},
                "engagement_start_date": {"type": "string", "description": "ISO 8601 date, e.g. 2024-04-01"},
                "engagement_end_date":   {"type": "string", "description": "ISO 8601 date, e.g. 2024-09-30"},
                "systems_requested": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of system keys, e.g. [\"GOOGLE_WORKSPACE_EMAIL\", \"GCP_PROJECT_ACCESS\"]"
                },
                "gcp_projects":    {"type": "string", "description": "Comma-separated GCP project IDs (if applicable)"},
                "gcp_role":        {"type": "string", "description": "GCP IAM role level"},
                "slack_channels":  {"type": "string", "description": "Comma-separated Slack channel names"},
                "kintone_apps":    {"type": "string", "description": "Kintone apps/spaces to grant access"},
                "github_teams":    {"type": "string", "description": "GitHub teams or repos"},
                "agreement_type": {
                    "type": "string",
                    "enum": ["NDA", "NDA_AND_CONTRACT", "EXISTING", "NONE"]
                },
                "slack_thread_ts":  {"type": "string", "description": "Slack thread timestamp for updates"},
                "slack_channel_id": {"type": "string", "description": "Slack channel ID where request was submitted"},
                "notes":            {"type": "string", "description": "Additional notes"}
            },
            "required": [
                "contractor_full_name", "contractor_email", "contractor_type",
                "internal_sponsor_email", "department", "project_name", "purpose",
                "engagement_start_date", "engagement_end_date", "systems_requested",
                "agreement_type"
            ]
        }
    },

    {
        "name": "kintone_update_request_status",
        "description": (
            "Update the status and/or fields of an existing Kintone request record. "
            "Use this to reflect every state transition: approved, signed, provisioned, active, rejected, offboarded. "
            "Always update Kintone before sending Slack notifications."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id": {"type": "integer", "description": "Kintone record ID"},
                "status": {
                    "type": "string",
                    "enum": ["PENDING_APPROVAL", "APPROVED", "PENDING_SIGNATURE", "SIGNED",
                             "PROVISIONING", "ACTIVE", "SUSPENDED", "OFFBOARDED", "REJECTED"],
                    "description": "New status value"
                },
                "approver_email":        {"type": "string", "description": "Email of approver (set when approving/rejecting)"},
                "rejection_reason":      {"type": "string", "description": "Reason for rejection or suspension"},
                "docusign_envelope_id":  {"type": "string", "description": "DocuSign envelope ID (set after sending)"},
                "docusign_status":       {"type": "string", "description": "DocuSign envelope status"},
                "docusign_signed_at":    {"type": "string", "description": "ISO 8601 datetime when signed"},
                "provisioned_email":     {"type": "string", "description": "The @yourcompany.com email provisioned"},
                "provisioned_systems":   {"type": "string", "description": "Log of provisioned accounts, one per line"},
                "notes":                 {"type": "string", "description": "Append-only notes entry"}
            },
            "required": ["record_id", "status"]
        }
    },

    {
        "name": "kintone_get_request",
        "description": "Retrieve a full account request record from Kintone by record ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id": {"type": "integer", "description": "Kintone record ID"}
            },
            "required": ["record_id"]
        }
    },

    {
        "name": "kintone_list_expiring_requests",
        "description": (
            "List all ACTIVE requests with an engagement_end_date within the next N days. "
            "Use for proactive expiry reminders and offboarding scheduling."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "description": "Look ahead window in days (default: 30)", "default": 30}
            },
            "required": []
        }
    },

    # ── Approval gate ─────────────────────────────────────────────────────────

    {
        "name": "request_human_approval",
        "description": (
            "Send an approval request to the designated approver via Slack and PAUSE the workflow "
            "until a human explicitly approves or rejects. "
            "ALWAYS call this before any write operations (DocuSign, provisioning). "
            "Returns: {approved: bool, approver_slack_id: str, reason: str|null}"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id":         {"type": "integer",  "description": "Kintone record ID for this request"},
                "approver_channel":  {"type": "string",   "description": "Slack channel or user ID to send approval to"},
                "request_summary":   {"type": "string",   "description": "One-paragraph summary for the approver"},
                "urgency": {
                    "type": "string",
                    "enum": ["NORMAL", "URGENT"],
                    "description": "Flag URGENT only if engagement start is within 48 hours",
                    "default": "NORMAL"
                }
            },
            "required": ["record_id", "approver_channel", "request_summary"]
        }
    },

    # ── DocuSign ──────────────────────────────────────────────────────────────

    {
        "name": "docusign_send_agreement",
        "description": (
            "Send the appropriate agreement (NDA and/or contractor agreement) to the contractor "
            "via DocuSign eSignature. Only call this AFTER human approval has been received. "
            "Returns the envelope ID and a signing URL to share with the contractor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id":            {"type": "integer", "description": "Kintone record ID (for tracking)"},
                "contractor_name":      {"type": "string",  "description": "Contractor's full name"},
                "contractor_email":     {"type": "string",  "description": "Contractor's email address"},
                "agreement_type": {
                    "type": "string",
                    "enum": ["NDA", "NDA_AND_CONTRACT"],
                    "description": "Which agreement template(s) to send"
                },
                "company_signatory_email": {
                    "type": "string",
                    "description": "Company-side signatory email (if counter-signature needed)"
                },
                "expiry_date":          {"type": "string", "description": "ISO 8601 date — DocuSign envelope expiry"},
                "custom_fields":        {
                    "type": "object",
                    "description": "Optional template fields to pre-fill, e.g. {project_name: '...', start_date: '...'}"
                }
            },
            "required": ["record_id", "contractor_name", "contractor_email", "agreement_type"]
        }
    },

    {
        "name": "docusign_check_status",
        "description": (
            "Check the current status of a DocuSign envelope. "
            "Returns: {status: str, signed_at: str|null, declined_reason: str|null}"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "envelope_id": {"type": "string", "description": "DocuSign envelope ID"}
            },
            "required": ["envelope_id"]
        }
    },

    # ── Google Workspace ──────────────────────────────────────────────────────

    {
        "name": "google_workspace_create_account",
        "description": (
            "Create a Google Workspace user account (company email) for the contractor. "
            "Only call this AFTER the agreement is signed. "
            "Returns: {email: str, temp_password: str, user_id: str}"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id":       {"type": "integer", "description": "Kintone record ID (for audit trail)"},
                "first_name":      {"type": "string"},
                "last_name":       {"type": "string"},
                "suggested_email": {"type": "string", "description": "Proposed email, e.g. taro.yamada@yourcompany.com"},
                "department":      {"type": "string"},
                "job_title":       {"type": "string", "description": "e.g. 'External Advisor' or 'Engineering Contractor'"},
                "engagement_end_date": {"type": "string", "description": "ISO 8601 — used to set account expiry"}
            },
            "required": ["record_id", "first_name", "last_name", "suggested_email", "engagement_end_date"]
        }
    },

    {
        "name": "google_workspace_suspend_account",
        "description": "Suspend a Google Workspace account (e.g., on offboarding or suspension).",
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id":   {"type": "integer"},
                "user_email":  {"type": "string", "description": "The @yourcompany.com email to suspend"},
                "reason":      {"type": "string"}
            },
            "required": ["record_id", "user_email", "reason"]
        }
    },

    # ── GCP IAM ───────────────────────────────────────────────────────────────

    {
        "name": "gcp_grant_project_access",
        "description": (
            "Grant IAM role(s) to a user on one or more GCP projects. "
            "Only call AFTER the agreement is signed. "
            "Never grants roles/editor or roles/owner without allow_editor_override=true. "
            "Returns a list of {project_id, role, status} per project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id":    {"type": "integer"},
                "user_email":   {"type": "string", "description": "The user's Google account email"},
                "project_ids":  {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of GCP project IDs"
                },
                "role": {
                    "type": "string",
                    "description": "IAM role to grant, e.g. roles/viewer, roles/bigquery.dataViewer"
                },
                "allow_editor_override": {
                    "type": "boolean",
                    "description": "Set true only if editor/owner access was explicitly approved",
                    "default": false
                }
            },
            "required": ["record_id", "user_email", "project_ids", "role"]
        }
    },

    {
        "name": "gcp_revoke_project_access",
        "description": "Revoke a user's IAM bindings from one or more GCP projects.",
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id":   {"type": "integer"},
                "user_email":  {"type": "string"},
                "project_ids": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["record_id", "user_email", "project_ids"]
        }
    },

    # ── Slack ─────────────────────────────────────────────────────────────────

    {
        "name": "slack_add_user_to_channels",
        "description": "Invite a user to one or more Slack channels by their email address.",
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id":    {"type": "integer"},
                "user_email":   {"type": "string"},
                "channel_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Channel names without #, e.g. ['engineering', 'project-alpha']"
                }
            },
            "required": ["record_id", "user_email", "channel_names"]
        }
    },

    {
        "name": "slack_send_notification",
        "description": (
            "Send a Slack message to a channel or user. "
            "Use for status updates, welcome messages to the contractor, and offboarding notices."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "channel":     {"type": "string", "description": "Channel ID or user ID"},
                "message":     {"type": "string", "description": "Plain text message body"},
                "thread_ts":   {"type": "string", "description": "Thread timestamp to reply in-thread (optional)"},
                "blocks":      {"type": "array",  "description": "Optional Block Kit blocks for rich formatting"}
            },
            "required": ["channel", "message"]
        }
    },

    # ── GitHub ────────────────────────────────────────────────────────────────

    {
        "name": "github_add_to_teams",
        "description": "Add a user to GitHub organization teams by their GitHub username.",
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id":       {"type": "integer"},
                "github_username": {"type": "string"},
                "teams": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Team slugs, e.g. ['engineering', 'project-alpha-readonly']"
                },
                "role": {
                    "type": "string",
                    "enum": ["member", "maintainer"],
                    "default": "member"
                }
            },
            "required": ["record_id", "github_username", "teams"]
        }
    },

    {
        "name": "github_remove_from_teams",
        "description": "Remove a user from all or specific GitHub organization teams.",
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id":       {"type": "integer"},
                "github_username": {"type": "string"},
                "teams":           {"type": "array", "items": {"type": "string"}, "description": "Leave empty to remove from all teams"}
            },
            "required": ["record_id", "github_username"]
        }
    },

    # ── Offboarding ───────────────────────────────────────────────────────────

    {
        "name": "offboard_contractor",
        "description": (
            "Orchestration helper: revoke all system access for a contractor. "
            "Calls individual revocation tools for each system listed in the Kintone record. "
            "Use for scheduled offboarding or immediate deactivation. "
            "Returns a summary of what was revoked."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id": {"type": "integer", "description": "Kintone record ID"},
                "reason": {
                    "type": "string",
                    "enum": ["END_OF_ENGAGEMENT", "EARLY_TERMINATION", "POLICY_VIOLATION", "OTHER"],
                    "default": "END_OF_ENGAGEMENT"
                },
                "notes": {"type": "string", "description": "Additional context for the audit log"}
            },
            "required": ["record_id", "reason"]
        }
    }
]
