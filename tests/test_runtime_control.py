import os
from pathlib import Path

import pytest

from micforyou.runtime_control import ControlServer, new_control_endpoint, send_mode


def test_socket_rejects_wrong_token_and_pid_without_invoking_handler():
    path, token = new_control_endpoint()
    called = []
    def handler(mode, timeout):
        called.append(mode)
        return {'processing_mode':mode,'mode_revision':1,'mode_reason':'user_pause'}
    server = ControlServer(path, token, handler)
    try:
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        with pytest.raises(ValueError, match='token'):
            send_mode(path, 'bad-token', os.getpid(), 'passthrough', 1)
        with pytest.raises(ValueError, match='managed process|identity'):
            send_mode(path, token, os.getpid() + 10000, 'passthrough', 1)
        assert not called
        reply = send_mode(path, token, os.getpid(), 'passthrough', 1)
        assert reply['processing_mode'] == 'passthrough'
        assert called == ['passthrough']
    finally:
        server.close()
    assert not path.exists()
