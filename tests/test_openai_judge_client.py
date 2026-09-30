import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx
from openai import BadRequestError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test as test_module

USE_RESPONSES = "This model is only supported in v1/responses and not in v1/chat/completions. Use /v1/responses."


def bad_request(message: str) -> BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.openai.com/v1/x"))
    return BadRequestError(message, response=response, body=None)


class FakeOpenAI:
    def __init__(self, chat_error=None):
        self.chat_calls, self.responses_calls = [], []
        self._chat_error = chat_error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.responses = SimpleNamespace(create=self._respond)

    def _chat(self, **kwargs):
        self.chat_calls.append(kwargs)
        if self._chat_error:
            raise bad_request(self._chat_error)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="CHAT"))])

    def _respond(self, **kwargs):
        self.responses_calls.append(kwargs)
        return SimpleNamespace(output_text="RESP")


def client(fake, **cfg):
    c = test_module.OpenAIJudgeClient({"model": "gpt-6-sol", "api_key": "k", "reasoning_effort": "medium", **cfg})
    c._client = fake
    return c


class TestOpenAIJudgeClientApi(unittest.TestCase):
    def test_auto_uses_chat_when_it_works(self):
        fake = FakeOpenAI()
        self.assertEqual(client(fake).evaluate("S", "U"), "CHAT")
        self.assertEqual(fake.chat_calls[0]["reasoning_effort"], "medium")
        self.assertNotIn("temperature", fake.chat_calls[0])
        self.assertEqual(fake.responses_calls, [])

    def test_auto_switches_to_responses_and_stays(self):
        fake = FakeOpenAI(chat_error=USE_RESPONSES)
        c = client(fake)
        self.assertEqual((c.evaluate("S", "U1"), c.evaluate("S", "U2")), ("RESP", "RESP"))
        self.assertEqual(len(fake.chat_calls), 1)
        self.assertEqual(fake.responses_calls[0], {"model": "gpt-6-sol", "instructions": "S", "input": "U1",
                                                   "store": False, "reasoning": {"effort": "medium"}})

    def test_pinned_chat_raises_instead_of_switching(self):
        with self.assertRaises(BadRequestError):
            client(FakeOpenAI(chat_error=USE_RESPONSES), api="chat_completions").evaluate("S", "U")

    def test_pinned_responses_and_explicit_temperature(self):
        fake = FakeOpenAI()
        self.assertEqual(client(fake, api="responses", temperature=0.2).evaluate("S", "U"), "RESP")
        self.assertEqual(fake.chat_calls, [])
        self.assertEqual(fake.responses_calls[0]["temperature"], 0.2)

    def test_other_errors_are_not_swallowed(self):
        with self.assertRaises(BadRequestError):
            client(FakeOpenAI(chat_error="Invalid 'messages[1]'")).evaluate("S", "U")

    def test_bad_api_value(self):
        with self.assertRaises(ValueError):
            test_module.OpenAIJudgeClient({"api": "grpc", "api_key": "k"})


if __name__ == "__main__":
    unittest.main()
