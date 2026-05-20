"""Gate runner for conditional evaluation nodes."""
import re
from typing import Any, Dict

from simpleeval import SimpleEval, NameNotDefined  # type: ignore[import-untyped]

from dag_executor.schema import NodeResult, NodeStatus
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner


# GW-6041: condition strings carry `$name` references intended as
# SimpleEval name lookups, not string-interpolation targets. The
# executor's resolve_variables would otherwise inline string values
# directly into the expression text — turning `$issue_type == "Bug"`
# (where issue_type="Task") into `Task == "Bug"` and surfacing as
# `NameNotDefined: 'Task' is not defined`. We strip the `$` here and
# bind names via SimpleEval's name-lookup so types are preserved.
_DOLLAR_REF = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}|\$([a-zA-Z_][a-zA-Z0-9_]*)")


def _normalize_dollar_refs(condition: str) -> str:
    """Strip `$` / `${}` from variable references so SimpleEval treats them as names."""
    def _repl(m: "re.Match[str]") -> str:
        return m.group(1) or m.group(2)
    return _DOLLAR_REF.sub(_repl, condition)


@register_runner("gate")
class GateRunner(BaseRunner):
    """Runner for gate/condition evaluation nodes.

    Uses simpleeval for safe expression evaluation with no arbitrary code execution.
    """

    def run(self, ctx: RunnerContext) -> NodeResult:
        """Evaluate a gate condition.

        Args:
            ctx: Runner execution context

        Returns:
            NodeResult with COMPLETED if condition is truthy, FAILED if falsy
        """
        # Always start from the raw author-written condition. Pre-fix the
        # executor would interpolate `$name` references into the string; that
        # path is the bug GW-6041 — string values land as bare identifiers
        # which SimpleEval flags as NameNotDefined, and dict values trip its
        # "Sorry, Dict is not available" guard. We resolve refs ourselves via
        # SimpleEval's names dict so types survive.
        raw_condition = ctx.node_def.condition or ""
        # Tolerate the legacy resolved-inputs path: if the executor still set
        # `resolved_inputs["condition"]`, use the raw node_def value if it
        # contains `$` refs (more accurate); else fall back to the resolved
        # one for direct-construction test paths.
        if "$" not in raw_condition:
            legacy = ctx.resolved_inputs.get("condition") if ctx.resolved_inputs else None
            if isinstance(legacy, str) and legacy:
                raw_condition = legacy

        condition = _normalize_dollar_refs(raw_condition)

        try:
            # Create safe evaluator with restricted features
            evaluator = SimpleEval()

            # Build name bindings from every plausible source: caller-provided
            # resolved_inputs (preserves the existing direct-construction test
            # surface), upstream node outputs, workflow inputs, and channel
            # state. Channel store wins over node_outputs which wins over
            # workflow_inputs (most recent layer first).
            names: Dict[str, Any] = {}
            if ctx.workflow_inputs:
                names.update(ctx.workflow_inputs)
            if ctx.node_outputs:
                # node_outputs is keyed by node_id; flatten one level so the
                # condition author can write `$some_node_output_field` for
                # outputs the upstream node placed at the top level. Nested
                # node references (`$node.field`) aren't supported here —
                # gate conditions read channel state, which is the modern
                # path. Top-level flattening matches the existing call sites
                # in test_gate.
                for output_dict in ctx.node_outputs.values():
                    if isinstance(output_dict, dict):
                        names.update(output_dict)
            if ctx.channel_store is not None:
                # Pull every channel referenced in the raw condition. Reading
                # the whole store would be wasteful; the regex pre-walk gives
                # us exactly the names we need.
                for m in _DOLLAR_REF.finditer(raw_condition):
                    name = m.group(1) or m.group(2)
                    try:
                        value, _version = ctx.channel_store.read(name)
                        names[name] = value
                    except KeyError:
                        # Leave unbound; SimpleEval will raise NameNotDefined
                        # which we surface as the existing "Undefined variable"
                        # error (test_gate_dollar_ref_undefined_surfaces_clean_error).
                        pass
            # Direct-construction surface: caller-supplied resolved_inputs
            # still wins for test ergonomics. Drop "condition" since it's the
            # expression itself, not a name binding.
            for k, v in (ctx.resolved_inputs or {}).items():
                if k != "condition":
                    names[k] = v

            # JSON/YAML-style lowercase boolean + null aliases so authors can
            # write `$x == false` or `$x == null` naturally (matching the
            # JSON the LLM emits).
            names.setdefault("true", True)
            names.setdefault("false", False)
            names.setdefault("null", None)
            evaluator.names = names

            # Explicitly disable dangerous functions
            evaluator.functions = {}  # No function calls allowed

            # Evaluate condition
            result = evaluator.eval(condition)

            # Return status based on truthiness
            if result:
                return NodeResult(
                    status=NodeStatus.COMPLETED,
                    output={"condition": condition, "result": result}
                )
            else:
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=f"Gate condition evaluated to false: {condition}",
                    output={"condition": condition, "result": result}
                )

        except NameNotDefined as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Undefined variable in condition: {str(e)}"
            )
        except Exception as e:
            # Catch any evaluation errors (including security violations)
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Gate condition evaluation failed: {str(e)}"
            )
