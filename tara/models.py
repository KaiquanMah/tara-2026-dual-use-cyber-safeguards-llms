from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

UTC8 = timezone(timedelta(hours=8))

'''
Data classes used across the pipeline.

Prompt - created by ingest.py from prompts.json. Holds the PROMPT TEXT plus
  all METADATA fields from the source JSON. The 'raw' dict preserves the complete
  original record verbatim.

Response - created by runners after calling the model API. 
  - prompt_id LINKS BACK TO the ORIGINAL PROMPT
  - text holds the model's FINAL ANSWER
  - metadata stores provider-specific extras like REASONING TRACES, thinking
    blocks, model slug, and batch IDs
  - timestamp auto-generates in UTC+8 if not explicitly set
'''

@dataclass
class Prompt:
    id: str
    text: str
    category: str = ""
    category_id: str = ""
    scenario_id: str = ""
    scenario_name: str = ""
    intent_class: str = ""
    risk_level: str = ""
    artifact_type: str = ""
    expected_behavior: str = ""
    evaluation_focus: str = ""
    subdomain: str = ""
    persona: str = ""
    notes: str = ""
    references: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class Response:
    prompt_id: str
    model: str
    text: str
    finish_reason: str
    usage: dict = field(default_factory=dict)
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC8).isoformat()
