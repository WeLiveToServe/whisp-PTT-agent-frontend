import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from agents import Agent, ModelSettings, SQLiteSession


@dataclass
class SessionConfig:
    storage: str = ":memory:"
    namespace: Optional[str] = None
    sessions_table: str = "agent_sessions"
    messages_table: str = "agent_messages"


@dataclass
class AgentConfig:
    agent_id: str
    raw: Dict[str, Any]

    def build_agent(self) -> Agent:
        params: Dict[str, Any] = {}
        for key, param in (
            ("name", "name"),
            ("model", "model"),
            ("instructions", "instructions"),
                    ):
            if key in self.raw:
                params[param] = self.raw[key]

        if "handoffs" in self.raw:
            params["handoffs"] = self.raw["handoffs"]
        if "tools" in self.raw:
            params["tools"] = self.raw["tools"]

        model_settings_kwargs = {}
        if 'temperature' in self.raw:
            model_settings_kwargs['temperature'] = self.raw['temperature']
        if 'max_output_tokens' in self.raw:
            model_settings_kwargs['max_tokens'] = self.raw['max_output_tokens']
        if 'verbosity' in self.raw:
            verbosity_map = {'concise': 'low', 'short': 'low', 'default': 'medium', 'detailed': 'high', 'verbose': 'high'}
            raw_verbosity = str(self.raw['verbosity']).lower()
            mapped = verbosity_map.get(raw_verbosity, raw_verbosity)
            allowed = {'low', 'medium', 'high'}
            if mapped not in allowed:
                raise ValueError(f"Unsupported verbosity '{self.raw['verbosity']}'. Use one of {sorted(allowed)} or provide a mappable alias.")
            model_settings_kwargs['verbosity'] = mapped
        if 'reasoning' in self.raw:
            model_settings_kwargs['reasoning'] = self.raw['reasoning']
        if model_settings_kwargs:
            params['model_settings'] = ModelSettings(**model_settings_kwargs)

        return Agent(**params)

    def session_config(self) -> SessionConfig:
        data = self.raw.get("session") or {}
        return SessionConfig(
            storage=data.get("storage", ":memory:"),
            namespace=data.get("namespace"),
            sessions_table=data.get("sessions_table", "agent_sessions"),
            messages_table=data.get("messages_table", "agent_messages"),
        )


class AgentRegistry:
    def __init__(self, config_path: Path, agents: Dict[str, AgentConfig]):
        self.config_path = config_path
        self._agents = agents

    @classmethod
    def from_file(cls, config_path: str | Path) -> "AgentRegistry":
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Agent config not found: {path}")
        data = yaml.safe_load(path.read_text()) or {}
        agents = {
            agent_id: AgentConfig(agent_id=agent_id, raw=raw or {})
            for agent_id, raw in data.items()
        }
        return cls(path, agents)

    def list_agent_ids(self) -> list[str]:
        return sorted(self._agents.keys())

    def get_agent_config(self, agent_id: str) -> AgentConfig:
        if agent_id not in self._agents:
            available = ", ".join(self.list_agent_ids()) or "<none>"
            raise KeyError(f"Unknown agent '{agent_id}'. Available agents: {available}")
        return self._agents[agent_id]

    def build_agent(self, agent_id: str) -> Agent:
        return self.get_agent_config(agent_id).build_agent()

    def build_session(self, agent_id: str, session_id: Optional[str]) -> Optional[SQLiteSession]:
        if not session_id:
            return None
        cfg = self.get_agent_config(agent_id).session_config()
        storage_path = Path(cfg.storage)
        if str(storage_path).startswith('~'):
            storage_path = storage_path.expanduser()
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        namespace = cfg.namespace or agent_id
        db_path = storage_path
        return SQLiteSession(
            session_id=f"{namespace}:{session_id}",
            db_path=str(db_path),
            sessions_table=cfg.sessions_table,
            messages_table=cfg.messages_table,
        )


__all__ = ["AgentRegistry", "AgentConfig", "SessionConfig"]
