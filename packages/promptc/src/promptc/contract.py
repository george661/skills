"""Output contract parsing — parse_output() with JSON-first + line-scan fallback.

Error code vocabulary:
- required_missing: Required field missing from response
- type_mismatch: Value cannot be coerced to declared type
- enum_invalid: Value not in declared enum values
- contract_error: Contract definition issue (e.g., type=enum without values)
- pattern_mismatch: String value doesn't match declared regex pattern
- regex_timeout: Pattern validation exceeded timeout (ReDoS protection per PRP-PLAT-011)
- expression_error: required_when expression failed to evaluate (becomes warning)
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Optional

from .config import ParserConfig
from .expression import ExpressionError
from .expression import evaluate as evaluate_expression
from .schema import ContractParseResult, OutputDecl, ParseErrorInfo


def _regex_fullmatch_with_timeout(
    pattern: str, value: str, timeout_ms: int
) -> bool:
    """Execute regex fullmatch with timeout protection against ReDoS.

    Args:
        pattern: Regex pattern string
        value: String to match against
        timeout_ms: Timeout in milliseconds

    Returns:
        True if pattern matches value, False otherwise

    Raises:
        TimeoutError: If match exceeds configured timeout
    """
    compiled = re.compile(pattern)

    def do_match() -> Optional[re.Match[str]]:
        return compiled.fullmatch(value)

    timeout_seconds = timeout_ms / 1000.0
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(do_match)
        try:
            match = future.result(timeout=timeout_seconds)
            return match is not None
        except FuturesTimeoutError:
            raise TimeoutError(
                f"Regex fullmatch exceeded {timeout_ms}ms timeout"
            )


def parse_output(
    text: str,
    contract: list[OutputDecl],
    *,
    config: Optional[ParserConfig] = None,
) -> ContractParseResult:
    """Parse assistant response against output contract.

    Algorithm:
    1. JSON-first: find fenced JSON blocks that cover the contract
    2. Line-scan fallback: regex match FIELDNAME: value patterns
    3. Type coercion and validation
    4. required_when evaluation
    5. Return ContractParseResult (never raises)

    Args:
        text: Raw assistant response
        contract: List of OutputDecl defining expected fields
        config: Parser configuration (optional)

    Returns:
        ContractParseResult with fields, errors, warnings, raw, strategy
    """
    if config is None:
        config = ParserConfig()

    fields: dict[str, Any] = {}
    errors: list[ParseErrorInfo] = []
    warnings: list[str] = []
    strategy: str = "none"

    try:
        # Phase 1: JSON-first strategy
        json_result = _try_json_extraction(text, contract, warnings)
        if json_result is not None:
            fields, strategy = json_result, "json"
        else:
            # Phase 2: Line-scan fallback
            fields, strategy = _try_line_scan(text, contract)

        # Phase 3: Type coercion and validation
        fields, coercion_errors = _coerce_and_validate(fields, contract, config)
        errors.extend(coercion_errors)

        # Phase 4: required_when evaluation
        requirement_errors, requirement_warnings = _check_requirements(fields, contract)
        errors.extend(requirement_errors)
        warnings.extend(requirement_warnings)

    except Exception as e:
        # Top-level exception handler — should never happen but ensures no raises
        warnings.append(f"Unexpected error in parse_output: {e}")
        strategy = "none"
        fields = {}

    return ContractParseResult(
        fields=fields,
        errors=errors,
        warnings=warnings,
        raw=text,
        strategy=strategy,  # type: ignore
    )


def _try_json_extraction(
    text: str, contract: list[OutputDecl], warnings: list[str]
) -> Optional[dict[str, Any]]:
    """Try to find a fenced JSON block that covers the contract.

    Returns extracted fields dict if found, None otherwise.
    """
    # Find all fenced code blocks: ```json...``` or ```...```
    # Pattern: ``` optional(json) newline content ```
    fence_pattern = r"```(?:json)?\s*\n(.*?)\n```"
    matches = re.findall(fence_pattern, text, re.DOTALL | re.IGNORECASE)

    required_keys = {decl.name for decl in contract}
    partial_json_found = False

    for block_content in matches:
        try:
            parsed = json.loads(block_content)
            # Type guard: must be dict (per plan review warning)
            if not isinstance(parsed, dict):
                continue

            # Check if it covers the contract
            if required_keys.issubset(parsed.keys()):
                # Emit warnings for unknown keys
                extra_keys = set(parsed.keys()) - required_keys
                for key in extra_keys:
                    warnings.append(f"unknown field in JSON block: {key}")
                return parsed
            else:
                # Partial match — note it but keep looking
                partial_json_found = True
        except json.JSONDecodeError:
            # Malformed JSON — add warning and continue
            warnings.append("malformed JSON block found, skipping")
            continue

    # If we found partial JSON but no covering block, warn and fall back
    if partial_json_found:
        warnings.append("JSON block present but incomplete; fallback to line-scan")

    return None


def _try_line_scan(text: str, contract: list[OutputDecl]) -> tuple[dict[str, Any], str]:
    """Line-scan fallback: match FIELDNAME: value patterns.

    Returns (fields dict, strategy).
    """
    fields: dict[str, Any] = {}

    for decl in contract:
        # Compile regex: ^FIELDNAME:\s*(.+)$ with MULTILINE flag
        pattern = rf"^{re.escape(decl.name)}:\s*(.+)$"
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            # First occurrence wins, capture group is the value
            raw_value = match.group(1).strip()
            fields[decl.name] = raw_value

    strategy = "line-scan" if fields else "none"
    return fields, strategy


def _coerce_and_validate(
    fields: dict[str, Any], contract: list[OutputDecl], config: ParserConfig
) -> tuple[dict[str, Any], list[ParseErrorInfo]]:
    """Type coercion and validation for extracted fields.

    Returns (coerced_fields, errors).
    """
    coerced: dict[str, Any] = {}
    errors: list[ParseErrorInfo] = []

    for decl in contract:
        if decl.name not in fields:
            continue  # Missing field handled in requirements phase

        raw_value = fields[decl.name]

        try:
            coerced_value = _coerce_value(raw_value, decl, config)
            coerced[decl.name] = coerced_value
        except ValueError as e:
            errors.append(
                ParseErrorInfo(
                    code="type_mismatch",
                    message=str(e),
                    field=decl.name,
                )
            )
        except EnumValidationError as e:
            errors.append(
                ParseErrorInfo(
                    code="enum_invalid",
                    message=str(e),
                    field=decl.name,
                )
            )
        except ContractError as e:
            errors.append(
                ParseErrorInfo(
                    code="contract_error",
                    message=str(e),
                    field=decl.name,
                )
            )
        except PatternMismatchError as e:
            errors.append(
                ParseErrorInfo(
                    code="pattern_mismatch",
                    message=str(e),
                    field=decl.name,
                )
            )
        except TimeoutError as e:
            errors.append(
                ParseErrorInfo(
                    code="regex_timeout",
                    message=str(e),
                    field=decl.name,
                )
            )

    return coerced, errors


def _coerce_value(raw: Any, decl: OutputDecl, config: ParserConfig) -> Any:
    """Coerce raw value to declared type and validate.

    Raises ValueError, EnumValidationError, ContractError, or PatternMismatchError on failure.
    """
    typ = decl.type

    if typ == "string":
        value = str(raw) if not isinstance(raw, str) else raw
        # Validate pattern if present (with timeout protection per PRP-PLAT-011)
        if decl.pattern:
            try:
                if not _regex_fullmatch_with_timeout(
                    decl.pattern, value, config.regex_timeout_ms
                ):
                    raise PatternMismatchError(
                        f"Value '{value}' doesn't match pattern {decl.pattern}"
                    )
            except TimeoutError as e:
                raise TimeoutError(f"Pattern validation timeout: {e}")
        return value

    elif typ == "int":
        if isinstance(raw, int):
            return raw
        return int(raw)  # May raise ValueError

    elif typ == "float":
        if isinstance(raw, (int, float)):
            return float(raw)
        return float(raw)  # May raise ValueError

    elif typ == "bool":
        if isinstance(raw, bool):
            return raw
        # Accept string forms
        if isinstance(raw, str):
            lower = raw.lower()
            if lower == "true":
                return True
            elif lower == "false":
                return False
        raise ValueError(f"Cannot coerce '{raw}' to bool")

    elif typ == "list":
        if isinstance(raw, list):
            return raw
        # Line-scan: try to parse as JSON array literal
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Cannot coerce '{raw}' to list")

    elif typ == "object":
        if isinstance(raw, dict):
            return raw
        # Line-scan on object type: intentional symmetry with list behavior
        # Single-line object literals CAN be parsed from line-scan (e.g., "META: {\"version\": 2}")
        # This differs from original plan but provides consistent JSON literal handling
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Cannot coerce '{raw}' to object")

    elif typ == "enum":
        # Validate against declared values
        if decl.values is None:
            raise ContractError("enum type requires 'values' list")
        value = str(raw) if not isinstance(raw, str) else raw
        if value not in decl.values:
            raise EnumValidationError(
                f"Value '{value}' not in allowed enum values: {decl.values}"
            )
        return value

    else:
        raise ValueError(f"Unknown type: {typ}")


def _check_requirements(
    fields: dict[str, Any], contract: list[OutputDecl]
) -> tuple[list[ParseErrorInfo], list[str]]:
    """Check required_when conditions and unconditional requirements.

    Returns (errors, warnings).
    """
    errors: list[ParseErrorInfo] = []
    warnings: list[str] = []

    # Build evaluation namespace: {"outputs": fields} plus top-level aliases
    namespace = {"outputs": fields, **fields}

    for decl in contract:
        is_required = False

        if decl.required_when is not None:
            # Evaluate the expression
            try:
                result = evaluate_expression(decl.required_when, namespace)
                is_required = bool(result)
            except ExpressionError as e:
                # Expression error → warning, treat as not required
                warnings.append(f"required_when expression error for {decl.name}: {e}")
                is_required = False
        else:
            # No required_when → unconditionally required
            is_required = True

        # Check if field is missing and required
        if is_required and decl.name not in fields:
            errors.append(
                ParseErrorInfo(
                    code="required_missing",
                    message=f"Required field '{decl.name}' is missing",
                    field=decl.name,
                )
            )

    return errors, warnings


# Custom exceptions for internal use
class EnumValidationError(Exception):
    pass


class ContractError(Exception):
    pass


class PatternMismatchError(Exception):
    pass
