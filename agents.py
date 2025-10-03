# agents.py
# Defines agents using the OpenAI Agent library, preserving original call signatures.

import asyncio
import os

from openai.types.shared import Reasoning
from openai_agents import Agent, ModelSettings, Runner

# Default settings
DEFAULT_MODEL = "gpt-5"
DEFAULT_SETTINGS = ModelSettings(
    reasoning=Reasoning(effort="minimal"),  # can be "minimal", "low", "medium", "high"
    verbosity="low",                        # "low", "medium", "high"
)

# Internal helper to run an Agent and return final output as string
async def _run_agent(agent: Agent, text: str) -> str:
    try:
        result = await Runner.run(agent, text)
        return result.final_output.strip() if result and result.final_output else ""
    except Exception as e:
        return f"[ERROR calling {agent.name}: {e}]"


def agent_moneypenny(raw_text: str) -> str:
    """
    Pass raw transcript directly to a GPT agent.
    Returns the model response as string.
    """
    agent = Agent(
        name="Agent Moneypenny",
        instructions="Take raw transcripts and respond directly.",
        model=DEFAULT_MODEL,
        model_settings=DEFAULT_SETTINGS,
    )
    try:
        return asyncio.run(_run_agent(agent, raw_text))
    except RuntimeError:
        # Handles case where asyncio.run() conflicts with existing loop
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_agent(agent, raw_text))


def agent_maxwell(raw_text: str) -> str:
    """
    Coding-agent style summarization.
    Returns a structured coding prompt.
    """
    agent = Agent(
        name="Agent Maxwell",
        instructions="Summarize transcripts into structured coding prompts.",
        model=DEFAULT_MODEL,
        model_settings=DEFAULT_SETTINGS,
    )
    try:
        return asyncio.run(_run_agent(agent, raw_text))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_agent(agent, raw_text))
