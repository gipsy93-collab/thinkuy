"""Scheduler: refresco automático del catálogo cada 6 horas (criterio MVP)."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .. import config

log = logging.getLogger("radar.scheduler")


def build_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")

    def job() -> None:
        from ..harvester.pipeline import run_pipeline
        try:
            report = run_pipeline(sources=["scielo", "crossref", "openalex", "redalyc"], days=30)
            log.info("Harvest automático OK: %s", report["sources"])
        except Exception as e:  # noqa: BLE001
            log.error("Harvest automático falló: %s", e)

    sched.add_job(
        job,
        trigger=IntervalTrigger(hours=config.HARVEST_INTERVAL_HOURS),
        id="radar_harvest",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60 * 60,
    )
    return sched