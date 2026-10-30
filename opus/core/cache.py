# Copyright (c) 2025 OpusMusic
# Licensed under the MIT License.
# This file is part of OpusMusic


import os

import libsql_client

from opus import config, logger

# ── Turso Cache ────────────────────────────────────────────────
# Downloaded songs (audio/video bytes) yahan cache hote hain taaki
# same song dobara aane par API limit (200/day jaisi) hit na ho —
# pehle yahan check hota hai, na mile to hi API/yt-dlp/Saavn chain
# chalti hai. Multiple Turso DBs round-robin mein use hote hain;
# jo DB full ho jaye (quota/storage error) use is session ke liye
# "full" mark karke agli DB try karte hain. Sab full ho jayein to
# bas save karna band ho jata hai — koi error user tak nahi jaata,
# playback normal chalta rehta hai (bot API se hi serve karta rahega).

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS songs (
    video_id TEXT PRIMARY KEY,
    ext TEXT NOT NULL,
    data BLOB NOT NULL,
    created_at INTEGER DEFAULT (strftime('%s', 'now'))
)
"""

# Turso/libSQL storage-full ya quota-exceeded errors mein aam taur
# par yeh keywords aate hain — inमें se koi bhi mila to us DB ko
# full maan lenge (exact wording provider/plan ke hisab se badalta
# rehta hai, isliye hardcoded byte-limit ke bajaye error-text par
# depend karna zyada reliable hai).
FULL_MARKERS = (
    "quota",
    "storage",
    "database size",
    "disk full",
    "no space",
    "limit exceeded",
    "row limit",
    "database full",
)


class TursoCache:
    def __init__(self):
        self.databases = getattr(config, "TURSO_DATABASES", [])
        self._full = {i: False for i in range(len(self.databases))}
        self._index = 0
        self._ready = {i: False for i in range(len(self.databases))}

    @property
    def enabled(self) -> bool:
        return bool(self.databases)

    def _client(self, i: int):
        db = self.databases[i]
        # `libsql://` scheme WebSocket (wss://) transport use karta hai,
        # jo kai hosting platforms (Render jaise) par proxy/firewall
        # restrictions ki wajah se "400 Invalid response status" de
        # deta hai. `https://` scheme use karke HTTP-only transport
        # (Hrana-over-HTTP) force karte hain, jo yahan zyada reliable
        # hai.
        url = db["url"]
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        return libsql_client.create_client(url=url, auth_token=db["token"])

    async def _ensure_table(self, i: int, client):
        if self._ready.get(i):
            return
        try:
            await client.execute(CREATE_TABLE)
            self._ready[i] = True
        except Exception as e:
            logger.warning(f"[TursoCache DB{i}] Table init error: {e}")

    def _is_full_error(self, e: Exception) -> bool:
        text = str(e).lower()
        return any(marker in text for marker in FULL_MARKERS)

    # ── Read ───────────────────────────────────────────────────

    async def get(self, video_id: str):
        """
        Saari (non-full) DBs mein video_id dhoondta hai. Jahan bhi
        mil jaye wahi se (ext, data) return kar deta hai. Kahin nahi
        mila to None — caller normal download chain chalayega.
        """
        if not self.enabled:
            return None

        for i in range(len(self.databases)):
            client = None
            try:
                client = self._client(i)
                await self._ensure_table(i, client)
                result = await client.execute(
                    "SELECT ext, data FROM songs WHERE video_id = ?",
                    [video_id],
                )
                if result.rows:
                    ext, data = result.rows[0]
                    logger.info(f"[TursoCache DB{i}] Cache hit: {video_id}")
                    return ext, bytes(data)
            except Exception as e:
                logger.warning(f"[TursoCache DB{i}] Read error: {e}")
            finally:
                if client:
                    await client.close()

        return None

    # ── Write ──────────────────────────────────────────────────

    async def save(self, video_id: str, filepath: str, ext: str) -> bool:
        """
        Round-robin order mein DBs try karta hai. Jo DB full/quota
        error de use is session ke liye skip kar dete hain aur agli
        try karte hain. Sab full ho to bas False — koi exception
        bahar nahi jaati, playback pe koi asar nahi padta.
        """
        if not self.enabled:
            return False

        try:
            with open(filepath, "rb") as f:
                data = f.read()
        except Exception as e:
            logger.warning(f"[TursoCache] File read error: {e}")
            return False

        available = [i for i in range(len(self.databases)) if not self._full[i]]
        if not available:
            logger.warning("[TursoCache] Saari DBs full hain, save skip.")
            return False

        start = self._index % len(available)
        ordered = available[start:] + available[:start]
        self._index += 1

        for i in ordered:
            client = None
            try:
                client = self._client(i)
                await self._ensure_table(i, client)
                await client.execute(
                    "INSERT OR REPLACE INTO songs (video_id, ext, data) VALUES (?, ?, ?)",
                    [video_id, ext, data],
                )
                logger.info(f"[TursoCache DB{i}] Saved: {video_id}")
                return True
            except Exception as e:
                if self._is_full_error(e):
                    logger.warning(f"[TursoCache DB{i}] Full! Skipping from now on.")
                    self._full[i] = True
                else:
                    logger.warning(f"[TursoCache DB{i}] Write error: {e}")
            finally:
                if client:
                    await client.close()

        logger.warning("[TursoCache] Kisi bhi DB mein save nahi ho paya.")
        return False

    async def write_to_disk(self, video_id: str, ext: str, data: bytes, download_dir: str) -> str:
        os.makedirs(download_dir, exist_ok=True)
        filename = f"{download_dir}/{video_id}.{ext}"
        with open(filename, "wb") as f:
            f.write(data)
        return filename
