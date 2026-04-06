#!/usr/bin/env python3
"""Terminal chat UI for Rocky using Rich + Ollama."""

from __future__ import annotations

from dataclasses import dataclass
import textwrap
from typing import List

import requests
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "rocky"
EXIT_COMMANDS = {"quit", "exit", "q"}


@dataclass
class Message:
    role: str
    content: str


def build_header() -> Panel:
    title = Text("ROCKY CHAT", style="bold black on bright_cyan")
    subtitle = Text("Rocky | Eridian Engineer | Ship: The Blip-A", style="bold white")
    body = Group(title, subtitle)
    return Panel(body, border_style="bright_cyan", padding=(1, 2))


def build_footer(status: str, total_messages: int, hidden_messages: int) -> Panel:
    command_help = "Type message and press Enter | Commands: quit"
    history_text = f"Messages: {total_messages}"
    if hidden_messages > 0:
        history_text += f" | {hidden_messages} earlier hidden"
    content = Group(
        Text(command_help, style="cyan"),
        Text(f"Status: {status}", style="bold yellow"),
        Text(history_text, style="dim"),
    )
    return Panel(content, border_style="bright_blue", padding=(0, 1))


def message_panel(message: Message) -> Panel:
    if message.role == "user":
        return Panel(
            Text(message.content, style="bold cyan"),
            title="You",
            border_style="cyan",
            padding=(0, 1),
        )

    if message.role == "assistant":
        return Panel(
            Text(message.content, style="bold green"),
            title="Rocky",
            border_style="green",
            padding=(0, 1),
        )

    return Panel(
        Text(message.content, style="bold red"),
        title="Error",
        border_style="red",
        padding=(0, 1),
    )


def estimate_message_panel_height(content: str, content_width: int) -> int:
    if content_width <= 0:
        return 3

    wrapped_line_count = 0
    for line in content.splitlines() or [""]:
        wrapped = textwrap.wrap(
            line,
            width=content_width,
            replace_whitespace=False,
            drop_whitespace=False,
        )
        wrapped_line_count += max(1, len(wrapped))

    # Rich panel contributes top and bottom border lines around the content.
    return wrapped_line_count + 2


def build_conversation_panel(conversation: List[Message], console: Console) -> tuple[Panel, int]:
    if not conversation:
        empty_text = Text(
            "Start chatting with Rocky. He will remember earlier turns in this session.",
            style="dim",
        )
        return Panel(empty_text, title="Conversation", border_style="white"), 0

    # Keep newest messages visible by fitting panels into the available terminal rows.
    available_rows = max(4, console.size.height - 14)
    # Account for outer panel border + horizontal padding + inner message panel borders.
    estimated_content_width = max(20, console.size.width - 10)

    visible_reversed: List[Message] = []
    used_rows = 1  # one line for viewport text

    for message in reversed(conversation):
        message_height = estimate_message_panel_height(message.content, estimated_content_width)
        if used_rows + message_height > available_rows and visible_reversed:
            break
        visible_reversed.append(message)
        used_rows += message_height
        if used_rows >= available_rows:
            break

    visible_messages = list(reversed(visible_reversed))
    hidden_messages = len(conversation) - len(visible_messages)

    viewport = Text(f"Showing latest {len(visible_messages)} of {len(conversation)} messages", style="dim")
    if hidden_messages > 0:
        viewport.append(f" | {hidden_messages} earlier hidden", style="dim")

    blocks = [viewport]
    for message in visible_messages:
        blocks.append(message_panel(message))

    conversation_group = Group(*blocks)
    return (
        Panel(conversation_group, title="Conversation", border_style="white", padding=(0, 1)),
        hidden_messages,
    )


def request_ollama(messages: List[dict]) -> str:
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
    }

    try:
        response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=120)
        response.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            "Cannot connect to Ollama at http://localhost:11434. Start Ollama with `ollama serve` and try again."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("Ollama request timed out. Try a shorter prompt or retry.") from exc
    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        detail = ""
        if exc.response is not None and exc.response.text:
            detail = exc.response.text.strip()
        error_message = f"Ollama API error ({status_code})"
        if detail:
            error_message += f": {detail}"
        raise RuntimeError(error_message) from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Ollama returned invalid JSON.") from exc

    content = data.get("message", {}).get("content")
    if not content:
        raise RuntimeError("Ollama response did not include assistant content.")

    return content.strip()


def main() -> None:
    console = Console()
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=5),
        Layout(name="conversation", ratio=1),
        Layout(name="footer", size=5),
    )

    conversation: List[Message] = []
    chat_history: List[dict] = []
    status = "Ready"

    def redraw() -> int:
        layout["header"].update(build_header())
        conversation_panel, hidden_messages = build_conversation_panel(conversation, console)
        layout["conversation"].update(conversation_panel)
        layout["footer"].update(build_footer(status, len(conversation), hidden_messages))
        live.refresh()
        return hidden_messages

    with Live(layout, console=console, auto_refresh=False, screen=True) as live:
        while True:
            redraw()

            try:
                user_input = console.input("[bold cyan]You > [/]").strip()
            except KeyboardInterrupt:
                status = "Ctrl+C received. Exiting cleanly."
                redraw()
                break

            if not user_input:
                status = "Enter a message to chat with Rocky."
                continue

            command = user_input.lower()
            if command in EXIT_COMMANDS:
                status = "Quit command received. Goodbye."
                redraw()
                break

            conversation.append(Message(role="user", content=user_input))
            chat_history.append({"role": "user", "content": user_input})
            status = "Rocky is thinking..."
            redraw()

            try:
                reply = request_ollama(chat_history)
            except RuntimeError as exc:
                conversation.append(Message(role="error", content=str(exc)))
                status = "Request failed. Check error details above."
                continue

            conversation.append(Message(role="assistant", content=reply))
            chat_history.append({"role": "assistant", "content": reply})
            status = "Rocky responded."

    console.print("[bold green]Session ended.[/]")


if __name__ == "__main__":
    main()