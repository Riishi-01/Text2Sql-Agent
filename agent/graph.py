"""LangGraph agent for NL2SQL.

State machine:
  START -> generate_sql -> validate_sql -> [execute_sql | refuse] -> END

The agent:
1. Takes a natural language question
2. Generates SQL using LLM
3. Validates SQL against R1-R9 rules
4. Executes or refuses based on validation
"""
from typing import TypedDict, Optional, List, Dict, Any
from dataclasses import dataclass, field

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from core.config import settings
from agent.prompts import assemble_system_prompt, get_user_prompt, extract_sql
from agent.validator.sql_validator import validate_sql, ValidationResult
from agent.db import execute_query


@dataclass
class AgentState(TypedDict):
    """State for the NL2SQL agent.

    The state flows through:
    - question: user input
    - sql: generated SQL
    - validation: result of validation
    - columns: present if execute_sql ran
    - rows: query results
    - error: error message if failed
    """

    question: str
    sql: Optional[str]
    validation: Optional[Dict[str, Any]]
    columns: Optional[List[str]]
    rows: Optional[List[Dict[str, Any]]]
    error: Optional[str]


def generate_sql(state: AgentState) -> AgentState:
    """Generate SQL from natural language question.

    Uses ChatOpenAI with configured model (default gpt-4o).

    Args:
        state: Current agent state

    Returns:
        Updated state with sql field populated
    """
    try:
        # Assemble system prompt
        system_prompt = assemble_system_prompt()

        # Create LLM
        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=settings.openai_temperature,
        )

        # Create messages
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=get_user_prompt(state["question"])),
        ]

        # Generate SQL
        response = llm.invoke(messages)

        # Extract SQL from response
        raw_sql = response.content
        sql = extract_sql(raw_sql)

        return {
            **state,
            "sql": sql,
            "error": None,
        }

    except Exception as e:
        return {
            **state,
            "sql": None,
            "error": f"Failed to generate SQL: {str(e)}",
        }


def validate_sql_node(state: AgentState) -> AgentState:
    """Validate generated SQL against R1-R9 rules.

    Args:
        state: Current agent state

    Returns:
        Updated state with validation result
    """
    sql = state.get("sql")

    if not sql:
        return {
            **state,
            "validation": None,
            "error": "No SQL to validate",
        }

    # Validate SQL
    result = validate_sql(sql)

    return {
        **state,
        "validation": {
            "valid": result.valid,
            "sql": result.sql,
            "errors": result.errors,
            "warnings": result.warnings,
            "rule_failures": result.rule_failures,
        },
        "sql": result.sql,  # Use potentially modified SQL (R8 LIMIT injection)
    }


def execute_sql(state: AgentState) -> AgentState:
    """Execute validated SQL query.

    Args:
        state: Current agent state

    Returns:
        Updated state with query results
    """
    sql = state.get("sql")

    if not sql:
        return {
            **state,
            "error": "No SQL to execute",
        }

    try:
        rows, columns = execute_query(sql)

        return {
            **state,
            "columns": columns,
            "rows": rows,
            "error": None,
        }

    except Exception as e:
        return {
            **state,
            "error": f"Query execution failed: {str(e)}",
            "columns": None,
            "rows": None,
        }


def refuse(state: AgentState) -> AgentState:
    """Refuse to execute invalid SQL.

    Args:
        state: Current agent state

    Returns:
        Updated state with error message describing validation failures
    """
    validation = state.get("validation", {})
    errors = validation.get("errors", [])

    error_msg = "SQL validation failed:\n" + "\n".join(f"  - {e}" for e in errors)

    return {
        **state,
        "error": error_msg,
        "columns": None,
        "rows": None,
    }


def should_execute(state: AgentState) -> str:
    """Determine next step based on validation result.

    Args:
        state: Current agent state

    Returns:
        "execute" if SQL is valid, "refuse" otherwise
    """
    validation = state.get("validation")

    if validation and validation.get("valid"):
        return "execute"

    return "refuse"


def build_graph() -> StateGraph:
    """Build the LangGraph state machine.

    Returns:
        Compiled StateGraph
    """
    graph = StateGraph(AgentState)

    # Nodes
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql_node)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("refuse", refuse)

    # Entry
    graph.set_entry_point("generate_sql")

    # Edges
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_conditional_edges(
        "validate_sql",
        should_execute,
        {
            "execute": "execute_sql",
            "refuse": "refuse",
        },
    )
    graph.add_edge("execute_sql", END)
    graph.add_edge("refuse", END)

    return graph.compile()


# Global compiled graph (lazy init)
_graph = None


def get_graph() -> StateGraph:
    """Get the compiled graph (lazy initialization).

    Returns:
        Compiled StateGraph
    """
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_agent(question: str) -> AgentState:
    """Run the NL2SQL agent on a natural language question.

    Args:
        question: Natural language question

    Returns:
        Final agent state with results or error
    """
    graph = get_graph()

    initial_state = {
        "question": question,
        "sql": None,
        "validation": None,
        "columns": None,
        "rows": None,
        "error": None,
    }

    result = graph.invoke(initial_state)

    return result
