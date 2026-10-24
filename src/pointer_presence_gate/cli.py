"""Validate synthetic JSONL rows against required RFC 6901 string pointers."""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

MAX_POINTER_LENGTH = 4096
MAX_DEPTH = 128
ARRAY_INDEX = re.compile(r"(?:0|[1-9][0-9]*)\Z", re.ASCII)


class InvalidInput(Exception):
    """An input file does not satisfy the documented data contract."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvalidInput()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInput()
        result[key] = value
    return result


def _constant(_: str) -> Any:
    raise InvalidInput()


def _parse_document(raw: bytes) -> Any:
    try:
        source = raw.decode("utf-8", errors="strict")
        value = json.loads(
            source,
            object_pairs_hook=_pairs,
            parse_int=Decimal,
            parse_float=Decimal,
            parse_constant=_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, InvalidInput, InvalidOperation,
            RecursionError, ValueError, OverflowError):
        raise InvalidInput() from None
    _validate_tree(value)
    return value


def _validate_tree(root: Any) -> None:
    """Reject lone surrogates and containers deeper than the contract allows."""
    stack = [(root, 0)]
    while stack:
        value, parent_depth = stack.pop()
        if isinstance(value, str):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                raise InvalidInput()
        elif isinstance(value, dict):
            depth = parent_depth + 1
            if depth > MAX_DEPTH:
                raise InvalidInput()
            for key, child in value.items():
                stack.append((key, depth))
                stack.append((child, depth))
        elif isinstance(value, list):
            depth = parent_depth + 1
            if depth > MAX_DEPTH:
                raise InvalidInput()
            stack.extend((child, depth) for child in value)


def _read_policy(path: str) -> list[str]:
    try:
        policy = _parse_document(Path(path).read_bytes())
    except (OSError, InvalidInput):
        raise InvalidInput() from None
    if not isinstance(policy, dict) or set(policy) != {"required"}:
        raise InvalidInput()
    required = policy["required"]
    if not isinstance(required, list) or len(required) > 1000:
        raise InvalidInput()
    seen: set[str] = set()
    for pointer in required:
        if not isinstance(pointer, str) or pointer in seen or len(pointer) > MAX_POINTER_LENGTH:
            raise InvalidInput()
        seen.add(pointer)
        if pointer and (not pointer.startswith("/") or re.search(r"~(?![01])", pointer)):
            raise InvalidInput()
    return required


def _row_values(path: str) -> list[Any]:
    try:
        raw = Path(path).read_bytes()
        text = raw.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        raise InvalidInput() from None
    if not text:
        return []
    # JSON Lines delimiters are only CR, LF, and CRLF. Other Unicode line
    # separators remain ordinary data and are rejected by the JSON parser.
    lines = re.split(r"\r\n|\r|\n", text)
    if lines[-1] == "":
        lines.pop()
    rows: list[Any] = []
    for line in lines:
        if not line.strip():
            raise InvalidInput()
        try:
            row = _parse_document(line.encode("utf-8"))
        except InvalidInput:
            raise InvalidInput() from None
        if not isinstance(row, dict) or set(row) != {"id", "payload"}:
            raise InvalidInput()
        identifier = row["id"]
        if not isinstance(identifier, str) or not identifier:
            raise InvalidInput()
        rows.append(row)
    identifiers = [row["id"] for row in rows]
    if len(set(identifiers)) != len(identifiers):
        raise InvalidInput()
    return rows


def _tokens(pointer: str) -> list[str]:
    if not pointer:
        return []
    # RFC 6901 requires this order: decode ~1 first, then ~0.
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _present(payload: Any, tokens: list[str]) -> bool:
    current = payload
    for token in tokens:
        if isinstance(current, dict):
            if token not in current:
                return False
            current = current[token]
        elif isinstance(current, list):
            if not ARRAY_INDEX.fullmatch(token):
                return False
            # Compare decimal text to the array length before int conversion;
            # this safely handles arbitrarily long indices.
            size = len(current)
            size_text = str(size)
            if len(token) > len(size_text) or (len(token) == len(size_text) and token >= size_text):
                return False
            current = current[int(token)]
        else:
            return False
    return True


def _check(policy_path: str, rows_path: str) -> tuple[str, int, list[int]]:
    # Both sources are parsed independently before the decision is made.
    policy: list[str] | None = None
    rows: list[Any] | None = None
    policy_error = rows_error = False
    try:
        policy = _read_policy(policy_path)
    except InvalidInput:
        policy_error = True
    try:
        rows = _row_values(rows_path)
    except InvalidInput:
        rows_error = True
    if policy_error or rows_error:
        raise InvalidInput()
    assert policy is not None and rows is not None
    decoded = [_tokens(pointer) for pointer in policy]
    missing = [line for line, row in enumerate(rows, 1)
               if any(not _present(row["payload"], tokens) for tokens in decoded)]
    return ("missing_required" if missing else "valid", len(rows), missing)


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(prog="pointer-presence-gate")
    parser.add_argument("policy", help="path to a policy JSON document")
    parser.add_argument("rows", help="path to a JSONL rows file")
    values = sys.argv[1:] if argv is None else argv
    if "-h" in values or "--help" in values:
        parser.print_help()
        return 0
    try:
        args = parser.parse_args(values)
    except InvalidInput:
        sys.stdout.write('{"status":"invalid_input"}\n')
        return 2
    try:
        status, count, missing = _check(args.policy, args.rows)
        result = {"status": status, "record_count": count, "missing_lines": missing}
        code = 1 if missing else 0
    except InvalidInput:
        result = {"status": "invalid_input"}
        code = 2
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
