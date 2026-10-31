# Copyright (c) 2025 OpusMusic
# Licensed under the MIT License.
# This file is part of OpusMusic
#
# Debug: logs every callback-query that reaches the bot, so you can see
# whether taps on Rich Message buttons arrive at all. Delete when done.

import logging

from opus import app

logger = logging.getLogger("opus.cb")


@app.on_callback_query(group=-1)
async def _log_callbacks(_, query):
    msg = getattr(query, "message", None)
    logger.info(
        "[CB] data=%r user=%s chat=%s msg=%s",
        query.data,
        getattr(query.from_user, "id", None),
        getattr(getattr(msg, "chat", None), "id", None),
        getattr(msg, "id", None),
    )
    # group=-1 only logs; it never stops the real handlers
