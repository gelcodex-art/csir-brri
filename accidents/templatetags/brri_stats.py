from django import template

register = template.Library()


@register.filter
def pval(p):
    """A p-value as in a written report: 0.023, or 1.3E-06 when very small."""
    if p is None:
        return "-"
    return f"{p:.1E}" if p < 0.001 else f"{p:.3f}"


@register.filter
def num(x, places=2):
    """A number with a fixed count of decimals; "-" when there is none."""
    if x is None:
        return "-"
    return f"{x:,.{int(places)}f}"
