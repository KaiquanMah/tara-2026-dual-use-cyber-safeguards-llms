from abc import ABC, abstractmethod
from ..models import Prompt, Response
from ..config import TrackConfig

'''
Abstract base class / ABC that all runners inherit from.
  BaseRunner
    ├── OpenRouterRunner      (1-by-1 only)
    ├── ClaudeDirectRunner    (1-by-1 + batch)
    └── OpenAIDirectRunner    (1-by-1 + batch)

`BaseRunner` is an **abstract class** (inherits from `ABC`) that defines the interface every runner must implement:
- **`run_one(prompt) -> Response`** - marked `@abstractmethod` with `...` body. Every runner **must** provide this. It sends one prompt to the model API and returns the response.
- **`run_batch(prompts) -> list[Response]`** - optional. The base class provides a default that raises `NotImplementedError`. Runners that support batch (ClaudeDirect, OpenAIDirect) override it. OpenRouter doesn't, so it inherits the error.

The `...` is Python's **Ellipsis literal** - it's a valid no-op expression, used here as a placeholder for "this method body will be defined by subclasses." It's equivalent to `pass` but conventionally signals "intentionally left blank" in abstract method stubs. The `@abstractmethod` decorator is what actually enforces that subclasses override it - `...` is just the body.


Each concrete runner MUST implement run_one(). 

run_batch() is OPTIONAL - the base class provides a default that raises NotImplementedError for
runners that don't support it (like OpenRouter).



---


So since openrouter does not implement a run_batch method, it does not hit the notimplementederror as long as the method is not run for openrouter obj?



Yes, that's exactly right. In Python:

1. `OpenRouterRunner` inherits from `BaseRunner`
2. `OpenRouterRunner` only defines `run_one` - it does NOT define `run_batch`
3. So when you call `openrouter_runner.run_batch(prompts)`, Python looks up the method resolution order (MRO) and finds `run_batch` on `BaseRunner`
4. `BaseRunner.run_batch` raises `NotImplementedError`

The key insight: the `@abstractmethod` decorator on `run_one` means `OpenRouterRunner` MUST implement `run_one` or it can't be instantiated. 
But `run_batch` is NOT abstract - it's just a concrete method on the base class that raises an error. 
`OpenRouterRunner` is free to NOT override it, and calling it will just hit the base class's error-raising version.

It is correct that:
- As long as nobody calls `run_batch` on an `OpenRouterRunner` instance, the `NotImplementedError` is never raised
- The `__main__.py` only calls `run_batch` when `args.mode == "batch"`, and the `test-openrouter-deepseek` track has `modes: ["one_by_one"]` (not batch)
- But even if someone ran `python -m tara run test-openrouter-deepseek --mode batch`, the `cmd_run_track` function would still try to call `runner.run_batch(to_run)` and get the error

So the guard is at the config level (track's `modes` field doesn't include `"batch"`) and at the code level (base class raises error if called).

Correct. `run_batch` on `BaseRunner` is **not** abstract - it's a concrete default that raises `NotImplementedError`. `OpenRouterRunner` never overrides it, so:

- ✅ `one_by_one` mode: calls `run_one(p)` → works fine (OpenRouter implements it)
- ✅ `batch` mode never tried: no issue, the error never fires
- ❌ `batch` mode attempted: Python walks MRO, finds `BaseRunner.run_batch`, error raised

The actual guard is in `cmd_run_track()` in `__main__.py` - it only calls `runner.run_batch(to_run)` when `args.mode == "batch"`. If someone ran `--mode batch` on an OpenRouter track, they'd get:

```
NotImplementedError: 'test-openrouter-deepseek' does not support batch mode
```


'''

class BaseRunner(ABC):
    def __init__(self, config: TrackConfig):
        self.config = config

    @abstractmethod
    def run_one(self, prompt: Prompt) -> Response:
        ...

    def run_batch(self, prompts: list[Prompt]) -> list[Response]:
        raise NotImplementedError(f"'{self.config.key}' does not support batch mode")
