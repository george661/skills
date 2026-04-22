"""Model resolution for prompt nodes."""
from typing import Any, Dict

from dag_executor.schema import ModelTier, NodeDef, WorkflowDef


def resolve_model(
    node_def: NodeDef,
    workflow_def: WorkflowDef,
    workflow_inputs: Dict[str, Any],
) -> ModelTier:
    """Resolve the effective model for a prompt node.

    Resolution order (highest precedence first):
      1. workflow_inputs["__model_override__"]  — CLI/API/UI override
      2. node_def.model                          — explicit per-node
      3. workflow_def.default_model              — workflow-wide default
      4. ModelTier.LOCAL                         — global fallback (haiku-class)

    strict_model=True on a node blocks step 1 (override is silently ignored,
    node declaration wins).

    Args:
        node_def: The node being executed
        workflow_def: The workflow definition containing the node
        workflow_inputs: Runtime inputs, may contain __model_override__

    Returns:
        The resolved ModelTier to use for this execution

    Raises:
        ValueError: If all 4 tiers yield None (ambiguous — workflow has no
                    default, node has no model, no override, no fallback set).
                    In practice, tier 4 always returns LOCAL, so this only
                    happens if LOCAL is explicitly removed from ModelTier enum.
    """
    # Tier 1: override (unless strict_model blocks it)
    override_str = workflow_inputs.get("__model_override__")
    if override_str and not getattr(node_def, "strict_model", False):
        try:
            return ModelTier(override_str)
        except ValueError:
            valid_values = [tier.value for tier in ModelTier]
            raise ValueError(
                f"Invalid __model_override__ value: {override_str!r}. "
                f"Must be one of {valid_values}"
            )

    # Tier 2: node-level model
    if node_def.model:
        return node_def.model

    # Tier 3: workflow default
    if workflow_def.default_model:
        return workflow_def.default_model

    # Tier 4: global fallback
    return ModelTier.LOCAL
