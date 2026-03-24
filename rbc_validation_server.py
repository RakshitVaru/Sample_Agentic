"""
RBC CTE Validation MCP Server
Adapted for RBC internal API with error learning loop
"""

import asyncio
import json
import requests
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import os

# MCP SDK
try:
    from mcp.server import Server
    from mcp.types import Tool, TextContent
    import mcp.server.stdio
except ImportError:
    print("Installing mcp...")
    os.system("pip install mcp")
    from mcp.server import Server
    from mcp.types import Tool, TextContent
    import mcp.server.stdio

# Configuration
RBC_API_ENDPOINT = os.getenv("RBC_API_ENDPOINT", "https://your-rbc-api.com/chat/completions")
RBC_API_KEY = os.getenv("RBC_API_KEY", "your-api-key-here")
MODEL = os.getenv("MODEL", "claude-sonnet-4-6")

# Paths
BASE_DIR = Path(__file__).parent.parent
AGENTS_DIR = BASE_DIR / ".github" / "agents" / "specialists"
TRACKS_DIR = BASE_DIR / "tracks"
REPORTS_DIR = BASE_DIR / "reports"

# Initialize MCP Server
app = Server("rbc-cte-validation-system")

# Global state
tracks_db = {"agents": {}, "validations": [], "error_history": []}
rewards_system = {
    "points": {
        "validation_pass": 10,
        "validation_fail": -5,
        "hallucination_detected": 20,
        "bug_found": 15,
        "edge_case_covered": 5,
        "error_learned": 25,
        "successful_retry": 15
    }
}

@dataclass
class Track:
    """Track for communication between agents"""
    track_id: str
    sender: str
    receiver: str
    message: Dict[str, Any]
    timestamp: str
    status: str = "pending"
    iteration: int = 0  # For learning loop

@dataclass
class AgentScore:
    """Reward tracking for agents"""
    agent_name: str
    total_points: int = 0
    validations_run: int = 0
    bugs_found: int = 0
    hallucinations_detected: int = 0
    errors_learned: int = 0
    level: str = "Novice"

class RBCAPIClient:
    """Client for RBC internal API"""
    
    @staticmethod
    def call_completion(system_prompt: str, user_message: str, temperature: float = 0.7) -> str:
        """Call RBC internal chat completions API"""
        try:
            response = requests.post(
                RBC_API_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {RBC_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "max_tokens": 8096,
                    "temperature": temperature
                },
                timeout=120
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"❌ RBC API Error: {e}")
            raise

class AgentLoader:
    """Loads agent prompts from MD files"""
    
    @staticmethod
    def load_agent(agent_name: str) -> str:
        """Load agent system prompt from MD file"""
        # Support both with and without .agent.md suffix
        possible_files = [
            AGENTS_DIR / f"{agent_name}.agent.md",
            AGENTS_DIR / f"{agent_name}.md",
            AGENTS_DIR / f"{agent_name}-agent.md"
        ]
        
        for agent_file in possible_files:
            if agent_file.exists():
                with open(agent_file, 'r', encoding='utf-8') as f:
                    return f.read()
        
        # Default if not found
        return f"You are the {agent_name} agent. Perform your assigned tasks autonomously."
    
    @staticmethod
    def list_agents() -> List[str]:
        """List all available agents"""
        if not AGENTS_DIR.exists():
            return []
        agents = []
        for f in AGENTS_DIR.glob("*.md"):
            # Remove .agent.md or .md suffix
            name = f.stem.replace('.agent', '')
            agents.append(name)
        return agents

class TracksManager:
    """Manages communication tracks between agents"""
    
    @staticmethod
    def create_track(sender: str, receiver: str, message: Dict, iteration: int = 0) -> Track:
        """Create a new communication track"""
        track = Track(
            track_id=f"track_{int(datetime.now().timestamp() * 1000)}",
            sender=sender,
            receiver=receiver,
            message=message,
            timestamp=datetime.now().isoformat(),
            iteration=iteration
        )
        
        tracks_db["validations"].append(asdict(track))
        TracksManager.save_tracks()
        return track
    
    @staticmethod
    def update_track(track_id: str, status: str, response: Dict = None):
        """Update track status"""
        for track in tracks_db["validations"]:
            if track["track_id"] == track_id:
                track["status"] = status
                if response:
                    track["response"] = response
                track["updated_at"] = datetime.now().isoformat()
                break
        TracksManager.save_tracks()
    
    @staticmethod
    def log_error(agent: str, error: str, context: Dict, iteration: int):
        """Log error for learning"""
        error_entry = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "error": error,
            "context": context,
            "iteration": iteration
        }
        tracks_db["error_history"].append(error_entry)
        TracksManager.save_tracks()
    
    @staticmethod
    def get_error_history(agent: str = None) -> List[Dict]:
        """Get error history for learning"""
        if agent:
            return [e for e in tracks_db["error_history"] if e["agent"] == agent]
        return tracks_db["error_history"]
    
    @staticmethod
    def save_tracks():
        """Persist tracks to JSON"""
        tracks_file = TRACKS_DIR / "validation_tracks.json"
        TRACKS_DIR.mkdir(parents=True, exist_ok=True)
        with open(tracks_file, 'w') as f:
            json.dump(tracks_db, f, indent=2)
    
    @staticmethod
    def load_tracks():
        """Load tracks from JSON"""
        global tracks_db
        tracks_file = TRACKS_DIR / "validation_tracks.json"
        if tracks_file.exists():
            try:
                with open(tracks_file, 'r') as f:
                    tracks_db = json.load(f)
            except json.JSONDecodeError:
                tracks_db = {"agents": {}, "validations": [], "error_history": []}

class RewardsManager:
    """Manages agent rewards and scoring"""
    
    @staticmethod
    def award_points(agent_name: str, event_type: str, details: str = ""):
        """Award points to agent"""
        if agent_name not in tracks_db["agents"]:
            tracks_db["agents"][agent_name] = asdict(AgentScore(agent_name))
        
        agent_score = tracks_db["agents"][agent_name]
        points = rewards_system["points"].get(event_type, 0)
        agent_score["total_points"] += points
        
        # Update specific counters
        if event_type == "validation_pass":
            agent_score["validations_run"] += 1
        elif event_type == "bug_found":
            agent_score["bugs_found"] += 1
        elif event_type == "hallucination_detected":
            agent_score["hallucinations_detected"] += 1
        elif event_type == "error_learned":
            agent_score["errors_learned"] += 1
        
        # Update level
        total = agent_score["total_points"]
        if total >= 100:
            agent_score["level"] = "Expert"
        elif total >= 50:
            agent_score["level"] = "Advanced"
        elif total >= 20:
            agent_score["level"] = "Intermediate"
        
        TracksManager.save_tracks()
        
        return {
            "agent": agent_name,
            "event": event_type,
            "points_awarded": points,
            "new_total": agent_score["total_points"],
            "level": agent_score["level"],
            "details": details
        }
    
    @staticmethod
    def get_leaderboard() -> List[Dict]:
        """Get agent leaderboard"""
        agents = list(tracks_db["agents"].values())
        return sorted(agents, key=lambda x: x["total_points"], reverse=True)

class AgentExecutor:
    """Executes agent logic using RBC API"""
    
    @staticmethod
    async def execute(agent_name: str, prompt: str, context: Dict = None, 
                     error_history: List[Dict] = None) -> str:
        """Execute agent with RBC API"""
        # Load agent system prompt from MD file
        system_prompt = AgentLoader.load_agent(agent_name)
        
        # Add error learning context if available
        if error_history:
            system_prompt += f"\n\n## Previous Errors (Learn from these)\n{json.dumps(error_history, indent=2)}"
        
        # Add context if provided
        if context:
            prompt = f"Context:\n{json.dumps(context, indent=2)}\n\nTask:\n{prompt}"
        
        # Call RBC API
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            RBCAPIClient.call_completion,
            system_prompt,
            prompt
        )
        
        return response

# MCP Tool Definitions
@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all MCP tools"""
    return [
        Tool(
            name="run_validation",
            description="Execute full CTE validation workflow with error learning loop. 100% autonomous.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cte_file_path": {"type": "string", "description": "Path to CTE SQL file"},
                    "smt_file_path": {"type": "string", "description": "Path to SMT schema file"},
                    "code_file_path": {"type": "string", "description": "Path to reference code file"},
                    "max_retries": {"type": "integer", "description": "Max learning iterations", "default": 3}
                },
                "required": ["cte_file_path", "smt_file_path", "code_file_path"]
            }
        ),
        Tool(
            name="get_validation_status",
            description="Check status of validation run",
            inputSchema={
                "type": "object",
                "properties": {
                    "validation_id": {"type": "string"}
                }
            }
        ),
        Tool(
            name="get_leaderboard",
            description="Get agent performance leaderboard",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_error_history",
            description="Get error history for learning analysis",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Optional: filter by agent"}
                }
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls"""
    
    if name == "run_validation":
        result = await run_validation_with_learning(
            arguments["cte_file_path"],
            arguments["smt_file_path"],
            arguments["code_file_path"],
            arguments.get("max_retries", 3)
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "get_validation_status":
        status = get_validation_status(arguments.get("validation_id"))
        return [TextContent(type="text", text=json.dumps(status, indent=2))]
    
    elif name == "get_leaderboard":
        leaderboard = RewardsManager.get_leaderboard()
        return [TextContent(type="text", text=json.dumps(leaderboard, indent=2))]
    
    elif name == "get_error_history":
        history = TracksManager.get_error_history(arguments.get("agent_name"))
        return [TextContent(type="text", text=json.dumps(history, indent=2))]
    
    return [TextContent(type="text", text="Unknown tool")]

async def run_validation_with_learning(
    cte_file: str, 
    smt_file: str, 
    code_file: str,
    max_retries: int = 3
) -> Dict:
    """
    Main validation workflow with ERROR LEARNING LOOP
    This is what makes it 100% agentic!
    """
    
    validation_id = f"val_{int(datetime.now().timestamp())}"
    iteration = 0
    
    results = {
        "validation_id": validation_id,
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "iterations": [],
        "final_status": None
    }
    
    print(f"\n{'='*70}")
    print(f"🚀 RBC CTE Validation Started: {validation_id}")
    print(f"{'='*70}\n")
    
    while iteration < max_retries:
        iteration_result = {
            "iteration": iteration + 1,
            "started_at": datetime.now().isoformat(),
            "agents_executed": [],
            "errors": [],
            "corrections_applied": []
        }
        
        try:
            print(f"🔄 Iteration {iteration + 1}/{max_retries}")
            
            # Get error history for learning
            error_history = TracksManager.get_error_history()
            
            # Phase 1: Orchestrator creates plan
            print("📋 [1/10] Orchestrator: Creating validation plan...")
            
            orchestrator_prompt = f"""
            Create comprehensive validation plan for:
            - CTE: {cte_file}
            - SMT: {smt_file}
            - Code: {code_file}
            
            Iteration: {iteration + 1}
            Previous errors: {len(error_history)} documented
            
            Available MCP integrations:
            - Trino (lz layer queries)
            - Oracle/Postgres (data sources)
            - SMT Converter (entity analysis)
            - DBT Converter (model parsing)
            - Jira (issue tracking)
            - Confluence (documentation)
            
            Return JSON plan with execution strategy.
            """
            
            if error_history:
                orchestrator_prompt += f"\n\nLEARN FROM PREVIOUS ERRORS:\n{json.dumps(error_history[-5:], indent=2)}"
            
            plan = await AgentExecutor.execute(
                "orchestrator",
                orchestrator_prompt,
                error_history=error_history[-10:] if error_history else None
            )
            
            iteration_result["agents_executed"].append("orchestrator")
            iteration_result["plan"] = plan
            
            # Phase 2: SMT Understanding
            print("🔍 [2/10] SMT Understanding Agent: Analyzing schema...")
            
            with open(smt_file, 'r') as f:
                smt_content = f.read()
            
            smt_analysis = await AgentExecutor.execute(
                "smt-understanding",
                f"Analyze and convert to JSON:\n\n{smt_content}",
                error_history=TracksManager.get_error_history("smt-understanding")
            )
            
            iteration_result["agents_executed"].append("smt-understanding")
            
            # Phase 3: Code Checker
            print("📄 [3/10] Code Checker: Comparing with reference code...")
            
            with open(code_file, 'r') as f:
                code_content = f.read()
            
            code_check = await AgentExecutor.execute(
                "code-checker",
                f"Compare SMT with code:\n\nSMT Analysis:\n{smt_analysis}\n\nCode:\n{code_content}",
                error_history=TracksManager.get_error_history("code-checker")
            )
            
            iteration_result["agents_executed"].append("code-checker")
            
            # Phase 4: Validator (1st Line of Defense)
            print("✅ [4/10] Validator: Checking CTE alignment...")
            
            with open(cte_file, 'r') as f:
                cte_content = f.read()
            
            validation_result = await AgentExecutor.execute(
                "validator",
                f"""Validate with confidence threshold 0.9:
                
                CTE:\n{cte_content}
                
                SMT Analysis:\n{smt_analysis}
                
                Code Check:\n{code_check}
                
                Return JSON with status, confidence, findings, business_keys.
                """,
                error_history=TracksManager.get_error_history("validator")
            )
            
            try:
                validation_data = json.loads(validation_result)
            except:
                validation_data = {"status": "ERROR", "confidence": 0.0, "findings": [validation_result]}
            
            iteration_result["agents_executed"].append("validator")
            iteration_result["validation"] = validation_data
            
            # Check validation status
            if validation_data.get("confidence", 0) < 0.9:
                error_msg = f"Validation confidence below threshold: {validation_data.get('confidence')}"
                TracksManager.log_error("validator", error_msg, validation_data, iteration + 1)
                iteration_result["errors"].append(error_msg)
                
                # Try to learn and correct
                if iteration < max_retries - 1:
                    print(f"⚠️  Low confidence - learning and retrying...")
                    reward = RewardsManager.award_points("validator", "error_learned", error_msg)
                    iteration_result["corrections_applied"].append(reward)
                    iteration += 1
                    results["iterations"].append(iteration_result)
                    continue
                else:
                    results["final_status"] = "failed_validation"
                    results["iterations"].append(iteration_result)
                    return results
            
            reward = RewardsManager.award_points("validator", "validation_pass")
            
            # Phase 5: Subset Creator
            print("📊 [5/10] Subset Creator: Generating test data...")
            
            business_keys = validation_data.get("business_keys", ["id"])
            
            subset_data = await AgentExecutor.execute(
                "subset-creator",
                f"Create test subsets for keys: {business_keys}\n\nGenerate 16 records with edge cases.",
                error_history=TracksManager.get_error_history("subset-creator")
            )
            
            iteration_result["agents_executed"].append("subset-creator")
            
            # Phase 6 & 7: Functional Validators (Parallel)
            print("⚡ [6-7/10] Functional Validators: Running basic + advanced...")
            
            basic_result, advanced_result = await asyncio.gather(
                AgentExecutor.execute("functional-basic", f"Validate: {subset_data}"),
                AgentExecutor.execute("functional-advanced", f"Complex validation: {subset_data}")
            )
            
            iteration_result["agents_executed"].extend(["functional-basic", "functional-advanced"])
            
            # Phase 8: Team Lead (Anti-Hallucination)
            print("👔 [8/10] Team Lead: Monitoring for hallucinations...")
            
            monitoring = await AgentExecutor.execute(
                "team-lead",
                f"""Monitor for hallucinations and contradictions:
                
                Validator: {validation_result}
                Basic: {basic_result}
                Advanced: {advanced_result}
                
                Check for inconsistencies.
                """,
                error_history=TracksManager.get_error_history("team-lead")
            )
            
            try:
                monitoring_data = json.loads(monitoring)
            except:
                monitoring_data = {"overall_confidence": 90, "hallucination_flags": []}
            
            iteration_result["agents_executed"].append("team-lead")
            
            if monitoring_data.get("hallucination_flags"):
                for flag in monitoring_data["hallucination_flags"]:
                    reward = RewardsManager.award_points("team-lead", "hallucination_detected", 
                                                        flag.get("issue", ""))
            
            # Phase 9: Coordinator
            print("📋 [9/10] Coordinator: Aggregating results...")
            
            final_summary = await AgentExecutor.execute(
                "coordinator",
                f"Aggregate all results:\n{json.dumps([validation_data, basic_result, advanced_result, monitoring_data])}",
                error_history=TracksManager.get_error_history("coordinator")
            )
            
            iteration_result["agents_executed"].append("coordinator")
            
            # Phase 10: UI Developer
            print("🎨 [10/10] UI Developer: Generating HTML report...")
            
            report = await AgentExecutor.execute(
                "ui-developer",
                f"Generate HTML report for validation {validation_id}:\n{final_summary}"
            )
            
            iteration_result["agents_executed"].append("ui-developer")
            
            # Save report
            report_file = REPORTS_DIR / f"validation_{validation_id}_iter{iteration+1}.html"
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            with open(report_file, 'w') as f:
                f.write(report)
            
            iteration_result["report_file"] = str(report_file)
            iteration_result["status"] = "completed"
            
            # Success!
            results["final_status"] = "completed"
            results["iterations"].append(iteration_result)
            
            print(f"\n{'='*70}")
            print(f"✅ Validation Complete!")
            print(f"{'='*70}")
            print(f"Status: {results['final_status']}")
            print(f"Iterations: {iteration + 1}")
            print(f"Report: {report_file}")
            print(f"{'='*70}\n")
            
            return results
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Error in iteration {iteration + 1}: {error_msg}")
            
            TracksManager.log_error("system", error_msg, {
                "iteration": iteration + 1,
                "cte_file": cte_file,
                "agents_executed": iteration_result["agents_executed"]
            }, iteration + 1)
            
            iteration_result["errors"].append(error_msg)
            iteration_result["status"] = "error"
            results["iterations"].append(iteration_result)
            
            # Learn and retry
            if iteration < max_retries - 1:
                print(f"🔄 Learning from error and retrying...")
                RewardsManager.award_points("system", "error_learned", error_msg)
                iteration += 1
            else:
                results["final_status"] = "failed_after_retries"
                return results
    
    results["final_status"] = "max_retries_reached"
    return results

def get_validation_status(validation_id: str) -> Dict:
    """Get status of a validation run"""
    validation_tracks = [t for t in tracks_db["validations"] 
                        if validation_id in str(t.get("message", {}))]
    
    return {
        "validation_id": validation_id,
        "tracks": validation_tracks[-10:],  # Last 10 tracks
        "total_tracks": len(validation_tracks),
        "completed": sum(1 for t in validation_tracks if t["status"] == "completed"),
        "errors": TracksManager.get_error_history()
    }

async def main():
    """Run MCP server"""
    # Load existing tracks
    TracksManager.load_tracks()
    
    # Create directories
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    TRACKS_DIR.mkdir(parents=True, exist_ok=True)
    
    print("🚀 RBC CTE Validation MCP Server Starting...")
    print(f"📁 Agents directory: {AGENTS_DIR}")
    print(f"📊 Tracks directory: {TRACKS_DIR}")
    print(f"📄 Reports directory: {REPORTS_DIR}")
    print(f"🤖 Available agents: {', '.join(AgentLoader.list_agents())}")
    print(f"🔗 RBC API: {RBC_API_ENDPOINT}")
    print()
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
