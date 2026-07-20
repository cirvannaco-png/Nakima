from security.ssrf_guard import unsafe_target_reason


def test_no_hostname_is_unsafe():
    assert unsafe_target_reason(None) is not None
    assert unsafe_target_reason("") is not None


def test_loopback_is_unsafe():
    assert "loopback" in unsafe_target_reason("127.0.0.1")


def test_private_range_is_unsafe():
    assert unsafe_target_reason("10.0.0.5") is not None
    assert unsafe_target_reason("192.168.1.1") is not None
    assert unsafe_target_reason("172.16.0.1") is not None


def test_link_local_cloud_metadata_is_unsafe():
    assert "link-local" in unsafe_target_reason("169.254.169.254")


def test_unresolvable_hostname_is_unsafe(monkeypatch):
    import socket

    import security.ssrf_guard as guard_mod

    def _raise(*a, **kw):
        raise socket.gaierror("nope")

    monkeypatch.setattr(guard_mod.socket, "getaddrinfo", _raise)
    assert "didn't resolve" in unsafe_target_reason("this-does-not-resolve.invalid")


def test_public_looking_address_is_safe(monkeypatch):
    import security.ssrf_guard as guard_mod

    monkeypatch.setattr(guard_mod.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))])
    assert unsafe_target_reason("example.test") is None
