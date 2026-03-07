"""
Background watcher that keeps the mail search index fresh.

Polls the Core Spotlight store.db for changes and rebuilds the
SQLite cache when new mail is indexed by the Spotlight daemon.

Usage:
    watcher = SpotlightWatcher()
    asyncio.create_task(watcher.run())
    # ... later ...
    watcher.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time

from macbot.spotlight.mail_search import MailSearchIndex, _find_store_db

log = logging.getLogger(__name__)

# How often to check for store.db changes (seconds)
_DEFAULT_POLL_INTERVAL = 30.0

# Debounce: wait this long after detecting a change before rebuilding,
# in case the Spotlight daemon is still writing
_DEBOUNCE_SECONDS = 5.0


class SpotlightWatcher:
    """Watches Core Spotlight store.db and keeps the mail index fresh."""

    def __init__(
        self,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        index: MailSearchIndex | None = None,
    ):
        self._poll_interval = poll_interval
        self._index = index or MailSearchIndex()
        self._running = False
        self._last_mtime: float = 0
        self._last_rebuild: float = 0

    @property
    def index(self) -> MailSearchIndex:
        return self._index

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        """Main loop: initial build + poll for changes."""
        self._running = True
        log.info("Spotlight watcher starting")

        # Initial index build (run in thread to not block the event loop)
        await self._rebuild_in_thread()

        # Poll loop
        while self._running:
            try:
                await asyncio.sleep(self._poll_interval)
                if not self._running:
                    break

                store_db = _find_store_db()
                if store_db is None:
                    continue

                current_mtime = store_db.stat().st_mtime
                if current_mtime > self._last_mtime:
                    # Debounce — Spotlight may still be writing
                    log.debug("Store.db changed, waiting %.0fs for debounce", _DEBOUNCE_SECONDS)
                    await asyncio.sleep(_DEBOUNCE_SECONDS)
                    if not self._running:
                        break

                    await self._rebuild_in_thread()

            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Error in spotlight watcher loop")
                await asyncio.sleep(self._poll_interval)

        self._index.close()
        log.info("Spotlight watcher stopped")

    async def _rebuild_in_thread(self) -> None:
        """Run the rebuild in a thread pool to avoid blocking the event loop."""
        loop = asyncio.get_running_loop()
        t0 = time.time()
        try:
            count = await loop.run_in_executor(None, self._do_rebuild)
            elapsed = time.time() - t0
            log.info("Mail index rebuilt: %d messages in %.1fs", count, elapsed)
        except FileNotFoundError:
            log.warning("No Core Spotlight store.db found — mail index unavailable")
        except Exception:
            log.exception("Failed to rebuild mail index")

    def _do_rebuild(self) -> int:
        count = self._index.rebuild()
        store_db = _find_store_db()
        if store_db:
            self._last_mtime = store_db.stat().st_mtime
        self._last_rebuild = time.time()
        return count
