"""Settings API routes for dashboard configuration."""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from .notifier import SlackNotifier, SlackNotifierConfigError
from .settings_store import (
    WHITELISTED_KEYS,
    mask_secret,
    merge_settings,
    put_setting,
)


class PutSettingsRequest(BaseModel):
    """Request model for PUT /api/settings."""
    updates: Dict[str, Any]
    updated_by: Optional[str] = None


class ErrorDetail(BaseModel):
    """Error detail for validation failures."""
    key: str
    detail: str


class PutSettingsResponse(BaseModel):
    """Response model for PUT /api/settings."""
    settings: Dict[str, Dict[str, Any]]
    errors: Optional[List[ErrorDetail]] = None


def validate_setting_value(key: str, value: Any) -> Optional[str]:
    """Validate a setting value against type and range constraints.

    Args:
        key: Setting key
        value: Setting value to validate

    Returns:
        Error message if invalid, None if valid
    """
    if key == "slack_enabled" or key == "trigger_enabled":
        if not isinstance(value, bool):
            return f"must be boolean, got {type(value).__name__}"

    elif key == "slack_webhook_url":
        if value and not isinstance(value, str):
            return f"must be string, got {type(value).__name__}"
        if value and not (value.startswith("https://") or value.startswith("http://")):
            return "must be valid https URL or empty"

    elif key == "slack_bot_token":
        if value and not isinstance(value, str):
            return f"must be string, got {type(value).__name__}"
        if value and not value.startswith("xoxb-"):
            return "must start with 'xoxb-' or be empty"

    elif key == "slack_channel_id":
        if value and not isinstance(value, str):
            return f"must be string, got {type(value).__name__}"
        if value and not re.match(r'^[CG][A-Z0-9]+$', value):
            return "must match ^[CG][A-Z0-9]+$ or be empty"

    elif key == "trigger_secret":
        if value and not isinstance(value, str):
            return f"must be string, got {type(value).__name__}"
        if value and len(value) < 16:
            return "must be at least 16 characters or empty"

    elif key == "trigger_rate_limit_per_min":
        if not isinstance(value, int):
            return f"must be integer, got {type(value).__name__}"
        if value < 1 or value > 1000:
            return "must be between 1 and 1000"

    elif key == "max_sse_connections":
        if not isinstance(value, int):
            return f"must be integer, got {type(value).__name__}"
        if value < 1 or value > 500:
            return "must be between 1 and 500"

    elif key == "dashboard_url":
        if not isinstance(value, str):
            return f"must be string, got {type(value).__name__}"
        if not (value.startswith("https://") or value.startswith("http://")):
            return "must be valid http/https URL"

    elif key == "workflows_dir":
        if not isinstance(value, str):
            return f"must be string, got {type(value).__name__}"
        if not value:
            return "must be non-empty path string"

    return None


def create_settings_router(settings: Any, db_path: Path) -> APIRouter:
    """Create settings API router.

    Args:
        settings: Dashboard Settings instance
        db_path: Path to SQLite database

    Returns:
        FastAPI router with settings endpoints
    """
    router = APIRouter()

    @router.get("/api/settings")
    async def get_settings() -> Dict[str, Any]:
        """Get merged settings with secrets masked.

        Returns merged view: env → db → defaults.
        Secrets are masked in the response.
        """
        merged = merge_settings(settings, db_path)

        # Mask secrets in the response
        result = {}
        for key, setting in merged.items():
            value = setting["value"]
            if setting["is_secret"] and value:
                value = mask_secret(value)

            result[key] = {
                "value": value,
                "source": setting["source"],
                "is_secret": setting["is_secret"],
            }

        return {"settings": result}

    @router.put("/api/settings")
    async def put_settings(request: PutSettingsRequest) -> Dict[str, Any]:
        """Update settings via database overrides.

        Validates all keys, runs cross-field validation, and applies changes
        atomically. On success, reloads app.state.settings.

        Returns:
            200 with masked settings on success
            400 with error details on validation failure
        """
        errors: List[ErrorDetail] = []

        # Validate all keys are whitelisted
        for key in request.updates.keys():
            if key not in WHITELISTED_KEYS:
                errors.append(ErrorDetail(
                    key=key,
                    detail=f"Unknown setting key: {key}"
                ))

        if errors:
            raise HTTPException(status_code=400, detail={"errors": [e.model_dump() for e in errors]})

        # Validate each value
        for key, value in request.updates.items():
            error = validate_setting_value(key, value)
            if error:
                errors.append(ErrorDetail(key=key, detail=error))

        if errors:
            raise HTTPException(status_code=400, detail={"errors": [e.model_dump() for e in errors]})

        # Build candidate settings for cross-field validation
        # Start with current merged values
        current = merge_settings(settings, db_path)

        # Apply updates
        candidate_values = {}
        for key in WHITELISTED_KEYS:
            if key in request.updates:
                candidate_values[key] = request.updates[key]
            else:
                candidate_values[key] = current[key]["value"]

        # Convert workflows_dir string to Path for Settings validation
        if "workflows_dir" in candidate_values and isinstance(candidate_values["workflows_dir"], str):
            candidate_values["workflows_dir"] = Path(candidate_values["workflows_dir"])

        # Try to construct a Settings instance with the candidate values
        # This will run the Slack coherency validator
        from .config import Settings as SettingsClass
        try:
            SettingsClass(**candidate_values)
        except ValidationError as e:
            for error_dict in e.errors():
                loc = error_dict.get("loc", ())
                field = loc[0] if loc else "unknown"
                errors.append(ErrorDetail(
                    key=str(field),
                    detail=error_dict.get("msg", "Validation failed")
                ))
            raise HTTPException(status_code=400, detail={"errors": [err.model_dump() for err in errors]})

        # All validations passed - write to database
        for key, value in request.updates.items():
            put_setting(db_path, key, value, updated_by=request.updated_by)

        # Reload settings in-memory
        settings.reload_from_db(db_path)

        # Return masked merged settings
        merged = merge_settings(settings, db_path)
        result = {}
        for key, setting in merged.items():
            value = setting["value"]
            if setting["is_secret"] and value:
                value = mask_secret(value)

            result[key] = {
                "value": value,
                "source": setting["source"],
                "is_secret": setting["is_secret"],
            }

        return {"settings": result}

    @router.post("/api/settings/slack/test")
    async def test_slack_notification() -> Dict[str, Any]:
        """Send a test Slack notification using the current merged settings.

        Does NOT modify stored settings. Returns ``{ok: bool, error: str|None}``.
        Uses the same ``SlackNotifier`` that runtime notifications use, so if
        this endpoint succeeds, real notifications will too.
        """
        merged = merge_settings(settings, db_path)

        def _val(key: str) -> Any:
            entry = merged.get(key, {})
            return entry.get("value") if isinstance(entry, dict) else None

        if not _val("slack_enabled"):
            return {"ok": False, "error": "Slack notifications are not enabled"}

        webhook = _val("slack_webhook_url") or None
        bot_token = _val("slack_bot_token") or None
        channel_id = _val("slack_channel_id") or None

        if not webhook and not bot_token:
            return {"ok": False, "error": "No Slack webhook or bot token configured"}

        card: Dict[str, Any] = {
            "text": "DAG Dashboard test notification",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "DAG Dashboard test notification"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "This is a test message sent from the dashboard "
                            "Settings page. If you can see it, your Slack "
                            "configuration is working."
                        ),
                    },
                },
            ],
        }

        try:
            notifier = SlackNotifier(
                db_path=db_path,
                webhook_url=webhook,
                bot_token=bot_token,
                channel_id=channel_id,
            )
        except SlackNotifierConfigError as exc:
            return {"ok": False, "error": str(exc)}

        try:
            notifier.notify("settings-test", "settings_test", card)
        except Exception as exc:  # pragma: no cover - defensive
            return {"ok": False, "error": str(exc)}

        return {"ok": True, "error": None}

    return router
