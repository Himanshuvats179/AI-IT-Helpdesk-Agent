"""Tool layer: definitions, mock backends, policy engine, and executor.

Design principle: the model PROPOSES a tool call; the executor + policy engine
DISPOSE. Every privileged effect goes through least-privilege backends and a
default-deny policy. Backends are swappable Protocols (mock today, Graph/Intune
tomorrow) — tool implementations never change.
"""
