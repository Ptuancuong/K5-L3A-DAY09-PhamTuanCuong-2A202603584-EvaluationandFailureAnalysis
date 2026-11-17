"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = _graded_ids(spec, base)
    problems += _report_problems(pr, graded)
    problems += [f"baseline: {p}" for p in _report_problems(base, graded)]

    # The PR must cover exactly the baseline's (item, seed) grid: no dropped, added or cherry-picked trials.
    pm, bm = pr.get("manifest") or {}, base.get("manifest") or {}
    if sorted(pm.get("seeds") or []) != sorted(bm.get("seeds") or []):
        problems.append(f"seeds {pm.get('seeds')} differ from the baseline's {bm.get('seeds')}")
    if spec.get("seeds") and sorted(pm.get("seeds") or []) != sorted(spec["seeds"]):
        problems.append(f"seeds {pm.get('seeds')} differ from the spec's {spec['seeds']}")
    if pm.get("items") != bm.get("items"):
        problems.append(f"manifest items {pm.get('items')} != baseline {bm.get('items')}")
    pk, bk = _keys(pr), _keys(base)
    if len(pk) != len(bk):
        problems.append(f"{len(pk)} rows vs {len(bk)} in the baseline")
    if set(pk) != set(bk):
        miss, extra = sorted(set(bk) - set(pk)), sorted(set(pk) - set(bk))
        problems.append(f"(item, seed) set differs from the baseline: missing {miss[:5]} extra {extra[:5]}")

    # Slice membership comes from labels, never from the PR: relabelling hides a regression.
    ps, bsl = _slices_by_item(pr), _slices_by_item(base)
    for item in sorted(set(ps) & set(bsl)):
        if ps[item] != bsl[item]:
            problems.append(f"{item}: slice tags {sorted(ps[item])} differ from the baseline's {sorted(bsl[item])}")
    problems += [f"{i}: rows disagree on slice tags across seeds" for i in _slices_inconsistent(pr)]

    # Ratchet: on the same eval set a spec may only get stricter.
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _graded_ids(spec: dict, base: dict) -> list[str]:
    """Spec metrics scored per row (a grader wrote them into the baseline rows)."""
    cols: set[str] = set()
    for r in base.get("rows") or []:
        cols |= set(r)
    return [m["id"] for m in spec.get("metrics", []) if m["id"] in cols]


def _keys(rep: dict) -> list[tuple[Any, Any]]:
    return [(r.get("item_id"), r.get("seed")) for r in rep.get("rows") or []]


def _slices_by_item(rep: dict) -> dict[Any, frozenset]:
    out: dict[Any, frozenset] = {}
    for r in rep.get("rows") or []:
        out.setdefault(r.get("item_id"), frozenset(r.get("slices") or []))
    return out


def _slices_inconsistent(rep: dict) -> list[Any]:
    seen: dict[Any, frozenset] = {}
    bad: list[Any] = []
    for r in rep.get("rows") or []:
        tags, item = frozenset(r.get("slices") or []), r.get("item_id")
        if seen.setdefault(item, tags) != tags and item not in bad:
            bad.append(item)
    return bad


def _report_problems(rep: dict, graded: list[str]) -> list[str]:
    problems: list[str] = []
    metrics = rep.get("metrics") or {}
    for k, v in metrics.items():
        if _num(v) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (NaN/inf slips past every threshold comparison)")
    rows = rep.get("rows") or []
    if not rows:
        return problems + ["report has no rows"]
    man = rep.get("manifest") or {}
    if _num(man.get("items")) and isinstance(man.get("seeds"), list):
        want = man["items"] * len(man["seeds"])
        if len(rows) != want:
            problems.append(f"{len(rows)} rows, manifest says {man['items']} items x {len(man['seeds'])} seeds = {want}")
        n_items = len({r.get("item_id") for r in rows})
        if n_items != man["items"]:
            problems.append(f"{n_items} distinct items in rows, manifest says {man['items']}")
    keys = _keys(rep)
    seen: set = set()
    dups = sorted({k for k in keys if k in seen or seen.add(k)}, key=str)
    if dups:
        problems.append(f"duplicate (item, seed) rows: {dups[:5]}")
    if rep.get("evaluator_failures"):
        problems.append(f"{len(rep['evaluator_failures'])} evaluator failure(s), first: {rep['evaluator_failures'][0]}")
    bad = [(r.get("item_id"), r.get("seed"), m) for r in rows for m in graded if not isinstance(r.get(m), bool)]
    if bad:
        problems.append(f"{len(bad)} graded value(s) missing/None/non-boolean, e.g. {bad[:3]}")
    if any(_num(r.get("cost")) and not math.isfinite(r["cost"]) for r in rows):
        problems.append("a row cost is NaN/inf")
    # The reported aggregates must be what the rows say (a hand-edited or stale metric is a lie).
    for m in graded:
        reported = metrics.get(m)
        vals = [r[m] for r in rows if isinstance(r.get(m), bool)]
        if not _num(reported) or not math.isfinite(reported) or not vals:
            continue
        actual = sum(vals) if m in ("secret_leak", "approval_bypass") else round(sum(vals) / len(vals), 4)
        if abs(actual - reported) > 1e-6:
            problems.append(f"metric {m} reports {reported} but its rows give {actual}")
    by_item: dict[Any, list[bool]] = {}
    for r in rows:
        if isinstance(r.get("pass_rate"), bool):
            by_item.setdefault(r.get("item_id"), []).append(r["pass_rate"])
    for k_name, reported in metrics.items():
        prefix = next((p for p in ("pass_at_", "pass_hat_") if k_name.startswith(p)), None)
        if prefix is None or not _num(reported) or not math.isfinite(reported) or not by_item:
            continue
        fn = stats.pass_at_k if prefix == "pass_at_" else stats.pass_hat_k
        k = int(k_name[len(prefix):])
        try:
            est = [fn(len(v), sum(v), k) for v in by_item.values()]
        except ValueError:
            problems.append(f"metric {k_name} reported but an item has fewer than {k} runs")
            continue
        actual = round(sum(est) / len(est), 4)
        if abs(actual - reported) > 1e-6:
            problems.append(f"metric {k_name} reports {reported} but its rows give {actual}")
    return problems


def _loosened(where: str, th: dict, base_th: dict, blocking: Any, base_blocking: Any) -> list[str]:
    out = []
    if "max" in base_th and ("max" not in th or th["max"] > base_th["max"]):
        out.append(f"{where}: max {base_th['max']} -> {th.get('max', 'removed')}")
    if "min" in base_th and ("min" not in th or th["min"] < base_th["min"]):
        out.append(f"{where}: min {base_th['min']} -> {th.get('min', 'removed')}")
    if "max_increase" in base_th and ("max_increase" not in th or th["max_increase"] > base_th["max_increase"]):
        out.append(f"{where}: max_increase {base_th['max_increase']} -> {th.get('max_increase', 'removed')}")
    if base_th.get("no_significant_drop") and not th.get("no_significant_drop"):
        out.append(f"{where}: no_significant_drop dropped")
    if base_blocking and not blocking:
        out.append(f"{where}: blocking -> non-blocking")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    problems: list[str] = []
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        if spec.get("eval_set") == base_spec.get("eval_set"):
            problems.append(f"RATCHET eval_set_version {base_spec.get('eval_set_version')} -> "
                            f"{spec.get('eval_set_version')} without a new eval set")
        return problems
    cur = {m["id"]: m for m in spec.get("metrics", [])}
    for bm in base_spec.get("metrics", []):
        m = cur.get(bm["id"])
        if m is None:
            problems.append(f"RATCHET metric {bm['id']} removed")
            continue
        problems += [f"RATCHET {p}" for p in _loosened(f"metric {bm['id']}", m.get("threshold") or {},
                                                        bm.get("threshold") or {}, m.get("blocking"), bm.get("blocking"))]
    cur_sl = {(x["name"], x["metric"]): x for x in spec.get("slices") or []}
    for bs in base_spec.get("slices") or []:
        x = cur_sl.get((bs["name"], bs["metric"]))
        if x is None:
            problems.append(f"RATCHET slice {bs['name']}/{bs['metric']} removed")
            continue
        problems += [f"RATCHET {p}" for p in _loosened(f"slice {bs['name']}/{bs['metric']}", x, bs,
                                                        x.get("blocking"), bs.get("blocking"))]
    if sorted(spec.get("seeds") or []) != sorted(base_spec.get("seeds") or []):
        problems.append(f"RATCHET seeds {base_spec.get('seeds')} -> {spec.get('seeds')}")
    if spec.get("eval_set") != base_spec.get("eval_set") or spec.get("labels") != base_spec.get("labels"):
        problems.append("RATCHET eval set / labels path changed on the same eval-set version")
    b, c = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if c.get("confidence", 0.95) > b.get("confidence", 0.95):
        problems.append(f"RATCHET bootstrap confidence {b.get('confidence', 0.95)} -> {c.get('confidence')} (wider CI)")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"            # a slice that lost all its rows cannot vouch for anything
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if "max" in sl and val > sl["max"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027),
                                                       confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
                else:
                    verdict = "missing"    # nothing to pair against the baseline
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        if verdict == "missing" and sl.get("blocking"):
            label = "BLOCK (missing)"
        lines.append(f"  {sid:<38} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
