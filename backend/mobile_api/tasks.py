from __future__ import annotations

from uuid import uuid4

from celery import shared_task

from mobile_api.notifications import claim_pending_deliveries, dispatch_claimed_deliveries


@shared_task(name="mobile_api.process_pending_notifications")
def process_pending_notifications(batch_size: int = 100, worker_id: str = "") -> dict:
    effective_worker = worker_id.strip() or f"mobile-{uuid4().hex[:8]}"
    batch = claim_pending_deliveries(worker_id=effective_worker, batch_size=batch_size)
    return dispatch_claimed_deliveries(batch)
