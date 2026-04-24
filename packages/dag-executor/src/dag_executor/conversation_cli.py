"""
CLI subcommands for conversation management.

Supports appending messages to conversations for testing and integration.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dag_executor.conversations import append_message, build_conversation_message_appended_event, list_messages


def run_conversation(argv: list[str]) -> None:
    """Handle 'dag-exec conversation' subcommands.

    Args:
        argv: Command-line arguments (e.g., ['append', '--db', '...'] or ['<conv-id>', '--json'])
    """
    parser = argparse.ArgumentParser(
        prog='dag-exec conversation',
        description='Manage conversation history and messages',
    )

    # Check if first arg is a positional conversation ID (for list subcommand)
    # This is a bit hacky but allows us to support both:
    # - dag-exec conversation <id>
    # - dag-exec conversation append <id> <role> <content>
    if argv and not argv[0].startswith('-') and argv[0] != 'append':
        # Positional form: conversation <id> [--json] [--db <path>]
        return run_list_positional(argv)

    subparsers = parser.add_subparsers(dest='subcommand', required=True)

    # append subcommand with both positional and flag-based forms
    append_parser = subparsers.add_parser(
        'append',
        help='Append a message to a conversation',
    )
    # Positional arguments (optional - can use flags instead for backward compat)
    append_parser.add_argument('conversation_id_pos', nargs='?', help='Conversation ID')
    append_parser.add_argument('role_pos', nargs='?', choices=['user', 'assistant', 'operator'], help='Message role')
    append_parser.add_argument('content_pos', nargs='?', help='Message content')

    # Flag-based arguments (for backward compatibility)
    append_parser.add_argument('--db', help='Path to SQLite database')
    append_parser.add_argument('--conversation-id', dest='conversation_id_flag', help='Conversation ID (alternative to positional)')
    append_parser.add_argument('--session-id', help='Session ID')
    append_parser.add_argument('--role', dest='role_flag', choices=['user', 'assistant', 'operator'], help='Message role (alternative to positional)')
    append_parser.add_argument('--content', dest='content_flag', help='Message content (alternative to positional)')
    append_parser.add_argument('--run-id', help='Workflow run ID')
    append_parser.add_argument('--node-id', default='cli-append', help='Node ID (default: cli-append)')
    append_parser.add_argument('--events-dir', help='Directory to write event NDJSON')
    append_parser.add_argument('--transition-reason', help='Session transition reason (e.g., fresh-context)')
    append_parser.add_argument('--parent-session-id', help='Parent session ID for chained sessions')

    args = parser.parse_args(argv)

    if args.subcommand == 'append':
        run_append(args)


def run_list_positional(argv: list[str]) -> None:
    """Execute conversation list using positional form: <conv-id> [--json] [--db <path>].

    Args:
        argv: Command-line arguments starting with conversation ID
    """
    parser = argparse.ArgumentParser(
        prog='dag-exec conversation',
        description='List messages in a conversation',
    )
    parser.add_argument('conversation_id', help='Conversation ID')
    parser.add_argument('--json', action='store_true', help='Output as JSON array')
    parser.add_argument('--db', help='Path to SQLite database')

    args = parser.parse_args(argv)

    # Resolve database path
    db_path_str = args.db or os.environ.get('DAG_DASHBOARD_DB')
    if not db_path_str:
        print("Error: --db required or set DAG_DASHBOARD_DB environment variable", file=sys.stderr)
        sys.exit(1)

    db_path = Path(db_path_str)
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    # List messages
    messages = list_messages(db_path, args.conversation_id)

    if not messages:
        print(f"Error: No messages found for conversation {args.conversation_id}", file=sys.stderr)
        sys.exit(1)

    # Output messages
    if args.json:
        # JSON output
        output = [
            {
                'id': msg.id,
                'conversation_id': msg.conversation_id,
                'session_id': msg.session_id,
                'role': msg.role,
                'content': msg.content,
                'created_at': msg.created_at,
                'execution_id': msg.execution_id,
                'run_id': msg.run_id,
            }
            for msg in messages
        ]
        print(json.dumps(output))
    else:
        # Human-readable output
        for msg in messages:
            print(f"{msg.role}: {msg.content}")

    sys.exit(0)


def run_append(args: argparse.Namespace) -> None:
    """Execute conversation append subcommand.

    Appends a message to chat_messages and writes the canonical event.
    Supports both positional and flag-based forms for backward compatibility.

    Args:
        args: Parsed arguments from argparse
    """
    # Resolve arguments: positional takes precedence over flags
    conversation_id = getattr(args, 'conversation_id_pos', None) or getattr(args, 'conversation_id_flag', None)
    role = getattr(args, 'role_pos', None) or getattr(args, 'role_flag', None)
    content = getattr(args, 'content_pos', None) or getattr(args, 'content_flag', None)

    # Validate required fields
    if not conversation_id:
        print("Error: conversation-id required (positional or --conversation-id)", file=sys.stderr)
        sys.exit(1)
    if not role:
        print("Error: role required (positional or --role)", file=sys.stderr)
        sys.exit(1)
    if not content:
        print("Error: content required (positional or --content)", file=sys.stderr)
        sys.exit(1)

    # Resolve database path
    db_path_str = args.db or os.environ.get('DAG_DASHBOARD_DB')
    if not db_path_str:
        print("Error: --db required or set DAG_DASHBOARD_DB environment variable", file=sys.stderr)
        sys.exit(1)

    db_path = Path(db_path_str)
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    # Resolve session_id: required for append
    session_id = getattr(args, 'session_id', None)
    if not session_id:
        print("Error: --session-id required", file=sys.stderr)
        sys.exit(1)

    # Append message to database
    message = append_message(
        db_path=db_path,
        role=role,
        content=content,
        conversation_id=conversation_id,
        session_id=session_id,
        run_id=getattr(args, 'run_id', None),
        execution_id=None,  # CLI appends don't have execution context
    )

    print(f"Message appended: id={message.id}")

    # Write canonical event if events-dir provided
    if hasattr(args, 'events_dir') and args.events_dir:
        events_dir = Path(args.events_dir)
        events_dir.mkdir(parents=True, exist_ok=True)

        if not args.run_id:
            print("Warning: --events-dir requires --run-id, skipping event write", file=sys.stderr)
            return

        event = build_conversation_message_appended_event(
            run_id=args.run_id,
            node_id=getattr(args, 'node_id', 'cli-append'),
            conversation_id=conversation_id,
            session_id=session_id,
            role=role,
            message_id=message.id,
            transition_reason=getattr(args, 'transition_reason', None),
            parent_session_id=getattr(args, 'parent_session_id', None),
        )

        # Write event to NDJSON file
        event_file = events_dir / f"{args.run_id}.ndjson"
        with open(event_file, "a") as f:
            f.write(json.dumps(event) + "\n")
        print(f"Event written: {event_file}")

    sys.exit(0)
