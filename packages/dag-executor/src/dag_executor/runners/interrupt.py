"""Interrupt runner for human-in-the-loop nodes."""
from typing import Optional
from simpleeval import SimpleEval, NameNotDefined  # type: ignore[import-untyped]

from dag_executor.schema import NodeResult, NodeStatus
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner


@register_runner("interrupt")
class InterruptRunner(BaseRunner):
    """Runner for interrupt nodes (human-in-the-loop).
    
    Interrupts workflow execution to request user input or approval.
    If an optional condition is provided, the interrupt only fires if
    the condition evaluates to true. Otherwise it auto-approves (completes).
    """
    
    def run(self, ctx: RunnerContext) -> NodeResult:
        """Execute interrupt node.

        Args:
            ctx: Runner execution context

        Returns:
            NodeResult with INTERRUPTED if condition is true/missing,
            COMPLETED if condition is false (auto-approved) or resumed
        """
        message = ctx.node_def.message
        resume_key = ctx.node_def.resume_key
        channels = ctx.node_def.channels or ["terminal"]

        # Check if already resumed (resume value present in workflow inputs)
        # We only treat this as a resume if the key exists AND has a non-empty value
        # AND it wasn't part of the original workflow inputs (it was injected via resume_values)
        # To detect this, we check if there's an interrupt checkpoint that indicates we're resuming
        # For simplicity, we'll check if the value is a string (resume values are typically strings)
        if resume_key in ctx.workflow_inputs:
            resume_value = ctx.workflow_inputs[resume_key]
            # Only treat as resumed if value is explicitly provided (not None, not False, not empty)
            # and is a non-empty string (typical resume pattern)
            if isinstance(resume_value, str) and resume_value:
                # Resume value provided - complete the node
                return NodeResult(
                    status=NodeStatus.COMPLETED,
                    output={
                        "message": message,
                        "resume_key": resume_key,
                        "resumed": True,
                        "resume_value": resume_value
                    }
                )

        # Check if condition is set
        condition = ctx.node_def.condition

        if condition:
            # Evaluate condition
            should_interrupt = self._evaluate_condition(condition, ctx)

            if not should_interrupt:
                # Auto-approve (condition is false)
                return NodeResult(
                    status=NodeStatus.COMPLETED,
                    output={
                        "message": message,
                        "resume_key": resume_key,
                        "auto_approved": True,
                        "condition": condition
                    }
                )

        # Interrupt workflow
        return NodeResult(
            status=NodeStatus.INTERRUPTED,
            output={
                "message": message,
                "resume_key": resume_key,
                "channels": channels
            }
        )
    
    def _evaluate_condition(self, condition: str, ctx: RunnerContext) -> bool:
        """Evaluate condition expression using simpleeval.

        Args:
            condition: Expression to evaluate
            ctx: Runner context with resolved_inputs

        Returns:
            True if condition is truthy, False otherwise
        """
        try:
            # Create safe evaluator with restricted features
            evaluator = SimpleEval()

            # Set available names from workflow inputs, node outputs, and resolved inputs
            # Start with workflow inputs (where condition variables typically come from)
            names = ctx.workflow_inputs.copy()

            # Add node outputs (for conditions referencing upstream nodes)
            for node_id, output in ctx.node_outputs.items():
                if isinstance(output, dict):
                    for key, value in output.items():
                        names[f"{node_id}.{key}"] = value
                else:
                    names[node_id] = output

            # Add resolved inputs (node-specific resolved values)
            names.update(ctx.resolved_inputs)

            evaluator.names = names

            # Explicitly disable dangerous functions
            evaluator.functions = {}  # No function calls allowed

            # Evaluate condition
            result = evaluator.eval(condition)

            return bool(result)

        except NameNotDefined:
            # If variable not defined, treat as false (auto-approve)
            return False
        except Exception:
            # Any evaluation error: treat as false (auto-approve)
            return False
