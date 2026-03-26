"""
Module defining the raw protocol commands used over the Tor network.
Uses strict Enums to prevent string typos during handshakes and messaging.
"""

from enum import Enum


class TorCommand(str, Enum):
    """Enumeration of all valid Tor protocol commands."""

    CHALLENGE = '/challenge'
    AUTH = '/auth'
    ACCEPTED = '/accepted'
    REJECT = '/reject'
    DISCONNECT = '/disconnect'
    MSG = '/msg'
    ACK = '/ack'
    DROP = '/drop'
