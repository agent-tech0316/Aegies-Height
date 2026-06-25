class AgentechError(Exception):
    """Base exception for the Agentech wrapper."""


class ConfigurationError(AgentechError, ValueError):
    """Raised when the selected runtime mode is not allowed or not configured."""


class SafetyError(AgentechError, RuntimeError):
    """Raised when a safety gate blocks a motion command."""
