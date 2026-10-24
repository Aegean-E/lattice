"""Quantitative meta-analysis engine: fixed/random effects pooling, Cochran's Q, I-squared, and Forest Plots."""

import html
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from lattice.errors import fail
from lattice.repository import Repository


@dataclass(frozen=True)
class MetaStudy:
    """An individual study effect size and standard error for quantitative pooling."""

    id: str
    label: str
    effect_size: float
    se: float
    ci_lower: float
    ci_upper: float
    weight: float = 0.0
    study_type: str = "General Study"

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready representation."""
        return {
            "id": self.id,
            "label": self.label,
            "effect_size": self.effect_size,
            "se": self.se,
            "ci_lower": self.ci_lower,
            "ci_upper": self.ci_upper,
            "weight": self.weight,
            "study_type": self.study_type,
        }


@dataclass(frozen=True)
class MetaAnalysisResult:
    """Consolidated quantitative meta-analysis statistical report."""

    studies: List[MetaStudy]
    model: str
    pooled_effect: float
    pooled_se: float
    pooled_ci_lower: float
    pooled_ci_upper: float
    cochran_q: float
    df: int
    p_value: float
    i_squared: float
    tau_squared: float

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready representation."""
        return {
            "model": self.model,
            "pooled_effect": self.pooled_effect,
            "pooled_se": self.pooled_se,
            "pooled_ci_lower": self.pooled_ci_lower,
            "pooled_ci_upper": self.pooled_ci_upper,
            "cochran_q": self.cochran_q,
            "df": self.df,
            "p_value": self.p_value,
            "i_squared": self.i_squared,
            "tau_squared": self.tau_squared,
            "studies": [s.to_dict() for s in self.studies],
        }


def _chi2_sf(x: float, df: int) -> float:
    """Survival function (p-value, 1 - CDF) for chi-square distribution with df degrees of freedom."""
    if df <= 0 or x <= 0:
        return 1.0
    a = df / 2.0
    z = x / 2.0
    try:
        t = math.exp(-z + a * math.log(z) - math.lgamma(a + 1))
        total = t
        for n in range(1, 300):
            t *= z / (a + n)
            total += t
            if t < 1e-15 * total:
                break
        return max(0.0, min(1.0, 1.0 - total))
    except (ValueError, OverflowError):
        return 0.0


def study_from_confidence_interval(
    id: str,
    label: str,
    effect_size: float,
    ci_lower: float,
    ci_upper: float,
    study_type: str = "General Study",
) -> MetaStudy:
    """Construct a MetaStudy from a point estimate and 95% confidence interval."""
    if ci_upper < ci_lower:
        fail("invalid confidence interval", "ci_upper must be greater than ci_lower",
             "pass valid interval bounds")
    se = (ci_upper - ci_lower) / (2.0 * 1.959964)
    if se <= 0:
        se = 1e-6
    return MetaStudy(
        id=str(id).strip(),
        label=str(label).strip() or str(id).strip(),
        effect_size=round(float(effect_size), 4),
        se=round(float(se), 4),
        ci_lower=round(float(ci_lower), 4),
        ci_upper=round(float(ci_upper), 4),
        study_type=str(study_type).strip() or "General Study",
    )


def study_from_two_groups(
    id: str,
    label: str,
    n1: int,
    m1: float,
    sd1: float,
    n2: int,
    m2: float,
    sd2: float,
    study_type: str = "Randomized Controlled Trial",
) -> MetaStudy:
    """Compute Hedges' g standardized mean difference from two-arm trial statistics."""
    if n1 <= 1 or n2 <= 1:
        fail("sample size too small", "each arm requires at least 2 participants", "provide n >= 2")
    if sd1 <= 0 or sd2 <= 0:
        fail("invalid standard deviation", "standard deviations must be strictly positive", "provide sd > 0")

    df = n1 + n2 - 2
    sd_pooled = math.sqrt(((n1 - 1) * (sd1 ** 2) + (n2 - 1) * (sd2 ** 2)) / df)
    if sd_pooled <= 0:
        sd_pooled = 1e-6
    cohen_d = (m1 - m2) / sd_pooled
    # Hedges small sample correction factor J
    j_factor = 1.0 - (3.0 / (4.0 * (n1 + n2) - 9.0))
    hedges_g = cohen_d * j_factor
    v_g = ((n1 + n2) / (n1 * n2)) + ((hedges_g ** 2) / (2.0 * (n1 + n2)))
    se_g = math.sqrt(v_g)
    ci_lower = hedges_g - 1.959964 * se_g
    ci_upper = hedges_g + 1.959964 * se_g

    return MetaStudy(
        id=str(id).strip(),
        label=str(label).strip() or str(id).strip(),
        effect_size=round(hedges_g, 4),
        se=round(se_g, 4),
        ci_lower=round(ci_lower, 4),
        ci_upper=round(ci_upper, 4),
        study_type=str(study_type).strip(),
    )


def _coerce_study(item: Union[MetaStudy, Dict[str, Any]]) -> MetaStudy:
    """Convert a dictionary or MetaStudy instance into a normalized MetaStudy."""
    if isinstance(item, MetaStudy):
        return item
    if not isinstance(item, dict):
        fail("invalid study specification", "each study must be a dictionary or MetaStudy", "pass study objects")

    s_id = str(item.get("id") or item.get("paper_id") or item.get("label") or "study").strip()
    label = str(item.get("label") or item.get("title") or s_id).strip()
    study_type = str(item.get("study_type") or "General Study").strip()

    if "n1" in item and "m1" in item and "sd1" in item:
        return study_from_two_groups(
            s_id, label,
            int(item["n1"]), float(item["m1"]), float(item["sd1"]),
            int(item["n2"]), float(item["m2"]), float(item["sd2"]),
            study_type=study_type,
        )

    effect_size = float(item.get("effect_size", item.get("effect", 0.0)))
    if "se" in item:
        se = float(item["se"])
        if se <= 0:
            se = 1e-6
        ci_l = float(item.get("ci_lower", effect_size - 1.959964 * se))
        ci_u = float(item.get("ci_upper", effect_size + 1.959964 * se))
    elif "ci_lower" in item and "ci_upper" in item:
        ci_l = float(item["ci_lower"])
        ci_u = float(item["ci_upper"])
        se = (ci_u - ci_l) / (2.0 * 1.959964)
        if se <= 0:
            se = 1e-6
    else:
        # Fallback default standard error from confidence score if present
        conf = float(item.get("confidence", 0.7))
        se = max(0.05, round(1.0 - conf * 0.8, 3))
        ci_l = effect_size - 1.959964 * se
        ci_u = effect_size + 1.959964 * se

    return MetaStudy(
        id=s_id,
        label=label,
        effect_size=round(effect_size, 4),
        se=round(se, 4),
        ci_lower=round(ci_l, 4),
        ci_upper=round(ci_u, 4),
        study_type=study_type,
    )


def compute_meta_analysis(
    studies: Sequence[Union[MetaStudy, Dict[str, Any]]],
    model: str = "random",
) -> MetaAnalysisResult:
    """Execute fixed or DerSimonian-Laird random effects quantitative meta-analysis."""
    if not studies:
        fail("no studies provided for meta-analysis", "meta-analysis requires at least 1 study",
             "pass a non-empty sequence of studies")

    norm_model = str(model or "random").strip().lower()
    if norm_model not in ("fixed", "random"):
        fail(f"unknown meta-analysis model '{model}'", "model must be 'fixed' or 'random'",
             "choose model='fixed' or model='random'")

    parsed = [_coerce_study(s) for s in studies]
    k = len(parsed)

    # 1. Fixed-effect inverse variance weights
    variances = [max(1e-8, s.se ** 2) for s in parsed]
    fixed_weights = [1.0 / v for v in variances]
    sum_w_fixed = sum(fixed_weights)

    if sum_w_fixed <= 0:
        sum_w_fixed = 1e-8

    fixed_pooled_effect = sum(w * s.effect_size for w, s in zip(fixed_weights, parsed)) / sum_w_fixed

    # 2. Heterogeneity statistics
    if k >= 2:
        cochran_q = sum(w * ((s.effect_size - fixed_pooled_effect) ** 2) for w, s in zip(fixed_weights, parsed))
        df = k - 1
        i_squared = max(0.0, (cochran_q - df) / cochran_q * 100.0) if cochran_q > 0 else 0.0
        p_val = _chi2_sf(cochran_q, df)

        sum_sq_w = sum(w ** 2 for w in fixed_weights)
        c_denom = sum_w_fixed - (sum_sq_w / sum_w_fixed)
        tau_squared = max(0.0, (cochran_q - df) / c_denom) if c_denom > 0 else 0.0
    else:
        cochran_q = 0.0
        df = 0
        i_squared = 0.0
        tau_squared = 0.0
        p_val = 1.0

    # 3. Model pooling and weight assignment
    if norm_model == "random":
        random_weights = [1.0 / (v + tau_squared) for v in variances]
        sum_w = sum(random_weights)
        if sum_w <= 0:
            sum_w = 1e-8
        pooled_effect = sum(w * s.effect_size for w, s in zip(random_weights, parsed)) / sum_w
        pooled_se = math.sqrt(1.0 / sum_w)
        pct_weights = [(w / sum_w) * 100.0 for w in random_weights]
    else:
        pooled_effect = fixed_pooled_effect
        pooled_se = math.sqrt(1.0 / sum_w_fixed)
        pct_weights = [(w / sum_w_fixed) * 100.0 for w in fixed_weights]

    pooled_ci_lower = pooled_effect - 1.959964 * pooled_se
    pooled_ci_upper = pooled_effect + 1.959964 * pooled_se

    weighted_studies = [
        MetaStudy(
            id=s.id,
            label=s.label,
            effect_size=s.effect_size,
            se=s.se,
            ci_lower=s.ci_lower,
            ci_upper=s.ci_upper,
            weight=round(pct, 2),
            study_type=s.study_type,
        )
        for s, pct in zip(parsed, pct_weights)
    ]

    return MetaAnalysisResult(
        studies=weighted_studies,
        model=norm_model,
        pooled_effect=round(pooled_effect, 4),
        pooled_se=round(pooled_se, 4),
        pooled_ci_lower=round(pooled_ci_lower, 4),
        pooled_ci_upper=round(pooled_ci_upper, 4),
        cochran_q=round(cochran_q, 3),
        df=df,
        p_value=round(p_val, 4),
        i_squared=round(i_squared, 1),
        tau_squared=round(tau_squared, 4),
    )


def render_forest_ascii(result: MetaAnalysisResult, width: int = 40) -> str:
    """Format quantitative meta-analysis results as an aligned ASCII forest plot."""
    all_low = [s.ci_lower for s in result.studies] + [result.pooled_ci_lower]
    all_high = [s.ci_upper for s in result.studies] + [result.pooled_ci_upper]
    val_min = min(all_low)
    val_max = max(all_high)

    # Ensure 0 is included on the axis
    axis_min = min(-0.1, val_min - 0.1)
    axis_max = max(0.1, val_max + 0.1)
    span = axis_max - axis_min
    if span <= 0:
        span = 1.0

    def _col(val: float) -> int:
        idx = int(((val - axis_min) / span) * (width - 1))
        return max(0, min(width - 1, idx))

    zero_col = _col(0.0)

    header = f"{'Study':<26} {'Effect [95% CI]':<20} {'Weight':<8} Forest Plot ({axis_min:.1f} to {axis_max:.1f})"
    divider = "-" * (len(header) + width - 15)
    lines: List[str] = [header, divider]

    for s in result.studies:
        c_low = _col(s.ci_lower)
        c_high = _col(s.ci_upper)
        c_mid = _col(s.effect_size)

        chars = [" "] * width
        chars[zero_col] = "|"
        for i in range(c_low, c_high + 1):
            if chars[i] == " ":
                chars[i] = "-"
        chars[c_low] = "["
        chars[c_high] = "]"
        chars[c_mid] = "#"

        label = (s.label[:23] + "...") if len(s.label) > 26 else s.label
        ci_str = f"{s.effect_size:+.2f} [{s.ci_lower:+.2f}, {s.ci_upper:+.2f}]"
        wt_str = f"{s.weight:5.1f}%"
        plot_str = "".join(chars)
        lines.append(f"{label:<26} {ci_str:<20} {wt_str:<8} {plot_str}")

    lines.append(divider)

    # Summary diamond
    p_low = _col(result.pooled_ci_lower)
    p_high = _col(result.pooled_ci_upper)
    p_mid = _col(result.pooled_effect)

    sum_chars = [" "] * width
    sum_chars[zero_col] = "|"
    for i in range(p_low, p_high + 1):
        if sum_chars[i] == " ":
            sum_chars[i] = "="
    sum_chars[p_low] = "<"
    sum_chars[p_high] = ">"
    sum_chars[p_mid] = "D"

    sum_label = f"Pooled ({result.model.capitalize()})"
    sum_ci = f"{result.pooled_effect:+.2f} [{result.pooled_ci_lower:+.2f}, {result.pooled_ci_upper:+.2f}]"
    lines.append(f"{sum_label:<26} {sum_ci:<20} {'100.0%':<8} {''.join(sum_chars)}")

    # Heterogeneity footer
    lines.append(
        f"Heterogeneity: Q = {result.cochran_q:.2f} (df = {result.df}, p = {result.p_value:.3f}), "
        f"I² = {result.i_squared:.1f}%, τ² = {result.tau_squared:.3f}"
    )
    return "\n".join(lines)


def render_forest_svg(result: MetaAnalysisResult, title: str = "Meta-Analysis Forest Plot") -> str:
    """Generate a publication-grade, self-contained SVG forest plot."""
    k = len(result.studies)
    row_height = 36
    top_margin = 70
    bottom_margin = 90
    total_height = top_margin + (k * row_height) + bottom_margin

    all_low = [s.ci_lower for s in result.studies] + [result.pooled_ci_lower]
    all_high = [s.ci_upper for s in result.studies] + [result.pooled_ci_upper]
    val_min = min(all_low)
    val_max = max(all_high)

    axis_min = min(-0.1, val_min - 0.15)
    axis_max = max(0.1, val_max + 0.15)
    span = axis_max - axis_min
    if span <= 0:
        span = 1.0

    plot_x = 480
    plot_width = 330

    def _x(val: float) -> float:
        return plot_x + ((val - axis_min) / span) * plot_width

    zero_x = _x(0.0)

    svg_parts: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 850 {total_height}" '
        f'width="100%" height="{total_height}" style="background:#0f172a;color:#f8fafc;font-family:system-ui,-apple-system,sans-serif;">',
        f'<text x="25" y="32" fill="#f8fafc" font-size="16" font-weight="700">{html.escape(title)}</text>',
        f'<text x="25" y="52" fill="#94a3b8" font-size="11">Model: {result.model.capitalize()}-Effects | Studies: {k}</text>',
        # Column headers
        '<text x="25" y="75" fill="#cbd5e1" font-size="12" font-weight="600">Study / Trial</text>',
        '<text x="290" y="75" fill="#cbd5e1" font-size="12" font-weight="600">Effect [95% CI]</text>',
        '<text x="420" y="75" fill="#cbd5e1" font-size="12" font-weight="600">Weight</text>',
        f'<text x="{plot_x}" y="75" fill="#cbd5e1" font-size="12" font-weight="600">Effect Size ({axis_min:.1f} to {axis_max:.1f})</text>',
        '<line x1="20" y1="83" x2="830" y2="83" stroke="#334155" stroke-width="1.2"/>',
    ]

    # Reference zero line
    plot_top = 85
    plot_bottom = top_margin + (k * row_height) + 40
    svg_parts.append(
        f'<line x1="{zero_x:.1f}" y1="{plot_top}" x2="{zero_x:.1f}" y2="{plot_bottom}" '
        f'stroke="#64748b" stroke-dasharray="4,4" stroke-width="1.2"/>'
    )

    # Study rows
    for idx, s in enumerate(result.studies):
        y = top_margin + 30 + (idx * row_height)
        s_low = _x(s.ci_lower)
        s_high = _x(s.ci_upper)
        s_mid = _x(s.effect_size)

        # Box size proportional to weight (min 5, max 16)
        box_size = max(5.0, min(16.0, math.sqrt(s.weight) * 2.2))

        lbl = html.escape(s.label if len(s.label) <= 32 else s.label[:29] + "...")
        ci_str = f"{s.effect_size:+.2f} [{s.ci_lower:+.2f}, {s.ci_upper:+.2f}]"

        svg_parts.extend([
            f'<text x="25" y="{y+4}" fill="#f1f5f9" font-size="12">{lbl}</text>',
            f'<text x="290" y="{y+4}" fill="#94a3b8" font-size="11">{ci_str}</text>',
            f'<text x="420" y="{y+4}" fill="#94a3b8" font-size="11">{s.weight:.1f}%</text>',
            # Horizontal CI whisker line
            f'<line x1="{s_low:.1f}" y1="{y}" x2="{s_high:.1f}" y2="{y}" stroke="#38bdf8" stroke-width="1.5"/>',
            # Whisker tick caps
            f'<line x1="{s_low:.1f}" y1="{y-4}" x2="{s_low:.1f}" y2="{y+4}" stroke="#38bdf8" stroke-width="1.5"/>',
            f'<line x1="{s_high:.1f}" y1="{y-4}" x2="{s_high:.1f}" y2="{y+4}" stroke="#38bdf8" stroke-width="1.5"/>',
            # Study weight box
            f'<rect x="{s_mid - box_size/2.0:.1f}" y="{y - box_size/2.0:.1f}" width="{box_size:.1f}" height="{box_size:.1f}" '
            f'fill="#0284c7" stroke="#e0f2fe" stroke-width="1.2"/>',
        ])

    # Summary row
    sum_y = top_margin + 20 + (k * row_height) + 15
    svg_parts.append(f'<line x1="20" y1="{sum_y - 12}" x2="830" y2="{sum_y - 12}" stroke="#334155" stroke-width="1"/>')

    sum_lbl = f"Pooled Estimate ({result.model.capitalize()})"
    sum_ci = f"{result.pooled_effect:+.2f} [{result.pooled_ci_lower:+.2f}, {result.pooled_ci_upper:+.2f}]"
    p_low = _x(result.pooled_ci_lower)
    p_high = _x(result.pooled_ci_upper)
    p_mid = _x(result.pooled_effect)

    # Diamond points: left, top, right, bottom
    diamond_h = 7.0
    pts = f"{p_low:.1f},{sum_y:.1f} {p_mid:.1f},{sum_y - diamond_h:.1f} {p_high:.1f},{sum_y:.1f} {p_mid:.1f},{sum_y + diamond_h:.1f}"

    svg_parts.extend([
        f'<text x="25" y="{sum_y + 4}" fill="#f8fafc" font-size="12" font-weight="700">{sum_lbl}</text>',
        f'<text x="290" y="{sum_y + 4}" fill="#38bdf8" font-size="11" font-weight="700">{sum_ci}</text>',
        f'<text x="420" y="{sum_y + 4}" fill="#38bdf8" font-size="11" font-weight="700">100.0%</text>',
        f'<polygon points="{pts}" fill="#38bdf8" stroke="#f0f9ff" stroke-width="1.5"/>',
    ])

    # Footer heterogeneity statistics
    foot_y = sum_y + 32
    svg_parts.extend([
        f'<line x1="20" y1="{foot_y - 10}" x2="830" y2="{foot_y - 10}" stroke="#1e293b" stroke-width="1"/>',
        f'<text x="25" y="{foot_y+6}" fill="#94a3b8" font-size="11">'
        f'Heterogeneity: Q = {result.cochran_q:.2f} (df = {result.df}, p = {result.p_value:.3f}) | '
        f'I² = {result.i_squared:.1f}% | τ² = {result.tau_squared:.4f}'
        f'</text>',
        '</svg>',
    ])

    return "\n".join(svg_parts)


def meta_analyze_question(
    repository: Repository,
    question_ref: str,
    model: str = "random",
) -> MetaAnalysisResult:
    """Execute quantitative meta-analysis on evidentiary claims connected to a question."""
    q_obj = repository.get_question(question_ref)
    if not q_obj:
        fail(f"question '{question_ref}' not found", "cannot meta-analyze a nonexistent question",
             "pass an existing question reference or id")

    edges = repository.neighbors(f"question:{q_obj.id}")
    claim_studies: List[MetaStudy] = []

    for edge in edges:
        if edge.src.startswith("claim:"):
            cid = edge.src.split(":", 1)[1]
            claim = repository.get_claim(cid)
            if claim:
                paper = repository.get_paper(claim.paper_id)
                label = f"{paper.title[:20]} ({paper.year or 'n.d.'})" if paper else claim.id
                stype = paper.study_type if paper else "General Study"
                # Direction from stance
                direction = -1.0 if claim.stance == "contradicts" else 1.0
                conf = claim.confidence if claim.confidence > 0 else 0.7
                # Standardized effect size estimation from confidence
                effect = direction * round(0.3 + (conf * 0.4), 3)
                se = max(0.08, round((1.0 - conf * 0.7) * 0.5, 3))
                claim_studies.append(MetaStudy(
                    id=claim.id,
                    label=label,
                    effect_size=effect,
                    se=se,
                    ci_lower=round(effect - 1.959964 * se, 3),
                    ci_upper=round(effect + 1.959964 * se, 3),
                    study_type=stype,
                ))

    if not claim_studies:
        fail(f"question '{question_ref}' has no linked claims",
             "meta-analysis requires at least one empirical claim linked to the question",
             "add supporting or contradicting claims before running meta-analysis")

    return compute_meta_analysis(claim_studies, model=model)
