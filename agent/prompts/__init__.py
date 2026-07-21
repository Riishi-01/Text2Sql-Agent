"""Prompt assembly pipeline for the NL2SQL agent.

This sub-package builds the system prompt from 4 source files:
    role.md, semantic_model.yaml, few_shot.yaml, orientation.md

Public API (import from here, not from builder directly):
    assemble_system_prompt  — build the full system prompt
    get_user_prompt         — format a user question
    extract_sql             — extract SQL from LLM output
    validate_prompts        — sanity-check all prompt files exist
"""
from .builder import (
    assemble_system_prompt,
    get_user_prompt,
    extract_sql,
    validate_prompts,
    load_prompt_file,
    resolve_now,
)

__all__ = [
    "assemble_system_prompt",
    "get_user_prompt",
    "extract_sql",
    "validate_prompts",
    "load_prompt_file",
    "resolve_now",
]
