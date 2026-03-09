"""
Conversation Compaction Module

Provides intelligent summarization of evicted conversation history
for seamless continuation after context pressure.

Key Components:
- PrioritizedSummarizer: Generates rich summaries with priority-based content inclusion
- SummarySection: Structured section of a summary

Usage:
    from src.memory.compaction import PrioritizedSummarizer

    summarizer = PrioritizedSummarizer(token_budget=6000)
    summary = summarizer.generate_summary(evicted_messages, use_llm=True)
"""

from .summarizer import (
    SUMMARY_PRIORITIES,
    SUMMARY_TOKEN_BUDGET,
    PrioritizedSummarizer,
    SummarySection,
)

__all__ = [
    "PrioritizedSummarizer",
    "SummarySection",
    "SUMMARY_TOKEN_BUDGET",
    "SUMMARY_PRIORITIES",
]
