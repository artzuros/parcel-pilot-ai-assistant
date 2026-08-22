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

def chat(messages, tools=None, temperature=0.1, max_tokens=1024):
    """One model call. Returns the raw chat.completions response."""
    kwargs = {"model": MODEL, "messages": messages,
              "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    return get_client().chat.completions.create(**kwargs)