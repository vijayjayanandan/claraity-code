"""
ClarAIty API

FastAPI server for querying and visualizing architecture clarity data.
Provides REST endpoints and WebSocket support for real-time updates.
"""

from .main import app

__all__ = ['app']
