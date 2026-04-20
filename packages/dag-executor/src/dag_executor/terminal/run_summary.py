"""Run summary rendering with box-drawn tables."""
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dag_executor.executor import WorkflowResult
    from dag_executor.schema import WorkflowDef


class RunSummary:
    """Renders workflow execution summary with node breakdown."""
    
    @staticmethod
    def render(result: "WorkflowResult", workflow_def: "WorkflowDef") -> str:
        """Render execution summary with per-node table and artifacts.
        
        Args:
            result: Workflow execution result
            workflow_def: Workflow definition
            
        Returns:
            Formatted summary string
        """
        use_unicode = not os.environ.get("NO_COLOR")
        
        # Box-drawing characters
        if use_unicode:
            top_left, top_right = "╭", "╮"
            bottom_left, bottom_right = "╰", "╯"
            horizontal, vertical = "─", "│"
            success_mark, fail_mark = "✓", "✗"
        else:
            top_left = top_right = bottom_left = bottom_right = "+"
            horizontal, vertical = "-", "|"
            success_mark, fail_mark = "OK", "X"
        
        lines = []
        
        # Header box
        title = f" Workflow: {workflow_def.name} "
        box_width = max(60, len(title) + 4)
        lines.append(f"{top_left}{horizontal * (box_width - 2)}{top_right}")
        lines.append(f"{vertical}{title.center(box_width - 2)}{vertical}")
        lines.append(f"{vertical} Status: {result.status.value:<{box_width - 11}}{vertical}")
        lines.append(f"{vertical} Run ID: {result.run_id:<{box_width - 11}}{vertical}")
        lines.append(f"{bottom_left}{horizontal * (box_width - 2)}{bottom_right}")
        lines.append("")
        
        # Node table header
        lines.append("Node Results:")
        lines.append("")
        lines.append(f"  {'Node':<20} {'Status':<12} {'Duration':<12}")
        lines.append(f"  {horizontal * 20} {horizontal * 12} {horizontal * 12}")
        
        # Node rows
        for node in result.nodes:
            node_name = next((n.name for n in workflow_def.nodes if n.id == node.id), node.id)
            
            # Status with marker
            status_str = node.status.value.upper()
            if node.status.value == "completed":
                status_str = f"{success_mark} {status_str}"
            elif node.status.value == "failed":
                status_str = f"{fail_mark} {status_str}"
            
            # Duration calculation
            duration_str = "N/A"
            if node.result and node.result.started_at and node.result.completed_at:
                delta = node.result.completed_at - node.result.started_at
                duration_ms = int(delta.total_seconds() * 1000)
                if duration_ms < 1000:
                    duration_str = f"{duration_ms}ms"
                else:
                    duration_str = f"{duration_ms / 1000:.1f}s"
            
            lines.append(f"  {node_name:<20} {status_str:<12} {duration_str:<12}")
        
        lines.append("")
        
        # Artifacts section
        if result.outputs:
            lines.append("Artifacts:")
            lines.append("")
            for key, value in result.outputs.items():
                lines.append(f"  {key}: {value}")
            lines.append("")
        
        return "\n".join(lines)
