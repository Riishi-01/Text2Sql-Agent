"""Prompt assembly and {{NOW}} resolution.

Assembles the 4-file system prompt:
1. role.md - static role + 8 hard rules
2. semantic_model.yaml - metrics, dims, synonyms (has {{NOW}})
3. few_shot.yaml - worked examples (has {{NOW}} in SQL)
4. orientation.md - ORM brief / gotchas

All {{NOW}} placeholders are resolved at runtime.
"""
import re
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from .config import settings
from .schema import get_dataset_max_date


def load_prompt_file(filename: str) -> str:
    """Load a prompt file from the prompts directory.
    
    Args:
        filename: Name of the file to load
        
    Returns:
        Contents of the file as string
    """
    file_path = settings.prompts_dir / filename
    
    if not file_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {file_path}")
    
    return file_path.read_text(encoding="utf-8")


def resolve_now(templates: str, now_value: str) -> str:
    """Resolve all {{NOW}} placeholders in a template.
    
    Args:
        templates: String containing {{NOW}} placeholders
        now_value: ISO date string to substitute (YYYY-MM-DD)
        
    Returns:
        Template with all {{NOW}} replaced
    """
    return templates.replace("{{NOW}}", now_value)


def assemble_system_prompt(now_value: str = None) -> str:
    """Assemble the complete system prompt from 4 files.
    
    Order: role -> semantic_model -> few_shot -> orientation
    
    Args:
        now_value: ISO date string for {{NOW}} resolution.
                   If None, fetched from dataset max date.
    
    Returns:
        Complete system prompt with all placeholders resolved
    """
    # Get NOW value
    if now_value is None:
        now_value = get_dataset_max_date()
    
    # Load all prompt components
    role = load_prompt_file("role.md")
    semantic_model = load_prompt_file("semantic_model.yaml")
    few_shot = load_prompt_file("few_shot.yaml")
    orientation = load_prompt_file("orientation.md")
    
    # Resolve {{NOW}} in each component
    # role.md may have {{NOW}} in output rule
    role = resolve_now(role, now_value)
    
    # semantic_model.yaml has {{NOW}} in dataset_max_date
    semantic_model = resolve_now(semantic_model, now_value)
    
    # few_shot.yaml has {{NOW}} in SQL queries
    few_shot = resolve_now(few_shot, now_value)
    
    # orientation.md is static (no placeholders)
    
    # Assemble final prompt
    parts = [
        role,
        "\n\n# Semantic Model\n\n" + semantic_model,
        "\n\n# Worked Examples\n\n" + few_shot,
        "\n\n# Data Orientation\n\n" + orientation,
    ]
    
    return "\n".join(parts)


def get_user_prompt(question: str) -> str:
    """Format the user question as a prompt.
    
    Args:
        question: Natural language question
        
    Returns:
        Formatted user prompt
    """
    return f"Question: {question}\n\nProvide the SQL query to answer this question."


def extract_sql(llm_output: str) -> str:
    """Extract SQL from LLM output.
    
    Handles both:
    - Raw SQL output
    - Markdown code blocks: ```sql ... ```
    
    Args:
        llm_output: Raw output from LLM
        
    Returns:
        Extracted SQL query
    """
    # Check for markdown code block
    code_block_pattern = r"```(?:sql)?\s*\n(.*?)\n```"
    match = re.search(code_block_pattern, llm_output, re.DOTALL | re.IGNORECASE)
    
    if match:
        return match.group(1).strip()
    
    # No code block, assume raw SQL
    return llm_output.strip()


# Validation functions for prompt files
def validate_prompts() -> Dict[str, Any]:
    """Validate all prompt files exist and are well-formed.
    
    Returns:
        Dict with validation results
    """
    results = {
        "valid": True,
        "files": {},
    }
    
    required_files = [
        "role.md",
        "semantic_model.yaml", 
        "few_shot.yaml",
        "orientation.md",
    ]
    
    for filename in required_files:
        file_path = settings.prompts_dir / filename
        
        if not file_path.exists():
            results["valid"] = False
            results["files"][filename] = {"error": "File not found"}
            continue
        
        content = file_path.read_text(encoding="utf-8")
        line_count = len(content.strip().split("\n"))
        
        results["files"][filename] = {
            "lines": line_count,
            "has_now": "{{NOW}}" in content,
        }
        
        # Check line count limit
        if line_count > 300:
            results["files"][filename]["warning"] = f"Exceeds 300 lines ({line_count})"
    
    return results
