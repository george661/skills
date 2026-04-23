"""
CLI subcommands for conversation management.

Supports appending messages to conversations for testing and integration.
"""

import argparse
import json
import sys
from pathlib import Path

from dag_executor.conversations import append_message, build_conversation_message_appended_event


def run_conversation(argv: list[str]) -> None:
    """Handle 'dag-exec conversation' subcommands.
    
    Args:
        argv: Command-line arguments (e.g., ['append', '--db', '...'])
    """
    parser = argparse.ArgumentParser(
        prog='dag-exec conversation',
        description='Manage conversation history and messages',
    )
    
    subparsers = parser.add_subparsers(dest='subcommand', required=True)
    
    # append subcommand
    append_parser = subparsers.add_parser(
        'append',
        help='Append a message to a conversation',
    )
    append_parser.add_argument('--db', required=True, help='Path to SQLite database')
    append_parser.add_argument('--conversation-id', required=True, help='Conversation ID')
    append_parser.add_argument('--session-id', required=True, help='Session ID')
    append_parser.add_argument('--role', required=True, choices=['user', 'assistant', 'operator'], help='Message role')
    append_parser.add_argument('--content', required=True, help='Message content')
    append_parser.add_argument('--run-id', help='Workflow run ID')
    append_parser.add_argument('--node-id', default='cli-append', help='Node ID (default: cli-append)')
    append_parser.add_argument('--events-dir', help='Directory to write event NDJSON')
    append_parser.add_argument('--transition-reason', help='Session transition reason (e.g., fresh-context)')
    append_parser.add_argument('--parent-session-id', help='Parent session ID for chained sessions')
    
    args = parser.parse_args(argv)
    
    if args.subcommand == 'append':
        run_append(args)


def run_append(args: argparse.Namespace) -> None:
    """Execute conversation append subcommand.
    
    Appends a message to chat_messages and writes the canonical event.
    
    Args:
        args: Parsed arguments from argparse
    """
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    
    # Append message to database
    message = append_message(
        db_path=db_path,
        role=args.role,
        content=args.content,
        conversation_id=args.conversation_id,
        session_id=args.session_id,
        run_id=args.run_id,
        execution_id=None,  # CLI appends don't have execution context
    )
    
    print(f"Message appended: id={message.id}")
    
    # Write canonical event if events-dir provided
    if args.events_dir:
        events_dir = Path(args.events_dir)
        events_dir.mkdir(parents=True, exist_ok=True)
        
        if not args.run_id:
            print("Warning: --events-dir requires --run-id, skipping event write", file=sys.stderr)
            return
        
        event = build_conversation_message_appended_event(
            run_id=args.run_id,
            node_id=args.node_id,
            conversation_id=args.conversation_id,
            session_id=args.session_id,
            role=args.role,
            message_id=message.id,
            transition_reason=args.transition_reason,
            parent_session_id=args.parent_session_id,
        )

        # Write event to NDJSON file
        event_file = events_dir / f"{args.run_id}.ndjson"
        with open(event_file, "a") as f:
            f.write(json.dumps(event) + "\n")
        print(f"Event written: {event_file}")
    
    sys.exit(0)
