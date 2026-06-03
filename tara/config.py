import json
from pathlib import Path
from dataclasses import dataclass, field

'''
Track Config - `tara/config.py`

Loads track definitions from `config/tracks.json` into `TrackConfig` dataclasses.

**`TrackConfig` fields:**

| Field | Type | Source in tracks.json | Purpose |
|-------|------|----------------------|---------|
| `key` | str | Dict key (e.g. `cvp-claude`) | Unique track identifier |
| `name` | str | `"name"` | Human-readable label |
| `provider` | str | `"anthropic"`, `"openai"`, `"openrouter"` | Determines which runner class to use |
| `model` | str | Model slug | Passed directly to the model API |
| `access` | str | `"direct"` or `"openrouter"` | Maps to runner selection |
| `api_key_env` | str | Env var name like `"ANTHROPIC_API_KEY"` | Pipeline reads key from env at runtime |
| `person` | str | Team member name | Tracks who ran it |
| `modes` | list[str] | `["one_by_one"]` or `["one_by_one", "batch"]` | Supported submission modes |
| `default_params` | dict | `{"temperature": 0.0, "max_tokens": 4096}` | Default model parameters |
| `reasoning` | list[str] or null | `["xhigh", "high"]` or omitted | Reasoning levels to try in cascade |

**`load_tracks(path)`** - reads `config/tracks.json`, iterates each entry under `"tracks"`, constructs a `TrackConfig` for each. The dict key becomes `.key`. Returns `dict[str, TrackConfig]` keyed by track name.
'''




@dataclass
class TrackConfig:
    key: str
    name: str
    provider: str
    model: str
    access: str
    api_key_env: str
    person: str
    modes: list[str] = field(default_factory=lambda: ["one_by_one"])
    default_params: dict = field(default_factory=dict)
    reasoning: list[str] | None = None
    rate_limit_delay: float | None = None


def load_tracks(path: str | Path) -> dict[str, TrackConfig]:
    path = Path(path)
    with open(path) as f:
        data = json.load(f)
    tracks = {}
    for key, cfg in data.get("tracks", {}).items():
        tracks[key] = TrackConfig(key=key, **cfg)
    return tracks
