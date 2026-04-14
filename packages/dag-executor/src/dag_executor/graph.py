"""Graph algorithms for DAG dependency resolution."""
from collections import deque
from typing import Dict, List, Set

from dag_executor.schema import NodeDef


class CycleDetectedError(Exception):
    """Raised when a cycle is detected in the DAG."""
    pass


def topological_sort_with_layers(nodes: List[NodeDef]) -> List[List[str]]:
    """
    Perform topological sort with Kahn's algorithm and group nodes into parallel execution layers.
    
    Args:
        nodes: List of NodeDef objects representing the workflow DAG
        
    Returns:
        List of layers, where each layer is a list of node IDs that can execute in parallel.
        Nodes in layer N+1 depend on nodes in layer N or earlier.
        
    Raises:
        CycleDetectedError: If the graph contains a cycle
    """
    if not nodes:
        return []
    
    # Build node map, in-degree count, and reverse adjacency list
    node_map: Dict[str, NodeDef] = {node.id: node for node in nodes}
    in_degree: Dict[str, int] = {node.id: 0 for node in nodes}
    dependents: Dict[str, List[str]] = {node.id: [] for node in nodes}

    # Count in-degrees and build reverse adjacency (dep -> nodes that depend on it)
    for node in nodes:
        for dep in node.depends_on:
            if dep not in node_map:
                raise ValueError(f"Node '{node.id}' depends on non-existent node '{dep}'")
            in_degree[node.id] += 1
            dependents[dep].append(node.id)
    
    # Initialize queue with nodes that have no dependencies
    queue: deque[str] = deque()
    for node_id, degree in in_degree.items():
        if degree == 0:
            queue.append(node_id)
    
    layers: List[List[str]] = []
    processed_count = 0
    
    # Process nodes layer by layer
    while queue:
        # All nodes currently in queue can execute in parallel (same layer)
        current_layer = list(queue)
        layers.append(current_layer)
        queue.clear()
        
        # Process each node in current layer
        for node_id in current_layer:
            processed_count += 1

            # Decrement in-degree for all nodes that depend on current node
            for dependent_id in dependents[node_id]:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)
    
    # If not all nodes were processed, there's a cycle
    if processed_count != len(nodes):
        # Find nodes involved in cycle
        remaining_nodes = [node_id for node_id, degree in in_degree.items() if degree > 0]
        cycle_info = _find_cycle_path(nodes, remaining_nodes)
        raise CycleDetectedError(
            f"Cycle detected in workflow graph. Cycle path: {cycle_info}"
        )
    
    return layers


def _find_cycle_path(nodes: List[NodeDef], remaining_nodes: List[str]) -> str:
    """
    Find a cycle path in the remaining unprocessed nodes.
    
    Args:
        nodes: All nodes in the graph
        remaining_nodes: Node IDs that couldn't be processed (involved in cycle)
        
    Returns:
        String representation of a cycle path
    """
    node_map = {node.id: node for node in nodes}
    remaining_set = set(remaining_nodes)
    
    # Start from any remaining node and follow dependencies to find cycle
    if not remaining_nodes:
        return "unknown"
    
    visited: Set[str] = set()
    path: List[str] = []
    
    def dfs(node_id: str) -> bool:
        """DFS to find cycle. Returns True if cycle found."""
        if node_id in path:
            return True
        
        if node_id in visited:
            return False
        
        visited.add(node_id)
        path.append(node_id)
        
        # Follow dependencies that are in remaining set
        node = node_map.get(node_id)
        if node:
            for dep in node.depends_on:
                if dep in remaining_set:
                    if dfs(dep):
                        return True
        
        path.pop()
        return False
    
    # Try DFS from each remaining node
    for start_node in remaining_nodes:
        visited.clear()
        path.clear()
        if dfs(start_node):
            # Extract cycle from path
            if path:
                cycle_start = path.index(start_node) if start_node in path else 0
                cycle_path = path[cycle_start:] + [start_node]
                return " -> ".join(cycle_path)
    
    # Fallback: just list the remaining nodes
    return " -> ".join(remaining_nodes[:3]) + (" -> ..." if len(remaining_nodes) > 3 else "")
