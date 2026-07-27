#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ble_json_buffer import try_parse_complete_json


def test_incomplete_json_returns_none():
    buffer = bytearray(b'{"ssid":"HAICHUANG-5')
    assert try_parse_complete_json(buffer) is None


def test_complete_json_parses():
    payload = {"ssid": "HAICHUANG-5G", "password": "secret123"}
    buffer = bytearray(json.dumps(payload).encode("utf-8"))
    assert try_parse_complete_json(buffer) == payload


def test_chunked_json_reassembly():
    full_json = b'{"ssid":"HAICHUANG-5G","password":"secret123"}'
    buffer = bytearray()

    for chunk_size in (20, 20, len(full_json)):
        chunk = full_json[:chunk_size]
        full_json = full_json[chunk_size:]
        buffer.extend(chunk)
        result = try_parse_complete_json(buffer)
        if full_json:
            assert result is None
        else:
            assert result == {"ssid": "HAICHUANG-5G", "password": "secret123"}


def test_invalid_complete_json_raises():
    buffer = bytearray(b'{"ssid":}')
    try:
        try_parse_complete_json(buffer)
        assert False, "expected JSONDecodeError"
    except json.JSONDecodeError:
        pass


if __name__ == "__main__":
    test_incomplete_json_returns_none()
    test_complete_json_parses()
    test_chunked_json_reassembly()
    test_invalid_complete_json_raises()
    print("All tests passed")
