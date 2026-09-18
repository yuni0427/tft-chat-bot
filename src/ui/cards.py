"""
アイテムビルド・構成レコメンドをHTML/CSSカードとして描画するモジュール。
Streamlit側では `st.markdown(get_base_css(), unsafe_allow_html=True)` を
アプリ起動時に一度呼び出し、その後 render_* 関数の戻り値を
`st.markdown(html, unsafe_allow_html=True)` で描画する想定。
"""
import html as _html

from src.schemas.comp_recommendation import CompRecommendation
from src.schemas.item_build import ItemBuildAdvice

_CONFIDENCE_BADGE_CLASS = {
    "HIGH": "badge-high",
    "MEDIUM": "badge-medium",
    "LOW": "badge-low",
}

_TIER_BADGE_CLASS = {
    "S": "badge-tier-s",
    "A": "badge-tier-a",
    "B": "badge-tier-b",
}


def get_base_css() -> str:
    return """
<style>
.tft-card {
    border: 1px solid #3a3a4a;
    border-radius: 12px;
    padding: 16px 18px;
    margin-bottom: 16px;
    background: #1e1e2f;
    color: #f0f0f0;
}
.tft-card h4 {
    margin-top: 0;
    margin-bottom: 10px;
}
.tft-section-title {
    font-size: 0.9em;
    font-weight: bold;
    color: #b0b0c0;
    margin: 12px 0 6px 0;
}
.core-item-box {
    border: 2px solid #ff4b4b;
    border-radius: 8px;
    padding: 8px 12px;
    margin: 4px 0;
    background: rgba(255, 75, 75, 0.08);
}
.core-item-box .item-name {
    font-weight: bold;
    color: #ff8080;
}
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.75em;
    font-weight: bold;
    margin-right: 6px;
}
.badge-high { background: #2ecc71; color: #08331b; }
.badge-medium { background: #3498db; color: #08243d; }
.badge-low { background: #95a5a6; color: #202020; }
.badge-tier-s { background: #e67e22; color: #3a2100; }
.badge-tier-a { background: #f1c40f; color: #3a2f00; }
.badge-tier-b { background: #7f8c8d; color: #1c1c1c; }
.badge-strategy-top4 { background: #5dade2; color: #08243d; }
.badge-strategy-balanced { background: #58d68d; color: #08331b; }
.badge-strategy-first { background: #f5b041; color: #3a2100; }
.badge-strategy-risk { background: #ec7063; color: #3a0d08; }
.badge-strategy-unknown { background: #626567; color: #f0f0f0; }
.bis-box {
    border: 1px solid #4a90d9;
    border-radius: 8px;
    padding: 8px 12px;
    margin: 4px 0;
    background: rgba(74, 144, 217, 0.08);
}
.substitute-row {
    display: flex;
    justify-content: space-between;
    padding: 4px 8px;
    border-bottom: 1px dashed #444;
    font-size: 0.92em;
}
.delta-place {
    color: #ffb84d;
    font-weight: bold;
}
.special-build-box {
    border: 2px dashed #9b59b6;
    border-radius: 8px;
    padding: 8px 12px;
    margin: 4px 0;
    background: rgba(155, 89, 182, 0.10);
}
.warning-box {
    border: 1px solid #e67e22;
    background: rgba(230, 126, 34, 0.1);
    border-radius: 8px;
    padding: 8px 12px;
    margin: 4px 0;
    font-size: 0.92em;
}
.debuff-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 6px;
    font-size: 0.88em;
}
.debuff-table td, .debuff-table th {
    border: 1px solid #444;
    padding: 4px 8px;
    text-align: left;
}
.debuff-table th {
    background: #2a2a3d;
}
.comp-meta-row {
    display: flex;
    gap: 16px;
    margin: 8px 0;
    font-size: 0.92em;
}
</style>
"""


def _esc(text) -> str:
    return _html.escape(str(text))


def _confidence_badge(level: str) -> str:
    css_class = _CONFIDENCE_BADGE_CLASS.get(level, "badge-low")
    return f'<span class="badge {css_class}">信頼度: {_esc(level)}</span>'


def _tier_badge(tier: str) -> str:
    css_class = _TIER_BADGE_CLASS.get(tier, "badge-tier-b")
    return f'<span class="badge {css_class}">Tier {_esc(tier)}</span>'


def _strategy_badge(comp: CompRecommendation) -> str:
    css_class = {
        "top4": "badge-strategy-top4",
        "balanced": "badge-strategy-balanced",
        "first_place": "badge-strategy-first",
        "high_risk_high_return": "badge-strategy-risk",
    }.get(comp.strategy_goal, "badge-strategy-unknown")
    return f'<span class="badge {css_class}">{_esc(comp.strategy_goal_label)}</span>'


def render_item_build_card(advice: ItemBuildAdvice) -> str:
    """アイテムビルドカードのHTMLを生成する。"""
    core_html = "".join(
        f'<div class="core-item-box"><span class="item-name">★ {_esc(ci.name)}</span>'
        f'<div>{_esc(ci.reason)}</div></div>'
        for ci in advice.core_items
    ) or '<div style="color:#999;">コアアイテムの十分な統計データがありません。</div>'

    bis = advice.bis_standard_build
    bis_first_place = bis.first_place_rate
    bis_top4 = bis.top4_rate
    bis_html = (
        f'<div class="bis-box">'
        f'{_confidence_badge(bis.confidence_level)}'
        f'<b>{_esc(" + ".join(bis.items))}</b><br/>'
        f'平均順位: {bis.avg_place} / '
        f'1位率: {f"{int(bis_first_place * 100)}%" if bis_first_place is not None else "未集計"} / '
        f'Top4率: {f"{int(bis_top4 * 100)}%" if bis_top4 is not None else "未集計"} '
        f'(サンプル {bis.sample_size}件)'
        f'{f"<br/><span style=\'color:#aaa;\'>{_esc(bis.special_note)}</span>" if bis.special_note else ""}'
        f'</div>'
    )

    sub_rows = "".join(
        f'<div class="substitute-row">'
        f'<span>{_esc(s.item)}{f" ({_esc(s.condition)})" if s.condition else ""}</span>'
        f'<span class="delta-place">+{s.delta_avg_place:.2f} 平均順位</span>'
        f'</div>'
        for s in advice.substitutes
    )
    sub_html = sub_rows or '<div style="color:#999;">代用候補の統計データはありません。</div>'

    special_html = ""
    if advice.special_synergy_builds:
        blocks = "".join(
            f'<div class="special-build-box">'
            f'{_confidence_badge(sb.confidence_level)}'
            f'<b>{_esc(" + ".join(sb.items))}</b><br/>'
            f'平均順位: {sb.avg_place} / '
            f'1位率: {f"{int(sb.first_place_rate * 100)}%" if sb.first_place_rate is not None else "未集計"} / '
            f'Top4率: {f"{int(sb.top4_rate * 100)}%" if sb.top4_rate is not None else "未集計"} '
            f'(サンプル {sb.sample_size}件)'
            f'{f"<br/><span style=\'color:#d9b3ff;\'>{_esc(sb.special_note)}</span>" if sb.special_note else ""}'
            f'</div>'
            for sb in advice.special_synergy_builds
        )
        special_html = (
            '<div class="tft-section-title">特殊アイテム枠（アーティファクト/紋章）</div>' + blocks
        )

    warning_html = "".join(
        f'<div class="warning-box">⚠️ <b>{_esc(" × ".join(w.items))}</b><br/>{_esc(w.reason)}</div>'
        for w in advice.anti_synergy_warnings
    ) or '<div style="color:#999;">特筆すべきアンチシナジーはありません。</div>'

    debuff_rows = "".join(
        f'<tr><td>{_esc(d.debuff_type)}</td><td>{_esc(d.carrier)}</td><td>{_esc(d.note)}</td></tr>'
        for d in advice.debuff_roles
    )
    debuff_html = (
        f'<table class="debuff-table"><tr><th>デバフ</th><th>担当</th><th>メモ</th></tr>{debuff_rows}</table>'
        if advice.debuff_roles
        else '<div style="color:#999;">デバフ担当の情報はありません。</div>'
    )

    return f"""
<div class="tft-card">
  <h4>🛡️ {_esc(advice.champion)} のアイテムビルド</h4>
  <div class="tft-section-title">必須コアアイテム</div>
  {core_html}
  <div class="tft-section-title">通常BiS（理想ビルド）</div>
  {bis_html}
  <div class="tft-section-title">代用候補（妥協時の統計変化）</div>
  {sub_html}
  {special_html}
  <div class="tft-section-title">アンチシナジー警告</div>
  {warning_html}
  <div class="tft-section-title">デバフ（分解/細断/重傷）担当チェック</div>
  {debuff_html}
</div>
"""


def render_comp_card(comp: CompRecommendation) -> str:
    """構成逆引きカードのHTMLを生成する。"""
    emblem_html = (
        f'<div>紋章の推奨装着先: <b>{_esc(comp.emblem_holder)}</b></div>'
        if comp.emblem_holder
        else ""
    )
    key_units_html = ", ".join(_esc(u) for u in comp.key_units)

    return f"""
<div class="tft-card">
  <h4>🧩 {_esc(comp.comp_name)}</h4>
  <div class="comp-meta-row">
    {_tier_badge(comp.tier)}
    {_confidence_badge(comp.confidence_level)}
    <span>平均順位: {comp.avg_place}</span>
        <span>1位率: {f"{int(comp.first_place_rate * 100)}%" if comp.first_place_rate is not None else "未集計"}</span>
    <span>Top4率: {int(comp.top4_rate * 100)}%</span>
    <span>サンプル: {comp.sample_size}件</span>
  </div>
    <div class="comp-meta-row">
        {_strategy_badge(comp)}
        <span>{_esc(comp.strategy_description)}</span>
    </div>
  <div>主要ユニット: {key_units_html}</div>
  {emblem_html}
  <div class="tft-section-title">アイテム活用理由</div>
  <div>{_esc(comp.item_synergy_reason)}</div>
</div>
"""
