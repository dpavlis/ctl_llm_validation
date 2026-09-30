import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx
from openai import BadRequestError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dpo_forge.agent_loop import AgentLoop  # noqa: E402

TOOLS_ON_CHAT = ("Function tools with reasoning_effort are not supported for gpt-6-sol in "
                 "/v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort to none")
NO_TEMPERATURE = "Unsupported parameter: 'temperature' is not supported with this model."


def bad_request(message: str) -> BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.openai.com/v1/x"))
    return BadRequestError(message, response=response, body=None)


class FakeMCP:
    def __init__(self):
        self.calls = []

    def list_tools(self):
        return [{"name": "sandbox_read_file", "description": "read a file",
                 "inputSchema": {"type": "object", "properties": {"filename": {"type": "string"}}}}]

    def to_openai_tools(self, tools):
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["inputSchema"]}} for t in tools]

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"content": "file body"}


class FakeOpenAI:
    """Chat refuses tools; responses answers a tool call, then text. Both
    reject temperature, like gpt-6-sol."""

    def __init__(self, chat_error: str = TOOLS_ON_CHAT, responses=None):
        self.chat_kwargs, self.responses_kwargs = [], []
        self._chat_error = chat_error
        self._responses = list(responses or [
            SimpleNamespace(status="completed", output_text="", output=[
                SimpleNamespace(type="reasoning", id="rs_1", summary=[]),
                SimpleNamespace(type="function_call", name="sandbox_read_file", call_id="call_1",
                                arguments=json.dumps({"filename": "graph.grf"})),
            ]),
            SimpleNamespace(status="completed", output_text="DONE", output=[]),
        ])
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.responses = SimpleNamespace(create=self._respond)

    def _chat(self, **kwargs):
        self.chat_kwargs.append(kwargs)
        raise bad_request(self._chat_error)

    def _respond(self, **kwargs):
        self.responses_kwargs.append({**kwargs, "input": list(kwargs["input"])})
        if "temperature" in kwargs:
            raise bad_request(NO_TEMPERATURE)
        return self._responses.pop(0)


def loop(fake, **kw) -> tuple[AgentLoop, FakeMCP]:
    mcp = FakeMCP()
    agent = AgentLoop(provider="openai", model="gpt-6-sol", mcp_client=mcp, **kw)
    agent._llm = fake
    return agent, mcp


class TestResponsesPort(unittest.TestCase):
    def test_auto_switches_to_responses_and_runs_the_tool_loop(self):
        fake = FakeOpenAI()
        agent, mcp = loop(fake, reasoning_effort="medium")
        self.assertEqual(agent.run("SYSTEM", "set it up"), "DONE")
        self.assertEqual(len(fake.chat_kwargs), 1)
        self.assertEqual(fake.chat_kwargs[0]["reasoning_effort"], "medium")
        self.assertEqual(mcp.calls, [("sandbox_read_file", {"filename": "graph.grf"})])
        first, *rest = [k for k in fake.responses_kwargs if "temperature" not in k]
        self.assertEqual(first["instructions"], "SYSTEM")
        self.assertEqual(first["reasoning"], {"effort": "medium"})
        self.assertIs(first["store"], False)
        self.assertEqual(first["tools"][0]["name"], "sandbox_read_file")
        self.assertNotIn("function", first["tools"][0])
        # The second turn replays the reasoning item and the call, then the result.
        replay = rest[0]["input"]
        self.assertEqual([getattr(i, "type", None) or i.get("type") for i in replay[1:]],
                         ["reasoning", "function_call", "function_call_output"])
        self.assertEqual(replay[-1], {"type": "function_call_output", "call_id": "call_1",
                                      "output": json.dumps({"content": "file body"})})

    def test_temperature_is_dropped_once_rejected(self):
        fake = FakeOpenAI()
        agent, _ = loop(fake)
        agent.run("S", "U")
        self.assertEqual(["temperature" in k for k in fake.responses_kwargs], [True, False, False])
        self.assertFalse(agent._supports_temperature)

    def test_switch_is_sticky(self):
        fake = FakeOpenAI(responses=[SimpleNamespace(status="completed", output_text="A", output=[]),
                                     SimpleNamespace(status="completed", output_text="B", output=[])])
        agent, _ = loop(fake, temperature=None)
        self.assertEqual((agent.run("S", "1"), agent.run("S", "2")), ("A", "B"))
        self.assertEqual(len(fake.chat_kwargs), 1)

    def test_pinned_chat_does_not_switch(self):
        agent, _ = loop(FakeOpenAI(), api="chat_completions")
        with self.assertRaises(BadRequestError):
            agent.run("S", "U")

    def test_pinned_responses_never_calls_chat(self):
        fake = FakeOpenAI(responses=[SimpleNamespace(status="completed", output_text="A", output=[])])
        agent, _ = loop(fake, api="responses", temperature=None)
        self.assertEqual(agent.run("S", "U"), "A")
        self.assertEqual(fake.chat_kwargs, [])

    def test_incomplete_empty_answer_raises(self):
        fake = FakeOpenAI(responses=[SimpleNamespace(status="incomplete", output_text="", output=[],
                                                     incomplete_details=SimpleNamespace(reason="max_output_tokens"))])
        agent, _ = loop(fake, api="responses", temperature=None)
        with self.assertRaisesRegex(RuntimeError, "max_output_tokens"):
            agent.run("S", "U")

    def test_unrelated_chat_error_is_not_swallowed(self):
        agent, _ = loop(FakeOpenAI(chat_error="Invalid 'messages[0]': bad role"))
        with self.assertRaises(BadRequestError):
            agent.run("S", "U")

    def test_bad_api_value(self):
        with self.assertRaises(ValueError):
            AgentLoop(provider="openai", model="m", mcp_client=FakeMCP(), api="grpc")


if __name__ == "__main__":
    unittest.main()
