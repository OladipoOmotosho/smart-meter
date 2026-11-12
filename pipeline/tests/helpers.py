"""Shared test doubles and builders. Import from here, never from test modules."""

from __future__ import annotations

from dataclasses import replace

from smart_meter import chain
from smart_meter.fingerprint import KEY_DOMAIN, READING_DOMAIN
from web3 import Web3


class ReadCall:
    def __init__(self, registry, key):
        self.registry, self.key = registry, key

    def call(self):
        if self.registry.error:
            raise OSError("RPC unavailable")
        return (self.registry.entries.get(self.key, bytes(32)), 1, "writer")


class Functions:
    def __init__(self, registry):
        self.registry = registry

    def getCommitment(self, key):
        return ReadCall(self.registry, key)

    def commit(self, key, value):
        return key, value


class Registry:
    """An in-memory stand-in for the registry's read API and commit call."""

    def __init__(self):
        self.entries = {}
        self.error = False
        self.functions = Functions(self)


def deployment_context(**changes) -> chain.DeploymentContext:
    """A well-formed, offline deployment record; override fields as needed."""
    address = Web3.to_checksum_address("0x" + "aa" * 20)
    base = chain.DeploymentContext(
        chain_id=31337,
        registry_address=address,
        deployment_tx_hash="0x" + "01" * 32,
        deployment_block_number=1,
        deployment_block_hash="0x" + "02" * 32,
        runtime_code_hash="0x" + "03" * 32,
        admin=address,
        aggregator=Web3.to_checksum_address("0x" + "bb" * 20),
        versions={
            "contract": "MeterCommitmentRegistry",
            "compiler": "0.8.24",
            "node_client": "anvil/v1.9.0",
            "reading_format": READING_DOMAIN,
            "key_format": KEY_DOMAIN,
        },
    )
    return replace(base, **changes)
