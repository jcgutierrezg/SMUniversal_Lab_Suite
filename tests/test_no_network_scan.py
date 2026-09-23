"""Refreshing the address list does not search the network.

pyvisa-py lists every interface it supports and filters by pattern only
afterwards, so asking it for GPIB, USB and serial resources still ran
its TCP/IP discovery: a UDP broadcast on every network interface and an
mDNS query, on every refresh. These pin that listing no longer does,
and that opening - which a typed LAN address still needs - is left
alone.
"""
import warnings

import pytest

from smuniversal_lab_suite.core.transports import visa_transport
from smuniversal_lab_suite.core.transports.visa_transport import (
    VisaTransport,
    silence_network_discovery,
)

tcpip = pytest.importorskip("pyvisa_py.tcpip")


def test_listing_asks_the_network_nothing(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("the network was searched")

    # Anything the TCP/IP listers would use to reach the network.
    monkeypatch.setattr(tcpip.socket, "socket", refuse)
    assert silence_network_discovery() is True
    for name in visa_transport._NETWORK_LISTERS:
        session = getattr(tcpip, name, None)
        if session is not None:
            assert session.list_resources() == [], name


def test_opening_is_untouched():
    """Only listing is replaced: a typed LAN address must still open."""
    silence_network_discovery()
    for name in visa_transport._NETWORK_LISTERS:
        session = getattr(tcpip, name, None)
        if session is None:
            continue
        for method in ("open", "after_parsing", "read", "write"):
            found = getattr(session, method, None)
            assert found is not visa_transport._nothing_on_the_network, \
                f"{name}.{method}"


def test_a_refresh_raises_no_network_warnings():
    """The zeroconf and psutil warnings came from the discovery itself."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        VisaTransport.list_available()
    network = [str(w.message) for w in caught
               if "zeroconf" in str(w.message) or "psutil" in str(w.message)]
    assert not network, network


def test_silencing_twice_is_harmless():
    assert silence_network_discovery() is True
    assert silence_network_discovery() is True
    assert tcpip.TCPIPInstrSession.list_resources() == []
