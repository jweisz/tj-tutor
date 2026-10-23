# tj-tutor

> A Socratic tutor for TJBot -- TJBot asks the questions, the student finds the "aha moment," on whatever subject you give it.

tj-tutor turns TJBot into a conversational Socratic tutor. The subject isn't hardcoded -- a lesson is just a YAML file describing a few concepts, each one requiring a genuine "aha moment" rather than a fact TJBot could just state. Nothing is a scripted dialogue tree -- an LLM drives every question, every judgment of what the student actually understands, and every decision about when to move on, hint, or celebrate. TJBot tracks progress on each concept independently, lets the conversation jump topics naturally (and picks back up where it left off), and reacts physically: a light show and a wave when a concept is truly mastered, a gentle color pulse when something isn't quite right.

The recipe ships with one example lesson, `lessons/space_basics.yaml`, which teaches three genuine "aha moments" about outer space to kids ages 6-8: that looking up means looking back in time, that the stars are just other suns almost unimaginably far away, and that a "year" is simply one trip around a sun. See [Customize](#customize) for teaching something else entirely.

## Requirements

[![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-3B+-cc342d)](https://www.raspberrypi.org/)
![Microphone](https://img.shields.io/badge/Hardware-Microphone-orange)
![LED](https://img.shields.io/badge/Hardware-LED-orange)
![Speaker](https://img.shields.io/badge/Hardware-Speaker-orange)
![Servo](https://img.shields.io/badge/Hardware-Servo-orange)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab)](https://python.org/)

The hardware above is only needed when running with `--interface tjbot`. By default this recipe runs with `--interface console`, which plays out the entire lesson in this terminal instead -- no Raspberry Pi, microphone, LED, or servo required. That's the easiest way to develop or try out a lesson before ever deploying it to a real TJBot.

Either way, you'll also need one LLM backend:

- [Ollama](https://ollama.com) running locally with a model pulled (e.g. `ollama pull gemma4:e2b`) -- free, no API key, and the default.
- [LM Studio](https://lmstudio.ai) (desktop app) or llmster (its headless daemon) serving a model, on this machine or another one on your network. See [Using LM Studio or llmster](#using-lm-studio-or-llmster).
- An [Anthropic API key](https://console.anthropic.com) -- put it in a `.env` file and set `provider = "anthropic"` in `recipe.toml` for noticeably better dialogue quality and judgment. See [Configure](#configure) for how to set it up.

## How It Works

Each turn runs two LLM calls against whichever provider is configured:

1. **Evaluate** -- a small, structured call reads the student's last reply and judges it against the current concept's mastery rubric: is this about the concept being taught right now, a *different* one of the lesson's concepts, or genuinely off-topic? Did it reveal a known misconception? Does it satisfy one or more rubric criteria?
2. **Respond** -- a second, free-form call generates the next thing TJBot actually says: a guiding follow-up question, a hint pulled from that concept's hint ladder if the student seems stuck, a warm celebration if they just nailed it, or a nudge back to an earlier topic they wandered away from before finishing it.

If the student raises a different concept mid-conversation, TJBot follows them there and remembers to circle back to the abandoned one once the new one is mastered. Off-topic tangents get a brief, kind acknowledgment and a steer back, with no effect on progress. The session ends once every concept in the lesson is mastered.

While this runs, a terminal dashboard (built with [Rich](https://github.com/Textualize/rich)) shows the learning plan and current concept, the evidence collected toward mastering each one, live LLM inference stats (latency, tokens, cache hits, estimated cost), and a scrolling debug log -- useful whether you're watching a console session or sitting next to the real robot.

## Configure

> [!CAUTION]
> Make sure you have configured your Raspberry Pi for TJBot by following the [setup instructions](https://github.com/tjbot-ce/tjbot/wiki/Bring-TJBot-to-Life). This only matters if you plan to run with `--interface tjbot` -- the default console mode needs no Pi setup at all.

All of this recipe's settings live under `[tutor]` in `recipe.toml`:

```toml
[tutor]
lesson_path = "lessons/space_basics.yaml"
interface = "console"          # "console" (this terminal) | "tjbot" (real hardware)

[tutor.llm]
provider = "ollama"            # "anthropic" | "ollama" | "lmstudio"
ollama_model = "gemma4:e2b"
anthropic_model = "claude-sonnet-4-6"
anthropic_effort = "low"        # "low" | "medium" | "high" -- anthropic only
ollama_host = "http://localhost:11434"
ollama_reasoning = "none"       # "none" | "low" | "medium" | "high" -- ollama reasoning models only
lmstudio_model = ""             # empty = first model the server lists
lmstudio_host = "http://localhost:1234"
lmstudio_reasoning = "none"     # "none" | "low" | "medium" | "high" -- lmstudio reasoning models only
```

`lesson_path` and `interface` can also be overridden for a single run without editing the file, via `--lesson` and `--interface` command-line flags. Everything under `[tutor.llm]` (provider, model, effort, Ollama/LM Studio host and reasoning) is recipe.toml-only -- edit the file to change your LLM backend.

If `provider = "anthropic"`, you need an `ANTHROPIC_API_KEY`. Copy `.env.sample` to `.env` and fill in your key:

```sh
cp .env.sample .env
# then edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is gitignored, so the key never gets committed, and it persists across runs/reboots (handy on a headless Pi) without polluting your shell profile. The recipe loads it automatically on startup via [python-dotenv](https://pypi.org/project/python-dotenv/); a real exported `ANTHROPIC_API_KEY` environment variable always takes precedence over the file if both are set.

> [!TIP]
> If you're using Claude Code to develop this recipe, this repo's `.claude/settings.json` already denies the `Read` tool access to `./.env`, so Claude can't read your key out of the file. That blocks the normal file-reading tools (Read/Grep/Glob), but it isn't an airtight sandbox -- a Bash command can still technically `cat .env` if explicitly instructed to. Don't paste your key into chat, and treat this as a guardrail against accidental exposure, not a hard security boundary.

## Run

You can run this recipe using the `tjbot` command or you can run it manually using `mise`.

### Run using `tjbot run`

Open a Terminal and run the following command (this assumes you checked out the project to your `Desktop` folder):

```sh
tjbot run /home/pi/Desktop/tj-tutor/
```

> [!NOTE]
> `tjbot` invokes `mise` under the hood, which will automatically install any required software dependencies before running the recipe.

You should see the following output:

```sh
$ tjbot run /home/pi/Desktop/tj-tutor

[start] $ uv run main.py

🤖 TJBot says: Hello there! I'm TJBot, and I'm so excited to explore outer space
with you today. Have you ever noticed that during a thunderstorm, you see the
lightning flash first, and then you hear the thunder boom a little bit later?
Why do you think that happens?

...
```

### Run manually using `mise`

Open a Terminal, navigate to this recipe's directory, and run using `mise`.

```sh
cd /home/pi/Desktop/tj-tutor
mise run start
```

## Customize

### Customization 1: Teach a different topic

This recipe ships with one lesson, `lessons/space_basics.yaml`, covering the three concepts described in [How It Works](#how-it-works). To teach something else instead:

1. Write a lightweight *seed* file describing your new concepts -- just an `id`, `domain`, `title`, and one-paragraph `summary` per concept (see `scripts/seeds/space_basics.seed.yaml` for the exact format).
2. Expand it into a full lesson plan with the bootstrap script, which calls an LLM once per concept to generate the Socratic teaching strategy, mastery rubric, hints, and misconceptions, then validates and writes the result as YAML:
   ```sh
   uv run python scripts/bootstrap_lesson.py \
     --seed scripts/seeds/my_topic.seed.yaml \
     --out lessons/my_topic.yaml \
     --provider anthropic
   ```
   Review the generated file before using it -- small local models in particular can need some hand-polishing.
3. Point the recipe at it: set `lesson_path = "lessons/my_topic.yaml"` in `recipe.toml`, or pass `--lesson lessons/my_topic.yaml` on the command line.

### Customization 2: Switch the LLM backend and model

By default this recipe runs entirely offline against a local Ollama model -- free, private, and no API key needed. For better dialogue quality and more reliable judgment of what a student actually understands, switch to Anthropic's API by editing `[tutor.llm]` in `recipe.toml`:

```toml
[tutor.llm]
provider = "anthropic"
anthropic_model = "claude-sonnet-4-6"
anthropic_effort = "low"        # "low" | "medium" | "high" -- trades latency/cost for response quality
```

(see [Configure](#configure) for setting up `ANTHROPIC_API_KEY` in `.env`). Any locally-pulled Ollama model can be used the same way via `ollama_model`.

#### Running models locally: speed and model choice

> [!CAUTION]
> Local models (whether through Ollama or LM Studio) can be **very slow** on modest hardware, and on a Raspberry Pi a single turn can take tens of seconds. That's long enough for the conversation to stop feeling like a conversation. Decide where the model runs before deploying to a real TJBot.

Each turn makes **two** LLM calls (evaluate, then respond), and each one sends roughly 1,000 tokens of prompt (persona, lesson content, and recent conversation) before generating a short reply. On a machine without a GPU, *reading that prompt* is usually the bulk of the wait, not writing the answer. So a turn's latency mostly depends on the hardware the model runs on:

| Where the model runs | Typical feel | Notes |
| --- | --- | --- |
| Anthropic API | A few seconds per turn | Fastest and best judgment, but needs internet and an API key. |
| A Mac (Apple Silicon) or a PC with a GPU, via Ollama or LM Studio | A few seconds per turn | E.g. Gemma 4 E4B in LM Studio on an iMac takes about 2-4 s per call once loaded. TJBot reaches it over your network (`ollama_host` / `lmstudio_host`). |
| The Raspberry Pi itself (CPU only) | Tens of seconds per turn | Works fully offline, but is slow. Fine for testing, sluggish for a child. |

**Recommended model: Google Gemma 4.** It was the best local model in our [evaluator tests](#evaluator-test-results), ahead of larger Qwen 3.5 and Granite 4.2 models. Pick the size for where it runs:

| Where the model runs | Model | Ollama | LM Studio / llmster |
| --- | --- | --- | --- |
| Raspberry Pi | Gemma 4 E2B (the default) | `gemma4:e2b` | `google/gemma-4-e2b` |
| Mac or GPU PC, serving TJBot over the network | Gemma 4 E4B | `gemma4:e4b` | `google/gemma-4-e4b` |

E4B scored 93% on the evaluator test suite and E2B scored 78%. E2B's misses all go the safe way: it never pulls the lesson off course, but it doesn't follow a student who asks about the *next* topic early, and it doesn't flag misconceptions. It's also the fastest model we tested, which matters most on a Pi. Other models work too (any Ollama or LM Studio model name will do), but the evaluator needs one that reliably follows a JSON schema. Tiny (~1B) models misjudge student answers much more often, and bigger isn't automatically better: both 8-9B models we tested scored lower than Gemma 4 E4B.

**Tips for keeping it responsive:**

- **Serve the model from a faster machine** if you have one. Run Ollama or LM Studio on a Mac or PC and point TJBot's Pi at it. No other changes are needed.
- **Keep reasoning off.** Reasoning models (Gemma 4, Granite 4.2, Qwen3, ...) can take many times longer when they think before answering. Both local providers disable this by default (`ollama_reasoning` / `lmstudio_reasoning = "none"`). Some model builds ignore this setting, though. If LM Studio's log says *"No valid custom reasoning fields found... Reasoning setting 'off' cannot be converted"*, that model will think anyway.
- **Keep the model loaded.** The first call after the model loads, or after it unloads from sitting idle, is much slower than the rest.
- **Watch the dashboard.** The stats panel shows per-call latency, so you can compare models directly. `thinking_delay_secs` controls how soon TJBot says it's thinking, so the student isn't left in silence.

#### Evaluator test results

The part of the tutor most sensitive to model quality is the **evaluator**: the structured call that decides whether a student's message is about the current concept, a different concept, or off-topic, and which rubric criteria it satisfies. A wrong call has visible consequences. If "I like pizza" is judged to be about another concept, TJBot abandons the current topic and switches to it.

`scripts/eval_evaluator.py` runs a fixed set of 18 student messages through the evaluator and scores each result by what the orchestrator would actually do with it. The set covers answers to the current concept, a misconception, off-topic chatter, and questions about the other two concepts, all written for `lessons/space_basics.yaml`. Use it to compare models before deploying, and re-run it after changing the evaluator prompt in `tutor/evaluator.py`:

```sh
uv run python scripts/eval_evaluator.py --provider lmstudio --model google/gemma-4-e4b \
  --host http://192.168.1.50:1234 --repeats 3
uv run python scripts/eval_evaluator.py --provider anthropic --model claude-sonnet-4-6
```

Local models vary from run to run, so use `--repeats 3` for them. `--verbose` prints passing cases too.

Results so far (October 2026, 3 runs each; local models served by LM Studio on an Apple Silicon iMac; latency is the median per evaluator call):

| Model | Provider | Passed | Median latency | Notes |
| --- | --- | --- | --- | --- |
| `claude-sonnet-4-6` | anthropic | 54/54 (100%) | 2.1 s | Reference. |
| `google/gemma-4-e4b` (4-bit) | lmstudio | 50/54 (93%) | 2.5 s | Best local option tested. Misses are mild: it sometimes keeps "is the sun a star?" on the current concept instead of switching. |
| `google/gemma-4-e2b` (4-bit) | lmstudio | 42/54 (78%) | 1.0 s | Fastest tested. Fails the same 4 cases every run, all in the safe direction: it calls questions about the other concepts off-topic (so TJBot steers back instead of following) and misses the misconception. Never derails the lesson. |
| `qwen/qwen3.5-9b` (4-bit) | lmstudio | 46/54 (85%) | 3.0 s | Larger but less consistent: misses the misconception, and sometimes calls orbit or star questions off-topic. |
| `granite-4.2-8b-mlx` (8-bit) | lmstudio | 35/54 (65%) | 3.8 s | Over-cautious: calls many genuine answers off-topic, so students miss credit, though it never derails the lesson. LM Studio can't turn this MLX build's reasoning off (see the tip above). |

What we learned along the way, which is mostly why the current evaluator looks the way it does:

- **Small models over-apply emphatic rules.** An earlier prompt said "you MUST set other_concept" when a message was about another concept. Gemma and Qwen then sent nearly every off-topic message to *some* concept (Gemma 11/18, Qwen 7/18 on a single run). Ordering the decision with off-topic first, and presenting it as a normal answer, fixed most of that.
- **Constrain ids with the schema, not the prompt.** Models put criterion ids in `target_concept_id`, or wrote `"null"` and `"misconception id: instant_seeing"` into `criteria_met`. The evaluator's response schema now lists the lesson's actual ids as enums (`evaluator_result_model()`), so grammar-constrained backends can't produce an invalid one.
- **Forbid extra JSON keys.** Without `additionalProperties: false`, Qwen added an unrequested `reasoning` essay to every result, tripling latency (8-10 s down to 3 s).
- **Reasoning models need reasoning off, and builds differ.** With reasoning on, Gemma 4 spent its whole token budget thinking and returned empty replies. MLX Granite 4.2 can't have reasoning disabled in LM Studio, and LM Studio then files its JSON answer under `reasoning_content`. The LM Studio provider falls back to reading it from there.

Not yet tested: Raspberry Pi hardware (expect the same pass rates, with much higher latency) and Ollama. If you test them, add a row.

#### Using LM Studio or llmster

`provider = "lmstudio"` talks to LM Studio's OpenAI-compatible API. That API is served both by the [LM Studio](https://lmstudio.ai) desktop app and by **llmster**, LM Studio's headless daemon, which is handy for running models on a separate always-on box. In both cases the server can run on the same machine as TJBot or on another machine on your network.

**On the machine serving the model:**

- **Desktop app:** open the Developer tab, download and load a model, and start the server. If TJBot is on a *different* machine, also enable **Serve on Local Network** in Server Settings.
- **llmster (headless):**
  ```sh
  curl -fsSL https://lmstudio.ai/install.sh | bash   # installs llmster and the `lms` CLI
  lms daemon up                                      # start the daemon
  lms get google/gemma-4-e4b                         # download a model (gemma-4-e2b on a Pi)
  lms server start --bind 0.0.0.0                    # listen on the network (default port 1234)
  ```
  Leave off `--bind 0.0.0.0` if the tutor runs on the same machine. For a Raspberry Pi, see [Running llmster on a Raspberry Pi](#running-llmster-on-a-raspberry-pi) below.

**In `recipe.toml`** on the machine running the tutor:

```toml
[tutor.llm]
provider = "lmstudio"
lmstudio_host = "http://192.168.1.50:1234"   # the server's IP/hostname; http://localhost:1234 if local
lmstudio_model = "google/gemma-4-e4b"        # a key from `lms ls`; leave "" to use the first model listed
```

Check that the tutor's machine can reach the server with `curl http://192.168.1.50:1234/v1/models`.

> [!WARNING]
> Serving on the network makes the model reachable by anyone on that network. LM Studio recommends turning on **Require Authentication** in Server Settings when you do. If you do, create an API token there and put it in `.env` as `LM_API_TOKEN=...`. The tutor sends it automatically.

Many current small models (Gemma 4, Qwen3, ...) are *reasoning* models that think before answering. That makes them much slower, which is bad for a spoken conversation, so the tutor turns reasoning off by default (`lmstudio_reasoning = "none"`). Set it to `"low"`, `"medium"` or `"high"` to trade latency for judgment.

With JIT model loading on (LM Studio's default), the first request loads the model, so expect the first turn to be slow. The bootstrap script works with LM Studio too: `--provider lmstudio --host http://192.168.1.50:1234 --model <key>`.

#### Running llmster on a Raspberry Pi

llmster runs on 64-bit ARM Linux, so it can run on a Raspberry Pi. That can be TJBot's own Pi, or a second Pi that acts as a model server for one or more TJBots. Some things to know first:

- **Hardware:** use a Raspberry Pi 5, ideally with 8 GB of RAM or more. Older Pis (including the 3B+ that TJBot was originally built on) don't have enough memory or speed to run a useful model. Generation is CPU-only, so stick to small models (roughly 2-4B parameters, 4-bit quantized). Expect each turn to take tens of seconds. See [Running models locally: speed and model choice](#running-models-locally-speed-and-model-choice) before committing to this setup.
- **OS:** a **64-bit** Raspberry Pi OS (Bookworm or newer). Check with `uname -m`, which should print `aarch64`.

**1. Install llmster** (on the Pi that will serve the model):

```sh
sudo apt-get update && sudo apt-get install -y libatomic1   # the installer requires it
curl -fsSL https://lmstudio.ai/install.sh | bash
exec $SHELL -l       # pick up ~/.lmstudio/bin on your PATH
lms --help           # check that the install worked
```

**2. Download a model and try it out:**

```sh
lms daemon up                 # start llmster
lms get google/gemma-4-e2b    # the recommended model for a Pi
lms ls                        # shows the exact model key to put in recipe.toml
lms load <model-key>          # load it into memory
lms server start              # add --bind 0.0.0.0 if TJBot is on a different machine
curl http://localhost:1234/v1/models
```

**3. Point the tutor at it** in `recipe.toml`:

```toml
[tutor.llm]
provider = "lmstudio"
lmstudio_model = "google/gemma-4-e2b"         # the exact key from `lms ls`
lmstudio_host = "http://localhost:1234"       # llmster on TJBot's own Pi
# lmstudio_host = "http://llm-pi.local:1234"  # llmster on a separate Pi
```

Then run the recipe as usual (`mise run start`). The dashboard header should show `provider=lmstudio` and the model name.

**4. (Optional) Start llmster on boot.** Create `/etc/systemd/system/lmstudio.service`, replacing `pi` with your username and `<model-key>` with your model:

```ini
[Unit]
Description=LM Studio Server (llmster)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=pi
Environment="HOME=/home/pi"
ExecStartPre=/home/pi/.lmstudio/bin/lms daemon up
ExecStartPre=/home/pi/.lmstudio/bin/lms load <model-key> --yes
ExecStart=/home/pi/.lmstudio/bin/lms server start --bind 0.0.0.0
ExecStop=/home/pi/.lmstudio/bin/lms daemon down

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now lmstudio.service
systemctl status lmstudio
```

Drop `--bind 0.0.0.0` if only the local TJBot uses it. If you do serve on the network, consider turning on authentication and setting `LM_API_TOKEN` (see above). See LM Studio's [headless docs](https://lmstudio.ai/docs/developer/core/headless) for more details.

## Troubleshoot

If you are having difficulties in making this recipe work, please see the [troubleshooting guide](https://github.com/tjbot-ce/tjbot/wiki/Troubleshooting-TJBot).

## Contribute

If you would like to contribute to TJBot, please see the [contributor's guide](https://github.com/tjbot-ce/tjbot/wiki/Contributing-to-TJBot).

## License

This project is licensed under Apache-2.0.
