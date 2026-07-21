# Text2SQL - Olist E-Commerce NL2SQL Agent

A LangGraph-based natural language to SQL agent for the Olist e-commerce dataset.

## Project Structure

```
Text2Sql/
├── agent/                    # Main agent package
│   ├── validator/            # SQL validation module
│   │   ├── __init__.py
│   │   └── sql_validator.py  # R1-R9 static SQL safety checks
│   ├── prompts/              # Prompt files (customize these)
│   │   ├── role.md           # Role definition & hard rules
│   │   ├── semantic_model.yaml  # Metrics, dimensions, synonyms
│   │   ├── few_shot.yaml     # Worked examples
│   │   └── orientation.md    # Data orientation guide
│   ├── __init__.py           # Package init
│   ├── config.py             # Environment & LangSmith configuration
│   ├── schema.py             # Database metadata loader
│   ├── prompts.py            # Prompt assembly & {{NOW}} resolution
│   ├── db.py                 # Read-only psycopg connection
│   ├── agent.py              # LangGraph state machine
│   └── main.py               # CLI entry point
├── tests/
│   └── test_validator.py     # 54 tests for R1-R9 rules
├── scripts/
│   └── init_db.sql           # Read-only role + materialized view
├── api/                      # FastAPI REST API
├── database/                 # Database setup scripts
└── data/                     # Olist dataset CSV files
```

## Quick Start

### 1. Install Dependencies

```bash
uv sync
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your OpenAI API key
```

Required environment variables:
- `OPENAI_API_KEY` - Your OpenAI API key
- `LANGSMITH_API_KEY` - (Optional) For tracing

### 3. Initialize Database

```bash
# Start PostgreSQL (Docker recommended)
docker run --name text2sql-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=text2sql \
  -p 5432:5432 \
  -d postgres:14

# Load data and create read-only role
uv run python -m database.setup_db

# Create nl2sql_ro role and materialized view
# (Run the SQL in scripts/init_db.sql manually or via Python)
```

### 4. Run the Agent

```bash
uv run python -m agent "Top 10 sellers by revenue in SP"
```

## Architecture

### LangGraph State Machine

```
START → generate_sql → validate_sql → [execute_sql | refuse] → END
```

- **generate_sql**: Uses ChatOpenAI (GPT-4o) with 4-file system prompt
- **validate_sql**: Static R1-R9 rule checks (no LLM)
- **execute_sql**: Read-only connection with statement timeout
- **refuse**: Returns validation errors to user

### SQL Safety Validator (R1-R9)

| Rule | Check | Result |
|------|-------|--------|
| R1 | sqlglot parse succeeds | Block on error |
| R2 | Must be SELECT or WITH...SELECT | Block otherwise |
| R3 | No DDL/DML keywords | Block on INSERT, UPDATE, DELETE, DROP, etc. |
| R4 | No system catalogs | Block on pg_*, information_schema |
| R5 | Only allowed tables | Block on unknown tables |
| R6 | No raw geolocation table | Block (use geolocation_by_zip) |
| R7 | No SELECT * | Block (list columns explicitly) |
| R8 | Auto-inject LIMIT | Add LIMIT 1000 to non-aggregating queries |
| R9 | Warn on INNER JOIN category_translation | Warning only |

### Prompt Structure

The 4-file prompt system:
1. **role.md** - Static role + 8 hard rules
2. **semantic_model.yaml** - Metrics, dimensions, synonyms (has `{{NOW}}`)
3. **few_shot.yaml** - 7 worked examples (has `{{NOW}}` in SQL)
4. **orientation.md** - ORM brief / gotchas

All `{{NOW}}` placeholders are resolved at runtime from `dataset_max_date`.

## Testing

```bash
# Run validator tests
uv run pytest tests/test_validator.py -v

# All 54 tests should pass
```

## Customization

### Prompt Files

Edit the files in `agent/prompts/` to customize:
- `semantic_model.yaml` - Add metrics, synonyms, sample values
- `few_shot.yaml` - Add more worked examples
- `orientation.md` - Add data-specific guidance

### Model Configuration

In `.env`:
```
OPENAI_MODEL=gpt-4o
OPENAI_TEMPERATURE=0.0
```

## Security

- Read-only database role (`nl2sql_ro`)
- Statement timeout (30s default)
- Static SQL validation (no LLM in validator)
- Forbidden keyword blocking
- System catalog isolation

## API Endpoints

The FastAPI server at `/api/main.py` provides:
- `GET /health` - Database health check
- `POST /query` - Execute read-only SQL queries

Start API:
```bash
uv run uvicorn api.main:app --reload
```

## License

MIT
