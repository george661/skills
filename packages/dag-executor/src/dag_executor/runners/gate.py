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
        condition = ctx.node_def.condition
        
        try:
            # Create safe evaluator with restricted features
            evaluator = SimpleEval()
            
            # Set available names from resolved inputs
            evaluator.names = ctx.resolved_inputs.copy()
            
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
