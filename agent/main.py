"""CLI entry point for Olist NL2SQL agent.

Usage:
    python -m agent "<question>"

Or with the installed script:
    olist-nl2sql "<question>"
"""
import sys
import json
from tabulate import tabulate

from agent.graph import run_agent
from core.config import settings


def format_output(state: dict) -> str:
    """Format agent output for display.
    
    Args:
        state: Final agent state
        
    Returns:
        Formatted output string
    """
    output = []
    
    # Add SQL if available
    if state.get("sql"):
        output.append(f"\nSQL:\n{state['sql']}\n")
    
    # Add validation warnings if any
    validation = state.get("validation")
    if validation and validation.get("warnings"):
        output.append("Warnings:")
        for warning in validation["warnings"]:
            output.append(f"  ⚠ {warning}")
        output.append("")
    
    # Add results or error
    if state.get("error"):
        output.append(f"Error: {state['error']}")
    elif state.get("rows") is not None:
        rows = state["rows"]
        columns = state.get("columns", [])
        
        if rows:
            output.append(f"Results ({len(rows)} rows):\n")
            
            # Format as table
            if columns:
                table_data = [[row.get(col, "") for col in columns] for row in rows]
                output.append(tabulate(table_data, headers=columns, tablefmt="psql"))
            else:
                output.append(json.dumps(rows, indent=2, default=str))
        else:
            output.append("No results found.")
    
    return "\n".join(output)


def main():
    """Main CLI entry point."""
    # Check for question argument
    if len(sys.argv) < 2:
        print("Usage: python -m agent \"<question>\"")
        print("\nExample:")
        print('  python -m agent "Top 10 sellers by revenue"')
        sys.exit(1)
    
    # Get question from command line
    question = " ".join(sys.argv[1:])
    
    # Print question
    print(f"\nQuestion: {question}")
    print("-" * 60)
    
    # Check for required API key
    if not settings.openai_api_key:
        print("\nError: OPENAI_API_KEY environment variable is not set.")
        print("Please set it in your .env file or environment.")
        sys.exit(1)
    
    # Run agent
    try:
        result = run_agent(question)
        print(format_output(result))
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Exit with appropriate code
    if result.get("error"):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
