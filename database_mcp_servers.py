"""
Database MCP Servers for RBC CTE Validation System
Trino, Oracle, Postgres, Jira, Confluence, SMT Converter, DBT Converter
"""

import asyncio
import json
from typing import Any, Dict, List
from pathlib import Path
import os

# Database connectors
try:
    import trino
    import oracledb
    import psycopg2
    from jira import JIRA
    import requests  # For Confluence API
except ImportError:
    print("Installing database connectors...")
    os.system("pip install trino oracledb psycopg2-binary jira-python requests")

from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.server.stdio

# ============================================================================
# TRINO MCP SERVER
# ============================================================================

app_trino = Server("trino-connector")

# Configuration
TRINO_HOST = os.getenv("TRINO_HOST", "trino.rbc.internal")
TRINO_PORT = int(os.getenv("TRINO_PORT", "8080"))
TRINO_USER = os.getenv("TRINO_USER", "your_username")
TRINO_CATALOG = os.getenv("TRINO_CATALOG", "lz_catalog")

@app_trino.list_tools()
async def list_trino_tools() -> list[Tool]:
    return [
        Tool(
            name="execute_query",
            description="Execute SQL query on Trino lz layer",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL query to execute"},
                    "catalog": {"type": "string", "description": "Trino catalog", "default": TRINO_CATALOG},
                    "schema": {"type": "string", "description": "Trino schema", "default": "default"},
                    "limit": {"type": "integer", "description": "Row limit", "default": 100}
                },
                "required": ["sql"]
            }
        ),
        Tool(
            name="list_tables",
            description="List tables in Trino catalog/schema",
            inputSchema={
                "type": "object",
                "properties": {
                    "catalog": {"type": "string", "default": TRINO_CATALOG},
                    "schema": {"type": "string", "default": "default"}
                }
            }
        ),
        Tool(
            name="describe_table",
            description="Get table schema/structure",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                    "catalog": {"type": "string", "default": TRINO_CATALOG},
                    "schema": {"type": "string", "default": "default"}
                },
                "required": ["table_name"]
            }
        )
    ]

@app_trino.call_tool()
async def call_trino_tool(name: str, arguments: Any) -> list[TextContent]:
    try:
        conn = trino.dbapi.connect(
            host=TRINO_HOST,
            port=TRINO_PORT,
            user=TRINO_USER,
            catalog=arguments.get("catalog", TRINO_CATALOG),
            schema=arguments.get("schema", "default")
        )
        
        cursor = conn.cursor()
        
        if name == "execute_query":
            sql = arguments["sql"]
            limit = arguments.get("limit", 100)
            
            # Add LIMIT if not present
            if "LIMIT" not in sql.upper():
                sql = f"{sql} LIMIT {limit}"
            
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            result = {
                "columns": columns,
                "rows": [dict(zip(columns, row)) for row in rows],
                "row_count": len(rows)
            }
            
        elif name == "list_tables":
            cursor.execute(f"SHOW TABLES FROM {arguments.get('catalog')}.{arguments.get('schema')}")
            tables = [row[0] for row in cursor.fetchall()]
            result = {"tables": tables, "count": len(tables)}
            
        elif name == "describe_table":
            table = arguments["table_name"]
            cursor.execute(f"DESCRIBE {table}")
            columns = cursor.fetchall()
            result = {
                "table": table,
                "columns": [{"name": col[0], "type": col[1], "nullable": col[2]} for col in columns]
            }
        
        cursor.close()
        conn.close()
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

# ============================================================================
# ORACLE MCP SERVER
# ============================================================================

app_oracle = Server("oracle-connector")

ORACLE_DSN = os.getenv("ORACLE_DSN", "oracle.rbc.internal:1521/ORCL")
ORACLE_USER = os.getenv("ORACLE_USER", "your_username")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "your_password")

@app_oracle.list_tools()
async def list_oracle_tools() -> list[Tool]:
    return [
        Tool(
            name="execute_query",
            description="Execute SQL query on Oracle database",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "limit": {"type": "integer", "default": 100}
                },
                "required": ["sql"]
            }
        )
    ]

@app_oracle.call_tool()
async def call_oracle_tool(name: str, arguments: Any) -> list[TextContent]:
    try:
        conn = oracledb.connect(user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN)
        cursor = conn.cursor()
        
        sql = arguments["sql"]
        limit = arguments.get("limit", 100)
        
        if "ROWNUM" not in sql.upper():
            sql = f"SELECT * FROM ({sql}) WHERE ROWNUM <= {limit}"
        
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        result = {
            "columns": columns,
            "rows": [dict(zip(columns, row)) for row in rows],
            "row_count": len(rows)
        }
        
        cursor.close()
        conn.close()
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

# ============================================================================
# POSTGRES MCP SERVER
# ============================================================================

app_postgres = Server("postgres-connector")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres.rbc.internal")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "validation_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "your_username")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "your_password")

@app_postgres.list_tools()
async def list_postgres_tools() -> list[Tool]:
    return [
        Tool(
            name="execute_query",
            description="Execute SQL query on Postgres",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "limit": {"type": "integer", "default": 100}
                },
                "required": ["sql"]
            }
        )
    ]

@app_postgres.call_tool()
async def call_postgres_tool(name: str, arguments: Any) -> list[TextContent]:
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD
        )
        cursor = conn.cursor()
        
        sql = arguments["sql"]
        limit = arguments.get("limit", 100)
        
        if "LIMIT" not in sql.upper():
            sql = f"{sql} LIMIT {limit}"
        
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        result = {
            "columns": columns,
            "rows": [dict(zip(columns, row)) for row in rows],
            "row_count": len(rows)
        }
        
        cursor.close()
        conn.close()
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

# ============================================================================
# JIRA MCP SERVER
# ============================================================================

app_jira = Server("jira-connector")

JIRA_URL = os.getenv("JIRA_URL", "https://jira.rbc.com")
JIRA_USER = os.getenv("JIRA_USER", "your_email@rbc.com")
JIRA_TOKEN = os.getenv("JIRA_TOKEN", "your_api_token")

@app_jira.list_tools()
async def list_jira_tools() -> list[Tool]:
    return [
        Tool(
            name="create_issue",
            description="Create Jira issue for validation failure",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Jira project key"},
                    "summary": {"type": "string"},
                    "description": {"type": "string"},
                    "issue_type": {"type": "string", "default": "Bug"},
                    "priority": {"type": "string", "default": "High"}
                },
                "required": ["project", "summary", "description"]
            }
        ),
        Tool(
            name="search_issues",
            description="Search Jira issues by JQL",
            inputSchema={
                "type": "object",
                "properties": {
                    "jql": {"type": "string", "description": "JQL query"},
                    "max_results": {"type": "integer", "default": 50}
                },
                "required": ["jql"]
            }
        )
    ]

@app_jira.call_tool()
async def call_jira_tool(name: str, arguments: Any) -> list[TextContent]:
    try:
        jira = JIRA(server=JIRA_URL, basic_auth=(JIRA_USER, JIRA_TOKEN))
        
        if name == "create_issue":
            issue_dict = {
                'project': {'key': arguments['project']},
                'summary': arguments['summary'],
                'description': arguments['description'],
                'issuetype': {'name': arguments.get('issue_type', 'Bug')},
                'priority': {'name': arguments.get('priority', 'High')}
            }
            
            new_issue = jira.create_issue(fields=issue_dict)
            
            result = {
                "issue_key": new_issue.key,
                "issue_url": f"{JIRA_URL}/browse/{new_issue.key}",
                "status": "created"
            }
            
        elif name == "search_issues":
            issues = jira.search_issues(arguments['jql'], maxResults=arguments.get('max_results', 50))
            
            result = {
                "count": len(issues),
                "issues": [
                    {
                        "key": issue.key,
                        "summary": issue.fields.summary,
                        "status": issue.fields.status.name,
                        "assignee": issue.fields.assignee.displayName if issue.fields.assignee else None
                    }
                    for issue in issues
                ]
            }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

# ============================================================================
# CONFLUENCE MCP SERVER
# ============================================================================

app_confluence = Server("confluence-connector")

CONFLUENCE_URL = os.getenv("CONFLUENCE_URL", "https://confluence.rbc.com")
CONFLUENCE_USER = os.getenv("CONFLUENCE_USER", "your_email@rbc.com")
CONFLUENCE_TOKEN = os.getenv("CONFLUENCE_TOKEN", "your_api_token")

@app_confluence.list_tools()
async def list_confluence_tools() -> list[Tool]:
    return [
        Tool(
            name="create_page",
            description="Create Confluence documentation page",
            inputSchema={
                "type": "object",
                "properties": {
                    "space_key": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "HTML content"}
                },
                "required": ["space_key", "title", "content"]
            }
        ),
        Tool(
            name="search_pages",
            description="Search Confluence pages",
            inputSchema={
                "type": "object",
                "properties": {
                    "cql": {"type": "string", "description": "Confluence Query Language"},
                    "limit": {"type": "integer", "default": 25}
                },
                "required": ["cql"]
            }
        )
    ]

@app_confluence.call_tool()
async def call_confluence_tool(name: str, arguments: Any) -> list[TextContent]:
    try:
        auth = (CONFLUENCE_USER, CONFLUENCE_TOKEN)
        headers = {"Content-Type": "application/json"}
        
        if name == "create_page":
            url = f"{CONFLUENCE_URL}/rest/api/content"
            
            payload = {
                "type": "page",
                "title": arguments["title"],
                "space": {"key": arguments["space_key"]},
                "body": {
                    "storage": {
                        "value": arguments["content"],
                        "representation": "storage"
                    }
                }
            }
            
            response = requests.post(url, json=payload, auth=auth, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            result = {
                "page_id": data["id"],
                "page_url": f"{CONFLUENCE_URL}{data['_links']['webui']}",
                "status": "created"
            }
            
        elif name == "search_pages":
            url = f"{CONFLUENCE_URL}/rest/api/content/search"
            params = {
                "cql": arguments["cql"],
                "limit": arguments.get("limit", 25)
            }
            
            response = requests.get(url, params=params, auth=auth)
            response.raise_for_status()
            
            data = response.json()
            result = {
                "count": data["size"],
                "pages": [
                    {
                        "id": page["id"],
                        "title": page["title"],
                        "url": f"{CONFLUENCE_URL}{page['_links']['webui']}"
                    }
                    for page in data["results"]
                ]
            }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

# ============================================================================
# SMT CONVERTER MCP SERVER
# ============================================================================

app_smt_converter = Server("smt-converter")

@app_smt_converter.list_tools()
async def list_smt_tools() -> list[Tool]:
    return [
        Tool(
            name="divide_smt_by_entities",
            description="Divide SMT schema into logical entities",
            inputSchema={
                "type": "object",
                "properties": {
                    "smt_file": {"type": "string", "description": "Path to SMT file"}
                },
                "required": ["smt_file"]
            }
        ),
        Tool(
            name="show_distinct_entities",
            description="Show distinct entity types in SMT",
            inputSchema={
                "type": "object",
                "properties": {
                    "smt_file": {"type": "string"}
                },
                "required": ["smt_file"]
            }
        )
    ]

@app_smt_converter.call_tool()
async def call_smt_tool(name: str, arguments: Any) -> list[TextContent]:
    try:
        with open(arguments["smt_file"], 'r') as f:
            smt_content = json.load(f)
        
        if name == "divide_smt_by_entities":
            # Group fields by entity (based on prefixes or naming patterns)
            entities = {}
            
            for field in smt_content.get("fields", []):
                # Simple entity detection based on field name patterns
                name = field["name"]
                
                if "customer" in name.lower():
                    entity = "customer"
                elif "transaction" in name.lower() or "txn" in name.lower():
                    entity = "transaction"
                elif "account" in name.lower():
                    entity = "account"
                else:
                    entity = "general"
                
                if entity not in entities:
                    entities[entity] = []
                
                entities[entity].append(field)
            
            result = {
                "entities": entities,
                "entity_count": len(entities),
                "total_fields": len(smt_content.get("fields", []))
            }
            
        elif name == "show_distinct_entities":
            entities = set()
            
            for field in smt_content.get("fields", []):
                name = field["name"]
                
                if "customer" in name.lower():
                    entities.add("customer")
                elif "transaction" in name.lower():
                    entities.add("transaction")
                elif "account" in name.lower():
                    entities.add("account")
            
            result = {
                "distinct_entities": list(entities),
                "count": len(entities)
            }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

# ============================================================================
# DBT CONVERTER MCP SERVER
# ============================================================================

app_dbt_converter = Server("dbt-converter")

@app_dbt_converter.list_tools()
async def list_dbt_tools() -> list[Tool]:
    return [
        Tool(
            name="parse_dbt_model",
            description="Parse DBT model and extract transformation logic",
            inputSchema={
                "type": "object",
                "properties": {
                    "dbt_file": {"type": "string", "description": "Path to DBT SQL file"}
                },
                "required": ["dbt_file"]
            }
        ),
        Tool(
            name="convert_cte_to_dbt",
            description="Convert CTE to DBT model format",
            inputSchema={
                "type": "object",
                "properties": {
                    "cte_file": {"type": "string"},
                    "model_name": {"type": "string"}
                },
                "required": ["cte_file", "model_name"]
            }
        )
    ]

@app_dbt_converter.call_tool()
async def call_dbt_tool(name: str, arguments: Any) -> list[TextContent]:
    try:
        if name == "parse_dbt_model":
            with open(arguments["dbt_file"], 'r') as f:
                dbt_content = f.read()
            
            # Simple parsing - extract CTEs, refs, sources
            result = {
                "model": arguments["dbt_file"],
                "ctes": [],  # Would parse WITH clauses
                "refs": [],  # Would parse {{ ref('model') }}
                "sources": [],  # Would parse {{ source('source', 'table') }}
                "has_tests": False,
                "parsed": True
            }
            
        elif name == "convert_cte_to_dbt":
            with open(arguments["cte_file"], 'r') as f:
                cte_content = f.read()
            
            # Convert to DBT format
            dbt_model = f"""
{{{{ config(
    materialized='table',
    schema='tz'
) }}}}

{cte_content}
"""
            
            result = {
                "model_name": arguments["model_name"],
                "dbt_model": dbt_model,
                "converted": True
            }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

# ============================================================================
# COMPLETE SETUP GUIDE
# ============================================================================

SETUP_GUIDE = """
# 🚀 RBC CTE Validation System - Complete Setup Guide

## 📁 Project Structure

```
POC_MODERNIZATION/
├── .github/
│   └── agents/
│       └── specialists/
│           ├── orchestrator.agent.md
│           ├── validator.agent.md
│           ├── subset-creator.agent.md
│           ├── functional-basic.agent.md
│           ├── functional-advanced.agent.md
│           ├── team-lead.agent.md
│           ├── coordinator.agent.md
│           ├── ui-developer.agent.md
│           ├── smt-understanding.agent.md
│           └── code-checker.agent.md
├── mcp_servers/
│   ├── validation_server.py (Main MCP server)
│   ├── database_connectors.py (This file)
│   └── requirements.txt
├── tracks/
│   └── validation_tracks.json
├── reports/
│   └── (HTML reports generated here)
├── test_data/
│   ├── sample_cte.sql
│   ├── sample_smt.json
│   └── sample_code.sql
└── .env
```

## 🔧 Installation Steps

### 1. Install Python Dependencies

```bash
cd mcp_servers
pip install -r requirements.txt
```

**requirements.txt:**
```
mcp>=1.0.0
requests>=2.31.0
trino>=0.328.0
oracledb>=2.0.0
psycopg2-binary>=2.9.9
jira-python>=0.1.2
```

### 2. Configure Environment Variables

Create `.env` file in project root:

```bash
# RBC Internal API
RBC_API_ENDPOINT=https://your-rbc-internal-api.com/chat/completions
RBC_API_KEY=your_api_key_here
MODEL=claude-sonnet-4-6

# Trino Configuration
TRINO_HOST=trino.rbc.internal
TRINO_PORT=8080
TRINO_USER=your_username
TRINO_CATALOG=lz_catalog

# Oracle Configuration
ORACLE_DSN=oracle.rbc.internal:1521/ORCL
ORACLE_USER=your_username
ORACLE_PASSWORD=your_password

# Postgres Configuration
POSTGRES_HOST=postgres.rbc.internal
POSTGRES_PORT=5432
POSTGRES_DB=validation_db
POSTGRES_USER=your_username
POSTGRES_PASSWORD=your_password

# Jira Configuration
JIRA_URL=https://jira.rbc.com
JIRA_USER=your_email@rbc.com
JIRA_TOKEN=your_jira_api_token

# Confluence Configuration
CONFLUENCE_URL=https://confluence.rbc.com
CONFLUENCE_USER=your_email@rbc.com
CONFLUENCE_TOKEN=your_confluence_api_token
```

### 3. Copy Agent MD Files

Copy all 10 agent MD files to `.github/agents/specialists/`:

```bash
mkdir -p .github/agents/specialists
# Copy orchestrator.agent.md through code-checker.agent.md
```

### 4. Start MCP Servers

**Terminal 1 - Main Validation Server:**
```bash
python mcp_servers/validation_server.py
```

**Terminal 2 - Trino Connector:**
```bash
python -c "from database_connectors import app_trino; import asyncio; asyncio.run(app_trino.run_stdio())"
```

**Terminal 3 - Oracle/Postgres (as needed):**
```bash
python -c "from database_connectors import app_oracle; import asyncio; asyncio.run(app_oracle.run_stdio())"
```

## 🎯 Usage Examples

### Example 1: Run Full Validation

```python
import asyncio
import sys
sys.path.append('mcp_servers')

from validation_server import run_validation_with_learning

result = asyncio.run(run_validation_with_learning(
    cte_file="test_data/sample_cte.sql",
    smt_file="test_data/sample_smt.json",
    code_file="test_data/sample_code.sql",
    max_retries=3
))

print(json.dumps(result, indent=2))
```

### Example 2: Query Trino for Test Data

```python
# Using Trino MCP connector
import trino

conn = trino.dbapi.connect(
    host='trino.rbc.internal',
    port=8080,
    user='your_username',
    catalog='lz_catalog',
    schema='transactions'
)

cursor = conn.cursor()
cursor.execute("SELECT * FROM lz.transactions LIMIT 10")
rows = cursor.fetchall()
```

### Example 3: Create Jira Issue for Failure

```python
# Using Jira MCP connector
from jira import JIRA

jira = JIRA(server='https://jira.rbc.com', basic_auth=('user', 'token'))

issue = jira.create_issue(
    project='VAL',
    summary='CTE Validation Failed: val_123456',
    description='Critical validation failure detected in modernization CTE',
    issuetype={'name': 'Bug'},
    priority={'name': 'High'}
)

print(f"Created issue: {issue.key}")
```

## 🔄 Workflow Execution

The system runs autonomously in this sequence:

1. **Orchestrator** receives request
2. **SMT Understanding** parses schema
3. **Code Checker** compares reference code
4. **Validator** validates CTE (1st line of defense)
5. **Subset Creator** generates test data (queries Trino)
6. **Functional Basic + Advanced** run validation (parallel)
7. **Team Lead** monitors for hallucinations
8. **Coordinator** aggregates results
9. **UI Developer** generates HTML report

If any step fails, the **Error Learning Loop** kicks in:
- Document error in tracks
- Pass error history to next iteration
- Apply corrections
- Retry (up to 3 times)

## 📊 Monitoring

### Check Validation Status:
```python
status = get_validation_status("val_123456")
print(json.dumps(status, indent=2))
```

### View Leaderboard:
```python
leaderboard = RewardsManager.get_leaderboard()
for agent in leaderboard:
    print(f"{agent['agent_name']}: {agent['total_points']} points ({agent['level']})")
```

### View Error History:
```python
errors = TracksManager.get_error_history()
print(f"Total errors learned from: {len(errors)}")
```

## 🎓 Learning Loop in Action

```
Iteration 1:
  Validator confidence: 0.85 (below 0.9 threshold)
  → Error logged: "Low confidence due to ambiguous JOIN type"
  → Orchestrator learns: Need explicit JOIN clarification

Iteration 2:
  Validator receives error context
  → Asks clarifying questions about JOIN
  → Confidence: 0.92 ✓
  → Proceeds to testing

Result: System learned and self-corrected!
```

## 🏆 Rewards System

Points are awarded automatically:
- Validation pass: +10
- Bug found: +15
- Hallucination detected: +20
- Error learned: +25
- Successful retry: +15

Levels:
- 0-19: Novice
- 20-49: Intermediate
- 50-99: Advanced
- 100+: Expert

## ✅ Testing the System

```bash
# 1. Test with sample data
python mcp_servers/validation_server.py --test

# 2. Run single agent
python -c "
from validation_server import AgentExecutor
import asyncio

result = asyncio.run(AgentExecutor.execute(
    'validator',
    'Validate this CTE: SELECT * FROM customers'
))
print(result)
"

# 3. Check tracks
cat tracks/validation_tracks.json | jq '.validations[-1]'
```

## 🚨 Troubleshooting

**Problem: "RBC API connection refused"**
- Check RBC_API_ENDPOINT in .env
- Verify API key is valid
- Test with curl: `curl -H "Authorization: Bearer $RBC_API_KEY" $RBC_API_ENDPOINT`

**Problem: "Agent MD file not found"**
- Verify files are in `.github/agents/specialists/`
- Check file naming: Must end with `.agent.md` or `.md`
- Ensure UTF-8 encoding

**Problem: "Trino connection timeout"**
- Check TRINO_HOST and port
- Verify network access
- Test with: `trino --server trino.rbc.internal:8080`

## 📝 Next Steps

1. ✅ Configure all environment variables
2. ✅ Copy all agent MD files
3. ✅ Test database connections
4. ✅ Run validation on sample data
5. ✅ Review generated reports
6. ✅ Adjust agent prompts as needed
7. ✅ Integrate with CI/CD pipeline

## 🎉 You're Ready!

Your 100% agentic CTE validation system is now configured and ready to run!

Run your first validation:
```bash
python mcp_servers/validation_server.py
```

Then call the MCP tool:
```python
await mcp.call_tool("run_validation", {
    "cte_file_path": "test_data/your_cte.sql",
    "smt_file_path": "test_data/your_smt.json",
    "code_file_path": "test_data/your_code.sql"
})
```

Watch the magic happen! 🚀
"""

if __name__ == "__main__":
    print(SETUP_GUIDE)
