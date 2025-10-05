#!/usr/bin/env python
"""Agent microservice and CLI runner for P. Smith and friends."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

from agents import Runner

from agent_factory import AgentRegistry

DEFAULT_CONFIG = Path(__file__).with_name("agents_config.yaml")


def ensure_api_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY environment variable is required.")


def load_registry(config_path: Optional[str]) -> AgentRegistry:
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    return AgentRegistry.from_file(path)


def resolve_input(text_arg: Optional[str], file_arg: Optional[str]) -> str:
    if text_arg and file_arg:
        sys.exit("Provide either --text or --input-file, not both.")
    if text_arg:
        return text_arg
    if file_arg:
        file_path = Path(file_arg)
        if not file_path.exists():
            sys.exit(f"Input file not found: {file_path}")
        return file_path.read_text(encoding="utf-8")
    data = sys.stdin.read()
    if not data.strip():
        sys.exit("No transcript provided. Use --text, --input-file, or pipe stdin.")
    return data




async def async_chat(agent, session, agent_id: str) -> None:
    print(f"Entering chat with {agent.name}. Type 'exit' or 'quit' to leave.")
    while True:
        try:
            user_input = input('You: ')
        except EOFError:
            print()
            break
        if user_input.strip().lower() in {'exit', 'quit'}:
            break
        if not user_input.strip():
            continue
        result = await Runner.run(agent, user_input, session=session)
        answer = result.final_output
        print(f"Agent: {answer}\n")

def run_chat(args: argparse.Namespace) -> None:
    ensure_api_key()
    registry = load_registry(args.config)
    agent_id = args.agent
    agent = registry.build_agent(agent_id)
    session_id = args.session or 'chat-repl'
    session = registry.build_session(agent_id, session_id)
    asyncio.run(async_chat(agent, session, agent_id))
def run_cli(args: argparse.Namespace) -> None:
    ensure_api_key()
    registry = load_registry(args.config)
    agent_id = args.agent
    transcript = resolve_input(args.text, args.input_file)
    agent = registry.build_agent(agent_id)
    session = registry.build_session(agent_id, args.session)
    result = Runner.run_sync(agent, transcript, session=session)
    print(result.final_output)


def create_app(args: argparse.Namespace):
    ensure_api_key()
    try:
        from fastapi import FastAPI, HTTPException
        from pydantic import BaseModel
    except ImportError as exc:
        sys.exit("FastAPI and pydantic are required for serve mode. Install with: pip install fastapi uvicorn")

    registry = load_registry(args.config)

    class AgentRequest(BaseModel):
        agent_id: str = args.agent
        transcript: str
        session_id: Optional[str] = None

    class AgentResponse(BaseModel):
        agent_id: str
        transcript: str
        metadata: dict[str, str]

    app = FastAPI(title="Agent Microservice", version="0.1.0")

    @app.post("/run", response_model=AgentResponse)
    async def run_agent(request: AgentRequest) -> AgentResponse:
        agent_id = request.agent_id or args.agent
        try:
            agent = registry.build_agent(agent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        session = registry.build_session(agent_id, request.session_id)
        result = await Runner.run(agent, request.transcript, session=session)
        return AgentResponse(
            agent_id=agent_id,
            transcript=result.final_output,
            metadata={
                "session_id": request.session_id or "",
                "agent_name": agent.name,
            },
        )

    @app.get("/agents")
    async def list_agents() -> dict[str, list[str]]:
        return {"agents": registry.list_agent_ids()}

    return app


def serve(args: argparse.Namespace) -> None:
    try:
        import uvicorn
    except ImportError:
        sys.exit("uvicorn is required for serve mode. Install with: pip install uvicorn")

    app = create_app(args)
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run OpenAI agents from config.")
    parser.add_argument("--config", help=f"Path to agent config (default: {DEFAULT_CONFIG})")
    parser.add_argument("--agent", default="psmith", help="Agent identifier to use")
    subparsers = parser.add_subparsers(dest="command", required=False)

    run_parser = subparsers.add_parser("run", help="Run once from CLI input")
    run_parser.add_argument("--text", help="Transcript text input")
    run_parser.add_argument("--input-file", help="Path to transcript file")
    run_parser.add_argument("--session", help="Optional session id for memory")
    run_parser.set_defaults(func=run_cli)

    chat_parser = subparsers.add_parser("chat", help="Interactive REPL that keeps talking to the agent")
    chat_parser.add_argument("--session", help="Optional session id for memory")
    chat_parser.set_defaults(func=run_chat)

    serve_parser = subparsers.add_parser("serve", help="Start HTTP microservice")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8080)
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto reload (development only)")
    serve_parser.set_defaults(func=serve)

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        args.command = "run"
        args.func = run_cli
    args.func(args)


if __name__ == "__main__":
    main()