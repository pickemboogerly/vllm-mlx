# SPDX-License-Identifier: Apache-2.0
"""
Gradio Text-Only Chatbot Interface for vllm-mlx.

A fast, text-only chat interface for LLM models.
Use this for text conversations without image/video overhead.

Usage:
    # First start the server with a model:
    vllm-mlx --model mlx-community/Llama-3.2-3B-Instruct-4bit --port 8000

    # Then run this app:
    vllm-mlx-text-chat

    # Or with custom settings:
    vllm-mlx-text-chat --server-url http://localhost:8000 --port 7861
"""

import argparse
import json
from pathlib import Path
import tempfile

import gradio as gr
import requests


def create_chat_function(server_url: str):
    """
    Create the chat function for Gradio ChatInterface.

    Args:
        server_url: URL of the vllm-mlx server

    Returns:
        Chat function compatible with the enhanced Gradio interface.
        The returned function has the signature:

            chat(
                message: str,
                history: list,
                system_prompt: str,
                model: str,
                max_tokens: int,
                temperature: float,
            ) -> str
    """

    def chat(
        message: str,
        history: list,
        system_prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """
        Process a text message and return response.

        Args:
            message: User's text message
            history: List of previous messages

        Returns:
            Assistant response text
        """
        # Build messages list for API
        messages = []

        # Optional system prompt as first message
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})

        # Add history
        for msg in history:
            if isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Extract text from multimodal content
                    text_parts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    content = " ".join(text_parts)
                messages.append({"role": role, "content": content})

        # Add current user message
        messages.append({"role": "user", "content": message})

        # Send request to server
        try:
            response = requests.post(
                f"{server_url}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=120,
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]

        except requests.exceptions.ConnectionError:
            return "Error: Cannot connect to server. Make sure vllm-mlx is running."
        except requests.exceptions.Timeout:
            return "Error: Timeout - server took too long to respond."
        except Exception as e:
            return f"Error: {str(e)}"

    return chat


def main():
    """Run the Gradio app."""
    parser = argparse.ArgumentParser(
        description="Gradio Text-Only Chat Interface for vllm-mlx",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Start with default settings
    vllm-mlx-text-chat

    # Connect to a different server
    vllm-mlx-text-chat --server-url http://localhost:9000

    # Create a public share link
    vllm-mlx-text-chat --share

Note: Make sure the vllm-mlx server is running:
    vllm-mlx --model mlx-community/Llama-3.2-3B-Instruct-4bit --port 8000
        """,
    )
    parser.add_argument(
        "--server-url",
        type=str,
        default="http://localhost:8000",
        help="URL of the vllm-mlx server (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7861,
        help="Port for Gradio interface (default: 7861)",
    )
    parser.add_argument(
        "--share",
        action="store_true",
        help="Create a public share link",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=512,
        help="Maximum tokens to generate (default: 512)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Sampling temperature (default: 0.7)",
    )
    args = parser.parse_args()

    print(f"Connecting to vllm-mlx server at: {args.server_url}")
    print(f"Starting Gradio text chat on port: {args.port}")

    # Create chat function used by the internal responder
    chat_fn = create_chat_function(server_url=args.server_url)

    # Feature flags (Phase 5: memory).
    enable_memory = True
    memory_summary_every_n_turns = 8

    # Define simple in-code presets for now. These can be
    # externalized to a config file in later phases.
    presets = {
        "default": {
            "label": "Default",
            "description": "Use CLI defaults for temperature and max_tokens.",
            "model": "default",
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
        },
        "creative": {
            "label": "Creative",
            "description": "Higher temperature for more diverse outputs.",
            "model": "default",
            "temperature": min(args.temperature + 0.3, 1.5),
            "max_tokens": args.max_tokens,
        },
        "precise": {
            "label": "Precise",
            "description": "Lower temperature for more focused answers.",
            "model": "default",
            "temperature": max(args.temperature - 0.3, 0.0),
            "max_tokens": args.max_tokens,
        },
    }

    preset_choices = [(cfg["label"], name) for name, cfg in presets.items()]

    # Session persistence location (Phase 4).
    session_dir = Path.home() / ".vllm_mlx_chat"
    session_file = session_dir / "sessions.json"

    def _default_initial_sessions():
        """Create a default single empty session."""
        return {
            "1": {
                "title": "Chat 1",
                "messages": [],
                "system_prompt": "",
                "preset": "default",
                "temperature": presets["default"]["temperature"],
                "max_tokens": presets["default"]["max_tokens"],
                "summary": "",
            }
        }

    def _load_sessions():
        """Load sessions from disk, falling back to a default."""
        try:
            if session_file.is_file():
                with session_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data:
                    return data
        except Exception:
            # On any error, fall back to a default in-memory structure.
            pass
        return _default_initial_sessions()

    def _save_sessions(sessions: dict) -> None:
        """Persist sessions to disk."""
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            with session_file.open("w", encoding="utf-8") as f:
                json.dump(sessions, f, ensure_ascii=False, indent=2)
        except Exception:
            # Persistence failures should not break the UI.
            pass

    # Load existing sessions if available, or fall back to a single default session.
    initial_sessions = _load_sessions()
    # Ensure there is at least one session and pick the smallest numeric id as active.
    numeric_ids = sorted(int(sid) for sid in initial_sessions.keys() if sid.isdigit())
    initial_session_id = str(numeric_ids[0]) if numeric_ids else "1"

    # Use a Blocks-based layout to allow future enhancements, including
    # multi-session support in memory.
    with gr.Blocks(title="vllm-mlx Text Chat") as demo:
        gr.Markdown(
            "## vllm-mlx Text Chat\n"
            "Fast text-only chat with LLM models on Apple Silicon."
        )

        # Global in-memory sessions state (Phase 3).
        sessions_state = gr.State(initial_sessions)
        active_session_id = gr.State(initial_session_id)

        # Main working area: sessions on the left, chat on the right.
        with gr.Row():
            # Left: session management
            with gr.Column(scale=1, min_width=220):
                session_dropdown = gr.Dropdown(
                    label="Sessions",
                    choices=[
                        (sess["title"], sid)
                        for sid, sess in initial_sessions.items()
                    ],
                    value=initial_session_id,
                    interactive=True,
                )
                session_title = gr.Textbox(
                    label="Session title",
                    placeholder="Name this chat (e.g. 'Bug triage')",
                    lines=1,
                )
                rename_chat_button = gr.Button("Rename")
                with gr.Row():
                    new_chat_button = gr.Button("New chat")
                    delete_chat_button = gr.Button("Delete")
                with gr.Row():
                    duplicate_chat_button = gr.Button("Duplicate")
                    export_chat_button = gr.Button("Export")

            # Right: primary chat experience
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(label="Conversation")
                msg = gr.Textbox(
                    label="Your message",
                    placeholder=(
                        "Enter to send, Shift+Enter for newline. "
                        "Slash commands like /summarize are supported."
                    ),
                    lines=3,
                    autofocus=True,
                )
                with gr.Row():
                    clear = gr.Button("Clear")
                    export_file = gr.File(
                        label="Exported session",
                        interactive=False,
                    )

                # Quick per-message controls under the input.
                with gr.Row():
                    preset_dropdown = gr.Dropdown(
                        label="Preset",
                        choices=preset_choices,
                        value="default",
                        interactive=True,
                    )
                    temperature_slider = gr.Slider(
                        label="Temperature",
                        minimum=0.0,
                        maximum=1.5,
                        value=args.temperature,
                        step=0.05,
                    )
                    enable_memory_checkbox = gr.Checkbox(
                        label="Memory",
                        value=enable_memory,
                    )

                # Attachments and debug tools.
                with gr.Row():
                    with gr.Column(scale=2):
                        attach_file = gr.File(
                            label="Attach text files as context (optional)",
                            file_types=["text"],
                            file_count="multiple",
                        )
                        gr.Markdown(
                            "_Attached files are included with your next message._"
                        )
                    with gr.Column(scale=1):
                        with gr.Accordion("Debug", open=False):
                            enable_debug_checkbox = gr.Checkbox(
                                label="Show debug request info",
                                value=False,
                            )
                            debug_info_box = gr.Textbox(
                                label="Last request (model / params / token hints)",
                                lines=6,
                                interactive=False,
                            )

        # Advanced session settings below the main area.
        with gr.Accordion("Advanced session settings", open=False):
            with gr.Row():
                with gr.Column(scale=2):
                    system_prompt = gr.Textbox(
                        label="System prompt",
                        placeholder=(
                            "Optional: instructions for this chat "
                            "(e.g. role, style, constraints)."
                        ),
                        lines=4,
                    )
                    memory_summary_box = gr.Textbox(
                        label="Conversation summary (read-only)",
                        lines=4,
                        interactive=False,
                    )
                with gr.Column(scale=1):
                    max_tokens_slider = gr.Slider(
                        label="Max tokens",
                        minimum=16,
                        maximum=max(args.max_tokens, 512),
                        value=args.max_tokens,
                        step=16,
                    )

        def _build_chatbot_history(messages):
            """Convert stored messages into Gradio Chatbot messages format.

            Newer Gradio versions expect a list of dictionaries, each with
            'role' and 'content' keys. We pass through our stored messages,
            filtering to user/assistant roles for display.
            """
            formatted = []
            for m in messages:
                role = m.get("role")
                content = m.get("content", "")
                if role in {"user", "assistant"}:
                    formatted.append({"role": role, "content": content})
            return formatted

        def _apply_slash_command(raw_message: str) -> tuple[str, str]:
            """Interpret simple slash commands and return (system_suffix, user_message)."""
            text = (raw_message or "").lstrip()
            if not text.startswith("/"):
                return "", raw_message

            parts = text.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "/summarize":
                sys_suffix = (
                    "You are summarizing the user's text. "
                    "Provide a concise summary highlighting key points."
                )
                return sys_suffix, arg or raw_message

            if cmd == "/translate":
                lang = arg or "English"
                sys_suffix = (
                    f"You are translating the user's text into {lang}. "
                    "Only output the translation."
                )
                return sys_suffix, arg or raw_message

            if cmd == "/fix":
                sys_suffix = (
                    "You are improving and correcting the user's text or code. "
                    "Preserve intent, fix errors, and improve clarity."
                )
                return sys_suffix, arg or raw_message

            # Unknown command: pass through unchanged
            return "", raw_message

        def respond(
            user_message,
            sessions,
            current_session_id,
            system_prompt_text,
            selected_preset,
            temperature_value,
            max_tokens_value,
            memory_enabled,
            attached_files,
            debug_enabled,
        ):
            """Send a message within the active session."""
            if sessions is None or not isinstance(sessions, dict):
                sessions = {}

            session_id = current_session_id or initial_session_id
            if session_id not in sessions:
                sessions[session_id] = {
                    "title": f"Chat {session_id}",
                    "messages": [],
                    "system_prompt": "",
                    "preset": "default",
                    "temperature": presets["default"]["temperature"],
                    "max_tokens": presets["default"]["max_tokens"],
                    "summary": "",
                }

            session = sessions[session_id]

            # Update session settings from UI
            session["system_prompt"] = system_prompt_text or ""
            session["preset"] = selected_preset or "default"
            session["temperature"] = float(temperature_value)
            session["max_tokens"] = int(max_tokens_value)
            session["enable_memory"] = bool(memory_enabled)

            preset_cfg = presets.get(session["preset"], presets["default"])
            model = preset_cfg["model"]

            # Handle optional attached files as extra context
            effective_user_message = user_message
            file_context = ""
            if attached_files:
                try:
                    contents = []
                    for f in attached_files:
                        file_path = (
                            f.name if hasattr(f, "name") else str(f)
                        )
                        with open(
                            file_path, "r", encoding="utf-8", errors="ignore"
                        ) as fh:
                            contents.append(fh.read())
                    if contents:
                        file_context = (
                            "\n\n[Attached file content]\n"
                            + "\n\n---\n\n".join(c.strip() for c in contents)
                        )
                except Exception:
                    file_context = "\n\n[Attached file(s) could not be read.]"

            # Apply slash command, if any, to refine system behavior
            slash_sys_suffix, cleaned_message = _apply_slash_command(
                effective_user_message
            )
            effective_user_message = cleaned_message + file_context

            # Call underlying chat function with the session's history
            history = session["messages"]
            # Combine system prompt with summary (if memory is enabled and present)
            combined_system_prompt = session["system_prompt"] or ""
            if slash_sys_suffix:
                combined_system_prompt = (
                    combined_system_prompt.rstrip()
                    + "\n\n[Slash command behavior]\n"
                    + slash_sys_suffix
                ).lstrip()
            if session.get("enable_memory") and session.get("summary"):
                combined_system_prompt = (
                    combined_system_prompt.rstrip()
                    + "\n\n[Conversation summary]\n"
                    + session["summary"]
                ).lstrip()

            assistant_reply = chat_fn(
                effective_user_message,
                history,
                combined_system_prompt,
                model,
                session["max_tokens"],
                session["temperature"],
            )

            # Update session history
            session["messages"] = history + [
                {"role": "user", "content": effective_user_message},
                {"role": "assistant", "content": assistant_reply},
            ]

            # Optionally update rolling summary every N user turns
            if session.get("enable_memory") and enable_memory and memory_summary_every_n_turns > 0:
                user_turns = sum(1 for m in session["messages"] if m.get("role") == "user")
                if user_turns % memory_summary_every_n_turns == 0:
                    # Build a plain-text transcript of the conversation so far
                    transcript_lines = []
                    for m in session["messages"]:
                        role = m.get("role", "")
                        content = m.get("content", "")
                        transcript_lines.append(f"{role.upper()}: {content}")
                    transcript = "\n".join(transcript_lines)

                    try:
                        # Use the backend model itself to summarize
                        summary_prompt = (
                            "You are a concise assistant that summarizes conversations.\n"
                            "Summarize the following conversation so far in a few sentences, "
                            "focusing on key facts, decisions, and tasks.\n\n"
                            f"{transcript}"
                        )
                        summary = chat_fn(
                            summary_prompt,
                            [],
                            "You summarize conversations.",
                            model,
                            256,
                            0.1,
                        )
                        if isinstance(summary, str):
                            session["summary"] = summary.strip()
                    except Exception:
                        # If summarization fails, keep the old summary.
                        pass

            sessions[session_id] = session

            # Optionally populate debug info text
            debug_text = ""
            if debug_enabled:
                debug_text = (
                    f"Model: {model}\n"
                    f"Temperature: {session['temperature']}\n"
                    f"Max tokens: {session['max_tokens']}\n"
                    f"Memory enabled: {session.get('enable_memory', False)}\n"
                    f"User chars (after transforms): {len(effective_user_message)}\n"
                    f"History turns: {len(session['messages'])}"
                )

            # Persist updated sessions to disk
            _save_sessions(sessions)

            chatbot_history = _build_chatbot_history(session["messages"])
            return (
                chatbot_history,
                "",
                sessions,
                session_id,
                session.get("summary", ""),
                debug_text,
            )

        def clear_chat(sessions, current_session_id):
            """Clear the visible chat and history for the active session."""
            if sessions is None or not isinstance(sessions, dict):
                sessions = {}

            session_id = current_session_id or initial_session_id
            if session_id not in sessions:
                sessions[session_id] = {
                    "title": f"Chat {session_id}",
                    "messages": [],
                    "system_prompt": "",
                    "preset": "default",
                    "temperature": presets["default"]["temperature"],
                    "max_tokens": presets["default"]["max_tokens"],
                    "summary": "",
                }

            session = sessions[session_id]
            session["messages"] = []
            session["summary"] = ""
            sessions[session_id] = session

            _save_sessions(sessions)

            return [], "", sessions, session_id, ""

        def new_chat(sessions, current_session_id):
            """Create a new empty session and switch to it."""
            if sessions is None or not isinstance(sessions, dict):
                sessions = {}

            # Generate a new numeric id
            if sessions:
                existing_ids = [int(sid) for sid in sessions.keys() if sid.isdigit()]
                next_id = str(max(existing_ids) + 1 if existing_ids else 1)
            else:
                next_id = "1"

            sessions[next_id] = {
                "title": f"Chat {next_id}",
                "messages": [],
                "system_prompt": "",
                "preset": "default",
                "temperature": presets["default"]["temperature"],
                "max_tokens": presets["default"]["max_tokens"],
                "summary": "",
            }

            _save_sessions(sessions)

            # Update dropdown choices
            choices = [(sess["title"], sid) for sid, sess in sessions.items()]

            return (
                sessions,
                next_id,
                gr.update(choices=choices, value=next_id),
                [],  # chatbot history
                "",  # input box
                "",  # system prompt
                "default",  # preset
                presets["default"]["temperature"],  # temperature slider
                presets["default"]["max_tokens"],  # max tokens slider
                "",  # memory summary
            )

        def switch_session(selected_session_id, sessions):
            """Switch to an existing session from the dropdown."""
            if sessions is None or not isinstance(sessions, dict):
                sessions = {}

            session_id = selected_session_id or initial_session_id
            if session_id not in sessions:
                sessions[session_id] = {
                    "title": f"Chat {session_id}",
                    "messages": [],
                    "system_prompt": "",
                    "preset": "default",
                    "temperature": presets["default"]["temperature"],
                    "max_tokens": presets["default"]["max_tokens"],
                    "summary": "",
                }

            session = sessions[session_id]
            chatbot_history = _build_chatbot_history(session["messages"])

            return (
                chatbot_history,
                session["title"],
                session["system_prompt"],
                session["preset"],
                session["temperature"],
                session["max_tokens"],
                sessions,
                session_id,
                session.get("summary", ""),
            )

        def rename_chat(sessions, current_session_id, new_title):
            """Rename the active session and update the dropdown."""
            if sessions is None or not isinstance(sessions, dict):
                sessions = {}

            title = (new_title or "").strip()
            if not title:
                # If no new title provided, keep the existing one.
                return (
                    sessions,
                    current_session_id,
                    gr.update(),  # no change to dropdown
                    title,
                )

            session_id = current_session_id or initial_session_id
            if session_id not in sessions:
                sessions[session_id] = _default_initial_sessions()["1"]

            sessions[session_id]["title"] = title
            _save_sessions(sessions)

            choices = [(sess["title"], sid) for sid, sess in sessions.items()]

            return (
                sessions,
                session_id,
                gr.update(choices=choices, value=session_id),
                title,
            )

        def delete_chat(sessions, current_session_id):
            """Delete the active session and switch to another if possible."""
            if sessions is None or not isinstance(sessions, dict):
                sessions = {}

            session_id = current_session_id or initial_session_id
            if session_id in sessions:
                del sessions[session_id]

            if not sessions:
                sessions = _default_initial_sessions()

            # Pick next active session (smallest numeric id)
            numeric_ids = sorted(
                int(sid) for sid in sessions.keys() if sid.isdigit()
            )
            next_id = str(numeric_ids[0]) if numeric_ids else "1"

            _save_sessions(sessions)

            # Update dropdown choices
            choices = [(sess["title"], sid) for sid, sess in sessions.items()]
            session = sessions[next_id]
            chatbot_history = _build_chatbot_history(session["messages"])

            return (
                sessions,
                next_id,
                gr.update(choices=choices, value=next_id),
                chatbot_history,
                "",
                session["system_prompt"],
                session["preset"],
                session["temperature"],
                session["max_tokens"],
                session.get("summary", ""),
            )

        def duplicate_chat(sessions, current_session_id):
            """Duplicate the active session into a new one."""
            if sessions is None or not isinstance(sessions, dict):
                sessions = {}

            session_id = current_session_id or initial_session_id
            if session_id not in sessions:
                sessions[session_id] = _default_initial_sessions()["1"]

            # Generate a new numeric id
            if sessions:
                existing_ids = [int(sid) for sid in sessions.keys() if sid.isdigit()]
                next_id = str(max(existing_ids) + 1 if existing_ids else 1)
            else:
                next_id = "1"

            base = sessions[session_id]
            sessions[next_id] = {
                "title": f"{base['title']} (copy)",
                "messages": list(base["messages"]),
                "system_prompt": base.get("system_prompt", ""),
                "preset": base.get("preset", "default"),
                "temperature": base.get(
                    "temperature", presets["default"]["temperature"]
                ),
                "max_tokens": base.get(
                    "max_tokens", presets["default"]["max_tokens"]
                ),
                "summary": base.get("summary", ""),
            }

            _save_sessions(sessions)

            # Update dropdown choices
            choices = [(sess["title"], sid) for sid, sess in sessions.items()]
            session = sessions[next_id]
            chatbot_history = _build_chatbot_history(session["messages"])

            return (
                sessions,
                next_id,
                gr.update(choices=choices, value=next_id),
                chatbot_history,
                "",
                session["system_prompt"],
                session["preset"],
                session["temperature"],
                session["max_tokens"],
                session.get("summary", ""),
            )

        def export_chat(sessions, current_session_id):
            """Export the active session as a JSON file."""
            if sessions is None or not isinstance(sessions, dict):
                sessions = {}

            session_id = current_session_id or initial_session_id
            if session_id not in sessions:
                sessions[session_id] = _default_initial_sessions()["1"]

            session = sessions[session_id]

            # Create a temporary file with the session JSON
            fd, path = tempfile.mkstemp(
                prefix=f"vllm_mlx_chat_{session_id}_", suffix=".json"
            )
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(session, f, ensure_ascii=False, indent=2)

            return path

        msg.submit(
            respond,
            inputs=[
                msg,
                sessions_state,
                active_session_id,
                system_prompt,
                preset_dropdown,
                temperature_slider,
                max_tokens_slider,
                enable_memory_checkbox,
                attach_file,
                enable_debug_checkbox,
            ],
            outputs=[
                chatbot,
                msg,
                sessions_state,
                active_session_id,
                memory_summary_box,
                debug_info_box,
            ],
        )

        clear.click(
            clear_chat,
            inputs=[sessions_state, active_session_id],
            outputs=[
                chatbot,
                msg,
                sessions_state,
                active_session_id,
                memory_summary_box,
            ],
        )

        new_chat_button.click(
            new_chat,
            inputs=[sessions_state, active_session_id],
            outputs=[
                sessions_state,
                active_session_id,
                session_dropdown,
                chatbot,
                msg,
                session_title,
                system_prompt,
                preset_dropdown,
                temperature_slider,
                max_tokens_slider,
                memory_summary_box,
            ],
        )

        session_dropdown.change(
            switch_session,
            inputs=[session_dropdown, sessions_state],
            outputs=[
                chatbot,
                session_title,
                system_prompt,
                preset_dropdown,
                temperature_slider,
                max_tokens_slider,
                sessions_state,
                active_session_id,
                memory_summary_box,
            ],
        )

        rename_chat_button.click(
            rename_chat,
            inputs=[sessions_state, active_session_id, session_title],
            outputs=[sessions_state, active_session_id, session_dropdown, session_title],
        )

        delete_chat_button.click(
            delete_chat,
            inputs=[sessions_state, active_session_id],
            outputs=[
                sessions_state,
                active_session_id,
                session_dropdown,
                chatbot,
                msg,
                system_prompt,
                preset_dropdown,
                temperature_slider,
                max_tokens_slider,
                memory_summary_box,
            ],
        )

        duplicate_chat_button.click(
            duplicate_chat,
            inputs=[sessions_state, active_session_id],
            outputs=[
                sessions_state,
                active_session_id,
                session_dropdown,
                chatbot,
                msg,
                system_prompt,
                preset_dropdown,
                temperature_slider,
                max_tokens_slider,
                memory_summary_box,
            ],
        )

        export_chat_button.click(
            export_chat,
            inputs=[sessions_state, active_session_id],
            outputs=export_file,
        )

    demo.launch(
        server_port=args.port,
        share=args.share,
    )


if __name__ == "__main__":
    main()
