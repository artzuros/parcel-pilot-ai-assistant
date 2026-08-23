import os
from openai import OpenAI

MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

_client = None

def get_client():
    global _client
    if _client is None:
        if not API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client

def chat(messages, tools=None, temperature=0.1, max_tokens=1024, on_delta=None):
    """One model call. Returns the raw chat.completions response.
    When on_delta is given, the call is streamed and on_delta(text) is
    invoked for every content chunk; the returned object keeps the same
    shape (choices[0].message.{content,tool_calls})."""
    kwargs = {"model": MODEL, "messages": messages,
              "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if on_delta is None:
        return get_client().chat.completions.create(**kwargs)

    # Streaming: accumulate deltas into the same shape as a non-streamed
    # completion. Tool-call arguments arrive in fragments and must be
    # merged per index.
    try:
        stream = get_client().chat.completions.create(
            stream=True, stream_options={"include_usage": True}, **kwargs)
    except Exception:
        # Some DeepSeek-compatible endpoints reject stream_options; fall
        # back to no usage rather than failing the whole turn.
        stream = get_client().chat.completions.create(stream=True, **kwargs)
    content, calls, usage = [], [], None
    for chunk in stream:
        if getattr(chunk, "usage", None) is not None:
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        if delta.content:
            content.append(delta.content)
            on_delta(delta.content)
        for tc in (delta.tool_calls or []):
            while len(calls) <= tc.index:
                calls.append({"id": "", "type": "function",
                              "function": {"name": "", "arguments": ""}})
            if tc.id:
                calls[tc.index]["id"] = tc.id
            if tc.function:
                if tc.function.name:
                    calls[tc.index]["function"]["name"] = tc.function.name
                if tc.function.arguments:
                    calls[tc.index]["function"]["arguments"] += tc.function.arguments

    class _Fn:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments
    class _Call:
        def __init__(self, c):
            self.id = c["id"]
            self.type = c["type"]
            self.function = _Fn(c["function"]["name"], c["function"]["arguments"])
    class _Msg:
        def __init__(self, text, call_list):
            self.content = text
            self.tool_calls = [_Call(c) for c in call_list] if call_list else None
    class _Choice:
        def __init__(self, msg):
            self.message = msg
    class _Resp:
        def __init__(self, choices, usage):
            self.choices = choices
            self.usage = usage

    return _Resp([_Choice(_Msg("".join(content), calls))], usage)
