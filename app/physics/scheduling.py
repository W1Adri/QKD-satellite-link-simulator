# ---------------------------------------------------------------------------
# app/physics/scheduling.py
# ---------------------------------------------------------------------------
# Purpose : Contention-aware key accounting for a satellite constellation over
#           a ground-station network.
#
#           WHY THIS EXISTS.  A constellation study that reports "M satellites
#           x N stations" by SUMMING every satellite-station pair answers a
#           question no operator can ask: it assumes every satellite talks to
#           every visible station at the same instant.  A QKD payload has ONE
#           optical terminal and a ground station has ONE telescope, so the
#           visible pairs at any instant form a bipartite graph in which only a
#           MATCHING can actually be served.  Without that constraint the
#           marginal value of the (N+1)-th station is trivially its standalone
#           key and the question is vacuous; with it, the value saturates, and
#           where it saturates is the result.
#
#           Three policies, deliberately spanning the bound:
#
#           1. "independent" — no contention.  Sum of all pairs.  Physically
#              unrealisable; reported only as the naive upper bound that a
#              N x M table implicitly claims.
#
#           2. "preemptive" — maximum-weight bipartite matching recomputed at
#              every sampling interval (Kuhn 1955 / Munkres 1957, via
#              scipy.optimize.linear_sum_assignment).  This is the exact
#              optimum of the PREEMPTIVE relaxation, in which a terminal may
#              re-point instantaneously and for free.  It therefore upper-bounds
#              every physically realisable schedule *in asymptotic key* — and it
#              is NOT an upper bound once finite-key effects are included,
#              because it shatters passes into fragments whose blocks are too
#              small to distil from.  That inversion is the point.
#
#           3. "contact" — non-preemptive: a pass is served whole or not at all,
#              so every finite-key block stays contiguous.  Selecting the best
#              such set is the maximum-weight independent set of an interval
#              conflict graph with two resource classes, which is NP-hard
#              (Arkin & Silverberg, Discrete Appl. Math. 18, 1 (1987): interval
#              scheduling with k machines is solvable, but the two-sided
#              satellite AND station constraint is not).  We therefore report a
#              greedy schedule together with an EXACT upper bound obtained by
#              relaxing one of the two resources — never a greedy number
#              presented as an optimum.
#
#           Bound chain, always reported together:
#               contact_greedy <= contact_OPT <= min(ub_sat, ub_gs)
#                                             <= preemptive <= independent
#
# References:
#   Kuhn, Naval Res. Logist. Q. 2, 83 (1955) — assignment problem.
#   Munkres, J. SIAM 5, 32 (1957) — O(n^3) algorithm; scipy's implementation.
#   Kleinberg & Tardos, "Algorithm Design" (2005) sec. 6.1 — weighted interval
#     scheduling DP, used here for the single-resource exact bound.
#   Nemhauser, Wolsey & Fisher, Math. Program. 14, 265 (1978) — the (1 - 1/e)
#     guarantee that makes the greedy marginal-value curve meaningful for the
#     monotone submodular policies (see `is_submodular_policy`).
#
# Exports:
#   Contact                       – one satellite pass seen by one station
#   ScheduleResult                – totals + which intervals each pair was given
#   schedule_independent / schedule_preemptive / schedule_contacts
#   contact_upper_bound           – exact single-resource relaxation bound
#   marginal_curve                – greedy add-one-element value curve
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Pair key: (satellite index, ground-station index)
Pair = Tuple[int, int]


@dataclass(frozen=True)
class Contact:
    """One contiguous pass of satellite *sat* over station *gs*.

    Index bounds are INCLUSIVE sample indices into the shared timeline, which
    is the same convention ``key_volume.segment_passes`` uses, so a contact and
    a key-volume pass refer to exactly the same samples.
    """
    sat: int
    gs: int
    i0: int
    i1: int
    t0: float
    t1: float
    bits: float                 # asymptotic key bits over the whole contact
    max_elev_deg: float = 0.0

    @property
    def duration_s(self) -> float:
        return self.t1 - self.t0


@dataclass
class ScheduleResult:
    """Outcome of one scheduling policy.

    Attributes:
        policy:        "independent" | "preemptive" | "contact".
        total_bits:    Asymptotic key bits actually delivered under the policy.
        intervals:     pair -> sorted list of interval indices awarded to it.
                       An interval index k denotes [t_k, t_{k+1}]; the weight of
                       that interval is the trapezoid contribution of the pair's
                       key rate over it, so summing awarded intervals for a pair
                       reproduces its trapezoid integral EXACTLY when the pair
                       wins every interval of a contact.
        contacts_kept: For non-preemptive policies, the contacts served whole.
        fragments:     pair -> list of (i0, i1) inclusive sample ranges actually
                       served, i.e. maximal runs of awarded intervals.  This is
                       what a finite-key block must be recomputed over.
        notes:         Anything the caller must state in a paper.
    """
    policy: str
    total_bits: float = 0.0
    intervals: Dict[Pair, List[int]] = field(default_factory=dict)
    contacts_kept: List[Contact] = field(default_factory=list)
    fragments: Dict[Pair, List[Tuple[int, int]]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


# ── Interval weights ────────────────────────────────────────────────────────

def interval_weights(
    timeline: Sequence[float],
    rates_by_pair: Dict[Pair, np.ndarray],
) -> Tuple[Dict[Pair, np.ndarray], List[int]]:
    """Convert per-sample key RATES into per-interval key BITS.

    The schedule is defined on intervals rather than samples because that is
    the only discretisation under which "pair p was served during [t_k,t_k+1]"
    composes back into the same trapezoid integral the unscheduled key volume
    uses.  Assigning *samples* instead would double-count the shared endpoint
    between two consecutive intervals.

    Args:
        timeline:      Shared time grid (seconds), length n, strictly increasing.
        rates_by_pair: pair -> dense array of secret-key rate in bit/s, length n.

    Returns:
        (weights_by_pair, active_intervals) where weights_by_pair maps a pair to
        an array of length n-1 of key BITS per interval, and active_intervals is
        the sorted list of interval indices where at least one pair is nonzero.
    """
    t = np.asarray(timeline, dtype=float)
    n = t.size
    if n < 2:
        return {}, []
    dt = np.diff(t)
    out: Dict[Pair, np.ndarray] = {}
    active = np.zeros(n - 1, dtype=bool)
    for pair, rate in rates_by_pair.items():
        r = np.asarray(rate, dtype=float)
        if r.size != n:
            raise ValueError(
                f"rate series for pair {pair} has length {r.size}, expected {n}")
        # Clamp negatives: a negative key rate is "no key", never a debit that
        # could make a schedule look better by dropping a pass.
        r = np.maximum(r, 0.0)
        w = 0.5 * (r[:-1] + r[1:]) * dt
        out[pair] = w
        active |= w > 0.0
    return out, [int(k) for k in np.flatnonzero(active)]


def contacts_from_elevation(
    sat: int,
    gs: int,
    timeline: Sequence[float],
    elevation_deg: Sequence[Optional[float]],
    weights: np.ndarray,
    elevation_threshold_deg: float,
) -> List[Contact]:
    """Segment one pair's timeline into contacts above the elevation threshold.

    Mirrors ``key_volume.segment_passes`` (same threshold semantics) so a
    contact and a key-volume pass are the same object seen from two modules.
    """
    t = np.asarray(timeline, dtype=float)
    elev = np.array([(-999.0 if e is None else float(e)) for e in elevation_deg])
    above = elev >= elevation_threshold_deg
    contacts: List[Contact] = []
    i = 0
    n = elev.size
    while i < n:
        if not above[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and above[j + 1]:
            j += 1
        if j > i:
            bits = float(weights[i:j].sum())     # intervals i .. j-1
            contacts.append(Contact(
                sat=sat, gs=gs, i0=i, i1=j,
                t0=float(t[i]), t1=float(t[j]),
                bits=bits,
                max_elev_deg=float(elev[i:j + 1].max()),
            ))
        i = j + 1
    return contacts


# ── Policy 1: no contention ─────────────────────────────────────────────────

def schedule_independent(
    weights_by_pair: Dict[Pair, np.ndarray],
    active: Sequence[int],
) -> ScheduleResult:
    """Every pair served simultaneously — the naive N x M sum."""
    res = ScheduleResult(policy="independent")
    act = list(active)
    for pair, w in weights_by_pair.items():
        idx = [k for k in act if w[k] > 0.0]
        if not idx:
            continue
        res.intervals[pair] = idx
        res.total_bits += float(w[idx].sum())
        res.fragments[pair] = _runs(idx)
    res.notes.append(
        "No contention: assumes every satellite serves every visible station "
        "simultaneously. Physically unrealisable with one terminal per node; "
        "reported only as the upper bound an unconstrained N x M table implies."
    )
    return res


# ── Policy 2: preemptive optimum (per-interval matching) ────────────────────

def schedule_preemptive(
    weights_by_pair: Dict[Pair, np.ndarray],
    active: Sequence[int],
    n_sat: int,
    n_gs: int,
    sat_terminals: int = 1,
    gs_terminals: int = 1,
) -> ScheduleResult:
    """Maximum-weight bipartite matching at every interval.

    Exact optimum of the preemptive relaxation, hence an upper bound on the
    asymptotic key of any realisable schedule.  Uses the Hungarian algorithm
    (scipy ``linear_sum_assignment``) on the small active submatrix of each
    interval; multiple terminals are modelled by replicating the corresponding
    rows/columns, which is the standard reduction from b-matching to matching.
    """
    from scipy.optimize import linear_sum_assignment

    res = ScheduleResult(policy="preemptive")
    if sat_terminals < 1 or gs_terminals < 1:
        raise ValueError("terminal counts must be >= 1")

    per_pair: Dict[Pair, List[int]] = {}
    for k in active:
        # Only pairs with key at this interval can be worth matching.
        live = [(s, g, float(w[k])) for (s, g), w in weights_by_pair.items()
                if w[k] > 0.0]
        if not live:
            continue
        sats = sorted({s for s, _, _ in live})
        gss = sorted({g for _, g, _ in live})
        si = {s: i for i, s in enumerate(sats)}
        gi = {g: j for j, g in enumerate(gss)}
        rows = len(sats) * sat_terminals
        cols = len(gss) * gs_terminals
        cost = np.zeros((rows, cols), dtype=float)
        for s, g, w in live:
            # Replicated rows/cols all carry the same weight; the matching then
            # picks at most `sat_terminals` distinct partners per satellite.
            for a in range(sat_terminals):
                for b in range(gs_terminals):
                    cost[si[s] * sat_terminals + a, gi[g] * gs_terminals + b] = -w
        ri, ci = linear_sum_assignment(cost)
        seen: set = set()
        for r, c in zip(ri, ci):
            w = -cost[r, c]
            if w <= 0.0:
                continue
            pair = (sats[r // sat_terminals], gss[c // gs_terminals])
            # A duplicated row and a duplicated column can both select the same
            # pair; that would serve one link twice and is not a valid schedule.
            if pair in seen:
                continue
            seen.add(pair)
            per_pair.setdefault(pair, []).append(k)
            res.total_bits += w

    for pair, idx in per_pair.items():
        idx.sort()
        res.intervals[pair] = idx
        res.fragments[pair] = _runs(idx)

    res.notes.append(
        "Preemptive optimum: terminals may re-point between consecutive "
        "samples at no cost. Upper-bounds any realisable schedule in ASYMPTOTIC "
        "key, but fragments passes, so it is not an upper bound once finite-key "
        "block sizes are accounted for."
    )
    return res


# ── Policy 3: non-preemptive contacts ───────────────────────────────────────

def schedule_contacts(
    contacts: Sequence[Contact],
    sat_terminals: int = 1,
    gs_terminals: int = 1,
) -> ScheduleResult:
    """Greedy max-weight selection of WHOLE contacts under both constraints.

    A contact is served in full or not at all, so every finite-key block stays
    contiguous.  Greedy by descending key, which is the standard heuristic; the
    exact optimum of this problem is NP-hard, so :func:`contact_upper_bound`
    must be reported alongside.

    Ties are broken by (start time, satellite, station) so the result is
    deterministic and independent of dict ordering.
    """
    res = ScheduleResult(policy="contact")
    order = sorted(contacts, key=lambda c: (-c.bits, c.t0, c.sat, c.gs))
    accepted_by_sat: Dict[int, List[Contact]] = {}
    accepted_by_gs: Dict[int, List[Contact]] = {}

    for c in order:
        if c.bits <= 0.0:
            continue
        if _overlap_count(accepted_by_sat.get(c.sat, ()), c) >= sat_terminals:
            continue
        if _overlap_count(accepted_by_gs.get(c.gs, ()), c) >= gs_terminals:
            continue
        accepted_by_sat.setdefault(c.sat, []).append(c)
        accepted_by_gs.setdefault(c.gs, []).append(c)
        res.contacts_kept.append(c)
        res.total_bits += c.bits

    res.contacts_kept.sort(key=lambda c: (c.t0, c.sat, c.gs))
    for c in res.contacts_kept:
        res.intervals.setdefault((c.sat, c.gs), []).extend(range(c.i0, c.i1))
        res.fragments.setdefault((c.sat, c.gs), []).append((c.i0, c.i1))
    for pair in res.intervals:
        res.intervals[pair].sort()

    res.notes.append(
        "Non-preemptive greedy over whole contacts: finite-key blocks stay "
        "contiguous. Greedy, not optimal — see the reported upper bound."
    )
    return res


def _overlap_count(accepted: Iterable[Contact], c: Contact) -> int:
    """How many already-accepted contacts overlap *c* in time."""
    return sum(1 for a in accepted if a.i0 <= c.i1 and c.i0 <= a.i1)


def contact_upper_bound(
    contacts: Sequence[Contact],
    sat_terminals: int = 1,
    gs_terminals: int = 1,
) -> Dict[str, Any]:
    """Exact upper bound on the non-preemptive optimum.

    Relax one of the two resource constraints at a time.  With only the
    satellite constraint left the problem decomposes into one weighted-interval-
    scheduling instance per satellite, solved exactly by the classical DP; the
    same holds per station.  The optimum of the true (two-sided) problem cannot
    exceed either relaxation, so min(ub_sat, ub_gs) is a valid upper bound.

    The DP is exact for a single terminal.  With k > 1 terminals the k-track
    version is still polynomial but is not implemented; in that case the bound
    falls back to the sum of all contacts for that resource and says so.
    """
    by_sat: Dict[int, List[Contact]] = {}
    by_gs: Dict[int, List[Contact]] = {}
    for c in contacts:
        by_sat.setdefault(c.sat, []).append(c)
        by_gs.setdefault(c.gs, []).append(c)

    exact_sat = sat_terminals == 1
    exact_gs = gs_terminals == 1
    ub_sat = sum(_wis(v) if exact_sat else sum(c.bits for c in v)
                 for v in by_sat.values())
    ub_gs = sum(_wis(v) if exact_gs else sum(c.bits for c in v)
                for v in by_gs.values())
    return {
        "ub_sat": ub_sat,
        "ub_gs": ub_gs,
        "bound": min(ub_sat, ub_gs),
        "exact": exact_sat and exact_gs,
        "note": (
            "min over the two single-resource relaxations, each solved exactly "
            "by weighted-interval-scheduling DP"
            if exact_sat and exact_gs else
            "relaxation with k>1 terminals is not DP-solved here; the "
            "corresponding side falls back to the trivial sum, so the bound is "
            "valid but loose"
        ),
    }


def _wis(contacts: Sequence[Contact]) -> float:
    """Weighted interval scheduling: max total weight of non-overlapping contacts.

    Kleinberg & Tardos sec. 6.1.  Contacts share inclusive sample bounds, so two
    contacts conflict when a.i0 <= b.i1 and b.i0 <= a.i1; sorting by end index
    and binary-searching the last compatible predecessor gives O(n log n).
    """
    if not contacts:
        return 0.0
    cs = sorted(contacts, key=lambda c: (c.i1, c.i0))
    ends = [c.i1 for c in cs]
    import bisect
    best = [0.0] * (len(cs) + 1)
    for i, c in enumerate(cs, start=1):
        # last contact whose end index is strictly before this one's start
        j = bisect.bisect_left(ends, c.i0)
        best[i] = max(best[i - 1], c.bits + best[j])
    return best[-1]


# ── Marginal-value curves ───────────────────────────────────────────────────

def marginal_curve(
    elements: Sequence[Any],
    evaluate: Callable[[Sequence[Any]], float],
    *,
    order: str = "greedy",
) -> List[Dict[str, Any]]:
    """Value of a network as elements are added one at a time.

    Args:
        elements: The candidate set (station ids, or satellite indices).
        evaluate: Called with a subset; returns the network key for that subset.
                  Must be deterministic — it is called O(len(elements)^2) times
                  under the greedy order.
        order:    "greedy"   — at each step add the element with the largest
                              marginal gain (the standard order for a monotone
                              submodular objective, Nemhauser et al. 1978, which
                              is what makes the curve's knee meaningful);
                  "given"    — add in the order supplied;
                  "standalone" — no accumulation: each element's value alone,
                              which is the naive additive number the curve is
                              meant to be compared against.

    Returns:
        One record per step: element, cumulative value, marginal gain, and the
        gain as a fraction of that element's standalone value (the saturation
        ratio — 1.0 means the element added everything it is worth, 0.0 means
        the network already covered it).
    """
    els = list(elements)
    standalone = {i: evaluate([e]) for i, e in enumerate(els)}

    if order == "standalone":
        return [{"element": e, "index": i, "cumulative": standalone[i],
                 "marginal": standalone[i], "standalone": standalone[i],
                 "saturation": 1.0}
                for i, e in enumerate(els)]

    chosen: List[int] = []
    curve: List[Dict[str, Any]] = []
    prev = 0.0
    remaining = list(range(len(els)))
    while remaining:
        if order == "greedy":
            gains = {i: evaluate([els[j] for j in chosen] + [els[i]]) for i in remaining}
            # Deterministic tie-break on index so reruns match exactly.
            pick = max(remaining, key=lambda i: (gains[i] - prev, -i))
            total = gains[pick]
        else:
            pick = remaining[0]
            total = evaluate([els[j] for j in chosen] + [els[pick]])
        chosen.append(pick)
        remaining.remove(pick)
        gain = total - prev
        curve.append({
            "element": els[pick],
            "index": pick,
            "cumulative": total,
            "marginal": gain,
            "standalone": standalone[pick],
            "saturation": (gain / standalone[pick]) if standalone[pick] > 0 else 0.0,
        })
        prev = total
    return curve


# ── helpers ─────────────────────────────────────────────────────────────────

def _runs(indices: Sequence[int]) -> List[Tuple[int, int]]:
    """Maximal runs of consecutive interval indices -> inclusive SAMPLE ranges.

    Interval k spans samples k and k+1, so a run of intervals [a..b] covers
    samples a..b+1 inclusive.
    """
    if not indices:
        return []
    idx = sorted(indices)
    out: List[Tuple[int, int]] = []
    start = prev = idx[0]
    for k in idx[1:]:
        if k == prev + 1:
            prev = k
            continue
        out.append((start, prev + 1))
        start = prev = k
    out.append((start, prev + 1))
    return out
