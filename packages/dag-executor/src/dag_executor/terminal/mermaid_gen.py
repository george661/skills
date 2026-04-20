"""Mermaid diagram generation from workflow definitions."""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dag_executor.schema import WorkflowDef


def generate_mermaid(workflow_def: "WorkflowDef") -> str:
    """Generate Mermaid flowchart from workflow definition.
    
    Args:
        workflow_def: Parsed workflow definition
        
    Returns:
        Mermaid diagram wrapped in code fence
    """
    lines = ["```mermaid", "graph TD", ""]
    
    # Output nodes
    for node in workflow_def.nodes:
        # Use node.name if available, otherwise node.id
        label = node.name or node.id
        lines.append(f"    {node.id}[{label}]")
    
    lines.append("")
    
    # Output dependency edges
    for node in workflow_def.nodes:
        if node.depends_on:
            for dep in node.depends_on:
                lines.append(f"    {dep} --> {node.id}")

    # Output conditional edges
    for node in workflow_def.nodes:
        if node.edges:
            for edge in node.edges:
                if edge.condition:
                    lines.append(f"    {node.id} -->|{edge.condition}| {edge.target}")
                elif edge.default:
                    lines.append(f"    {node.id} -->|default| {edge.target}")
    
    lines.append("```")
    return "\n".join(lines)
