"""Event handlers — bridge Engine events to WebSocket broadcasts.

Extracted from main.py — all on_* event callbacks and auto-save logic.
"""
from __future__ import annotations

import asyncio
import time

from shared.app_state import AppState
from shared.logger import get_logger

logger = get_logger(__name__)

# Will be set by register_events() — avoids circular import with ws.connection
_ws_manager = None


def _try_state() -> AppState | None:
    """Try to get AppState — returns None if lifespan hasn't run."""
    try:
        return AppState.instance()
    except RuntimeError:
        return None


def register_events(ws_manager) -> None:
    """Register all event handlers on the EventBus.

    Args:
        ws_manager: The ConnectionManager instance from ws.connection.
    """
    global _ws_manager
    _ws_manager = ws_manager

    state = _try_state()
    event_bus = state.event_bus if state else None

    if not event_bus:
        logger.warning("No EventBus — event handlers not registered")
        return

    event_bus.on("ai:task:completed", on_ai_completed)
    event_bus.on("ai:task:failed", on_ai_failed)
    event_bus.on("collector:context:ready", on_context_ready)
    event_bus.on("collector:progress", on_progress)

    # Auto-save session when task completes
    async def _on_context_ready(context, **kwargs):
        asyncio.create_task(on_all_completed(context.task_id))
    event_bus.on("collector:context:ready", _on_context_ready)


# ========== Event Handlers ==========


async def on_ai_completed(task_id: str, ai_id: str, response, **kwargs):
    """Handle AI completion event from engine."""
    await _ws_manager.broadcast({
        "type": "ai_completed",
        "data": {
            "task_id": task_id,
            "ai_id": ai_id,
            "full_text": response.content,
            "word_count": response.word_count,
            "elapsed_ms": int(response.duration * 1000),
        }
    })


async def on_ai_failed(task_id: str, ai_id: str, error: str, **kwargs):
    """Handle AI failure event from engine."""
    await _ws_manager.broadcast({
        "type": "ai_failed",
        "data": {"task_id": task_id, "ai_id": ai_id, "error": error}
    })


async def on_context_ready(context, **kwargs):
    """Handle RoundContext ready event."""
    await _ws_manager.broadcast({
        "type": "all_completed",
        "data": {
            "task_id": context.task_id,
            "summary": {
                "total_ais": context.summary.total_ais,
                "success_count": context.summary.success_count,
                "failure_count": context.summary.failure_count,
            }
        }
    })

    # Trigger comparison analysis
    asyncio.create_task(run_comparison(context.task_id))


async def run_comparison(task_id: str):
    """Run comparison analysis and broadcast result."""
    state = _try_state()
    comparison_engine = state.comparison_engine if state else None
    collector = state.collector if state else None

    if not comparison_engine or not collector:
        return

    ctx = collector.get_round_context(task_id)
    if not ctx:
        return

    try:
        comparison = await asyncio.to_thread(comparison_engine.analyze, ctx)
        await _ws_manager.broadcast({
            "type": "comparison_ready",
            "data": {
                "task_id": task_id,
                "comparison_context": {
                    "task_id": comparison.task_id,
                    "query": comparison.query,
                    "degraded": comparison.degraded,
                    "semantic_units_count": len(comparison.semantic_units),
                    "differences": [
                        {
                            "id": d.id,
                            "dimension": d.dimension,
                            "strength": d.strength,
                            "type": d.diff_type,
                            "involved_ais": [{"ai_id": a, "stance": s} for a, s in d.involved_ais],
                        }
                        for d in comparison.differences
                    ],
                    "unique_insights": [
                        {
                            "unit_id": u.unit_id,
                            "ai_id": u.ai_id,
                            "content": u.content,
                            "novelty_score": u.novelty_score,
                        }
                        for u in comparison.unique_insights
                    ],
                    "metrics": {
                        "total_units": comparison.metrics.total_units,
                        "overall_divergence": comparison.metrics.overall_divergence,
                        "top_difference_dimension": comparison.metrics.top_difference_dimension,
                    }
                }
            }
        })
    except Exception as e:
        logger.exception("Comparison analysis failed for task %s", task_id)
        await _ws_manager.broadcast({
            "type": "error",
            "data": {"task_id": task_id, "error": f"对比分析失败: {str(e)}", "recoverable": True}
        })


async def on_progress(task_id: str, completed_count: int, total_count: int, **kwargs):
    """Handle progress event from collector."""
    await _ws_manager.broadcast({
        "type": "progress",
        "data": {
            "task_id": task_id,
            "completed": completed_count,
            "total": total_count,
            "current_ai": kwargs.get("latest_ai_id", ""),
        }
    })


async def on_all_completed(task_id: str, **kwargs):
    """Save completed task to history."""
    state = _try_state()
    collector = state.collector if state else None
    storage = state.storage if state else None

    if not collector:
        return

    ctx = collector.get_round_context(task_id)
    if not ctx:
        return

    session_data = {
        "task_id": ctx.task_id,
        "query": ctx.query,
        "ai_ids": [r.ai_id for r in ctx.results],
        "completed_at": time.time(),
        "summary": {
            "total_ais": ctx.summary.total_ais,
            "success_count": ctx.summary.success_count,
            "failure_count": ctx.summary.failure_count,
        },
        "results": [
            {
                "ai_id": r.ai_id,
                "content": r.raw_text[:500],
                "word_count": r.normalized.word_count,
                "duration": r.duration,
            }
            for r in ctx.results
        ],
    }
    if storage:
        storage.save_session(session_data)
