"""Standalone Bloomberg CSV extraction: multi-file merge, validation, Fama-French.

Separate from ``forecasting_engine.ingest``, which reads Bloomberg's .xlsx
workbook exports against a fixed 8-signal contract. This package instead reads
whatever CSV exports a user hands it, merges them, and reports on the result —
no fixed column contract, no downstream forecasting pipeline plumbing.
"""
