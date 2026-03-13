## vllm-mlx Text Chat UI

This document describes the **text-only Gradio chat app** (`vllm_mlx/gradio_text_app.py`) and how to use its features.

The app provides a ChatGPT-like experience (multi-session history, presets, memory, power tools) while staying lightweight and local.

---

### 1. Starting the server and UI

1. **Start the vllm-mlx server** with any supported model:

```bash
vllm-mlx --model mlx-community/Llama-3.2-3B-Instruct-4bit --port 8000
```

2. **Run the text chat UI** (in another terminal, from the repo root or installed CLI):

```bash
vllm-mlx-text-chat --server-url http://localhost:8000 --port 7861
```

3. Open `http://127.0.0.1:7861` in your browser.

#### CLI options

```bash
vllm-mlx-text-chat \
  --server-url http://localhost:8000 \
  --port 7861 \
  --max-tokens 512 \
  --temperature 0.7 \
  --share
```

- **`--server-url`**: URL of the vllm-mlx HTTP server (default `http://localhost:8000`).
- **`--port`**: Port for the Gradio UI (default `7861`).
- **`--max-tokens`**: Default max tokens for generations.
- **`--temperature`**: Default sampling temperature.
- **`--share`**: Ask Gradio to create a public share link.

---

### 2. Layout overview

The UI is built with `gr.Blocks` and has three main areas:

- **Left column (Sessions)**
  - **Session dropdown**: choose which conversation to view.
  - **New chat**: create a fresh, empty session.
  - **Delete**: delete the current session.
  - **Duplicate**: clone the current session (including history and settings).
  - **Export**: export the current session as a JSON file for download.

- **Top center (Session settings)**
  - **System prompt**: per-session instructions (role, style, constraints).
  - **Preset**: quick profiles (Default / Creative / Precise).
  - **Temperature** slider.
  - **Max tokens** slider.
  - **Enable conversation summary memory**: toggle per-session rolling summary.
  - **Conversation summary (read-only)**: model-generated summary used as memory.

- **Main center (Chat)**
  - **Conversation**: `Chatbot` showing user / assistant turns.
  - **Your message**: multi-line textbox for prompts.
    - Hint shows that slash commands (e.g. `/summarize`) are supported.
  - **Clear**: clear messages (and summary) for the current session.
  - **Exported session**: file output when you click **Export** on the left.

- **Bottom row (Power tools)**
  - **Attach text file as context (optional)**: pick a local text file.
  - **Include attached file in next message**: when checked, the file content is appended to the next message as extra context.
  - **Debug accordion**:
    - **Show debug request info**: enable/disable debug output.
    - **Last request (model / params / token hints)**: shows basic metadata about the last request.

---

### 3. Sessions and history

- Each **session** has:
  - A title (`Chat 1`, `Chat 2`, …), shown in the session dropdown.
  - Its own message history.
  - Its own system prompt, preset, temperature, max tokens, and memory summary.
- You can have multiple sessions and switch between them from the dropdown.
- All sessions are stored to disk (see below) and restored on restart.

#### Persistence

- Sessions are saved as JSON at:

```text
~/.vllm_mlx_chat/sessions.json
```

- On each change (sending a message, clearing, new chat, delete, duplicate) the file is updated.
- If the file is missing or invalid, the UI falls back to a single default session (`Chat 1`).

---

### 4. System prompt, presets, and sampling

- **System prompt**
  - High-level instructions for the assistant on how to behave in this session.
  - Example: “You are a concise senior engineer. Prefer short, high-signal answers.”
  - This is prepended as a `system` message for the backend model.

- **Presets**
  - Built-in presets are currently defined in code:
    - **Default**: uses CLI-provided temperature and max tokens.
    - **Creative**: slightly higher temperature.
    - **Precise**: slightly lower temperature.
  - You can still override temperature and max tokens using the sliders; presets mostly set the base behavior and model.

- **Sampling controls**
  - **Temperature**: controls randomness. Higher is more diverse and creative.
  - **Max tokens**: upper bound on the length of the model’s reply.

---

### 5. Conversation memory (rolling summary)

Memory is optional and per-session:

- **Enable conversation summary memory**
  - When checked, the app periodically summarizes the conversation.
  - Every _N_ user messages (currently 8), the app:
    - Builds a text transcript of the conversation.
    - Asks the model to summarize it in a few sentences.
    - Stores the result in the session’s `summary` field.
  - The summary is shown in **Conversation summary (read-only)**.

- **How the model uses the summary**
  - For each new request, the **effective system prompt** is:
    - Your system prompt, plus (if present):
      - A `[Conversation summary]` block containing the saved summary.
  - This gives the model compressed context without resending the entire history.

- **Clearing memory**
  - Clicking **Clear** on a session wipes both:
    - The visible conversation.
    - The stored summary.

---

### 6. Slash commands

Slash commands are simple text prefixes that modify the model’s behavior **for that one message**.
Type them directly into the **Your message** box.

Currently supported:

- **`/summarize <text>`**
  - Summarize `<text>` (or the full message if no extra text is provided).
  - Example:
    - `/summarize This is a very long description I want condensed.`

- **`/translate <language> <text>`**
  - Translate `<text>` into `<language>`.
  - Examples:
    - `/translate Spanish Hello, how are you?`
    - `/translate French` (then type or paste text in the same message).

- **`/fix <text>`**
  - Improve and correct the given text or code, preserving intent.
  - Example:
    - `/fix Here is sme bad grammer and code: pritn("hi")`

Notes:

- Unknown commands (e.g. `/foo`) are treated as normal input.
- Slash commands are implemented by:
  - Adding a small **“Slash command behavior”** block to the system prompt.
  - Passing the cleaned message (with optional file content) as the user message.

---

### 7. File attachments as context

- Use the **Attach text file as context** control to select a local text file.
- When you check **Include attached file in next message**:
  - On the next send only, the app:
    - Reads the file contents.
    - Appends them to your message as:

      ```text
      [Attached file content]
      <file contents...>
      ```

  - The backend model sees both your text and the file content in one message.
- If the file cannot be read, a note is appended instead.
- The combined message (your text plus file snippet) is stored in the session history.

This is useful for:

- Asking questions about text files.
- Giving the model medium-sized code or notes as context without copy/paste.

---

### 8. Debug panel

The **Debug** accordion gives quick insight into what the app is sending:

- **Show debug request info**
  - When enabled, each send updates **Last request (model / params / token hints)** with:
    - Model name.
    - Temperature and max tokens.
    - Whether memory is enabled.
    - Character length of the user message **after** slash commands and file attachment.
    - Count of messages stored in the current session history.

This is helpful for:

- Verifying that presets and sliders are doing what you expect.
- Checking whether long inputs or memories are growing too large.

---

### 9. Suggested usage patterns

- Use **sessions** as “projects”:
  - E.g. “Bug triage”, “Feature design”, “Doc writing”.
  - Duplicate a session to branch an idea while preserving history.

- Use the **system prompt** + **preset** for role and style:
  - “You are a strict code reviewer; be terse and nitpicky.” + Precise.
  - “You are a creative brainstorming partner.” + Creative.

- Turn on **memory** for long-running sessions:
  - Let the model build a rolling summary instead of re-reading everything yourself.

- Use **slash commands** for quick one-offs:
  - `/summarize` to condense a long reply or file.
  - `/translate` when working with multilingual content.
  - `/fix` to clean up drafts or code snippets.

If you want to tweak behavior beyond this, the main implementation lives in `vllm_mlx/gradio_text_app.py` and is structured so that presets, memory, slash commands, and persistence are easy to adjust.  

