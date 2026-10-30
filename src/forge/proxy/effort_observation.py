"""Ephemeral, launch-scoped effort observations from the final outbound request."""

from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Any, Callable

from forge.core.effort_observation import AppliedEffort, EffortResolution
from forge.core.run_id import is_valid_run_id


class EffortObservations:
    """Keep only the latest dispatched request per launch and tier, with bounded memory."""

    def __init__(self, max_entries: int = 512) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._records: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    def observer(
        self,
        launch: str | None,
        *,
        tier: str,
        tier_source: str,
        client_model: str,
        mapped_model: str,
        resolution: EffortResolution,
    ) -> Callable[[AppliedEffort], None] | None:
        """Bind immutable routing/resolution facts to the client-stage observation."""
        if not is_valid_run_id(launch):
            return None
        assert launch is not None

        def observe(applied: AppliedEffort) -> None:
            if resolution.resolved is None and applied.applied is not None and applied.note is None:
                applied = replace(applied, note="Client construction supplied effort after resolution left it unset.")
            key = (launch, tier)
            self._records[key] = {
                "tier": tier,
                "tier_source": tier_source,
                "client_model": client_model,
                "mapped_model": mapped_model,
                **asdict(resolution),
                **asdict(applied),
                "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            self._records.move_to_end(key)
            while len(self._records) > self._max_entries:
                self._records.popitem(last=False)

        return observe

    def snapshot(self, launch: str) -> dict[str, dict[str, Any]]:
        """Return one validated launch's tier map without exposing other launches."""
        if not is_valid_run_id(launch):
            return {}
        return {tier: deepcopy(record) for (key, tier), record in self._records.items() if key == launch}
