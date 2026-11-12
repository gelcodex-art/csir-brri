"""
Probabilities for the tests on the Analysis page (chi-square, F and normal),
written out here so the system needs no extra statistics package. The methods
are the standard series / continued fractions for the incomplete gamma and
beta functions; tests.py checks them against published table values.
"""
import math

_TINY = 1e-300
_EPS = 1e-14


def _gamma_q(a, x):
    """Upper regularised incomplete gamma function Q(a, x)."""
    if x <= 0:
        return 1.0
    front = math.exp(-x + a * math.log(x) - math.lgamma(a))
    if x < a + 1:                       # series for P(a, x)
        ap, term, total = a, 1 / a, 1 / a
        for _ in range(1000):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * _EPS:
                break
        return max(0.0, 1 - total * front)
    b = x + 1 - a                       # continued fraction for Q(a, x)
    c, d = 1 / _TINY, 1 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = _TINY if abs(d) < _TINY else d
        c = b + an / c
        c = _TINY if abs(c) < _TINY else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < _EPS:
            break
    return min(1.0, front * h)


def _beta_cf(a, b, x):
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (_TINY if abs(d) < _TINY else d)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)),
                   -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1 + aa * d
            d = 1 / (_TINY if abs(d) < _TINY else d)
            c = 1 + aa / c
            c = _TINY if abs(c) < _TINY else c
            delta = d * c
            h *= delta
        if abs(delta - 1) < _EPS:
            break
    return h


def _beta_i(a, b, x):
    """Regularised incomplete beta function I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _beta_cf(a, b, x) / a
    return 1 - front * _beta_cf(b, a, 1 - x) / b


def chi2_p(chi2, df):
    """Chance of a chi-square value this large or larger with `df` degrees of freedom."""
    return _gamma_q(df / 2, chi2 / 2)


def f_p(f, df1, df2):
    """Chance of an F value this large or larger."""
    if f <= 0:
        return 1.0
    return _beta_i(df2 / 2, df1 / 2, df2 / (df2 + df1 * f))


def normal_p(z):
    """Two-sided chance of a standard normal value this far from zero."""
    return math.erfc(abs(z) / math.sqrt(2))


def p_text(p):
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"
