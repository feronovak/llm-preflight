import socket

import pytest


def test_real_hostname_lookup_fails_naming_the_host():
    with pytest.raises(AssertionError, match="example.com"):
        socket.getaddrinfo("example.com", 443)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.0.0.5", "::1"])
def test_loopback_lookup_passes(host):
    assert socket.getaddrinfo(host, 80)


@pytest.mark.parametrize("host", ["10.0.0.7", "8.8.8.8", "LOCALHOST.example.com"])
def test_other_hosts_fail(host):
    with pytest.raises(AssertionError):
        socket.getaddrinfo(host, 80)
