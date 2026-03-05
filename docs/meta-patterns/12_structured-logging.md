# Pattern: Structured Logging with Dual Outputs

> **STATUS: PROPOSED** - This pattern describes a DualLogger with JSONL output.
> Currently NOT DEPLOYED. The system uses standard Python logging.
> See Plan #60 for the current logging approach (SummaryLogger).

## Philosophy

**Two logs always stored:**
1. **Full log** - Every event, machine-parseable, for debugging and analysis
2. **Tractable log** - Key events only, human-readable, for monitoring

This addresses the common problem: logs are either too verbose to read or too sparse to debug.

## Implementation

### Dual File Strategy

```yaml
# config/config.yaml
logging:
  # Full structured log (JSONL) - every event
  full_log: "run.jsonl"

  # Human-readable log - key events only
  readable_log: "run.log"
  readable_level: INFO  # DEBUG, INFO, WARNING, ERROR

  # Which event types appear in readable log
  readable_events:
    - simulation_start
    - simulation_end
    - tick_start
    - tick_end
    - action_executed
    - auction_resolved
    - budget_exhausted
    - error
    - warning
```

### Python Implementation

```python
import logging
import json
from pathlib import Path
from datetime import datetime

class DualLogger:
    """Logger that writes to both full JSONL and readable text."""

    def __init__(
        self,
        full_log: Path,
        readable_log: Path,
        readable_level: str = "INFO",
        readable_events: list[str] | None = None,
    ):
        self.full_log = full_log
        self.readable_log = readable_log
        self.readable_level = getattr(logging, readable_level.upper())
        self.readable_events = set(readable_events or [])

        # Clear logs on init
        self.full_log.write_text("")
        self.readable_log.write_text("")

        # Setup Python logger for readable output
        self._logger = logging.getLogger("simulation")
        handler = logging.FileHandler(readable_log)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S"
        ))
        self._logger.addHandler(handler)
        self._logger.setLevel(self.readable_level)

    def log(self, event_type: str, data: dict, level: str = "INFO") -> None:
        """Log an event to both outputs."""
        # Always write to full log
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            **data,
        }
        with open(self.full_log, "a") as f:
            f.write(json.dumps(event) + "\n")

        # Write to readable log if event type matches
        if event_type in self.readable_events or level in ("WARNING", "ERROR"):
            msg = self._format_readable(event_type, data)
            log_level = getattr(logging, level.upper())
            self._logger.log(log_level, msg)

    def _format_readable(self, event_type: str, data: dict) -> str:
        """Format event for human-readable output."""
        # Customize formatting per event type
        formatters = {
            "tick_start": lambda d: f"--- Tick {d.get('tick', '?')} ---",
            "action_executed": lambda d: (
                f"  {d.get('agent_id', '?')}: {d.get('action_type', '?')} -> "
                f"{d.get('status', '?')}"
            ),
            "auction_resolved": lambda d: (
                f"  [AUCTION] Winner: {d.get('winner', '?')}, "
                f"Minted: {d.get('minted', 0)}"
            ),
            "budget_exhausted": lambda d: (
                f"=== BUDGET EXHAUSTED: ${d.get('spent', 0):.4f} ==="
            ),
            "error": lambda d: f"ERROR: {d.get('message', str(d))}",
        }
        formatter = formatters.get(event_type, lambda d: f"{event_type}: {d}")
        return formatter(data)
```

## Event Levels

| Level | Full Log | Readable Log | Use For |
|-------|----------|--------------|---------|
| DEBUG | Yes | If configured | Internal state, debugging |
| INFO | Yes | If event type matches | Normal operations |
| WARNING | Yes | Always | Recoverable issues |
| ERROR | Yes | Always | Failures |

## Example Outputs

### Full Log (run.jsonl)

```json
{"timestamp": "2026-01-12T10:30:00.123Z", "event_type": "tick_start", "tick": 1}
{"timestamp": "2026-01-12T10:30:00.456Z", "event_type": "agent_think_start", "agent_id": "alpha", "input_tokens": 1234}
{"timestamp": "2026-01-12T10:30:01.789Z", "event_type": "agent_think_end", "agent_id": "alpha", "output_tokens": 567}
{"timestamp": "2026-01-12T10:30:01.890Z", "event_type": "action_executed", "agent_id": "alpha", "action_type": "write", "status": "success"}
{"timestamp": "2026-01-12T10:30:02.000Z", "event_type": "tick_end", "tick": 1, "scrip": {"alpha": 95}}
```

### Readable Log (run.log)

```
10:30:00 [INFO] --- Tick 1 ---
10:30:01 [INFO]   alpha: write -> success
10:30:02 [INFO] --- Tick 2 ---
10:30:03 [INFO]   beta: invoke -> success
10:30:04 [WARNING] Agent gamma running low on compute (5 remaining)
10:30:05 [INFO]   [AUCTION] Winner: alpha, Minted: 50
```

## Viewing Logs

### Full Log Analysis

```bash
# View recent events
tail -20 run.jsonl | jq .

# Filter by event type
cat run.jsonl | jq 'select(.event_type == "action_executed")'

# Count events by type
cat run.jsonl | jq -r '.event_type' | sort | uniq -c

# Use view_log.py script
python scripts/view_log.py --type action_executed --last 10
```

### Readable Log

```bash
# Just read it
cat run.log

# Follow live
tail -f run.log

# Search for issues
grep -E "(WARNING|ERROR)" run.log
```

## Migration from Print Statements

Replace print statements with structured logging:

```python
# Before
if self.verbose:
    print(f"    {agent.agent_id}: {input_tokens} in, {output_tokens} out")

# After
self.logger.log("agent_think_end", {
    "agent_id": agent.agent_id,
    "input_tokens": input_tokens,
    "output_tokens": output_tokens,
}, level="DEBUG")
```

## Configuration Options

```yaml
logging:
  # Paths
  full_log: "logs/run.jsonl"       # Full structured log
  readable_log: "logs/run.log"     # Human-readable log

  # Readable log settings
  readable_level: INFO             # Minimum level for readable log
  readable_events:                 # Event types to include
    - simulation_start
    - simulation_end
    - tick_start
    - tick_end
    - action_executed
    - auction_resolved
    - budget_exhausted
    - checkpoint_saved
    - error
    - warning

  # Console output (optional)
  console_level: WARNING           # Only warnings/errors to console

  # Retention (optional)
  max_log_size_mb: 100            # Rotate when exceeded
  keep_last_n_runs: 5             # Keep last N run logs
```

## Benefits

| Concern | Full Log | Readable Log |
|---------|----------|--------------|
| Debugging | All details available | N/A (use full log) |
| Monitoring | Too verbose | Key events only |
| Post-mortems | Parse and analyze | Quick human review |
| Storage | Larger files | Smaller files |
| Machine processing | JSONL format | Text format |

## Trade-offs

- **Storage**: Two files instead of one (but readable is smaller)
- **Performance**: Two writes per event (but async IO mitigates)
- **Complexity**: More configuration (but sane defaults work)

## Origin

Adopted after finding simulation logs too verbose for human monitoring but needing full detail for debugging. The dual-output pattern provides both without compromise.
