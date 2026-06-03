import json
from pathlib import Path
from .models import Prompt, Response
from .config import TrackConfig

'''
File I/O for per-track results.

Manages 3 output files in outputs/{track}/:
  save_track_metadata()     track.json         - track config snapshot + run info

  save_response()           raw/{prompt_id}.json  - one file per prompt (resume safety)

  save_responses_aggregated()  responses.json   - all responses keyed by prompt_id

  load_existing()           reads raw/*.json        - returns dict[prompt_id, Response]
                                                      used by __main__.py to skip
                                                      already-completed prompts on re-run

Key detail: save_response() only writes if the file doesn't exist yet.
This is the resume-safety mechanism - so re-running the pipeline wont
overwrite or re-send prompts that already have saved responses.
'''


class Storage:
    def __init__(self, base_dir: str | Path, track: TrackConfig):
        self.base_dir = Path(base_dir) / track.key
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._raw_dir = self.base_dir / "raw"
        self._raw_dir.mkdir(exist_ok=True)

    def save_track_metadata(self, track: TrackConfig, run_info: dict):
        path = self.base_dir / "track.json"
        data = {"track": track.__dict__, "run": run_info}
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def save_response(self, response: Response):
        path = self._raw_dir / f"{response.prompt_id}.json"
        if not path.exists():
            with open(path, "w") as f:
                json.dump(response.__dict__, f, indent=2)

    def save_responses_aggregated(self, responses: list[Response]):
        path = self.base_dir / "responses.json"
        data = {r.prompt_id: r.__dict__ for r in responses}
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load_existing(self) -> dict[str, Response]:
        responses = {}
        for f_path in sorted(self._raw_dir.glob("*.json")):
            with open(f_path) as f:
                data = json.load(f)
            responses[data["prompt_id"]] = Response(**data)
        return responses
