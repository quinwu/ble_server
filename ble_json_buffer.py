#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from typing import Optional

MAX_WRITE_BUFFER_SIZE = 512
WRITE_BUFFER_TIMEOUT_SEC = 5.0


def try_parse_complete_json(buffer: bytearray) -> Optional[dict]:
    """Parse buffer when it contains a complete JSON object, otherwise return None."""
    text = buffer.decode("utf-8").strip()
    if not text:
        return None
    if not text.startswith("{"):
        raise ValueError("Invalid JSON: must start with '{'")
    if not text.endswith("}"):
        return None
    return json.loads(text)
