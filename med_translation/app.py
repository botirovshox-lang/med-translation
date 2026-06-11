"""
app.py — Medical CAT Translator UI (Streamlit)

Запуск:
    streamlit run app.py

Переменные окружения:
    ANTHROPIC_API_KEY — API-ключ Anthropic (обязателен для перевода)
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import streamlit as st

from med_cat_config import (
    APP_VERSION, MAX_GLOSSARY_TERMS_IN_PROMPT, MAX_TM_MATCHES_IN_PROMPT,
    SEGMENTS_LOG, DATA_DIR, TM_AUTO_INSERT, TM_GREEN, TM_YELLOW,
)

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')

# ─────────────────────────────────────────────────────────────────────────────
# Streamlit page config — MUST be first st call
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Medical CAT Translator",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Кэширование тяжёлых загрузок (один раз за сессию сервера)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner="Загрузка глоссариев…")
def _load_glossary():
    from terminology_loader import get_glossary
    return get_glossary()


@st.cache_resource(show_spinner="Загрузка TM…")
def _load_tm():
    from tm_loader import get_tm
    return get_tm()


@st.cache_resource(show_spinner="Загрузка запрещённых терминов…")
def _load_forbidden():
    from terminology_loader import get_forbidden
    return get_forbidden()


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Badges */
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.82em;
    font-weight: 600;
    margin-right: 4px;
}
.badge-approved  { background:#d4edda; color:#155724; border:1px solid #c3e6cb; }
.badge-reference { background:#d1ecf1; color:#0c5460; border:1px solid #bee5eb; }
.badge-error     { background:#f8d7da; color:#721c24; border:1px solid #f5c6cb; }
.badge-warning   { background:#fff3cd; color:#856404; border:1px solid #ffeeba; }

/* Risk badges */
.risk-CRITICAL { background:#ff4444; color:#fff; padding:3px 12px; border-radius:10px; font-weight:700; }
.risk-HIGH     { background:#ff8800; color:#fff; padding:3px 12px; border-radius:10px; font-weight:700; }
.risk-MEDIUM   { background:#ffc107; color:#212529; padding:3px 12px; border-radius:10px; font-weight:700; }
.risk-LOW      { background:#28a745; color:#fff; padding:3px 12px; border-radius:10px; font-weight:700; }

/* TM score bars */
.tm-score {
    display:inline-block; width:36px; text-align:right;
    font-weight:700; margin-right:8px;
}
.tm-100 { color:#28a745; }
.tm-97  { color:#28a745; }
.tm-94  { color:#ffc107; }
.tm-low { color:#888; }

/* Panel headers */
.panel-hdr {
    font-size:0.85em; font-weight:600; color:#555;
    text-transform:uppercase; letter-spacing:0.05em;
    margin-bottom:6px;
}
/* Workflow steps */
.wf-step {
    display:inline-block; background:#e9ecef; color:#333;
    padding:2px 10px; border-radius:8px; margin:2px;
    font-size:0.83em;
}
.wf-arrow { color:#888; margin:0 2px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

def _save_segment(record: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with open(SEGMENTS_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def _call_llm(
    source_ru: str,
    term_context: str,
    tm_context: str,
    api_key: str,
) -> str:
    """
    Вызывает Anthropic API с инжектированным глоссарным контекстом.

    Токен-оптимизация:
      - В промпт идут ТОЛЬКО совпавшие термины (не весь глоссарий)
      - TM: не более 3 сегментов
      - Системный промпт кэшируется Anthropic prompt cache
    """
    import anthropic

    system_parts = [
        "You are a professional medical translator specializing in Russian→English translation.",
        "Translate accurately and literally. Preserve all medical meaning.",
        "Do NOT paraphrase. Preserve all numbers, measurements, and dosages exactly.",
        "Return ONLY the translated text, nothing else.",
    ]

    if term_context:
        system_parts.append("\n" + term_context)

    if tm_context:
        system_parts.append("\n" + tm_context)

    system_prompt = "\n".join(system_parts)

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Translate to English:\n\n{source_ru}"}],
    )
    return msg.content[0].text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(f"## 🏥 Medical CAT Translator `v{APP_VERSION}`")
    st.divider()

    # API Key
    api_key = st.text_input(
        "Anthropic API Key",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        type="password",
        help="Ключ хранится только в памяти сессии",
    )

    st.divider()

    # Статистика глоссариев
    st.markdown('<div class="panel-hdr">📚 Загруженные ресурсы</div>',
                unsafe_allow_html=True)
    try:
        gl = _load_glossary()
        tm = _load_tm()
        fl = _load_forbidden()
        s  = gl.stats
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Approved", f"{s['approved']:,}")
            st.metric("TM сегм.", f"{len(tm.entries):,}")
        with col2:
            st.metric("Reference", f"{s['reference']:,}")
            st.metric("Запрещ.", f"{len(fl.entries):,}")
        st.caption(f"Всего терминов: {s['total']:,}")
    except Exception as e:
        st.error(f"Ошибка загрузки ресурсов: {e}")

    st.divider()
    st.caption("📁 Проект: textbook_01")
    if st.button("🔄 Сбросить кэш", use_container_width=True):
        st.cache_resource.clear()
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Session State
# ─────────────────────────────────────────────────────────────────────────────

defaults = {
    'translation':       '',
    'risk_result':       None,
    'term_matches':      [],
    'tm_matches':        [],
    'forbidden_pre':     [],
    'forbidden_post':    [],
    'workflow':          None,
    'status':            'pending',
    'segment_history':   [],
    'last_source':       '',
    'analysed':          False,
    'translated':        False,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# Основной интерфейс
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("## 🏥 Medical CAT Translator")

# ── Ввод / вывод ─────────────────────────────────────────────────────────────
col_src, col_tgt = st.columns(2, gap="medium")

with col_src:
    st.markdown('<div class="panel-hdr">📝 Исходный текст (RU)</div>',
                unsafe_allow_html=True)
    source_text = st.text_area(
        label="source",
        height=160,
        placeholder="Введите медицинский текст на русском…",
        label_visibility="collapsed",
    )
    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        btn_analyse = st.button("🔍 Анализ", use_container_width=True,
                                help="Анализ рисков и терминологии без перевода")
    with btn_col2:
        btn_translate = st.button("▶ Перевести", type="primary",
                                  use_container_width=True,
                                  disabled=not bool(api_key),
                                  help="Требуется API-ключ" if not api_key else "")

with col_tgt:
    st.markdown('<div class="panel-hdr">🌐 Перевод (EN)</div>',
                unsafe_allow_html=True)
    translation_text = st.text_area(
        label="translation",
        value=st.session_state.translation,
        height=160,
        placeholder="Перевод появится здесь…",
        label_visibility="collapsed",
        key="translation_edit",
    )
    tgt_col1, tgt_col2, tgt_col3 = st.columns([1, 1, 1])
    with tgt_col1:
        btn_confirm = st.button("✅ Подтвердить", use_container_width=True,
                                disabled=not bool(st.session_state.translation))
    with tgt_col2:
        btn_review  = st.button("🔁 На ревью",   use_container_width=True,
                                disabled=not bool(st.session_state.translation))
    with tgt_col3:
        if st.session_state.translation:
            st.download_button(
                "⬇ Export", data=st.session_state.translation,
                file_name="segment.txt", mime="text/plain",
                use_container_width=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Анализ (без перевода)
# ─────────────────────────────────────────────────────────────────────────────

def run_analysis(source: str) -> None:
    from terminology_engine import match_segment
    from risk_engine import score_risk
    from workflow_engine import recommend
    from forbidden_checker import pre_check
    from tm_loader import get_tm

    with st.spinner("Анализ…"):
        st.session_state.term_matches   = match_segment(source)
        st.session_state.risk_result    = score_risk(source)
        st.session_state.tm_matches     = get_tm().search(source, top_n=10)
        st.session_state.workflow       = recommend(st.session_state.risk_result)
        st.session_state.forbidden_pre  = pre_check(source)
        st.session_state.last_source    = source
        st.session_state.analysed       = True
        st.session_state.translated     = False


if btn_analyse and source_text.strip():
    run_analysis(source_text)

# ─────────────────────────────────────────────────────────────────────────────
# Перевод
# ─────────────────────────────────────────────────────────────────────────────

if btn_translate and source_text.strip() and api_key:
    # Всегда перезапускаем анализ перед переводом
    run_analysis(source_text)

    from terminology_engine import build_prompt_context, build_tm_context
    from forbidden_checker import post_check

    term_ctx = build_prompt_context(st.session_state.term_matches)
    tm_ctx   = build_tm_context(
        [m for m in st.session_state.tm_matches
         if m.score >= TM_YELLOW][:MAX_TM_MATCHES_IN_PROMPT]
    )

    # Автовставка TM-матча 100%
    auto_tm = next(
        (m for m in st.session_state.tm_matches if m.auto_insert), None
    )

    if auto_tm:
        translation = auto_tm.entry.target_en
        st.session_state.status = 'tm_auto'
        st.success("✅ Автовставка из TM (100%)")
    else:
        with st.spinner("Перевод…"):
            try:
                translation = _call_llm(
                    source_text, term_ctx, tm_ctx, api_key
                )
                st.session_state.status = 'translated'
            except Exception as e:
                st.error(f"Ошибка API: {e}")
                translation = ""

    if translation:
        st.session_state.translation  = translation
        st.session_state.forbidden_post = post_check(source_text, translation)
        st.session_state.translated   = True
        st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Подтверждение / ревью
# ─────────────────────────────────────────────────────────────────────────────

if btn_confirm and st.session_state.translation:
    rec = {
        'id':           datetime.utcnow().isoformat(),
        'source':       st.session_state.last_source or source_text,
        'translation':  st.session_state.translation,
        'status':       'confirmed',
        'risk_level':   getattr(st.session_state.risk_result, 'level', 'UNKNOWN'),
        'tm_score':     max((m.score for m in st.session_state.tm_matches), default=0),
        'forbidden':    len(st.session_state.forbidden_post) > 0,
    }
    _save_segment(rec)
    st.success("✅ Сегмент подтверждён и сохранён")
    # Сброс для следующего сегмента
    st.session_state.translation  = ''
    st.session_state.analysed     = False
    st.session_state.translated   = False
    st.rerun()

if btn_review and st.session_state.translation:
    rec = {
        'id':          datetime.utcnow().isoformat(),
        'source':      st.session_state.last_source or source_text,
        'translation': st.session_state.translation,
        'status':      'needs_review',
        'risk_level':  getattr(st.session_state.risk_result, 'level', 'UNKNOWN'),
    }
    _save_segment(rec)
    st.warning("🔁 Сегмент отправлен на ревью")
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Панели анализа — показываем если есть результаты
# ─────────────────────────────────────────────────────────────────────────────

if st.session_state.analysed:
    risk = st.session_state.risk_result
    wf   = st.session_state.workflow

    # ── Строка: Риск + Рабочий процесс ──────────────────────────────────────
    st.divider()
    risk_col, wf_col = st.columns([1, 2], gap="medium")

    with risk_col:
        st.markdown('<div class="panel-hdr">⚠️ Уровень риска</div>',
                    unsafe_allow_html=True)
        st.markdown(
            f'<span class="risk-{risk.level}">{risk.badge}</span>'
            f'&nbsp; Балл: <b>{risk.risk_score}</b>/100',
            unsafe_allow_html=True,
        )
        if risk.risk_reasons:
            with st.expander("Причины", expanded=False):
                for r in risk.risk_reasons:
                    st.markdown(f"• {r}")

    with wf_col:
        st.markdown('<div class="panel-hdr">📋 Рекомендуемый рабочий процесс</div>',
                    unsafe_allow_html=True)
        # Стрелочный вывод шагов
        steps_html = " <span class='wf-arrow'>→</span> ".join(
            f"<span class='wf-step'>{s.name_ru}</span>"
            for s in wf.steps
        )
        st.markdown(steps_html, unsafe_allow_html=True)
        st.caption(wf.rationale)

    # ── Pre-translation предупреждения ───────────────────────────────────────
    if st.session_state.forbidden_pre:
        st.divider()
        st.markdown('<div class="panel-hdr">⚡ Предупреждения до перевода</div>',
                    unsafe_allow_html=True)
        for alert in st.session_state.forbidden_pre:
            icon = "🔴" if alert.severity == 'error' else "🟡"
            cls  = "badge-error" if alert.severity == 'error' else "badge-warning"
            msg  = alert.message
            st.markdown(
                f'{icon} <span class="badge {cls}">{alert.severity.upper()}</span> {msg}',
                unsafe_allow_html=True,
            )

    st.divider()
    tab_terms, tab_tm, tab_forbidden = st.tabs(
        ["📚 Термины", "🔁 TM-матчи", "🚫 Запрещённые"]
    )

    # ── TAB: Терминология ────────────────────────────────────────────────────
    with tab_terms:
        matches = st.session_state.term_matches
        if not matches:
            st.info("Совпадений с глоссарием не найдено для этого сегмента.")
        else:
            st.caption(f"Найдено совпадений: {len(matches)} "
                       f"(approved: {sum(1 for m in matches if m.is_approved)}, "
                       f"reference: {sum(1 for m in matches if not m.is_approved)})")

            for m in matches:
                tier_cls  = "badge-approved" if m.is_approved else "badge-reference"
                tier_lbl  = "APPROVED" if m.is_approved else "REFERENCE"
                en_display = " / ".join(m.entry.english_variants[:3])
                pct        = f"{int(m.score * 100)}%"

                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(
                        f'<span class="badge {tier_cls}">{tier_lbl}</span> '
                        f'**{m.entry.russian}** → {en_display}',
                        unsafe_allow_html=True,
                    )
                with col_b:
                    st.caption(f"{m.match_type} {pct}")

    # ── TAB: TM-матчи ────────────────────────────────────────────────────────
    with tab_tm:
        tm_matches = st.session_state.tm_matches
        if not tm_matches:
            st.info("TM-матчи ≥94% не найдены.")
        else:
            for m in tm_matches:
                # Цвет по score
                if m.score >= TM_AUTO_INSERT:
                    score_color = "tm-100"
                elif m.score >= TM_GREEN:
                    score_color = "tm-97"
                elif m.score >= TM_YELLOW:
                    score_color = "tm-94"
                else:
                    score_color = "tm-low"

                with st.expander(
                    f"{'🟢' if m.score >= TM_GREEN else '🟡'} "
                    f"{m.score}% — {m.entry.source_ru[:80]}…",
                    expanded=m.score >= TM_AUTO_INSERT,
                ):
                    col_src, col_tgt = st.columns(2)
                    with col_src:
                        st.markdown("**Исходник (RU)**")
                        st.text(m.entry.source_ru[:400])
                    with col_tgt:
                        st.markdown("**Перевод (EN)**")
                        st.text(m.entry.target_en[:400])
                        if m.auto_insert:
                            if st.button("↙ Вставить", key=f"tm_insert_{m.score}"):
                                st.session_state.translation = m.entry.target_en
                                st.rerun()

    # ── TAB: Запрещённые термины ─────────────────────────────────────────────
    with tab_forbidden:
        post_alerts = st.session_state.forbidden_post
        pre_alerts  = st.session_state.forbidden_pre

        if not post_alerts and not pre_alerts:
            st.success("✅ Запрещённых переводов не обнаружено.")
        else:
            all_alerts = pre_alerts + post_alerts
            for alert in all_alerts:
                sev_cls = "badge-error" if alert.severity == 'error' else "badge-warning"
                stage   = "до перевода" if alert.stage == 'pre' else "в переводе"
                pref    = (f" → Рекомендуется: **{alert.preferred_en}**"
                           if alert.preferred_en else "")
                st.markdown(
                    f'{alert.icon} <span class="badge {sev_cls}">'
                    f'{alert.severity.upper()}</span> '
                    f'**{alert.forbidden_en}** ({stage}) — {alert.russian_term}'
                    f'{pref}\n\n'
                    f'<small>Причина: {alert.reason}</small>',
                    unsafe_allow_html=True,
                )
                st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Post-translation forbidden check alert (всплывает сразу после перевода)
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.translated and st.session_state.forbidden_post:
    st.toast(
        f"⚠️ {len(st.session_state.forbidden_post)} запрещённых терминов в переводе!",
        icon="🚫",
    )

# ─────────────────────────────────────────────────────────────────────────────
# История сегментов
# ─────────────────────────────────────────────────────────────────────────────
with st.expander("📜 История сегментов", expanded=False):
    if SEGMENTS_LOG.exists():
        lines = SEGMENTS_LOG.read_text(encoding='utf-8').strip().split('\n')
        lines = [l for l in lines if l.strip()]
        if lines:
            recent = lines[-20:][::-1]   # последние 20, новые сверху
            for line in recent:
                try:
                    rec = json.loads(line)
                    status_icon = {"confirmed": "✅", "needs_review": "🔁"}.get(
                        rec.get('status', ''), "⚪"
                    )
                    risk_lvl = rec.get('risk_level', '?')
                    src_short = rec.get('source', '')[:60]
                    tgt_short = rec.get('translation', '')[:60]
                    st.markdown(
                        f"{status_icon} `{rec.get('id','')[:16]}` "
                        f"**[{risk_lvl}]** {src_short}…\n\n"
                        f"→ {tgt_short}…"
                    )
                    st.divider()
                except Exception:
                    pass
        else:
            st.info("Нет подтверждённых сегментов.")
    else:
        st.info("История пуста.")

# ─────────────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    f"<div style='text-align:center;color:#aaa;font-size:0.75em;margin-top:20px;'>"
    f"Medical CAT Translator v{APP_VERSION} · "
    f"Глоссарий: approved + reference · "
    f"TM: MedlinePlus · "
    f"Движок: Claude Haiku"
    f"</div>",
    unsafe_allow_html=True,
)
