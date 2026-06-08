"""KPortWatch — TOML parsing helpers."""
from __future__ import annotations

import logging

logger = logging.getLogger("kportwatch.config")


def read_toml(path: str) -> dict:
    """Read a TOML file, returning an empty dict on any error."""
    import tomllib
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        logger.debug("Config file not found: %s — using defaults", path)
    except Exception as e:
        logger.warning("Failed to read config file %s: %s", path, e)
    return {}


def parse_port_list(raw) -> frozenset[int] | None:
    """Parse a TOML port list into a frozenset of validated port ints."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        return None
    ports = set()
    for p in raw:
        if isinstance(p, int) and 0 <= p <= 65535:
            ports.add(p)
    return frozenset(ports)


def parse_safe_ports(raw) -> dict[int, str] | None:
    """Parse a TOML safe-ports table into {port: service_name}."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    result: dict[int, str] = {}
    for key, val in raw.items():
        try:
            port = int(key)
            if 0 <= port <= 65535:
                result[port] = str(val)
        except (ValueError, TypeError):
            continue
    return result if result else None


def parse_custom_rules(raw_rules: list) -> list:
    """Parse [[custom_rules]] entries from TOML into CustomRule objects."""
    from shared.config.rules import CustomRule

    rules: list[CustomRule] = []
    if not isinstance(raw_rules, list):
        return rules
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            continue
        match = raw_rule.get("match", {})
        level = raw_rule.get("level", "WARNING")
        if isinstance(level, str) and level.upper() in ("INFO", "WARNING", "CRITICAL"):
            level = level.upper()
        else:
            level = "WARNING"
        rule = CustomRule(
            port=match.get("port") if isinstance(match.get("port"), int) else None,
            port_pattern=match.get("port_pattern") if isinstance(match.get("port_pattern"), str) else None,
            remote_ip=match.get("remote_ip") if isinstance(match.get("remote_ip"), str) else None,
            process_name=match.get("process_name") if isinstance(match.get("process_name"), str) else None,
            proto=match.get("proto") if isinstance(match.get("proto"), str) else None,
            level=level,
            message=raw_rule.get("message", "Custom rule triggered"),
        )
        rules.append(rule)
    return rules
