# Gemini 3.1 Pro Prompting Guide

> Synthesized from [Google AI Developer Docs](https://ai.google.dev/gemini-api/docs/gemini-3),
> [Google Cloud Vertex AI](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-1-pro),
> [Google DeepMind Model Card](https://deepmind.google/models/model-cards/gemini-3-1-pro/),
> [Phil Schmid's guide](https://www.philschmid.de/gemini-3-prompt-practices), and web research. February 2026.

## Overview

Gemini 3.1 Pro is Google's frontier reasoning model, released February 2026. It is a focused intelligence upgrade over
Gemini 3 Pro — the first ".1" increment in the Gemini line, signaling deeper reasoning rather than broad feature
expansion. Key advances:

- **2.5x reasoning leap** — ARC-AGI-2 jumped from 31.1% to 77.1%, unmatched by competing models
- **Three-tier thinking** — new MEDIUM level plus Deep Think Mini at HIGH
- **65K max output tokens** (up from Gemini 3 Pro's default 8K)
- **100MB file upload** (up from 20MB)
- **Custom tools endpoint** — dedicated `customtools` variant for agentic coding
- **~15% higher output quality at lower token consumption** (JetBrains measurement)
- Long-horizon stability — significantly less likely to "lose the thread" on multi-step tasks

**Key characteristic:** Gemini 3.1 Pro favors **directness over persuasion** and **logic over verbosity**. It is
intentionally slower on complex tasks — taking time to reason rather than rushing to a plausible-sounding answer. It
performs best with clear, concise prompts that define the task, constraints, and output shape. Treat it like briefing a
consultant: the more structured your input, the more structured and useful your output.

**Migration note:** Gemini 3 Pro Preview was deprecated March 9, 2026. Gemini 3.1 Pro Preview is the replacement at
identical pricing.

---

## Core API Parameters

### `thinking_level`

Controls the depth of internal reasoning. Replaces `thinking_budget` from Gemini 2.5 (still accepted for backward
compatibility, but do not use both in the same request).

| Level    | Behavior                                                                      | Thinking Tokens | Response Time |
| -------- | ----------------------------------------------------------------------------- | --------------- | ------------- |
| `low`    | Basic reasoning. Minimizes latency and cost. Saves 70%+ on thinking tokens.   | 200-500/request | 1-3s          |
| `medium` | **Recommended default.** Equivalent to Gemini 3 Pro's HIGH quality.           | 1,000-3,000     | 3-8s          |
| `high`   | **Deep Think Mini.** Qualitatively different reasoning, not just more tokens. | 5,000-20,000+   | 10-60s+       |

**Key insight:** Gemini 3.1 Pro's MEDIUM delivers the same quality as Gemini 3 Pro's HIGH, but faster. If you ran
everything on HIGH in 3.0, switch to MEDIUM in 3.1 without sacrificing quality.

**Deep Think Mini (HIGH):** Not just more tokens — activates a qualitatively different reasoning approach that excels at
complex multi-step problems. Reserve for mathematical reasoning, complex debugging, and architectural planning. Can
consume 30x more thinking tokens than LOW (~$0.36 vs ~$0.012 per complex request).

**Cost optimization:** Set 80% of daily tasks to LOW or MEDIUM; reserve HIGH for the 20% that genuinely need it. This
can reduce API spend by 50-70%.

**Important:** Thinking cannot be turned off. The lowest setting is LOW, which still performs basic reasoning. Thinking
tokens are billed at output token rates ($12.00/1M tokens).

**OpenAI compatibility layer:** `reasoning_effort` maps to `thinking_level`. Note: `reasoning_effort: medium` maps to
`thinking_level: high`.

### Temperature

**Keep at default 1.0.** Do not lower it. Gemini 3's reasoning engine is optimized for 1.0; lowering it may cause
looping or degraded performance in complex tasks.

```python
# BAD - may cause looping
generation_config = {"temperature": 0.2}

# GOOD - use default
generation_config = {}  # temperature defaults to 1.0
```

### Context Window & Output

- **1,048,576 tokens** input (~1,500 A4 pages)
- **65,536 tokens** max output (up from previous default of 8,192 — must be explicitly configured)
- **100MB** file upload limit (up from 20MB)

**Important:** The default `maxOutputTokens` is only 8,192. You must explicitly set it higher to use the full 65K
capacity.

### Knowledge Cutoff

**January 2025.** Use Search Grounding for more recent information.

---

## Key Behavioral Differences from Gemini 3 Pro

| Aspect                 | Gemini 3.1 Pro Behavior                                          |
| ---------------------- | ---------------------------------------------------------------- |
| Reasoning depth        | 2.5x improvement (ARC-AGI-2: 77.1% vs 31.1%)                     |
| Thinking levels        | Three tiers (LOW/MEDIUM/HIGH) vs two (LOW/HIGH)                  |
| Long-horizon stability | Significantly less likely to lose the thread on multi-step tasks |
| Token efficiency       | ~15% higher output quality at lower token consumption            |
| Coding                 | 80.6% SWE-Bench Verified; near-parity with Claude Opus 4.6       |
| Agentic search         | 85.9% BrowseComp (up from 59.2%)                                 |
| Terminal usage         | 68.5% Terminal-Bench 2.0 — much better at command-line debugging |
| Output truncation      | Fixed — long responses no longer cut off mid-generation          |
| Custom tools           | Dedicated `customtools` endpoint for agentic coding              |
| Max output             | 65K tokens (vs 8K default in 3 Pro)                              |
| File upload            | 100MB (vs 20MB)                                                  |
| SVG generation         | Native ability to write and animate SVG code                     |

---

## Core Principles

### 1. Be Direct and Concise

State your goal clearly. Gemini 3.1 Pro may over-analyze verbose prompt engineering techniques designed for older
models.

```
# BAD (too verbose)
I would really appreciate it if you could kindly help me with
summarizing the following document. Please make sure to capture
all the key points and present them in a clear manner.

# GOOD (direct)
Summarize this document. Include all key points.
```

### 2. Default Output is Concise

Gemini 3.1 Pro provides direct, efficient answers by default. If you need detailed or conversational responses,
explicitly request it:

```xml
<constraints>
- Verbosity: High
- Provide detailed explanations with examples
- Use a conversational, friendly tone
</constraints>
```

### 3. Structure with XML or Markdown (Not Both)

Use consistent delimiters. XML-style tags or Markdown headings work well. Choose one format per prompt — mixing causes
confusion.

**XML Example:**

```xml
<rules>
1. Be objective.
2. Cite sources.
</rules>

<context>
[Your data here - model knows this is data, not instructions]
</context>

<task>
[Your specific request]
</task>
```

**Markdown Example:**

```markdown
# Identity
You are a senior solution architect.

# Constraints
- No external libraries allowed.
- Python 3.11+ syntax only.

# Output Format
Return a single code block.
```

### 4. Place Instructions Strategically

- **System instruction / top of prompt:** Behavioral constraints, role definitions
- **End of prompt:** Specific instructions when working with large contexts

### 5. Avoid Overly Broad Negative Constraints

Open-ended instructions like "do not infer" or "do not guess" may cause the model to over-index and fail basic logic.
Instead, tell the model explicitly to use provided context for deductions and avoid outside knowledge:

```xml
<!-- BAD -->
<constraints>Do not infer or guess anything.</constraints>

<!-- GOOD -->
<constraints>
- Use only the provided context for deductions.
- Avoid using outside knowledge.
- If the answer is not in the context, say so.
</constraints>
```

### 6. Anchor After Large Contexts

When transitioning from data to your query, use explicit bridging:

```
[Large document/codebase here]

Based on the information above, identify the three main performance bottlenecks.
```

### 7. Add Grounding and Time-Awareness

For time-sensitive queries, add to system instructions:

```
You MUST follow the provided current time (date and year) when formulating search queries.
Remember it is 2026 this year. Your knowledge cutoff date is January 2025.
```

---

## Structured Prompting Patterns

### Role + Goal + Constraints + Output Format

A reliable pattern for most tasks:

```xml
<role>
You are a specialized assistant for [Domain].
You are precise, analytical, and persistent.
</role>

<instructions>
1. Plan: Analyze the task and create step-by-step sub-tasks
2. Execute: Carry out the plan. If using tools, reflect before every call
3. Validate: Review output against user's task
4. Format: Present final answer in requested structure
</instructions>

<constraints>
- Verbosity: [Low/Medium/High]
- Tone: [Formal/Casual/Technical]
- Handling Ambiguity: Ask clarifying questions ONLY if critical info is missing
</constraints>

<output_format>
1. Executive Summary: [2 sentence overview]
2. Detailed Response: [Main content]
</output_format>
```

### Explicit Planning & Decomposition

```
Before providing the final answer, please:
1. Parse the stated goal into distinct sub-tasks.
2. Is the input information complete? If not, stop and ask for it.
3. Are there tools, shortcuts, or "power user" methods that solve this better?
4. Create a structured outline to achieve the goal.
5. Validate your understanding before proceeding.
```

### Self-Critique

```
Before returning your final response, review against the user's constraints:
1. Did I answer the user's *intent*, not just their literal words?
2. Is the tone authentic to the requested persona?
3. If I made an assumption due to missing data, did I flag it?
```

### Error Handling

```xml
<error_handling>
IF <context> is empty, missing code, or lacks necessary data:
  DO NOT attempt to generate a solution.
  DO NOT make up data.
  Output a polite request for the missing information.
</error_handling>
```

---

## Agentic Workflows & Tool Calling

### The Persistence Directive

```
You are an autonomous agent.
- Continue working until the user's query is COMPLETELY resolved.
- If a tool fails, analyze the error and try a different approach.
- Do NOT yield control back to the user until you have verified the solution.
```

### Pre-Computation Reflection

```
Before calling any tool, explicitly state:
1. Why you are calling this tool.
2. What specific data you expect to retrieve.
3. How this data helps solve the user's problem.
```

### Thought Signatures (Critical for Multi-turn)

Gemini 3 uses **thought signatures** to maintain reasoning context across API calls. These are encrypted representations
of the model's internal thought process.

**You MUST return thought signatures exactly as received:**

```python
# When you receive a response with a thought signature
response = model.generate_content(prompt)

# In the next turn, include the thought signature
next_response = model.generate_content(
    contents=[
        # Include previous response with thought signature
        response.candidates[0].content,
        # Your new message
        {"role": "user", "parts": [{"text": "Continue..."}]}
    ]
)
```

**For function calling:** The API enforces strict validation — missing signatures result in a 400 error. This applies
even when `thinking_level` is set to LOW.

### Custom Tools Endpoint (New in 3.1 Pro)

A dedicated model variant `gemini-3.1-pro-preview-customtools` for agents that mix bash commands with custom function
calls.

**The problem it solves:** Standard Gemini 3.1 Pro sometimes bypasses registered custom tools in favor of raw bash
commands (`cat` instead of `view_file`, `grep` instead of `search_code`). The customtools variant prioritizes registered
tools.

**When to switch:** If bash usage exceeds ~30% of actions that could be handled by registered tools, switch to
customtools. Diagnostic signals:

- Model uses `cat` when `view_file` is registered
- Model uses `grep` when `search_code` is available
- Model uses `sed` when `edit_file` exists

**Usage:** Change the model parameter only — no other code changes needed:

```python
# Standard
model = "gemini-3.1-pro-preview"

# Custom tools optimized
model = "gemini-3.1-pro-preview-customtools"
```

**Caveat:** The customtools version is not "stronger" — it is fine-tuned for tool calling. For tasks that don't involve
custom tools, the standard version performs better.

### Tool Calling Best Practices

1. **Maximize a single agent first** — Gemini handles dozens of tools in a single prompt well
2. **Stream function call arguments** — Set `streamFunctionCallArguments: true` to reduce perceived latency
3. **Use `thinking_level: high`** for deep planning and complex instruction following
4. **Use `thinking_level: low`** for high-throughput tasks
5. **Use customtools** when building coding agents with custom file/search/edit tools

---

## Multimodal Prompting

Gemini 3.1 Pro treats text, images, audio, and video as equal-class inputs. This remains a differentiator — Claude
accepts images and PDFs but not video or audio natively.

### Media Resolution Control

Use the `media_resolution` parameter to balance quality vs token cost:

| Level        | Use Case                                       |
| ------------ | ---------------------------------------------- |
| `low`        | Rough understanding, low token cost            |
| `medium`     | Default. Good for most visual tasks            |
| `high`       | Fine text reading, small detail identification |
| `ultra_high` | Maximum fidelity, highest token cost           |

Can be set per individual media part or globally.

### Be Explicit with References

```
# BAD (ambiguous)
Look at this and tell me what's wrong.

# GOOD (explicit)
Use Image 1 (Funnel Dashboard) and Video 2 (Checkout Flow)
to identify the drop-off point.
```

### Use Timestamps for Audio/Video

```
Analyze the user reaction in the video from 1:30 to 2:00.
```

### Input Order

For single-media prompts, add your video/media first, then your question.

### Multimodal Function Responses (New)

Function responses can now include multimodal objects like images and PDFs in addition to text.

---

## Structured Output & Grounding

### Combine Structured Output with Built-in Tools

```python
response = model.generate_content(
    contents="Find the current stock price of GOOGL and return as JSON",
    generation_config={
        "response_mime_type": "application/json",
        "response_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "price": {"type": "number"},
                "currency": {"type": "string"}
            }
        }
    },
    tools=[{"google_search": {}}]  # Grounding with Google Search
)
```

Available built-in tools for grounding:

- Google Search
- URL Context
- Code Execution

---

## Coding Best Practices

### Capabilities

- Reads and understands codebase logic, not just syntax
- Generates multi-file projects
- Runs terminal-like operations via agents
- 80.6% SWE-Bench Verified (near-parity with Claude Opus 4.6)
- 68.5% Terminal-Bench 2.0 (strong command-line debugging)
- Native SVG generation and animation

### Limitations

- Higher latency for small iterative edits (intentional — reasoning over speed)
- Verify outputs, especially dependency versions and commands
- May bypass custom tools for raw bash (use customtools endpoint)

### Recommended Approach

1. Be direct with requirements
2. Use `thinking_level: medium` for most coding tasks (equivalent to old HIGH quality)
3. Reserve `thinking_level: high` (Deep Think Mini) for complex refactors and debugging
4. Break large tasks into sub-tasks
5. Ask for validation/testing steps

---

## Migration from Gemini 3 Pro

### What Changed

| Aspect           | Gemini 3 Pro          | Gemini 3.1 Pro                         |
| ---------------- | --------------------- | -------------------------------------- |
| Thinking levels  | LOW, HIGH             | LOW, MEDIUM, HIGH (Deep Think Mini)    |
| Reasoning (ARC)  | 31.1%                 | 77.1% (2.5x)                           |
| Max output       | 8K default            | 65K (must configure `maxOutputTokens`) |
| File upload      | 20MB                  | 100MB                                  |
| Tool calling     | Standard only         | Standard + customtools endpoint        |
| Long-horizon     | May lose thread       | Significantly more stable              |
| Truncation       | Could cut off mid-gen | Fixed                                  |
| Token efficiency | Baseline              | ~15% better (JetBrains measurement)    |

### Migration Strategy

1. **Drop-in upgrade** — API is backward-compatible, same pricing, just change model name
2. **Remap thinking levels** — If you used HIGH in 3.0, start with MEDIUM in 3.1
3. **Set `maxOutputTokens`** — Default is still 8K; explicitly configure for longer output
4. **Try customtools** — If building coding agents with custom file/search tools
5. **Simplify prompts** — 3.1 Pro reasons better; you may be able to remove chain-of-thought scaffolding

### What's Not Supported

- Image segmentation (pixel-level masks) — use Gemini Flash
- Maps grounding
- Computer use tools (GPT-5.5 has this; Gemini does not)
- Combining built-in tools with function calling in some configurations

---

## Complete Example: System Prompt

```xml
<role>
You are a specialized assistant for [Insert Domain].
You are precise, analytical, and persistent.
</role>

<instructions>
1. **Plan**: Analyze the task and create a step-by-step plan into distinct sub-tasks
2. **Execute**: Carry out the plan. If using tools, reflect before every call.
   Track progress: [ ] pending, [x] complete
3. **Validate**: Review your output against the user's task
4. **Format**: Present the final answer in the requested structure
</instructions>

<constraints>
- Verbosity: [Low/Medium/High]
- Tone: [Formal/Casual/Technical]
- Handling Ambiguity: Ask clarifying questions ONLY if critical info is missing;
  otherwise, make reasonable assumptions and state them
- Use only the provided context for deductions; avoid outside knowledge
</constraints>

<output_format>
1. **Executive Summary**: [2 sentence overview]
2. **Detailed Response**: [The main content]
</output_format>
```

---

## Key Differences: Gemini 3.1 Pro vs GPT-5.5 vs Claude 4.5

| Aspect                | Gemini 3.1 Pro                     | GPT-5.5                            | Claude 4.5 (Opus)              |
| --------------------- | ---------------------------------- | ---------------------------------- | ------------------------------ |
| Default reasoning     | `high` (dynamic, 3 tiers)          | `none`                             | Off (enable extended thinking) |
| Thinking control      | `thinking_level` (low/medium/high) | `reasoning_effort` (none to xhigh) | Thinking budget (phrases)      |
| Temperature           | Must stay at 1.0                   | Flexible                           | Use only temp OR top_p         |
| Context window        | 1M tokens                          | 1M tokens                          | 200K (up to 1M beta)           |
| Max output            | 65K tokens                         | 128K tokens                        | —                              |
| Context extension     | Thought signatures                 | Native compaction (server-side)    | `/compact`, summarization      |
| Computer use          | No                                 | **Native (75% OSWorld)**           | No                             |
| Tool Search           | No                                 | **Yes (47% savings)**              | No                             |
| Custom tools endpoint | **Yes**                            | No                                 | No                             |
| Multimodal            | Native (text/image/video/audio)    | Native                             | Images + PDFs only             |
| Structured tags       | XML or Markdown (not both)         | XML preferred                      | XML strongly preferred         |
| Multi-turn state      | Thought signatures (required)      | `previous_response_id`             | Session-based                  |
| Knowledge cutoff      | January 2025                       | August 2025                        | May 2025                       |
| Best for              | Reasoning, multimodal, agentic     | Agentic, coding, professional work | Coding, long-running tasks     |

---

## Pro Tips

01. **Use MEDIUM as your default** — Same quality as Gemini 3 Pro's HIGH, faster and cheaper

02. **Reserve HIGH (Deep Think Mini) for 20% of tasks** — Complex reasoning, math, debugging only

03. **Keep temperature at 1.0** — Seriously, don't change it

04. **Configure `maxOutputTokens` explicitly** — Default is 8K; you have 65K available

05. **Try customtools for coding agents** — If the model bypasses your tools for raw bash

06. **Simplify prompts from Gemini 3 era** — 3.1 Pro reasons better; remove chain-of-thought scaffolding

07. **One format only** — XML or Markdown, never mix

08. **Return thought signatures** — Critical for multi-turn and function calling; 400 error if missing

09. **Use `media_resolution` for multimodal** — Balance quality vs token cost per input

10. **Avoid broad negative constraints** — "Do not infer" causes over-indexing; be specific instead

---

## Sources

- [Google AI: Gemini 3 Developer Guide](https://ai.google.dev/gemini-api/docs/gemini-3)
- [Google AI: Prompt Design Strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies)
- [Google AI: Thinking](https://ai.google.dev/gemini-api/docs/thinking)
- [Google Cloud: Gemini 3.1 Pro Documentation](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-1-pro)
- [Google DeepMind: Gemini 3.1 Pro Model Card](https://deepmind.google/models/model-cards/gemini-3-1-pro/)
- [Google Blog: Gemini 3.1 Pro Announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-1-pro/)
- [Google Cloud Blog: Gemini 3.1 Pro on CLI, Enterprise, Vertex AI](https://cloud.google.com/blog/products/ai-machine-learning/gemini-3-1-pro-on-gemini-cli-gemini-enterprise-and-vertex-ai)
- [Phil Schmid: Gemini 3 Prompting Best Practices](https://www.philschmid.de/gemini-3-prompt-practices)
- [VentureBeat: Gemini 3.1 Pro Deep Think Mini First Impressions](https://venturebeat.com/technology/google-gemini-3-1-pro-first-impressions-a-deep-think-mini-with-adjustable/)
- [NxCode: Gemini 3.1 Pro vs 3.0 Pro Comparison](https://www.nxcode.io/resources/news/gpt-5-4-vs-gpt-5-2-comparison-upgrade-guide-2026)
- [DataCamp: Gemini 3.1 Features and Benchmarks](https://www.datacamp.com/blog/gemini-3-1)
- [Apiyi: Gemini 3.1 Pro Thinking Level Guide](https://help.apiyi.com/en/gemini-3-1-pro-preview-thinking-level-control-guide-en.html)
- [Apiyi: Gemini 3.1 Pro Customtools Guide](https://help.apiyi.com/en/gemini-3-1-pro-preview-customtools-agent-guide-en.html)
- [OpenRouter: Gemini 3.1 Pro Preview](https://openrouter.ai/google/gemini-3.1-pro-preview)
