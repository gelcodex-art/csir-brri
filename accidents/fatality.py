"""
Fatality Index study (BRRI research objective iv): is the Fatality Index of
casualties in crashes involving a foreign-registered vehicle different from that
of casualties in crashes involving only Ghanaian-registered vehicles?

The unit is the casualty: injured drivers and riders (on the vehicle rows),
passengers and pedestrians. Outcome: killed (injury 1 - Fatal) or injured
(2 - Hospitalised, 3 - Injured not hospitalised). Each crash is put in a group
from its vehicles:

  Foreign   at least one vehicle registered abroad;
  Ghanaian  every vehicle registered in Ghana;
  left out  no foreign vehicle, but at least one whose registration is not known
            (or no vehicle recorded at all).

A vehicle is foreign when "30 Registered in" is Foreign or its registration code
is 12 (Foreign); Ghanaian when "Registered in" is Ghana, or it is empty and the
registration code is a Ghana region or the army (1-11).

The same steps as the analysis workbook (Obj4_Analysis): the 2 x 2 table with
Wilson confidence intervals, the two-proportion z test, Pearson and Yates
chi-square, Fisher's exact test, the size of the difference (difference in
Fatality Index, risk ratio, odds ratio, phi, excess deaths), and a check by year
(Cochran-Mantel-Haenszel). `build()` returns everything the page shows.
"""
import math

from django.db.models import Count, Q
from django.db.models.functions import ExtractYear

from . import codebook as cb
from . import stats
from .models import PassengerCasualty, PedestrianCasualty, Vehicle

FOREIGN, GHANAIAN, LEFT_OUT = "Foreign", "Ghanaian", "Left out"
GROUPS = (FOREIGN, GHANAIAN)
ALPHAS = ("0.10", "0.05", "0.01")
INJURED = (1, 2, 3, 9)              # 9: injured, not known if hospitalised (recoded data)
KILLED = 1


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def z_critical(alpha):
    """z with a two-sided chance `alpha` of a value this far from zero (1.96 for 0.05)."""
    lo, hi = 0.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if stats.normal_p(mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def wilson(killed, n, z):
    """Wilson score interval for killed / n, as (lower, upper) per 100."""
    if not n:
        return None, None
    p = killed / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    scale = 1 + z * z / n
    return 100 * (centre - half) / scale, 100 * (centre + half) / scale


def _log_choose(n, k):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_p(a, b, c, d):
    """Fisher's exact test, two-sided: the chance, with all four margins fixed, of a
    table as unlikely as this one or more so (hypergeometric distribution of a)."""
    n1, killed, n = a + b, a + c, a + b + c + d
    lo, hi = max(0, killed - (n - n1)), min(n1, killed)
    base = _log_choose(n, n1)
    logs = {k: _log_choose(killed, k) + _log_choose(n - killed, n1 - k) - base
            for k in range(lo, hi + 1)}
    limit = logs[a] + 1e-7                      # tables as likely as the one seen, or less
    return min(1.0, sum(math.exp(v) for v in logs.values() if v <= limit))


def _pearson(a, b, c, d):
    """Pearson chi-square (1 df, no correction) of a 2 x 2 table; None if a margin is 0."""
    n1, n2, k, m = a + b, c + d, a + c, b + d
    if not (n1 and n2 and k and m):
        return None
    return (n1 + n2) * (a * d - b * c) ** 2 / (n1 * n2 * k * m)


def compare(a, b, c, d, alpha=0.05):
    """Every figure for the table foreign (a killed, b injured) and Ghanaian (c, d)."""
    z = z_critical(alpha)
    n1, n2 = a + b, c + d
    n, k, m = n1 + n2, a + c, b + d
    out = {"z_crit": z, "n1": n1, "n2": n2, "n": n, "killed": k, "injured": m}
    out["rows"] = []
    for label, killed, total in ((FOREIGN, a, n1), (GHANAIAN, c, n2), ("Total", k, n)):
        low, high = wilson(killed, total, z)
        out["rows"].append({"label": label, "killed": killed, "injured": total - killed,
                            "total": total, "fi": 100 * killed / total if total else None,
                            "low": low, "high": high})
    if not (n1 and n2 and k and m):
        out["ok"] = False                       # a whole row or column is empty: no test
        return out
    out["ok"] = True
    p1, p2, p = a / n1, c / n2, k / n
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    zs = (p1 - p2) / se
    chi2 = _pearson(a, b, c, d)
    yates = n * max(0, abs(a * d - b * c) - n / 2) ** 2 / (n1 * n2 * k * m)
    out.update(
        p1=p1, p2=p2, pooled=p, se=se, z=zs, p_z=stats.normal_p(zs),
        chi2=chi2, p_chi2=stats.chi2_p(chi2, 1), yates=yates, p_yates=stats.chi2_p(yates, 1),
        p_fisher=fisher_p(a, b, c, d),
        min_expected=min(n1 * k / n, n1 * m / n, n2 * k / n, n2 * m / n),
        phi=(a * d - b * c) / math.sqrt(n1 * n2 * k * m),
        excess=a - n1 * p2)
    out["p_max"] = max(out["p_z"], out["p_chi2"], out["p_yates"], out["p_fisher"])
    out["significant"] = out["p_max"] < alpha
    half = z * 100 * math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    out["diff"] = (100 * (p1 - p2), 100 * (p1 - p2) - half, 100 * (p1 - p2) + half)
    if a and c:                                 # risk ratio, log-scale interval
        rr = p1 / p2
        s = math.sqrt(1 / a - 1 / n1 + 1 / c - 1 / n2)
        out["rr"] = (rr, math.exp(math.log(rr) - z * s), math.exp(math.log(rr) + z * s))
    if a and b and c and d:                     # odds ratio, Woolf interval
        odds = a * d / (b * c)
        s = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
        out["or"] = (odds, math.exp(math.log(odds) - z * s), math.exp(math.log(odds) + z * s))
    return out


def by_year(cells):
    """Year by year, and the Cochran-Mantel-Haenszel test that adjusts for year.
    cells: {year: (a, b, c, d)}."""
    rows, mh_num, mh_den, sum_a, sum_e, sum_v = [], 0.0, 0.0, 0, 0.0, 0.0
    for year in sorted(cells):
        a, b, c, d = cells[year]
        n1, n2 = a + b, c + d
        n = n1 + n2
        chi2 = _pearson(a, b, c, d)
        rows.append({"year": year, "a": a, "n1": n1, "fi1": 100 * a / n1 if n1 else None,
                     "c": c, "n2": n2, "fi2": 100 * c / n2 if n2 else None,
                     "diff": (100 * a / n1 - 100 * c / n2) if n1 and n2 else None,
                     "p": stats.chi2_p(chi2, 1) if chi2 is not None else None})
        if n > 1 and n1 and n2:
            mh_num += a * d / n
            mh_den += b * c / n
            sum_a += a
            sum_e += n1 * (a + c) / n
            sum_v += n1 * n2 * (a + c) * (b + d) / (n * n * (n - 1))
    out = {"rows": rows, "higher": sum(1 for r in rows if r["diff"] is not None and r["diff"] > 0),
           "compared": sum(1 for r in rows if r["diff"] is not None)}
    if mh_den and sum_v:
        out["mh_or"] = mh_num / mh_den
        out["cmh"] = (sum_a - sum_e) ** 2 / sum_v
        out["p_cmh"] = stats.chi2_p(out["cmh"], 1)
    return out


# ---------------------------------------------------------------------------
# From the records
# ---------------------------------------------------------------------------
def _groups(accidents):
    """{accident id: FOREIGN | GHANAIAN | LEFT_OUT} for accidents that have vehicles."""
    foreign = Q(registered_in=2) | Q(registration_code=cb.REG_CODE_FOREIGN)
    ghana = (Q(registered_in=1) | Q(registered_in__isnull=True,
                                    registration_code__in=cb.REG_CODES_GHANA)) & ~foreign
    out = {}
    for row in (Vehicle.objects.filter(accident__in=accidents).values("accident_id")
                .annotate(n=Count("pk"), f=Count("pk", filter=foreign),
                          g=Count("pk", filter=ghana))):
        out[row["accident_id"]] = (FOREIGN if row["f"] else
                                   GHANAIAN if row["g"] == row["n"] else LEFT_OUT)
    return out


def _casualties(accidents):
    """{accident id: [killed, casualties]}, and how many casualties have no injury
    recorded (they cannot be counted as killed or injured)."""
    out, unknown = {}, 0
    sources = ((Vehicle, "driver_injury"), (PassengerCasualty, "severity"),
               (PedestrianCasualty, "severity"))
    for model, field in sources:
        qs = model.objects.filter(accident__in=accidents)
        if model is not Vehicle:                # an uninjured driver is not a casualty
            unknown += qs.filter(**{f"{field}__isnull": True}).count()
        for row in (qs.filter(**{f"{field}__in": INJURED}).values("accident_id")
                    .annotate(n=Count("pk"), k=Count("pk", filter=Q(**{field: KILLED})))):
            cell = out.setdefault(row["accident_id"], [0, 0])
            cell[0] += row["k"]
            cell[1] += row["n"]
    return out, unknown


def build(accidents, alpha=0.05):
    """The whole study for the accidents the page filters selected."""
    groups = _groups(accidents)
    casualties, no_injury = _casualties(accidents)
    years = dict(accidents.annotate(y=ExtractYear("accident_date")).values_list("id", "y"))

    totals = {g: [0, 0] for g in (FOREIGN, GHANAIAN, LEFT_OUT)}
    yearly = {}
    no_vehicle = 0
    for acc_id, (killed, n) in casualties.items():
        group = groups.get(acc_id)
        if group is None:                       # no vehicle recorded
            no_vehicle += n
            group = LEFT_OUT
        totals[group][0] += killed
        totals[group][1] += n
        if group in GROUPS:
            cell = yearly.setdefault(years.get(acc_id), [0, 0, 0, 0])
            i = 0 if group == FOREIGN else 2
            cell[i] += killed
            cell[i + 1] += n - killed
    a, n1 = totals[FOREIGN]
    c, n2 = totals[GHANAIAN]
    result = compare(a, n1 - a, c, n2 - c, alpha)
    result.update(
        alpha=alpha, all_casualties=sum(t[1] for t in totals.values()),
        left_out=totals[LEFT_OUT][1], no_vehicle=no_vehicle, no_injury=no_injury,
        crashes={key: sum(1 for v in groups.values() if v == g)
                 for key, g in (("foreign", FOREIGN), ("ghanaian", GHANAIAN),
                                ("left_out", LEFT_OUT))},
        years=by_year({y: tuple(v) for y, v in yearly.items() if y is not None}))
    result["statement"] = statement(result) if result["ok"] else []
    return result


# ---------------------------------------------------------------------------
# In words
# ---------------------------------------------------------------------------
def _p(p):
    return f"{p:.1E}" if p < 0.001 else f"{p:.3f}"


def _years(result):
    rows = [r for r in result["years"]["rows"] if r["year"] is not None]
    return f"{rows[0]['year']}-{rows[-1]['year']}" if rows else ""


def statement(r):
    """The result in the words of a written report (as Obj4_Analysis section 7)."""
    f, g = r["rows"][0], r["rows"][1]
    span = _years(r)
    lines = [
        f"Of {r['n']:,} classified casualties{f' ({span})' if span else ''}, {f['killed']:,} of "
        f"{f['total']:,} casualties in crashes involving a foreign-registered vehicle were killed "
        f"(FI = {f['fi']:.1f}; {100 * (1 - r['alpha']):.0f}% CI {f['low']:.1f}-{f['high']:.1f}), "
        f"compared with {g['killed']:,} of {g['total']:,} in crashes involving only "
        f"Ghanaian-registered vehicles (FI = {g['fi']:.1f}; {100 * (1 - r['alpha']):.0f}% CI "
        f"{g['low']:.1f}-{g['high']:.1f})."]
    diff, low, high = r["diff"]
    verdict = ("is statistically significant" if r["significant"]
               else "is not statistically significant")
    lines.append(
        f"The difference of {diff:.1f} percentage points ({100 * (1 - r['alpha']):.0f}% CI "
        f"{low:.1f} to {high:.1f}) {verdict}: z = {r['z']:.2f}, p = {_p(r['p_z'])}; Pearson "
        f"χ²(1) = {r['chi2']:.2f}, p = {_p(r['p_chi2'])}; Yates χ²(1) = {r['yates']:.2f}, "
        f"p = {_p(r['p_yates'])}; Fisher's exact p = {_p(r['p_fisher'])}. H₀ is "
        f"{'rejected' if r['significant'] else 'not rejected'} at α = {r['alpha']:.2f}.")
    parts = []
    if "rr" in r:
        rr, rl, rh = r["rr"]
        more = "as likely" if rr >= 1 else "as likely (that is, less likely)"
        parts.append(f"A casualty in a foreign-vehicle crash was {rr:.2f} times {more} to be "
                     f"killed (RR {100 * (1 - r['alpha']):.0f}% CI {rl:.2f}-{rh:.2f}"
                     + (f"; OR = {r['or'][0]:.2f}" if "or" in r else "") + ")")
        parts.append(f"equivalent to about {r['excess']:.0f} excess deaths over the period"
                     if r["excess"] >= 0 else
                     f"about {-r['excess']:.0f} fewer deaths than at the Ghanaian-group rate")
    years = r["years"]
    if "mh_or" in years:
        size = "small" if abs(r["phi"]) < 0.1 else "moderate" if abs(r["phi"]) < 0.3 else "large"
        tail = (f"The association is {size} in absolute terms (φ = {r['phi']:.3f}) and, after "
                f"adjusting for year, MH OR = {years['mh_or']:.2f} (CMH p = {_p(years['p_cmh'])})"
                f"; FI was higher for the foreign group in {years['higher']} of "
                f"{years['compared']} years.")
    else:
        tail = f"The association is measured by φ = {r['phi']:.3f}."
    lines.append((", ".join(parts) + ". " if parts else "") + tail)
    return lines


def headline(r):
    """One plain sentence for the top of the page."""
    if not r["ok"]:
        return ""
    f, g = r["rows"][0]["fi"], r["rows"][1]["fi"]
    if r["significant"]:
        word = "more" if f > g else "less"
        return (f"Casualties in crashes involving a foreign-registered vehicle were {word} likely "
                f"to be killed: {f:.1f} killed per 100 casualties, against {g:.1f} in crashes "
                f"with only Ghanaian-registered vehicles. The difference is too large to be "
                f"chance (all four tests agree).")
    return (f"{f:.1f} killed per 100 casualties in crashes involving a foreign-registered "
            f"vehicle, against {g:.1f} with only Ghanaian-registered vehicles. The difference "
            f"could be chance: at least one of the four tests does not find it significant.")
