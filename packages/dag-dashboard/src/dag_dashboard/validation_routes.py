"""API routes for workflow validation."""
from pathlib import Path
from typing import List

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError as PydanticValidationError

from dag_executor.parser import load_workflow_from_string
from dag_executor.validator import WorkflowValidator

from .models import ValidateRequest, ValidateResponse, ValidationIssueOut

router = APIRouter(prefix="/api/workflows", tags=["validation"])


def _primary_workflows_dir(workflows_dirs: List[Path]) -> Path:
    """Get the primary (first) workflows directory.
    
    Returns:
        First workflows_dir
        
    Raises:
        HTTPException: If workflows_dirs list is empty
    """
    if not workflows_dirs:
        raise HTTPException(
            status_code=500,
            detail="No workflows directories configured"
        )
    return workflows_dirs[0]


@router.post("/validate", response_model=ValidateResponse)
async def validate_workflow(request: Request, body: ValidateRequest) -> ValidateResponse:
    """Validate a workflow definition YAML.
    
    Parses YAML, runs WorkflowValidator, returns errors and warnings.
    Catches YAML parse errors and Pydantic schema validation errors.
    
    Args:
        request: FastAPI request (provides app.state.workflows_dirs)
        body: ValidateRequest with yaml string
        
    Returns:
        ValidateResponse with errors and warnings lists
    """
    errors: list[ValidationIssueOut] = []
    warnings: list[ValidationIssueOut] = []
    
    # Parse YAML
    try:
        workflow_def = load_workflow_from_string(body.yaml)
    except yaml.YAMLError as e:
        errors.append(ValidationIssueOut(
            severity="error",
            node_id=None,
            code="yaml_error",
            message=f"YAML parsing failed: {str(e)}"
        ))
        return ValidateResponse(errors=errors, warnings=warnings)
    except PydanticValidationError as e:
        # Schema validation failed (missing required fields, wrong types, etc.)
        errors.append(ValidationIssueOut(
            severity="error",
            node_id=None,
            code="schema_error",
            message=f"Schema validation failed: {str(e)}"
        ))
        return ValidateResponse(errors=errors, warnings=warnings)
    except Exception as e:
        # Other parsing errors
        errors.append(ValidationIssueOut(
            severity="error",
            node_id=None,
            code="parse_error",
            message=f"Failed to parse workflow: {str(e)}"
        ))
        return ValidateResponse(errors=errors, warnings=warnings)
    
    # Get workflows directory for validator context
    workflows_dirs: List[Path] = request.app.state.workflows_dirs
    workflows_dir = _primary_workflows_dir(workflows_dirs)
    
    # Run WorkflowValidator
    validator = WorkflowValidator(workflows_dir=workflows_dir)
    result = validator.validate(workflow_def)
    
    # Convert ValidationIssue to ValidationIssueOut
    for issue in result.errors:
        errors.append(ValidationIssueOut(
            severity=issue.severity,
            node_id=issue.node_id,
            code=issue.code,
            message=issue.message
        ))
    
    for issue in result.warnings:
        warnings.append(ValidationIssueOut(
            severity=issue.severity,
            node_id=issue.node_id,
            code=issue.code,
            message=issue.message
        ))
    
    return ValidateResponse(errors=errors, warnings=warnings)
