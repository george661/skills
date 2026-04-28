"""Gate runner for conditional evaluation nodes."""
from simpleeval import SimpleEval, NameNotDefined  # type: ignore[import-untyped]

from dag_executor.schema import NodeResult, NodeStatus
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner


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
        # Prefer the resolved condition (with $variable references replaced by
        # their concrete values via variables.resolve_variables) when the
        # executor placed it under resolved_inputs["condition"]. Fall back to
        # the raw field only when nothing was resolved — some test paths
        # construct a RunnerContext directly with `condition` already inlined.
        resolved_condition = ctx.resolved_inputs.get("condition") if ctx.resolved_inputs else None
        condition = resolved_condition if isinstance(resolved_condition, str) and resolved_condition else ctx.node_def.condition

        try:
            # Create safe evaluator with restricted features
            evaluator = SimpleEval()

            # Set available names from resolved inputs. Drop "condition" from
            # the names dict — it's the expression text itself, not a value
            # the expression should reference.
            names = {k: v for k, v in (ctx.resolved_inputs or {}).items() if k != "condition"}
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
