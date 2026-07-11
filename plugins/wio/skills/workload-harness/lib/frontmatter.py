#!/usr/bin/env python3
"""frontmatter -- minimal YAML-subset parser/emitter for .workers/ metadata.

The wio guest has no pip, so no PyYAML. This module parses exactly the subset
the workload-harness v2 format uses (CONTRACT.md):

  * scalars: strings (bare or quoted), ints, floats, true/false, null/~
  * inline lists  [a, b, 3]
  * inline dicts  {k: v, k2: 2}
  * dash lists (each item a scalar or inline dict)
  * nested mappings via 2-space indentation
  * block scalars ``>-`` (folded, single space join) and ``|`` (literal)

Anything else raises ValueError with a line number -- a parse failure must be
loud (check.py G9), never a silently-empty dict.

dump() re-emits the same subset with stable (insertion) key order and
round-trips: parse(dump(m)) == m.
"""
from __future__ import annotations


def _scalar(tok: str):
    t = tok.strip()
    if t == "" or t in ("null", "~"):
        return None
    if t == "true":
        return True
    if t == "false":
        return False
    if (t.startswith('"') and t.endswith('"') and len(t) >= 2) or (
        t.startswith("'") and t.endswith("'") and len(t) >= 2
    ):
        return t[1:-1]
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


def _split_top(s: str, sep: str = ",") -> list[str]:
    """Split on sep at bracket/quote depth zero."""
    out, buf, depth, quote = [], [], 0, None
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf or out:
        out.append("".join(buf))
    return out


def _inline(tok: str, lineno: int):
    t = tok.strip()
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_inline(p, lineno) for p in _split_top(inner)]
    if t.startswith("{") and t.endswith("}"):
        inner = t[1:-1].strip()
        d = {}
        if not inner:
            return d
        for part in _split_top(inner):
            if ":" not in part:
                raise ValueError(f"line {lineno}: bad inline dict entry {part!r}")
            k, v = part.split(":", 1)
            d[_key(k, lineno)] = _inline(v, lineno)
        return d
    if t.startswith("[") or t.startswith("{"):
        raise ValueError(f"line {lineno}: unterminated inline collection {t!r}")
    return _scalar(t)


def _key(tok: str, lineno: int) -> str:
    k = tok.strip()
    if (k.startswith('"') and k.endswith('"')) or (k.startswith("'") and k.endswith("'")):
        k = k[1:-1]
    if not k:
        raise ValueError(f"line {lineno}: empty key")
    return k


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse(text: str) -> dict:
    lines = text.splitlines()
    root: dict = {}
    # stack of (indent, container) -- containers are dicts or lists
    stack: list[tuple[int, object]] = [(-1, root)]
    pending_key: tuple[int, dict, str] | None = None  # (indent, parent, key) awaiting nested value
    i = 0
    while i < len(lines):
        raw = lines[i]
        lineno = i + 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ValueError(f"line {lineno}: tabs in indentation")
        ind = _indent_of(raw)
        body = raw.strip()

        # resolve pending key: nested block starts strictly deeper
        if pending_key is not None:
            pk_ind, pk_parent, pk_key = pending_key
            if ind > pk_ind:
                container: object = [] if body.startswith("- ") or body == "-" else {}
                pk_parent[pk_key] = container
                # record at the KEY's indent so the pop loop below keeps it
                # as current for this first child line and its siblings
                stack.append((pk_ind, container))
                pending_key = None
            else:
                pk_parent[pk_key] = None
                pending_key = None

        # pop stack to the container this line belongs to
        while stack and ind <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError(f"line {lineno}: bad indentation")
        _, cur = stack[-1]

        if body.startswith("- ") or body == "-":
            if not isinstance(cur, list):
                # a dash at same indent as its key's children: allow list under pending dict? no.
                raise ValueError(f"line {lineno}: list item outside a list context")
            item = body[1:].strip()
            if item == "":
                raise ValueError(f"line {lineno}: empty list item")
            cur.append(_inline(item, lineno))
            i += 1
            continue

        if not isinstance(cur, dict):
            raise ValueError(f"line {lineno}: mapping entry inside a list")
        if ":" not in body:
            raise ValueError(f"line {lineno}: expected 'key: value', got {body!r}")
        ktok, vtok = body.split(":", 1)
        key = _key(ktok, lineno)
        v = vtok.strip()
        if v in (">-", ">", "|", "|-"):
            # block scalar: consume deeper-indented lines
            block: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip() == "":
                    block.append("")
                    j += 1
                    continue
                if _indent_of(nxt) <= ind:
                    break
                block.append(nxt.strip() if v.startswith(">") else nxt[ind + 2 :])
                j += 1
            while block and block[-1] == "":
                block.pop()
            joiner = " " if v.startswith(">") else "\n"
            cur[key] = joiner.join(block)
            i = j
            continue
        if v == "":
            pending_key = (ind, cur, key)
            i += 1
            continue
        cur[key] = _inline(v, lineno)
        i += 1

    if pending_key is not None:
        pending_key[1][pending_key[2]] = None
    return root


def load(path) -> tuple[dict, str]:
    """(meta, body) for a ----fenced markdown file; ({}, text) if unfenced."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError(f"{path}: unterminated frontmatter fence")
    meta = parse(text[4 : end + 1])
    body = text[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    return meta, body


def _dump_scalar(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v)
    if s == "" or s != s.strip() or any(c in s for c in ":#{}[],\"'\n") or s in (
        "null", "~", "true", "false",
    ):
        return '"' + s.replace('"', "'") + '"'
    return s


def _dump_inline(v) -> str:
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_dump_inline(x)}" for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(_dump_inline(x) for x in v) + "]"
    return _dump_scalar(v)


def dump(meta: dict, _indent: int = 0) -> str:
    out = []
    pad = " " * _indent
    for k, v in meta.items():
        if isinstance(v, dict) and v and any(isinstance(x, (dict, list)) for x in v.values()):
            out.append(f"{pad}{k}:")
            out.append(dump(v, _indent + 2))
        elif isinstance(v, str) and "\n" in v:
            out.append(f"{pad}{k}: |")
            for ln in v.split("\n"):
                out.append(f"{pad}  {ln}")
        else:
            out.append(f"{pad}{k}: {_dump_inline(v)}")
    return "\n".join(out)


def save(path, meta: dict, body: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n" + dump(meta) + "\n---\n\n" + body.lstrip("\n"))


if __name__ == "__main__":
    import sys

    m, b = load(sys.argv[1])
    print(m)
