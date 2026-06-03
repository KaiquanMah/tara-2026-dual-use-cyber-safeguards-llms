from .openrouter import OpenRouterRunner
from .claude_direct import ClaudeDirectRunner
from .openai_direct import OpenAIDirectRunner

'''
Runner registry. Maps provider strings to runner classes.

  get_runner("openrouter")     -> OpenRouterRunner      (1-by-1 only)
  get_runner("claude_direct")  -> ClaudeDirectRunner    (1-by-1 + batch)
  get_runner("openai_direct")  -> OpenAIDirectRunner    (1-by-1 + batch)

Called by __main__.py after reading the track config's provider field to
instantiate the correct runner for that track.
'''

RUNNER_MAP = {
    "openrouter": OpenRouterRunner,
    "claude_direct": ClaudeDirectRunner,
    "openai_direct": OpenAIDirectRunner,
}

def get_runner(runner_key: str):
    cls = RUNNER_MAP.get(runner_key)
    if cls is None:
        available = list(RUNNER_MAP.keys())
        raise ValueError(f"Unknown runner '{runner_key}'. Available: {available}")
    return cls
