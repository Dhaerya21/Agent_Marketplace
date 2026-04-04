"""
Pipeline Execution Engine
===========================
Executes multi-agent pipelines sequentially, passing output from
each step as input to the next. Similar to N8N workflow execution.
"""

import json
import time
from datetime import datetime, timezone
from .agent_proxy import proxy
from .models import db, Agent, Purchase, Pipeline, PipelineRun


def validate_pipeline_access(user_id, config):
    """
    Validate that user has purchased all agents in the pipeline.
    Returns (valid, error_message).
    """
    steps = config.get("steps", [])
    if not steps:
        return False, "Pipeline has no steps."

    if len(steps) > 10:
        return False, "Pipeline cannot have more than 10 steps."

    for i, step in enumerate(steps):
        agent_id = step.get("agent_id")
        if not agent_id:
            return False, f"Step {i+1} is missing an agent_id."

        agent = Agent.query.get(agent_id)
        if not agent:
            return False, f"Step {i+1} references unknown agent '{agent_id}'."

        purchase = Purchase.query.filter_by(user_id=user_id, agent_id=agent_id).first()
        if not purchase:
            return False, f"You haven't purchased '{agent.name}' (required for step {i+1})."

    return True, None


def execute_pipeline(pipeline_id, user_id, input_text):
    """
    Execute a saved pipeline.

    Pipeline config format:
    {
        "steps": [
            {"agent_id": "researcher", "label": "Research"},
            {"agent_id": "documentation", "label": "Write Docs"},
            {"agent_id": "citation", "label": "Fact-Check"}
        ]
    }

    Each step's output becomes the next step's input.
    Returns the PipelineRun record.
    """
    pipeline = Pipeline.query.get(pipeline_id)
    if not pipeline or pipeline.user_id != user_id:
        return None, "Pipeline not found."

    config = json.loads(pipeline.config) if isinstance(pipeline.config, str) else pipeline.config
    steps = config.get("steps", [])

    # Validate access
    valid, error = validate_pipeline_access(user_id, config)
    if not valid:
        return None, error

    # Create run record
    run = PipelineRun(
        pipeline_id=pipeline_id,
        user_id=user_id,
        status="running",
        input_text=input_text,
        total_steps=len(steps),
        steps_completed=0,
    )
    db.session.add(run)
    db.session.commit()

    # Execute steps sequentially
    current_input = input_text
    step_results = []
    pipeline_start = time.time()

    for i, step in enumerate(steps):
        agent_id = step.get("agent_id")
        label = step.get("label", f"Step {i+1}")

        agent = Agent.query.get(agent_id)
        if not agent:
            run.status = "failed"
            run.output_text = json.dumps({
                "error": f"Agent '{agent_id}' not found at step {i+1}.",
                "steps_completed": i,
                "step_results": step_results,
            })
            run.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            return run, None

        # Run agent
        step_start = time.time()
        result = proxy.run_agent(agent.a2a_url, current_input, agent.agent_type)
        step_elapsed = round(time.time() - step_start, 3)

        step_result = {
            "step": i + 1,
            "label": label,
            "agent_name": agent.name,
            "agent_id": agent_id,
            "elapsed_sec": step_elapsed,
            "success": result.get("success", False),
        }

        if result.get("success"):
            step_result["output"] = result
            # Prepare input for next step -- pass the full result as JSON
            current_input = json.dumps(result, ensure_ascii=False)
        else:
            step_result["error"] = result.get("error", "Unknown error")
            step_results.append(step_result)
            run.status = "failed"
            run.steps_completed = i
            run.output_text = json.dumps({
                "error": f"Pipeline failed at step {i+1}: {step_result['error']}",
                "steps_completed": i,
                "step_results": step_results,
            })
            run.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            return run, None

        step_results.append(step_result)
        run.steps_completed = i + 1
        db.session.commit()

    # Pipeline completed successfully
    total_elapsed = round(time.time() - pipeline_start, 3)
    run.status = "completed"
    run.output_text = json.dumps({
        "success": True,
        "total_elapsed_sec": total_elapsed,
        "steps_completed": len(steps),
        "step_results": step_results,
        "final_output": result,  # Last step's output
    })
    run.completed_at = datetime.now(timezone.utc)
    db.session.commit()

    return run, None
