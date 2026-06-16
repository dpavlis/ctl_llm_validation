"""Generic agentic tool-use loop.

Drives an LLM through repeated tool calls against an MCP server until
the model produces a final text response (stop_reason end_turn / stop).

Used by the setup agent; not used by the judge (which is a one-shot call).
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from .mcp_client import MCPClient


class AgentLoop:
    """
    LLM + MCP tool loop.

    Supports Anthropic and OpenAI providers. Tools are drawn from the
    MCPClient's tool list; an optional filter narrows which tools the
    LLM sees.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        mcp_client: MCPClient,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 8192,
        max_rounds: int = 40,
        temperature: float = 0.0,
    ):
        self._provider = provider
        self._model = model
        self._mcp = mcp_client
        self._api_key = api_key
        self._base_url = base_url
        self._max_tokens = max_tokens
        self._max_rounds = max_rounds
        self._temperature = temperature
        self._llm = None

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        if self._provider == "anthropic":
            import anthropic
            key = _resolve_key(self._api_key, "ANTHROPIC_API_KEY")
            self._llm = anthropic.Anthropic(api_key=key)
        elif self._provider == "openai":
            from openai import OpenAI
            key = _resolve_key(self._api_key, "OPENAI_API_KEY")
            self._llm = OpenAI(api_key=key, base_url=self._base_url)
        else:
            raise ValueError(f"Unknown provider: {self._provider!r}")
        return self._llm

    def run(
        self,
        system_prompt: str,
        user_message: str,
        tool_filter: Optional[list[str]] = None,
    ) -> str:
        """
        Run the agentic loop and return the model's final text.

        tool_filter: if set, only these MCP tool names are exposed to the LLM.
        """
        all_tools = self._mcp.list_tools()
        if tool_filter:
            all_tools = [t for t in all_tools if t["name"] in tool_filter]

        messages = [{"role": "user", "content": user_message}]

        if self._provider == "anthropic":
            return self._run_anthropic(system_prompt, messages, all_tools)
        else:
            return self._run_openai(system_prompt, messages, all_tools)

    # ------------------------------------------------------------------
    # Anthropic
    # ------------------------------------------------------------------

    def _run_anthropic(self, system: str, messages: list, mcp_tools: list) -> str:
        llm = self._get_llm()
        tools = self._mcp.to_anthropic_tools(mcp_tools)

        for _round in range(self._max_rounds):
            print(f"    [agent round {_round+1}] LLM call …", flush=True)
            kwargs: dict[str, Any] = dict(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,
                temperature=self._temperature,
            )
            if tools:
                kwargs["tools"] = tools

            response = llm.messages.create(**kwargs)

            if response.stop_reason == "end_turn":
                print(f"    [agent round {_round+1}] done (end_turn)", flush=True)
                return _extract_anthropic_text(response.content)

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        print(f"    [agent round {_round+1}] tool: {block.name}  {_fmt_args(block.input, block.name)}", flush=True)
                        result = self._call_tool_safe(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": _to_str(result),
                        })
                messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop — return whatever text is available
            return _extract_anthropic_text(response.content)

        raise RuntimeError(
            f"[agent_loop] Exceeded {self._max_rounds} rounds without end_turn"
        )

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------

    def _run_openai(self, system: str, messages: list, mcp_tools: list) -> str:
        llm = self._get_llm()
        tools = self._mcp.to_openai_tools(mcp_tools)
        all_msgs = [{"role": "system", "content": system}] + messages

        for _round in range(self._max_rounds):
            print(f"    [agent round {_round+1}] LLM call …", flush=True)
            kwargs: dict[str, Any] = dict(
                model=self._model,
                messages=all_msgs,
                temperature=self._temperature,
            )
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = llm.chat.completions.create(**kwargs)
            choice = response.choices[0]

            if choice.finish_reason == "stop":
                print(f"    [agent round {_round+1}] done (stop)", flush=True)
                return choice.message.content or ""

            if choice.finish_reason == "tool_calls":
                all_msgs.append(choice.message)
                for tc in (choice.message.tool_calls or []):
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    print(f"    [agent round {_round+1}] tool: {tc.function.name}  {_fmt_args(args, tc.function.name)}", flush=True)
                    result = self._call_tool_safe(tc.function.name, args)
                    all_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": _to_str(result),
                    })
                continue

            return choice.message.content or ""

        raise RuntimeError(
            f"[agent_loop] Exceeded {self._max_rounds} rounds without stop"
        )

    # ------------------------------------------------------------------

    def _call_tool_safe(self, name: str, arguments: dict) -> Any:
        try:
            return self._mcp.call_tool(name, arguments)
        except Exception as exc:
            return f"[tool error] {exc}"


def _resolve_key(configured: Optional[str], env_name: str) -> Optional[str]:
    """Return the API key, falling back to env if the config value is unset or unexpanded."""
    if configured and not configured.startswith("${"):
        return configured
    return os.environ.get(env_name)


def _extract_anthropic_text(content: list) -> str:
    parts = [block.text for block in content if hasattr(block, "text")]
    return "\n".join(parts)


def _to_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


# Key args to surface per tool — everything else is suppressed to keep lines short
_TOOL_KEY_ARGS: dict[str, list[str]] = {
    "sandbox_write_file":   ["sandboxPath", "filename"],
    "sandbox_delete_file":  ["sandboxPath", "filename"],
    "sandbox_read_file":    ["sandboxPath", "filename"],
    "job_run":              ["jobFile", "sandboxCode"],
    "job_await":            ["runId"],
    "job_validate":         ["jobFile"],
    "job_get_log":          ["runId"],
    "job_get_tracking":     ["runId"],
    "job_get_edge_debug_data": ["runId", "edgeId"],
}


def _fmt_args(args: dict, tool_name: str = "") -> str:
    """Return a short one-line summary of tool arguments."""
    if not args:
        return ""
    priority = _TOOL_KEY_ARGS.get(tool_name, [])
    # show priority keys first, then fill up to 3 total from remaining keys
    shown = [k for k in priority if k in args]
    for k in args:
        if k not in shown:
            shown.append(k)
        if len(shown) >= 3:
            break
    parts = []
    for k in shown:
        vs = str(args[k])
        if len(vs) > 60:
            vs = vs[:57] + "…"
        parts.append(f"{k}={vs!r}")
    return "  ".join(parts)
