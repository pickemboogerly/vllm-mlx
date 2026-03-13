## vllm-mlx Gradio Chat Enhancement Plan

This document tracks the long-running plan to evolve the **text-only Gradio app** into a near-ChatGPT experience with power-user features, while keeping the implementation lightweight and maintainable.

It is written so that another LLM (or future you) can restore context without previous chat history.

---

### 1. Current state (as of March 2026)

- **Multimodal app**: `vllm_mlx/gradio_app.py`
  - Uses `gr.ChatInterface` with `multimodal=True` and `gr.MultimodalTextbox`.
  - Sends messages to `POST {server_url}/v1/chat/completions` with:
    - `model: "default"`
    - `messages`: built from chat history, including encoded images/videos.
  - CLI flags: `--server-url`, `--port`, `--share`, `--max-tokens`, `--temperature`, `--text-only`.
  - Intended to stay relatively simple; it already does multimodal and is “good enough” as an advanced demo.

- **Text-only app**: `vllm_mlx/gradio_text_app.py`
  - Uses a simple `gr.ChatInterface` with a single `chat_fn`.
  - Builds a `messages` list from history + current message and POSTs to the same `/v1/chat/completions` endpoint with:
    - `model: "default"`
    - `max_tokens`, `temperature` from CLI.
  - No concepts of sessions, presets, memory, system prompts, or debug tools yet.

**Design decision:** The text-only app will become the **power-user, ChatGPT-like interface**, while the multimodal app stays simple and focused on multimodal demoing.

---

### 2. Target capabilities (high-level)

We want the text-only Gradio app to:

- **Match core ChatGPT UX**
  - Multi-turn chat with markdown + code rendering.
  - Multi-session chat history (sidebar listing conversations).
  - Per-session system instructions.
  - Ability to export/import conversations.

- **Support power-user workflows**
  - Configurable **presets** (model + sampling params + system prompt).
  - **System prompt templates** library.
  - Optional **“memory”** via rolling summaries + pinned context.
  - Basic **slash commands** (`/summarize`, `/translate`, `/fix`, etc.).
  - Per-request parameter overrides and a small **debug panel**.

- **Stay lightweight**
  - Keep dependencies minimal (Gradio + requests + maybe PyYAML or plain JSON).
  - Use simple on-disk JSON/YAML files for configs and histories.
  - Offload heavy features (e.g. RAG indexing) to separate scripts, not the Gradio runtime.

---

### 3. Data & configuration model

These concepts are used across the plan.

#### 3.1 Session model

Each chat session represents one conversation tab/chat in the UI:

- `id: str` – unique identifier (e.g. UUID or incrementing int as string).
- `title: str` – auto-titled from early messages; user can rename.
- `created_at: float` – timestamp.
- `updated_at: float` – timestamp.
- `preset_name: str | None` – which preset is active for this session.
- `system_prompt: str` – system instructions for the entire chat.
- `messages: list[dict]` – OpenAI-style conversation:
  - `{"role": "system" | "user" | "assistant", "content": str | list}`.
  - We will treat content as **pure text** here (multimodal is for the other app).
- Optional advanced fields:
  - `pinned_snippets: list[str]` – user-pinned context to prepend.
  - `summary: str | None` – rolling summary for memory (if enabled).

**Persistence:**

- Store sessions in a simple JSON file, e.g. `~/.vllm_mlx_chat/sessions.json`.
- Shape:
  - `{"sessions": {<id>: <Session>, ...}, "active_session_id": <id or null>}`.
- Periodically or on-change, write back to disk if a “Save history” option is enabled.

#### 3.2 Presets (`presets.yaml` or in-code defaults)

Presets define “profiles” like Coding, Reasoning, Creative:

- `name: str` – internal name (id).
- `label: str` – human-readable label for dropdown.
- `description: str` – short explanation for tooltips.
- `model: str` – model name passed to the backend.
- `temperature: float`
- `top_p: float | None`
- `max_tokens: int`
- Optional: `system_prompt: str` – default system prompt for this preset.

Implementation options:

- **Phase 1–2**: Hard-code a `PRESETS` dict in Python.
- **Phase 3+**: Move to `presets.yaml` loaded at startup (with minimal third-party deps).

#### 3.3 System prompt templates (`system_prompts.yaml` or in-code defaults)

These provide reusable instruction blocks:

- `id: str`
- `label: str`
- `prompt: str` – the text to insert into the session-level system prompt.

These can be combined or appended to the session system prompt from a dropdown.

#### 3.4 App config (`config.yaml`, optional)

Global configuration to avoid hardcoding:

- `server_url_default: str`
- `available_models: list[str]`
- Feature flags:
  - `enable_history: bool`
  - `enable_memory: bool`
  - `enable_debug_panel: bool`
  - `enable_presets: bool`
- Defaults for `max_tokens`, `temperature` if not overridden by CLI.

CLI args (e.g. `--server-url`, `--max-tokens`) should override config values.

---

### 4. UI layout (for `gradio_text_app.py`)

We will replace the simple `gr.ChatInterface` with a custom `gr.Blocks` layout.

#### 4.1 High-level layout

- **Left sidebar**
  - **Sessions list**:
    - Vertical list of buttons or a `gr.Radio`/`gr.Dropdown` showing session titles.
    - Buttons: “New chat”, “Duplicate”, “Delete”, “Export”.
  - **Presets**:
    - `gr.Dropdown` of presets.
    - Button: “Set as default for new chats”.
  - Checkbox: “Store chats on this machine” (toggles persistence).

- **Center (main)**
  - Top:
    - `gr.Accordion` or `gr.Group` with:
      - `System prompt` textbox (multi-line, per session).
      - Display of current model + preset name.
  - Middle:
    - `gr.Chatbot` showing the conversation.
  - Bottom:
    - `gr.Textbox` for user input.
    - “Send” button (submits).
    - “Stop” button (cancels in-flight request, if feasible).
    - Short help text indicating keyboard shortcuts.

- **Right sidebar (advanced)**
  - `gr.Accordion` labeled “Advanced / Power tools”:
    - **Sampling controls**: temperature, top_p, max_tokens.
    - **Prompt templates** dropdown + “Insert into system prompt”.
    - **Pinned context** view: list of pinned snippets with “Unpin” buttons.
    - **Debug panel** (if enabled):
      - Last request parameters (model, temperature, max_tokens).
      - Token estimates (if easy to get).
      - Last latency and any error messages.

#### 4.2 State wiring

Use Gradio `State` to hold:

- `sessions_state: dict` – mapping session ids to session objects.
- `active_session_id: str | None`.
- Optional: `app_config` loaded at launch.

All event handlers (send, new chat, rename, delete, change preset, modify system prompt) will modify this state and then refresh the visible components.

---

### 5. Chat function behavior

The new chat function will have a richer signature than the original simple `chat(message, history)`.

#### 5.1 Inputs and state (conceptual)

The function will receive (through Gradio wiring):

- `user_message: str`
- `sessions_state: dict` (State)
- `active_session_id: str` (State)
- Current UI controls values:
  - `selected_preset_name: str`
  - `system_prompt_text: str`
  - Sampling settings (temperature, top_p, max_tokens) from sliders.

Outputs:

- Updated chatbot messages to display.
- Updated `sessions_state`.
- Updated `active_session_id` (usually unchanged).

#### 5.2 Building the API request

Steps:

1. **Resolve active session**
   - If `active_session_id` is `None`, create a new session and set it active.
2. **Apply pending UI changes**
   - Set the session’s `preset_name` from dropdown.
   - Update `system_prompt` from the system prompt textbox.
3. **Interpret slash commands in `user_message` (optional)**
   - If `user_message` starts with `/`, transform into a structured prompt (e.g. `/summarize`).
4. **Build `messages` list**
   - Start with a `system` message if `system_prompt` is non-empty.
   - Prepend pinned snippets as a separate `system` or `user` message, if any.
   - Append existing `messages` from the session.
   - Append the new `user` message.
5. **Determine parameters**
   - Start from preset’s model and sampling params.
   - Override with UI controls if they differ.
6. **Call backend**
   - POST to `f"{server_url}/v1/chat/completions"` with:
     - `model`
     - `messages`
     - `max_tokens`
     - `temperature`, `top_p` if applicable.
7. **Update session**
   - Append the new user message and assistant response to `session["messages"]`.
   - Update `updated_at`.
   - If auto-titling conditions are met (e.g. first assistant response present and `title` looks like a placeholder), generate a title (heuristic or via model) and store it.
   - If memory is enabled, update `summary` every N turns.
8. **Persist sessions (if enabled)**
   - Save `sessions_state` to disk.

The function returns the updated conversation (for `gr.Chatbot`) and updated states.

---

### 6. “Memory” and pinned context

These are optional enhancements that can be turned off via config.

#### 6.1 Rolling summary memory

- Maintain a `summary: str | None` in each session.
- Every N turns (configurable, e.g. every 8 user messages):
  - Ask the backend model for a concise summary of the conversation so far.
  - Replace or append to `summary`.
- For each request:
  - Prepend the summary as a system message, e.g.:
    - “Conversation summary so far (do not repeat verbatim, just use as context): ...”

#### 6.2 Pinned context

- Allow user to pin any previous message (user or assistant).
- Store short text snippets in `session["pinned_snippets"]`.
- On each request, include pinned snippets near the top of the `messages` list, ahead of the main conversation, so they are always considered as context.

---

### 7. Multi-session history behavior

Key flows:

- **New chat**
  - Create a fresh session with:
    - `preset_name` set to default preset.
    - Empty `messages`, default or empty `system_prompt`.
  - Switch `active_session_id`.
  - Clear `Chatbot` display.

- **Switch session**
  - On selecting a session from sidebar:
    - Set `active_session_id`.
    - Load its messages into `Chatbot`.
    - Load its `system_prompt` and `preset_name` into the corresponding components.

- **Duplicate session**
  - Clone an existing session (deep copy messages & settings, new id and title).

- **Delete session**
  - Remove from `sessions_state`.
  - Persist to disk.
  - If deleted was active, pick another session or create a new one.

- **Export session**
  - Provide a button that exports the active session as:
    - JSON (raw messages + metadata), or
    - Markdown (human-readable transcript).

---

### 8. Power-user tools and ergonomics

These features are nice-to-have but should not bloat the baseline UX.

- **Slash commands**
  - Recognize `"/summarize"`, `"/translate <lang>"`, `"/fix"`, etc.
  - Internally adjust the `system` and `user` messages for that single request.

- **Message-level actions**
  - At minimum: “Copy to clipboard” and “Use as prompt” (populate textbox).
  - If practical: “Pin as context” from a message.

- **Debug panel**
  - Show last request payload (or a safe version), parameters, and response metadata.
  - Useful for advanced users; hide behind a toggle (config + UI).

---

### 9. Phased implementation plan

This is the recommended order of work, so progress is incremental and testable.

#### Phase 1 – Switch to `Blocks` and keep behavior equivalent

- In `vllm_mlx/gradio_text_app.py`:
  - Replace `gr.ChatInterface` with a `gr.Blocks` layout containing:
    - One `gr.Chatbot`.
    - One input `gr.Textbox`.
    - A “Send” button.
  - Wire the existing `chat_fn` into this layout so behavior is unchanged.
  - Keep the current CLI and request construction logic.

Deliverable: UI still simple, but using `Blocks`, so it can be extended.

#### Phase 2 – Single-session enhancements with presets and system prompt

- Add:
  - System prompt textbox above the chat.
  - Preset dropdown backed by a small in-code `PRESETS` dict.
  - Sampling sliders (temperature, max_tokens) tied to the request.
- Update chat function to:
  - Prepend system prompt as a system message.
  - Use preset + slider values when calling `/v1/chat/completions`.

Deliverable: A much more configurable single-session chat.

#### Phase 3 – Multi-session support (in-memory only)

- Introduce `sessions_state` and `active_session_id` as Gradio `State` objects.
- Implement:
  - “New chat” button.
  - Sidebar list of sessions (titles).
  - Switching between sessions.
- Store full messages and settings per session in memory.

Deliverable: Multiple chats in one app instance, but not yet persisted to disk.

#### Phase 4 – Persistent history

- Implement JSON-based persistence:
  - On launch, load sessions from file (if present).
  - On each mutation, write sessions back to file, if “Store chats” is enabled.
- Add buttons:
  - Delete session.
  - Duplicate session.
  - Export active session (JSON and/or Markdown).

Deliverable: Chat history survives reloads and can be backed up/exported.

#### Phase 5 – Memory and pinned context (optional)

- Add:
  - Pinned snippets per session and UI to manage them.
  - Rolling summary that is periodically updated and used as context.
- Make both controlled by config flags to keep minimal setups lean.

Deliverable: Basic “knowledge retention” closer to ChatGPT-like memory.

#### Phase 6 – Slash commands and power tools

- Implement a small parser for leading `/` commands.
- Add a debug panel and maybe simple stats (latency).
- Consider text-file upload support for code/data context.

Deliverable: A strong power-user experience without significantly increasing code complexity.

---

### 10. Notes for future implementers / LLMs

- The **backend contract** is the OpenAI-compatible `/v1/chat/completions` endpoint already used in both apps. Do not change this without updating both apps.
- Prefer **small, testable changes** per phase. After each phase:
  - Start the text app (e.g. `vllm-mlx-text-chat`) and manually verify core flows.
- If Gradio API versions change, re-check how `State` and `Blocks` wiring are done, but keep the high-level layout and state concepts intact.
- The multimodal app in `gradio_app.py` should remain relatively simple; major feature work should target the text app unless there is a specific need.

