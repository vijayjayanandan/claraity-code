"""
ClarAIty FastAPI Server

Complete server setup with all endpoints, WebSocket, and dependency injection.
"""

import logging
import asyncio
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from ..config import ClarityConfig, get_config
from ..core.database import ClarityDB
from ..core.generator import ClarityGenerator
from ..sync.orchestrator import SyncOrchestrator
from ..sync.file_watcher import FileWatcher, start_watching
from .endpoints import router as clarity_router
from .websocket import websocket_endpoint, manager as ws_manager

logger = logging.getLogger(__name__)


# Global instances (initialized on startup)
_db: Optional[ClarityDB] = None
_generator: Optional[ClarityGenerator] = None
_sync_orchestrator: Optional[SyncOrchestrator] = None
_file_watcher: Optional[FileWatcher] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown.

    Handles:
    - Database initialization
    - File watcher startup
    - Sync orchestrator startup
    - Cleanup on shutdown
    """
    global _db, _generator, _sync_orchestrator, _file_watcher

    config = get_config()

    logger.info("Starting ClarAIty server...")
    logger.info(f"Config: enabled={config.enabled}, mode={config.mode}, auto_sync={config.auto_sync}")

    try:
        # Initialize database
        db_path = Path(config.db_path)
        if not db_path.exists():
            logger.warning(f"Database not found at {db_path}, will be created on first use")
            db_path.parent.mkdir(parents=True, exist_ok=True)

        _db = ClarityDB(str(db_path))
        logger.info(f"Database initialized: {db_path}")

        # Initialize generator
        if config.enable_generate_mode:
            _generator = ClarityGenerator(
                model_name=config.llm_model,
                base_url=config.llm_base_url,
                api_key_env=config.llm_api_key_env
            )
            logger.info("ClarityGenerator initialized")

        # Initialize sync orchestrator
        if config.enable_document_mode:
            _sync_orchestrator = SyncOrchestrator(
                clarity_db=_db,
                working_directory=str(Path.cwd()),
                auto_sync=config.auto_sync
            )
            logger.info("SyncOrchestrator initialized")

            # Start file watcher if enabled
            if config.enable_file_watcher and config.auto_sync:
                _file_watcher = FileWatcher(
                    watch_directory=str(Path.cwd()),
                    watch_patterns=config.watch_patterns,
                    ignore_patterns=config.ignore_patterns
                )
                _file_watcher.start()
                logger.info(f"FileWatcher started on {Path.cwd()}")

        # Set dependencies in endpoints module
        from .endpoints import set_dependencies
        set_dependencies(_db=_db, _generator=_generator, _sync_orchestrator=_sync_orchestrator)
        logger.info("Dependencies injected into endpoints")

        logger.info("✅ ClarAIty server started successfully")

        yield  # Server is running

    finally:
        # Cleanup on shutdown
        logger.info("Shutting down ClarAIty server...")

        if _file_watcher:
            _file_watcher.stop()
            logger.info("FileWatcher stopped")

        if _db:
            _db.close()
            logger.info("Database closed")

        logger.info("✅ ClarAIty server shutdown complete")


def create_app(config: Optional[ClarityConfig] = None) -> FastAPI:
    """
    Create FastAPI application with all routes and middleware.

    Args:
        config: Optional ClarityConfig (uses global if not provided)

    Returns:
        Configured FastAPI app
    """
    if config is None:
        config = get_config()

    # Create app
    app = FastAPI(
        title="ClarAIty API",
        description="Architecture Clarity Layer for AI Code Generation",
        version="1.0.0",
        lifespan=lifespan
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include clarity router
    app.include_router(clarity_router)

    # WebSocket endpoint
    @app.websocket("/ws/clarity/{session_id}")
    async def clarity_websocket(websocket, session_id: str):
        """WebSocket for real-time updates."""
        await websocket_endpoint(websocket, session_id)

    # Health check
    @app.get("/")
    async def root():
        """Root endpoint - health check."""
        return {
            "service": "ClarAIty API",
            "version": "1.0.0",
            "status": "running",
            "config": {
                "enabled": config.enabled,
                "mode": config.mode,
                "auto_sync": config.auto_sync,
            }
        }

    @app.get("/health")
    async def health():
        """Detailed health check."""
        health_status = {
            "status": "healthy",
            "database": "unknown",
            "sync": "unknown",
            "generator": "unknown",
        }

        try:
            if _db:
                stats = _db.get_statistics()
                health_status["database"] = "connected"
                health_status["database_stats"] = stats
        except Exception as e:
            health_status["database"] = f"error: {str(e)}"

        if _sync_orchestrator:
            sync_status = _sync_orchestrator.get_status()
            health_status["sync"] = "active" if sync_status['syncing'] else "idle"
            health_status["sync_info"] = sync_status

        if _generator:
            health_status["generator"] = "ready"

        return health_status

    return app


# Dependency injection functions

def get_db() -> ClarityDB:
    """
    Get database dependency.

    Raises:
        RuntimeError: If database not initialized
    """
    if _db is None:
        raise RuntimeError("Database not initialized")
    return _db


def get_generator() -> ClarityGenerator:
    """
    Get generator dependency.

    Raises:
        RuntimeError: If generator not initialized
    """
    if _generator is None:
        raise RuntimeError("Generator not initialized")
    return _generator


def get_sync_orchestrator() -> SyncOrchestrator:
    """
    Get sync orchestrator dependency.

    Raises:
        RuntimeError: If sync orchestrator not initialized
    """
    if _sync_orchestrator is None:
        raise RuntimeError("Sync orchestrator not initialized")
    return _sync_orchestrator


# Update endpoints to use dependency injection
# (In a production setup, we'd use FastAPI's Depends() properly)
# For now, we'll inject manually in the endpoints


def run_server(
    host: str = "0.0.0.0",
    port: int = 8766,
    config: Optional[ClarityConfig] = None,
    reload: bool = False
):
    """
    Run the ClarAIty server.

    Args:
        host: Host to bind to (default: 0.0.0.0)
        port: Port to bind to (default: 8766)
        config: Optional ClarityConfig
        reload: Enable auto-reload (development mode)
    """
    import uvicorn

    if config is None:
        config = get_config()

    logger.info(f"Starting ClarAIty server on {host}:{port}")
    logger.info(f"Docs available at http://{host}:{port}/docs")

    # Create app
    app = create_app(config)

    # Run
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level=config.log_level.lower()
    )


# CLI entry point
if __name__ == "__main__":
    import sys

    # Parse CLI arguments
    port = 8766
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Invalid port: {sys.argv[1]}")
            sys.exit(1)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run server
    run_server(port=port)
