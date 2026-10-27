"""Read the x-preferences block of the master profile."""

HOME_STATUSES = frozenset({"citizen", "stamp4", "mobility"})
DEFAULT_HOME = frozenset({"BR", "PT"})


def _prefs(master: dict) -> dict:
    return master.get("x-preferences") or {}


def markets(master: dict) -> list[str]:
    return [str(m).upper() for m in _prefs(master).get("markets") or []]


def primary_market(master: dict) -> str | None:
    found = markets(master)
    return found[0] if found else None


def work_rights(master: dict, code: str) -> dict | None:
    return (_prefs(master).get("workRights") or {}).get(code.upper())


def home_codes(master: dict) -> frozenset[str]:
    rights = _prefs(master).get("workRights")
    if not rights:  # absent or {}: the profile says nothing, so the old default holds
        return DEFAULT_HOME
    return frozenset(c for c, r in rights.items() if r.get("status") in HOME_STATUSES)


def pay_floor(master: dict, market: str | None) -> dict | None:
    floor = _prefs(master).get("payFloor")
    if not floor:
        return None
    if "amount" in floor:
        return floor
    key = market.upper() if market else None
    return floor.get(key) or floor.get("default")


def ireland_pay_floor(master: dict) -> dict | None:
    """The personal floor for Irish jobs: only an explicit payFloor.IE entry.

    The legacy single object and "default" never apply to Ireland, where the permit floors
    are checked by the permit rule (spec section 3).
    """
    floor = _prefs(master).get("payFloor")
    if not isinstance(floor, dict) or "amount" in floor:
        return None
    return floor.get("IE")


def degree_recognised(master: dict, code: str = "IE") -> str:
    return (work_rights(master, code) or {}).get("degreeRecognised", "unknown")


def self_apply(master: dict, code: str = "IE") -> bool:
    return bool((work_rights(master, code) or {}).get("selfApply", False))
