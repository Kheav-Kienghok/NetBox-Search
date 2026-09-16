import threading

from rapidfuzz import fuzz, process


class SearchCache:
    """Holds the combined search_index rows in memory for fast fuzzy lookups.

    Reloaded from SQLite after every sync so requests never hit the DB on the
    hot path, and a lock protects against reading mid-reload.
    """

    def __init__(self) -> None:
        self._rows: list[dict] = []
        self._choices: list[str] = []
        self._lock = threading.Lock()

    def reload(self) -> None:
        # imported lazily to avoid a circular import with database/sync
        from app.database import load_search_index

        rows = load_search_index()
        with self._lock:
            self._rows = rows
            self._choices = [r["search_text"] for r in rows]

    def size(self) -> int:
        with self._lock:
            return len(self._rows)

    def all_rows(self) -> list[dict]:
        """Every synced row, unfiltered - used for the default 'show everything'
        view rather than requiring a search term first."""
        with self._lock:
            return list(self._rows)

    def search(self, query: str, limit: int = 500, score_cutoff: float = 55.0) -> list[dict]:
        """Substring matches first (so '10.0.0.5' doesn't lose to a fuzzier
        but unrelated '10.0.0.9'), then fuzzy matches fill any remaining slots
        - which is what makes typos/partial names still findable. An empty
        query returns every row (no query required to see the data).
        """
        query = (query or "").strip().lower()
        with self._lock:
            rows, choices = self._rows, self._choices

        if not query:
            return rows[:limit]

        substring_idx = [i for i, c in enumerate(choices) if query in c]
        substring_idx.sort(key=lambda i: len(choices[i]))  # shorter/more specific text first
        substring_idx = substring_idx[:limit]
        results = [{**rows[i], "_score": 100.0} for i in substring_idx]

        remaining = limit - len(results)
        if remaining > 0:
            exclude = set(substring_idx)
            candidates = [(i, c) for i, c in enumerate(choices) if i not in exclude]
            if candidates:
                idxs, texts = zip(*candidates)
                matches = process.extract(
                    query, texts, scorer=fuzz.WRatio, limit=remaining, score_cutoff=score_cutoff
                )
                for _, score, local_idx in matches:
                    results.append({**rows[idxs[local_idx]], "_score": round(score, 1)})

        return results


search_cache = SearchCache()
