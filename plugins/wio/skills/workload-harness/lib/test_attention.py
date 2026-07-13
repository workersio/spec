#!/usr/bin/env python3
"""Bare-runnable selftest for attention.py (no pytest)."""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attention  # noqa: E402

FAILS = 0


def ok(name, cond, detail=""):
    global FAILS
    if cond:
        print(f"PASS {name}")
    else:
        FAILS += 1
        print(f"FAIL {name} {detail}")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


root = tempfile.mkdtemp(prefix="wio-attn-")
# hot surface: heavily tested (3 situations, sync+async), heavily documented
write(os.path.join(root, "tests", "test_pay.py"), """
def test_pay_basic():
    shop.pay(1)
    shop.pay(2)

async def test_pay_async():
    await shop.pay(1)

def test_pay_retry():
    shop.pay(1)
""")
# cold surface: documented + issue-mentioned, ZERO tests
write(os.path.join(root, "README.md"), """
Use `shop.pay(...)` to charge. Streaming results come from
`stream_orders()` -- see docs. stream_orders supports resume.
pay pay pay
""")
write(os.path.join(root, "docs", "streams.md"),
      "stream_orders() yields orders incrementally. stream_orders is durable.")
write(os.path.join(root, "src", "shop", "streams.py"), "def stream_orders(): pass\n")
write(os.path.join(root, "src", "shop", "pay.py"), "def pay(x): pass\n")
issues = os.path.join(root, "issues.jsonl")
write(issues, json.dumps({"title": "stream_orders drops rows", "body": "stream_orders bug"}) + "\n")

SURFACES = [
    {"name": "shop.pay()", "tokens": ["pay"], "files": ["src/shop/pay.py"]},
    {"name": "stream_orders()", "tokens": ["stream_orders"],
     "files": ["src/shop/streams.py"]},
]

rows = attention.probe(root, SURFACES, issues_path=issues)
by = {r["surface"]: r for r in rows}

pay, stream = by["shop.pay()"], by["stream_orders()"]
ok("pay-situations", pay["test_situations"] == 3, pay)
ok("pay-callsites", pay["test_callsites"] >= 4, pay)
ok("pay-modalities", set(pay["tested_modalities"]) == {"sync", "async"}, pay)
ok("stream-zero-tests", stream["test_situations"] == 0 and stream["test_callsites"] == 0,
   stream)
ok("stream-issues", stream["issue_mentions"] == 2, stream)
ok("stream-docs", stream["doc_mentions"] >= 3, stream)
# The whole thesis in one assertion: the documented-but-untested surface
# outranks the hot, hammered one.
ok("inversion", rows[0]["surface"] == "stream_orders()" and
   stream["weight"] > pay["weight"], rows)
# Cells: the async cell of pay is tested (1 situation); its threaded cell is
# empty and must carry the full realness; stream's every cell is empty.
cells = attention.cells(rows)
cw = {(c["surface"], c["axis"]): c for c in cells}
ok("cell-async-counted", cw[("shop.pay()", "modality:async")]["situations"] == 1, cells[:4])
ok("cell-threaded-empty", cw[("shop.pay()", "modality:threaded")]["situations"] == 0)
ok("cell-weight-order",
   cw[("shop.pay()", "modality:threaded")]["weight"]
   > cw[("shop.pay()", "modality:sync")]["weight"])
ok("cells-ranked", cells == sorted(cells, key=lambda c: (-c["weight"], c["surface"], c["axis"])))

# Determinism: byte-identical on re-run
rows2 = attention.probe(root, SURFACES, issues_path=issues)
ok("deterministic", json.dumps(rows) == json.dumps(rows2))
# No git checkout -> churn 0, never fatal
ok("churn-no-git", pay["churn"] == 0 and stream["churn"] == 0)

shutil.rmtree(root)
print("SELFTEST", "FAIL" if FAILS else "OK")
sys.exit(1 if FAILS else 0)
