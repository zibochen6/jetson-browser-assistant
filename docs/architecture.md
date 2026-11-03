# Architecture

```text
English task → Qwen parsing → structured requirements
                           ↓
Actual DOM / public scene → adapter builds current legal candidates
                           ↓
                  Laya chooses operation + target
                           ↓
                  stale-state / target validation
                           ↓
                  Playwright UI execution
                           ↓
                 wait → fresh observation → repeat
                           ↓
           independent verifier → exports / terminal result
```

- Qwen3.5-4B runs through pinned CUDA llama.cpp, with thinking disabled and MTP
  depth2. It parses requests and supplies necessary input text; finite recovery
  is explicitly recorded. No MTP tuning/comparison is performed by setup.
- Laya v19s uses the original v5 wrapper with PyTorch CUDA and fast=False. It sees
  textual facts and candidates, not screenshots. Candidate grouping/input
  preparation is part of the API latency, not just bare model forward time.
- Flight adapters focus actual Trip.com controls, constrain city/airport categories,
  choose calendar dates deterministically and verify complete result cards.
- Whiteboard adapters expose public read/export APIs. Edit capabilities are clearly
  labeled executor capabilities encoded as choices, not fictitious DOM buttons.
  Geometry and low-level create/drag/type recipes belong to the executor. It never
  applies a generated scene via updateScene.
- A legal output can still be wrong. Independent completion checks, stale-target
  retries, no-progress detection and action/time budgets remain necessary.

Loopback endpoints:8790 flight service/visualizer;8791 Laya;8792 Qwen;8793 board.
Model requests never leave the device. There is no authentication on these local
control APIs; do not bind or forward them to an untrusted network.

Persistent profiles and process records live inside the checkout. Process control
checks both command identity and working directory before signaling a PID. Another
checkout cannot silently reuse the same fixed ports. Models and browsers outlive
terminal input loops; explicit stop commands own shutdown.

Extension requires three things: a reliable fresh observation, implemented legal
tools, and an independent success condition. Keep meaningful alternative candidates
for Laya; don't turn the entire task into one forced choice and claim model planning.
Evaluate new labels/states separately from demonstration tasks and keep failures.
