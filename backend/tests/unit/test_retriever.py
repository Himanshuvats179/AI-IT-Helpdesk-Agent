"""Hybrid retriever behaviour over the seeded KB."""
from __future__ import annotations

from tests.conftest import make_retriever


async def test_vpn_query_matches(seeded):
    result = seeded.search("my vpn will not connect to the network", category="vpn")
    assert not result.no_good_match
    assert "KB-0003" in result.cited_ids()


async def test_password_query_matches(seeded):
    result = seeded.search("I forgot my password and cannot log in", category="password_reset")
    assert "KB-0001" in result.cited_ids()


async def test_empty_query_no_match(seeded):
    result = seeded.search("    ", category=None)
    assert result.no_good_match


async def test_unindexed_retriever_no_match():
    result = make_retriever().search("anything at all")
    assert result.no_good_match


async def test_gibberish_not_high_confidence(seeded):
    result = seeded.search("florble wuzzle gribble snarf zonk", category=None)
    assert result.confidence != "high"
