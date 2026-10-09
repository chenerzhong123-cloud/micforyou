"""Same-user local control protocol. No audio or model data crosses the socket."""

from __future__ import annotations

from contextlib import contextmanager
import atexit
import fcntl
import hmac
import json
import os
from pathlib import Path
import socket
import stat
import threading
import uuid
from typing import Callable


def new_control_endpoint() -> tuple[Path, str]:
    directory = Path("/tmp") / f"micforyou-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("unsafe runtime control directory")
    directory.chmod(0o700)
    token = uuid.uuid4().hex
    return directory / f"{token}.sock", token


@contextmanager
def state_lock(state_path: Path):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.with_suffix(".lock").open("a") as stream:
        os.chmod(stream.name, 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _receive(stream: socket.socket) -> dict:
    value = bytearray()
    while b"\n" not in value:
        data = stream.recv(4096 - len(value))
        if not data:
            raise ValueError("incomplete control message")
        value.extend(data)
        if len(value) >= 4096:
            raise ValueError("control message exceeds size limit")
    payload = json.loads(bytes(value).split(b"\n", 1)[0])
    if not isinstance(payload, dict):
        raise ValueError("invalid control message")
    return payload


def send_mode(path: Path, token: str, pid: int, mode: str, timeout: float) -> dict:
    if mode not in {"tse", "passthrough"} or timeout <= 0:
        raise ValueError("invalid mode or timeout")
    request_id = uuid.uuid4().hex
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(timeout + 0.5)
        stream.connect(str(path))
        stream.sendall((json.dumps({
            "id": request_id, "token": token, "pid": pid,
            "mode": mode, "timeout": timeout,
        }) + "\n").encode())
        response = _receive(stream)
    if response.get("id") != request_id or response.get("pid") != pid:
        raise ValueError("control response does not match the managed process")
    if not response.get("ok"):
        raise ValueError(response.get("error", "mode switch failed"))
    if response.get("processing_mode") != mode:
        raise ValueError("audio callback did not confirm requested mode")
    return response


class ControlServer:
    def __init__(self, path: Path, token: str, handler: Callable[[str, float], dict]):
        self.path = path
        self.token = token
        self.handler = handler
        self._closed = threading.Event()
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.bind(str(path))  # never unlink an existing endpoint
        path.chmod(0o600)
        self._socket.listen(4)
        self._socket.settimeout(0.2)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        atexit.register(self.close)

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                client, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with client:
                request = {}
                response = {"pid": os.getpid(), "ok": False}
                try:
                    client.settimeout(2)
                    request = _receive(client)
                    if not hmac.compare_digest(str(request.get("token", "")), self.token):
                        raise ValueError("invalid runtime control token")
                    if request.get("pid") != os.getpid():
                        raise ValueError("managed process identity changed")
                    timeout = min(float(request["timeout"]), 15)
                    result = self.handler(request["mode"], timeout)
                    response.update(result, ok=True)
                except Exception as error:
                    response["error"] = str(error)
                response["id"] = request.get("id")
                try:
                    client.sendall((json.dumps(response) + "\n").encode())
                except OSError:
                    pass

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._socket.close()
        self._thread.join(timeout=0.5)
        self.path.unlink(missing_ok=True)
