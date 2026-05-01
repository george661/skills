"""Server-side DAG layout computation using layered graph layout (Sugiyama)."""
import hashlib
from collections import deque
from typing import Any, Dict, List, Tuple


def topological_sort_with_layers(nodes: List[Dict[str, Any]]) -> Dict[int, List[str]]:
    """
    Perform topological sort and assign nodes to layers.

    Uses Kahn's algorithm to compute layers based on longest path from root.

    Args:
        nodes: List of node dicts with 'node_name' and 'depends_on' fields

    Returns:
        Dict mapping layer index to list of node names in that layer
    """
    # Build adjacency list and in-degree map
    graph: Dict[str, List[str]] = {}
    in_degree: Dict[str, int] = {}

    for node in nodes:
        node_name = node["node_name"]
        graph[node_name] = []
        in_degree[node_name] = 0

    for node in nodes:
        node_name = node["node_name"]
        depends_on = node.get("depends_on") or []
        for parent in depends_on:
            if parent in graph:
                graph[parent].append(node_name)
                in_degree[node_name] += 1

    # Find all root nodes (in-degree = 0)
    queue = deque([(name, 0) for name, deg in in_degree.items() if deg == 0])

    layers: Dict[int, List[str]] = {}

    while queue:
        node_name, layer = queue.popleft()

        if layer not in layers:
            layers[layer] = []
        layers[layer].append(node_name)

        # Process children
        for child in graph[node_name]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append((child, layer + 1))

    return layers


def compute_layout(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute DAG layout with node positions and edge routes.

    Args:
        nodes: List of node execution dicts from database

    Returns:
        Layout data with nodes (including x, y, layer) and edges
    """
    if not nodes:
        return {"nodes": [], "edges": []}

    # Compute failure path
    failure_path = compute_failure_path(nodes)

    # Assign layers using topological sort
    layers_dict = topological_sort_with_layers(nodes)

    # Layout parameters
    NODE_WIDTH = 200
    NODE_HEIGHT = 80
    LAYER_SPACING = 250
    NODE_SPACING = 120

    # Compute node positions
    layout_nodes = []
    node_positions: Dict[str, Tuple[float, float]] = {}

    for layer_idx, node_names in sorted(layers_dict.items()):
        layer_count = len(node_names)
        y = layer_idx * LAYER_SPACING

        # Center nodes horizontally
        total_width = layer_count * NODE_WIDTH + (layer_count - 1) * NODE_SPACING
        start_x = -total_width / 2

        for i, node_name in enumerate(node_names):
            x = start_x + i * (NODE_WIDTH + NODE_SPACING) + NODE_WIDTH / 2

            # Find the original node data
            node_data = next((n for n in nodes if n["node_name"] == node_name), None)
            if not node_data:
                continue

            node_positions[node_name] = (x, y)

            layout_nodes.append({
                "id": node_data.get("id", f"{node_data['run_id']}:{node_name}"),
                "node_name": node_name,
                "x": x,
                "y": y,
                "layer": layer_idx,
                "status": node_data.get("status", "pending"),
                "depends_on": node_data.get("depends_on", []),
                "node_data": node_data.get("node_data", {}),
                "model": node_data.get("model"),
                "tokens": node_data.get("tokens"),
                "cost": node_data.get("cost"),
                "started_at": node_data.get("started_at"),
                "finished_at": node_data.get("finished_at"),
                "error": node_data.get("error"),
                "failure_path": node_name in failure_path,
            })

    # Build edges from depends_on relationships and conditional edges
    # NOTE: If a node has both 'edges:' (conditional edges) and 'depends_on:', only
    # the 'edges:' are rendered. The 'depends_on:' field is used for topological
    # sorting but is not rendered as visual edges when conditional edges are present.
    # This is intentional: nodes with conditional routing define their outgoing edges
    # explicitly via the edges: list, while depends_on: is for simple linear dependencies.
    edges = []

    for node in layout_nodes:
        node_name = node["node_name"]
        node_data = node.get("node_data", {})
        depends_on = node.get("depends_on") or []

        # Check if node has conditional edges defined
        conditional_edges = node_data.get("edges")

        if conditional_edges:
            # Build edges from conditional EdgeDef list
            for edge_index, edge_def in enumerate(conditional_edges):
                # Get source position
                if node_name not in node_positions:
                    continue
                source_pos = node_positions[node_name]

                # Handle both single target and multi-target (fan-out)
                targets = edge_def.get("targets") or ([edge_def.get("target")] if edge_def.get("target") else [])

                # Generate stable edge_group_id for fan-out siblings
                edge_group_id = hashlib.sha256(f"{node_name}:{edge_index}".encode()).hexdigest()[:16]

                for target_index, target_name in enumerate(targets):
                    if target_name in node_positions:
                        target_pos = node_positions[target_name]
                        edge_id = f"{node_name}-{target_name}-{edge_index}"

                        edges.append({
                            "source": node_name,
                            "target": target_name,
                            "edge_id": edge_id,
                            "edge_group_id": edge_group_id,
                            "branch_set_id": node_name,  # All conditional edges from same source
                            "edge_index": edge_index,
                            "target_index": target_index,
                            "condition": edge_def.get("condition"),
                            "default": edge_def.get("default", False),
                            "failure_path": node_name in failure_path and target_name in failure_path,
                            "points": [
                                {"x": source_pos[0], "y": source_pos[1] + NODE_HEIGHT / 2},
                                {"x": target_pos[0], "y": target_pos[1] - NODE_HEIGHT / 2},
                            ]
                        })
        elif depends_on:
            # Fallback to depends_on for nodes without conditional edges
            for parent_name in depends_on:
                if parent_name in node_positions:
                    source_pos = node_positions[parent_name]
                    target_pos = node_positions[node_name]
                    edge_id = f"{parent_name}-{node_name}-0"

                    # Simple straight-line edge routing
                    # In a production system, you might use spline routing to avoid overlaps
                    edges.append({
                        "source": parent_name,
                        "target": node_name,
                        "edge_id": edge_id,
                        "failure_path": parent_name in failure_path and node_name in failure_path,
                        "points": [
                            {"x": source_pos[0], "y": source_pos[1] + NODE_HEIGHT / 2},
                            {"x": target_pos[0], "y": target_pos[1] - NODE_HEIGHT / 2},
                        ]
                    })

    return {
        "nodes": layout_nodes,
        "edges": edges,
    }


def compute_failure_path(nodes: List[Dict[str, Any]]) -> set[str]:
    """
    Compute the failure path: set of nodes that are failed or depend on failed nodes.

    A node is on the failure path if:
    - Its status is 'failed', OR
    - It transitively depends on a failed node AND its status is skipped/pending/not-started

    Args:
        nodes: List of node dicts with 'node_name', 'status', and 'depends_on' fields

    Returns:
        Set of node names on the failure path
    """
    # Build dependency graph (reverse: child → parents)
    node_map = {node["node_name"]: node for node in nodes}
    failure_path = set()

    # First pass: mark all failed nodes
    for node in nodes:
        if node.get("status") == "failed":
            failure_path.add(node["node_name"])

    # Second pass: BFS to find all nodes that depend on failed nodes
    # Build forward dependency graph (parent → children)
    forward_deps: Dict[str, List[str]] = {}
    for node in nodes:
        node_name = node["node_name"]
        depends_on = node.get("depends_on") or []
        for parent in depends_on:
            if parent not in forward_deps:
                forward_deps[parent] = []
            forward_deps[parent].append(node_name)

    # BFS from failed nodes to find downstream
    queue = deque(failure_path)
    while queue:
        current = queue.popleft()
        # Add all children that are skipped/pending/not-started
        for child in forward_deps.get(current, []):
            if child not in failure_path:
                child_status = node_map[child].get("status", "pending")
                if child_status in ("skipped", "pending", "not-started"):
                    failure_path.add(child)
                    queue.append(child)

    return failure_path
