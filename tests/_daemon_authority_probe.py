"""Minimal real execution-child probe used by daemon authority boundary tests."""
from __future__ import annotations

import errno
import json
import os
import socket
import struct
import sys


def main(result_path: str) -> int:
    result: dict[str, object] = {}
    try:
        root = socket.socket(fileno=int(os.environ["ROOT_AUTHORITY_FD"]))
    except OSError as exc:
        result["root_errno"] = exc.errno
    else:
        result["root_open"] = True
        root.close()
    child = socket.socket(fileno=int(os.environ["LINGTAI_DRIVER_AUTHORITY_FD"]))
    request = json.dumps({"version": 1, "op": "hello"}, separators=(",", ":")).encode()
    child.sendall(struct.pack("!I", len(request)) + request)
    header = child.recv(4)
    size = struct.unpack("!I", header)[0]
    response = bytearray()
    while len(response) < size:
        response.extend(child.recv(size - len(response)))
    result["child_role"] = json.loads(bytes(response).decode())["role"]
    child.close()
    with open(result_path, "w", encoding="utf-8") as output:
        json.dump(result, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
