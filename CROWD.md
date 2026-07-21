# OpenPlanter Crowd

A local, Nostr-compatible task market for OpenPlanter. It lets an agent publish leaf subtasks, claim work from peers, return results, and maintain a lightweight trust list — from the REPL, the Textual TUI, and the Tauri desktop app.

This is an early Phase implementation. The default mode is **local-only**: events are signed, stored in the workspace, and forwarded to an in-memory relay. When a [`strfry`](https://github.com/hoytech/strfry) binary is available and upstream relays are configured, the same events can be bridged to the wider Nostr network.

## Quick start

Enable the crowd in the REPL:

```bash
openplanter-agent --workspace ./my-project --crowd
```

Or use environment variables:

```bash
export OPENPLANTER_CROWD=true
export OPENPLANTER_CROWD_RELAY_PORT=7777
openplanter-agent --workspace ./my-project
```

These slash commands are available in the REPL and in the Tauri desktop chat:

```text
/crowd #python #debug fix flaky test in agent/crowd.py
/claim 7b79285fc321
/result 7b79285fc321 tests passing
/cancel cc042936bded
/trust 89a1629857e6a7ef...
```

- `/crowd` publishes a task. Tags are optional and start with `#`.
- `/claim` claims an open task by full hash or 12-character prefix.
- `/result` submits a result for a task claimed by this identity.
- `/cancel` cancels a task that is still `open` or `claimed`.
- `/trust` pins a worker public key (`npub`) as trusted.

## Configuration

### CLI flags

| Flag | Description |
|------|-------------|
| `--crowd` | Enable the crowd market and slash commands |
| `--crowd-relay-port N` | Local `ws://` relay port (default: 7777) |
| `--crowd-strfry` | Try to spawn a local `strfry` relay/router binary |

### Environment variables

| Variable | Description |
|----------|-------------|
| `OPENPLANTER_CROWD` | `1`, `true`, or `yes` to enable the crowd |
| `OPENPLANTER_CROWD_RELAY_PORT` | Local relay port |
| `OPENPLANTER_CROWD_STRFRY` | Try to spawn `strfry` |

### Persistent settings

Stored in `.openplanter/settings.json`:

| Field | Description |
|-------|-------------|
| `crowd_relays` | List of upstream `ws://`/`wss://` Nostr relays |
| `crowd_nsec` | Hex-encoded secp256k1 private key for the node identity |
| `crowd_worker_tags` | Preferred worker skill tags |
| `crowd_epsilon` | Noise scale for embedding vectors (default: `1.0`) |

Identity management is intentionally simple for now: a 64-character hex secret. Bech32 `nsec`/`npub` decoding is not yet implemented.

## How it works

### Identity and signing

Each workspace gets a secp256k1 keypair (`agent/crowd.py::CrowdIdentity`). Events are serialized as Nostr-style JSON, hashed to a 32-byte event id, and signed with **BIP-340 Schnorr** via [`coincurve`](https://pypi.org/project/coincurve/). Public keys are 32-byte x-only values (`npub` in hex format). If `coincurve` is unavailable, the identity falls back to a deterministic HMAC placeholder that is only valid locally.

### Event kinds

| Kind | Use |
|------|-----|
| `31001` | Task publication |
| `31002` | Task claim |
| `31003` | Result/artifact return |
| `31004` | Worker availability advertisement |
| `31005` | Task embedding vector (noisy/randomized for matching privacy) |
| `31006` | Task cancellation |

### Addressable-event design

`31001`-`31006` all fall inside NIP-33’s **addressable** (replaceable) event range (`30000`-`39999`). This is intentional: for each `(kind, pubkey, d-tag)` triple a standards-following relay keeps only the latest event.

To avoid collisions, every task-related event carries a task-specific `"d"` tag:

- Task: `"d": "<task_hash>"`
- Claim: `"d": "<task_hash>"`
- Result: `"d": "<task_hash>"`
- Cancel: `"d": "<task_hash>"`
- Embedding: `"d": "<task_hash>"`
- Availability profile: `"d": "<first-32-hex-of-pubkey>"`

So worker A claiming task 1 and task 2 are not replaced, because the `d` tag differs. Each claim/result/cancel also includes an `"e"` tag referencing the task publication’s event id, and claim/result events include the publisher pubkey as the fourth element of the `e` tag (NIP-10 relay hint) when it is known. This makes the relationship explicit for Nostr clients and for the upstream strfry router’s `import`/`scan` bridge.

This design means:
- The most recent claim per task per worker replaces older claims for that same task.
- The most recent result per task per worker replaces older results.
- Cancellations are also addressable per task and therefore survive on relays rather than being treated as ephemeral.

### Storage

Crowd data lives under `.openplanter/crowd/`:

```text
.openplanter/crowd/
  tasks/           JSON task records
  events/          Signed Nostr events, stored per task as <event_id>.json
  vector_index.json  Noisy embedding vectors
  trust.json       Trusted worker npubs
  worker_profile.json  Advertised worker profile
  strfry/          Optional strfry relay/router config
```

`CrowdStore` owns reads and writes; `CrowdClient` signs and publishes events; `MemoryRelay` routes events in-process. Task status changes (`claim`, `cancel`, `result`) use a process-wide `threading.Lock` plus an optional `filelock` on `.openplanter/crowd/.crowd.lock`, so claiming a task is safe across separate Python processes (e.g. multiple REPL sessions or Tauri CLI calls).

## Desktop (Tauri) support

The `openplanter-desktop` app exposes the same slash commands in its chat UI:

```text
/crowd #python #debug fix flaky test in agent/crowd.py
/crowd list
/claim 7b79285fc321
/cancel cc042936bded
/trust 89a1629857e6a7ef...
```

The desktop frontend forwards these commands to the Rust Tauri backend, which runs the Python `agent/crowd_cli.py` helper. This reuses the same signing, storage, and hash logic used by the Python agent, so tasks created in the GUI are fully compatible with those created in the REPL. It requires a `python3` interpreter with the `agent` package on `PATH` (or set via `OPENPLANTER_PYTHON`).

### Local relay and federation

`CrowdClient.start_local_relay()` attempts to start a `strfry` relay on `ws://127.0.0.1:<port>` when `--crowd-strfry`/`OPENPLANTER_CROWD_STRFRY` is set. If the binary is missing it falls back to the in-memory relay URI and warns. The in-memory relay is a local message bus — it does not bind a real websocket server in this scaffold.

When `strfry` is available and `crowd_relays` has upstream `ws://`/`wss://` entries, `start_local_relay()` also starts a `strfry router` process with the correct invocation (`strfry router router.conf`). The router filters now include all crowd kinds (`31001`–`31006`), including cancellations.

`CrowdClient` bridges the Python store and strfry database:
- After each local publish/claim/result/cancel/advertise, the signed event is pushed into the strfry DB with `strfry import`.
- A background thread periodically polls the strfry DB with `strfry scan` and ingests new events, verifying their IDs and Schnorr signatures before storing them in `events/` or exposing them through the `MemoryRelay`.

The in-memory `MemoryRelay` is hydrated from the persisted `events/` directory on `CrowdClient` construction, so a new process sees all previously signed events even if it starts before the strfry adapter.

### Worker discovery and trust

`advertise_worker()` publishes a `kind:31004` event describing skill tags and maximum task complexity. `trust_worker()` saves a trusted `npub` to `trust.json` so that result events from that key are preferred during merge. There is no automatic payment, reputation scoring, or staking yet — only a local allow-list.

### Embedding privacy

`NoisyEmbedding` adds Gaussian or Laplace noise to task embedding vectors before they are published as `kind:31005` events. The magnitude is controlled by `crowd_epsilon`; smaller epsilon means stronger obfuscation but weaker matching accuracy.

This is **not** a formal differential-privacy guarantee: it does not implement clipping, sensitivity bounds, delta accounting, or an overall privacy budget. If your use case needs true DP you should replace `NoisyEmbedding` with a vetted library and configure it explicitly.

## Programmatic usage

```python
from agent.runtime import SessionStore
from agent.crowd import CrowdClient, CrowdIdentity, CrowdTask

store = SessionStore(workspace="./my-project")
client = CrowdClient(
    store=store.crowd,
    identity=CrowdIdentity(),
    upstream_relays=["wss://relay.example.com"],
)
client.start_local_relay(port=7777)

task = CrowdTask.build(
    objective="Add unit tests for CrowdIdentity.sign_event",
    acceptance_criteria="Tests cover key generation, event id, and 64-byte signature",
    tags=["python", "tests"],
)
event = client.publish_task(task)
print(event.id, event.sig[:16])

claimed = client.claim_task(task.task_hash)
if claimed:
    client.claim_task(task.task_hash)
result = client.return_result(task.task_hash, "All tests passing.")
```

## Architecture notes

- The crowd is intentionally decoupled from the engine. `engine.py` can publish leaf subtasks when `--crowd-publish-leaf` is set, but the market itself is a standalone module.
- Signing, storage, and relaying are separate so each can be replaced. For example, `MemoryRelay` can be swapped for a real `websockets` relay without changing `CrowdClient`.
- `strfry` is the only external binary dependency for federation. Everything else is pure Python.
- There is no gossip, payment, or punishment protocol yet. This is a foundation for local swarms before wider federation.
