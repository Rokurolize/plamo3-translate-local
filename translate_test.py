#!/usr/bin/env python3
"""Dependency-free smoke test of the chat-template translation path.

  python translate_test.py
  PLAMO_URL=http://127.0.0.1:8000/v1 python translate_test.py

The WebUI uses the raw-PFML /v1/completions path instead; see docs/API.md.
"""
import json
import os
import urllib.request

BASE = os.environ.get("PLAMO_URL", "http://127.0.0.1:8000/v1").rstrip("/")
MODEL = "plamo-3-translate"
STOP = ["<|plamo:tag|>", "<|plamo:bos|>"]

TESTS = [
    ("Japanese -> English", "会議は来週の月曜日に変更されました。", "en"),
    ("English -> Japanese", "The meeting has been rescheduled to next Monday.", "ja"),
]

for desc, text, target_lang in TESTS:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": text}],
        "temperature": 0,
        "max_tokens": 512,
        "stop": STOP,
        "chat_template_kwargs": {"target_lang": target_lang},
    }
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.load(resp)
    print(f"[{desc}]")
    print(f"  source: {text}")
    print(f"  output: {result['choices'][0]['message']['content'].strip()}")
    print()
