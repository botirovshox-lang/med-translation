"""
app_v55.py — Medical CAT Translator v5.5 + Anthropic hybrid

Объединяет:
  - v5.5: DOCX CAT workflow, QA, back-check, safety review (OpenAI)
  - Наша система: глоссарии, TM, риск-оценка, рабочие процессы (Anthropic + локальные)

Запуск:
    streamlit run app_v55.py
"""
import streamlit as st
import pandas as pd
import json
from pathlib import Path
# Removed: ag-Grid no longer used, using Streamlit columns instead

# Config
from config_v55 import APP_NAME, APP_VERSION, DEFAULT_TRANSLATION_MODEL, AVAILABLE_MODELS

# Database
from db import (
    init_db,
    get_projects,
    get_project,
    get_segments,
    get_segment,
    update_segment,
    confirm_segment,
    add_glossary_term,
    get_glossary,
    glossary_prompt,
    import_tm_rows,
    delete_project,
)

# CAT workflow (v5.5)
from docx_cat import import_docx_project, export_translated_docx
from pipeline import translate_segment, qa_segment, extract_terms_from_segment, back_translate_check

# TM search
from tm import find_tm_suggestion

# Google Translate
from google_translate import translate_google, GOOGLE_TRANSLATE_AVAILABLE

# Инициализация
init_db()

# Streamlit config
st.set_page_config(
    page_title=APP_NAME,
    page_icon="🏥",
    layout="wide",
)

st.title(f"🏥 {APP_NAME} v{APP_VERSION}")

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ Параметры")
    translation_model = st.selectbox("Translation model", AVAILABLE_MODELS, index=0)
    review_model = st.selectbox("Review / QA model", AVAILABLE_MODELS, index=0)
    st.caption("Recommended: gpt-5.5 (not gpt-5.5-thinking)")

    # Информация о загруженных ресурсах
    st.markdown("---")
    st.subheader("📚 Loaded Resources")

    from pathlib import Path
    from config_v55 import APPROVED_TSV, FORBIDDEN_TSV, TM_TSV

    resources = {
        "✅ Approved Glossary": APPROVED_TSV,
        "⚠️ Forbidden Terms": FORBIDDEN_TSV,
        "🔁 MedlinePlus TM": TM_TSV,
    }

    for name, path in resources.items():
        if path.exists():
            st.success(f"{name} — Loaded")
        else:
            st.warning(f"{name} — Not found")

    st.markdown("---")
    st.caption(
        "**Glossary Usage**:\n"
        "• 500 top approved terms injected into prompts\n"
        "• Forbidden terms checked in QA\n"
        "• MedlinePlus TM for 100% matches"
    )

# ─────────────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────────────
tabs = st.tabs([
    "📥 Import DOCX",
    "✏️ Segment Editor",
    "📚 Glossary",
    "🔁 TM",
    "📤 Export",
    "📋 Backlog",
    "📊 Stats",
])

# ── TAB 0: Import DOCX ────────────────────────────────────────────────────────
with tabs[0]:
    st.subheader("📥 Import DOCX Project")
    uploaded = st.file_uploader("Upload DOCX", type=["docx"])
    title = st.text_input("Project title")
    source_lang = st.text_input("Source language", value="Russian")
    target_lang = st.text_input("Target language", value="English")

    if uploaded and st.button("Create project"):
        pid, count = import_docx_project(uploaded, title or uploaded.name, source_lang, target_lang)
        st.success(f"✅ Project #{pid}; {count} segments")

    projects = get_projects()
    if projects:
        st.subheader("Projects")
        st.dataframe(pd.DataFrame(projects))

# ── TAB 1: Segment Editor (v5.5 Variant 2) ──────────────────────────────────
with tabs[1]:
    st.subheader("✏️ Segment Editor")
    projects = get_projects()
    if not projects:
        st.info("⚠️ Import a DOCX project first")
    else:
        # Project selection
        labels = {f"#{p['id']} — {p['title']}": p['id'] for p in projects}
        pid = labels[st.selectbox("Project", list(labels.keys()))]
        project = get_project(pid)

        # Controls: Delete project, Status filter, Table height
        col_del, col_status, col_height = st.columns([1, 2, 2])

        with col_del:
            if st.button("🗑️ Delete Project", help="Permanently delete this project and all its segments"):
                if st.checkbox("⚠️ Confirm deletion"):
                    delete_project(pid)
                    st.success("✅ Project deleted")
                    st.rerun()

        with col_status:
            status_filter = st.selectbox("Status", [
                'all', 'new', 'translated', 'qa_done', 'back_checked', 'confirmed', 'needs_review', 'failed'
            ], label_visibility="collapsed")

        with col_height:
            table_height = st.slider("Table height (px)", 200, 800, 400, step=50, label_visibility="collapsed")

        segs = get_segments(pid, status_filter)

        # Initialize session state
        if 'selected_segment_id' not in st.session_state:
            st.session_state.selected_segment_id = None
        if 'current_page' not in st.session_state:
            st.session_state.current_page = 0
        if 'target_cache' not in st.session_state:
            st.session_state.target_cache = {}

        if segs:
            st.markdown("### 📋 Segment Editor (Like Memsource)")

            # Pagination and search
            items_per_page = 20
            total_pages = (len(segs) + items_per_page - 1) // items_per_page

            # Initialize search state if not exists
            if 'search_query' not in st.session_state:
                st.session_state.search_query = ''

            # Navigation row
            col_prev, col_page, col_next = st.columns([1, 3, 1], gap="small")
            with col_prev:
                if st.button("◀ Prev", use_container_width=True):
                    if st.session_state.current_page > 0:
                        st.session_state.current_page -= 1
                        st.rerun()
            with col_page:
                st.markdown(f"**Page {st.session_state.current_page + 1} / {total_pages}**")
            with col_next:
                if st.button("Next ▶", use_container_width=True):
                    if st.session_state.current_page < total_pages - 1:
                        st.session_state.current_page += 1
                        st.rerun()

            # Jump to page and search row
            col_jump1, col_jump2, col_search1, col_search2 = st.columns([0.8, 0.4, 2, 0.6], gap="small")

            with col_jump1:
                st.markdown("**Стр:**")
            with col_jump2:
                page_input = st.number_input(
                    "Jump to page",
                    min_value=1,
                    max_value=total_pages,
                    value=st.session_state.current_page + 1,
                    key="page_jump_input",
                    label_visibility="collapsed"
                )
                if page_input != st.session_state.current_page + 1:
                    st.session_state.current_page = page_input - 1
                    st.rerun()

            with col_search1:
                search_query = st.text_input(
                    "Поиск в сегментах",
                    value=st.session_state.search_query,
                    placeholder="Найти текст...",
                    key="search_input",
                    label_visibility="collapsed"
                )
                st.session_state.search_query = search_query

            with col_search2:
                if st.button("✕", key="clear_search", help="Очистить поиск"):
                    st.session_state.search_query = ''
                    st.rerun()

            st.markdown("---")

            # Filter segments by search query
            if st.session_state.search_query:
                search_lower = st.session_state.search_query.lower()
                filtered_segs = [
                    seg for seg in segs
                    if search_lower in (seg.get('source_text') or '').lower() or
                       search_lower in (seg.get('target_text') or '').lower()
                ]
                # Show search results
                st.info(f"🔍 Найдено: **{len(filtered_segs)}** из **{len(segs)}** сегментов")
                filtered_total_pages = (len(filtered_segs) + items_per_page - 1) // items_per_page
                # Reset to page 1 for filtered results
                st.session_state.current_page = 0
                start_idx = 0
                end_idx = items_per_page
                page_segs = filtered_segs[start_idx:end_idx]
            else:
                filtered_total_pages = total_pages
                start_idx = st.session_state.current_page * items_per_page
                end_idx = start_idx + items_per_page
                page_segs = segs[start_idx:end_idx]

            # Two-column layout: Table (left) + Suggestions (right)
            left_col, right_col = st.columns([2, 1], gap="large")

            # ═══════════════════════════════════════════════════════
            # LEFT COLUMN: TABLE
            # ═══════════════════════════════════════════════════════
            with left_col:
                # CSS для выравнивания высоты строк таблицы
                st.markdown("""
                <style>
                [data-testid="column"] > div > div {
                    min-height: 110px;
                }
                </style>
                """, unsafe_allow_html=True)

                # Get segments for current page
                start_idx = st.session_state.current_page * items_per_page
                end_idx = start_idx + items_per_page
                page_segs = segs[start_idx:end_idx]

                # Table header
                header_cols = st.columns([0.8, 0.8, 3.5, 4, 1, 0.8, 0.8, 0.8, 0.8, 0.8, 1.2, 0.8, 0.6, 0.6], gap="small")
                with header_cols[0]:
                    st.markdown("**Select**")
                with header_cols[1]:
                    st.markdown("**ID**")
                with header_cols[2]:
                    st.markdown("**Source**")
                with header_cols[3]:
                    st.markdown("**Target**")
                with header_cols[4]:
                    st.markdown("**TM%**")
                with header_cols[5]:
                    st.markdown("**TM**")
                with header_cols[6]:
                    st.markdown("**GPT**")
                with header_cols[7]:
                    st.markdown("**Google**")
                with header_cols[8]:
                    st.markdown("**QA**")
                with header_cols[9]:
                    st.markdown("**Back**")
                with header_cols[10]:
                    st.markdown("**Status**")
                with header_cols[11]:
                    st.markdown("**QA**")
                with header_cols[12]:
                    st.markdown("**Status**")
                with header_cols[13]:
                    st.markdown("")  # Empty column

                st.markdown("---")

                # Table rows - interactive
                for seg in page_segs:
                    row_cols = st.columns([0.8, 0.8, 3.5, 4, 1, 0.8, 0.8, 0.8, 0.8, 0.8, 1.2, 0.8, 0.6, 0.6], gap="small")

                    # Select button
                    with row_cols[0]:
                        if st.button("✓", key=f"select_{seg['id']}", use_container_width=True):
                            st.session_state.selected_segment_id = seg['id']
                            st.rerun()

                    # ID
                    with row_cols[1]:
                        st.markdown(f"**{seg['id']}**")

                    # Source
                    with row_cols[2]:
                        st.caption(seg['source_text'])

                    # Target (editable) - with session state caching
                    with row_cols[3]:
                        # Always load fresh from DB first
                        db_target = seg.get('target_text') or ''

                        # Use cache only if we just translated
                        if seg['id'] in st.session_state.target_cache:
                            display_target = st.session_state.target_cache[seg['id']]
                        else:
                            display_target = db_target
                            if display_target:
                                st.session_state.target_cache[seg['id']] = display_target

                        # Use unique key to force re-render
                        new_target = st.text_area(
                            "target",
                            value=display_target,
                            height=100,
                            key=f"target_{seg['id']}_{display_target[:20] if display_target else 'empty'}",
                            label_visibility="collapsed"
                        )
                        if new_target != display_target:
                            update_segment(seg['id'], target_text=new_target)
                            st.session_state.target_cache[seg['id']] = new_target

                    # TM%
                    with row_cols[4]:
                        tm_score_val = seg.get('tm_match_score')
                        if tm_score_val is not None and tm_score_val > 0:
                            st.caption(f"{tm_score_val:.0f}%")
                        else:
                            st.caption("—")

                    # TM button
                    with row_cols[5]:
                        if st.button("🔍", key=f"tm_{seg['id']}", use_container_width=True, help="Find TM"):
                            m = find_tm_suggestion(seg['source_text'])
                            if m:
                                update_segment(seg['id'], tm_match_score=m['score'], tm_suggestion=m['target_text'])
                                st.success(f"✅ {m['score']:.0f}%")
                            else:
                                st.info("❌ No match")
                            st.rerun()

                    # Trans button (OpenAI)
                    with row_cols[6]:
                        if st.button("▶️", key=f"trans_{seg['id']}", use_container_width=True, help="Translate (OpenAI)"):
                            try:
                                import html
                                # Декодируем исходный текст от HTML-сущностей
                                source_clean = html.unescape(seg['source_text'])
                                m = find_tm_suggestion(source_clean)
                                if m and m['score'] == 100:
                                    trans_result = m['target_text']
                                    update_segment(seg['id'], target_text=trans_result, status='translated',
                                                 tm_match_score=m['score'], tm_suggestion=m['target_text'])
                                else:
                                    tm = '' if not m else m['target_text']
                                    trans_result = translate_segment(source_clean, glossary_prompt(pid), translation_model, tm)
                                    if m:
                                        update_segment(seg['id'], target_text=trans_result, status='translated',
                                                     tm_match_score=m['score'], tm_suggestion=m['target_text'])
                                    else:
                                        update_segment(seg['id'], target_text=trans_result, status='translated')

                                # Update cache BEFORE rerun
                                st.session_state.target_cache[seg['id']] = trans_result
                                st.session_state.selected_segment_id = seg['id']
                                st.success(f"✅ Translated: {trans_result[:50]}...")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error: {str(e)}")

                    # Trans button (Google)
                    with row_cols[7]:
                        if st.button("🌐", key=f"trans_google_{seg['id']}", use_container_width=True, help="Translate (Google)"):
                            if not GOOGLE_TRANSLATE_AVAILABLE:
                                st.error("❌ Google Translate недоступен")
                            else:
                                try:
                                    import html
                                    # Декодируем исходный текст от HTML-сущностей
                                    source_clean = html.unescape(seg['source_text'])
                                    # Check TM first
                                    m = find_tm_suggestion(source_clean)
                                    trans_result = translate_google(source_clean, source_lang='ru', target_lang='en')
                                    if trans_result:
                                        if m:
                                            update_segment(seg['id'], target_text=trans_result, status='translated',
                                                         tm_match_score=m['score'], tm_suggestion=m['target_text'])
                                        else:
                                            update_segment(seg['id'], target_text=trans_result, status='translated')
                                        st.session_state.target_cache[seg['id']] = trans_result
                                        st.session_state.selected_segment_id = seg['id']
                                        st.success(f"✅ Google: {trans_result[:50]}...")
                                        st.rerun()
                                    else:
                                        st.error("❌ Пустой результат от Google")
                                except Exception as e:
                                    st.error(f"❌ Google ошибка: {str(e)}")

                    # QA button
                    with row_cols[8]:
                        if st.button("✓", key=f"qa_{seg['id']}", use_container_width=True, help="QA Check"):
                            target = seg.get('target_text') or ''
                            if target:
                                try:
                                    rep = qa_segment(seg['source_text'], target, glossary_prompt(pid), review_model)
                                    ns = 'qa_done' if rep.get('verdict') == 'pass' else 'needs_review'
                                    overall_score = rep.get('overall_score', 0)
                                    update_segment(seg['id'], qa_report=json.dumps(rep, ensure_ascii=False, indent=2), qa_score=overall_score, status=ns)
                                    st.session_state.selected_segment_id = seg['id']

                                    if overall_score:
                                        st.success(f"✓ {overall_score:.0f}/100")
                                    else:
                                        st.success("✓ QA Done")
                                except Exception as e:
                                    st.error(f"❌ QA Error: {str(e)}")
                            else:
                                st.warning("⚠️ No text")
                            st.rerun()

                    # Back-check button
                    with row_cols[9]:
                        if st.button("⤴️", key=f"back_{seg['id']}", use_container_width=True, help="Back-check"):
                            target = seg.get('target_text') or ''
                            if target:
                                try:
                                    rep = back_translate_check(seg['source_text'], target, project.get('source_language', 'Russian'), review_model)
                                    ns = 'back_checked' if rep.get('verdict') == 'pass' else 'needs_review'
                                    semantic_score = rep.get('semantic_score', 0)
                                    update_segment(seg['id'], back_translation=rep.get('back_translation'), back_translation_report=json.dumps(rep, ensure_ascii=False, indent=2), back_translation_score=semantic_score, status=ns)
                                    st.session_state.selected_segment_id = seg['id']

                                    if semantic_score:
                                        st.success(f"✓ {semantic_score:.0f}/100")
                                    else:
                                        st.success("✓ Back-check Done")
                                except Exception as e:
                                    st.error(f"❌ Back-check Error: {str(e)}")
                            else:
                                st.warning("⚠️ No text")
                            st.rerun()

                    # Status
                    with row_cols[10]:
                        st.caption(seg.get('status', 'new'))

                    # QA score (compact like Memsource)
                    with row_cols[11]:
                        qa_score_val = seg.get('qa_score', 0)
                        if qa_score_val:
                            # Determine color based on score
                            if qa_score_val >= 90:
                                st.markdown(f"<div style='background: #28a745; color: white; text-align: center; padding: 1px 4px; border-radius: 2px; font-weight: bold; font-size: 11px;'>{qa_score_val:.0f}</div>", unsafe_allow_html=True)
                            elif qa_score_val >= 75:
                                st.markdown(f"<div style='background: #ffc107; color: #000; text-align: center; padding: 1px 4px; border-radius: 2px; font-weight: bold; font-size: 11px;'>{qa_score_val:.0f}</div>", unsafe_allow_html=True)
                            else:
                                st.markdown(f"<div style='background: #dc3545; color: white; text-align: center; padding: 1px 4px; border-radius: 2px; font-weight: bold; font-size: 11px;'>{qa_score_val:.0f}</div>", unsafe_allow_html=True)
                        else:
                            st.caption("—")

                    # Status toggle button (✓ = confirmed, ❌ = needs review)
                    with row_cols[12]:
                        current_status = seg.get('status', 'new')
                        is_confirmed = current_status == 'confirmed'
                        button_label = "✓" if is_confirmed else "❌"
                        button_style = "success" if is_confirmed else "secondary"

                        if st.button(button_label, key=f"toggle_{seg['id']}", use_container_width=True,
                                   help="Toggle confirmation status"):
                            if is_confirmed:
                                # Switch from confirmed to needs_review
                                update_segment(seg['id'], status='needs_review')
                                st.session_state.selected_segment_id = seg['id']
                                st.info("❌ Marked for review")
                            else:
                                # Switch to confirmed
                                target = seg.get('target_text') or ''
                                if target:
                                    confirm_segment(seg['id'])
                                    st.session_state.selected_segment_id = seg['id']
                                    st.success("✓ Confirmed!")
                                else:
                                    st.warning("⚠️ No text to confirm")
                            st.rerun()

                    # Placeholder for column 13 (removed - only 13 columns needed)
                    with row_cols[13]:
                        st.empty()

            # End of table in left column

            # ═══════════════════════════════════════════════════════
            # RIGHT COLUMN: SUGGESTIONS
            # ═══════════════════════════════════════════════════════
            with right_col:
                if not st.session_state.selected_segment_id:
                    st.markdown("### 💡 Suggestions")
                    st.markdown("Select a segment from the table to view suggestions.")
                else:
                    seg = get_segment(st.session_state.selected_segment_id)
                    if seg and seg['project_id'] == pid:
                        st.markdown(f"### 💡 Segment #{seg['id']}")
                        st.markdown("---")
                        # Source text
                        with st.expander("📝 Source", expanded=True):
                            st.caption(seg['source_text'])

                        # Create tabs for suggestions
                        tab_tm, tab_qa, tab_back = st.tabs(["🔍 TM", "✓ QA", "⤴️ Back"])

                    # TM Match Tab
                    with tab_tm:
                        if seg.get('tm_suggestion'):
                            tm_score = seg.get('tm_match_score', 0)
                            st.success(f"**Match: {tm_score:.0f}%**")
                            st.code(seg['tm_suggestion'], language="text")
                        else:
                            st.info("No TM match found. Click 🔍 to search.")

                    # QA Report Tab
                    with tab_qa:
                        status = seg.get('status', 'new')
                        st.caption(f"Status: **{status}**")

                        if seg.get('qa_report'):
                            try:
                                qa_rep = json.loads(seg['qa_report'])

                                # Compact metrics row
                                col_qa1, col_qa2, col_qa3, col_qa4, col_qa5 = st.columns(5)
                                with col_qa1:
                                    st.metric("Accuracy", f"{qa_rep.get('accuracy_score', 0):.0f}", delta=None, label_visibility="collapsed")
                                with col_qa2:
                                    st.metric("Terminology", f"{qa_rep.get('terminology_score', 0):.0f}", delta=None, label_visibility="collapsed")
                                with col_qa3:
                                    st.metric("Completeness", f"{qa_rep.get('completeness_score', 0):.0f}", delta=None, label_visibility="collapsed")
                                with col_qa4:
                                    st.metric("Numbers", f"{qa_rep.get('numerical_score', 0):.0f}", delta=None, label_visibility="collapsed")
                                with col_qa5:
                                    overall = qa_rep.get('overall_score', 0)
                                    if overall >= 90:
                                        st.markdown(f"""
                                        <div style="background-color: #28a745; padding: 8px; border-radius: 5px; text-align: center;">
                                            <span style="color: white; font-weight: bold; font-size: 14px;">{overall:.0f}</span>
                                        </div>
                                        """, unsafe_allow_html=True)
                                    elif overall >= 75:
                                        st.warning(f"**{overall:.0f}**")
                                    else:
                                        st.error(f"**{overall:.0f}**")

                                st.markdown("---")

                                # Issues
                                if qa_rep.get('critical_issues'):
                                    st.error(f"🔴 **Critical Issues:**\n\n" + "\n\n".join(qa_rep['critical_issues']))
                                if qa_rep.get('minor_issues'):
                                    st.warning(f"🟡 **Minor Issues:**\n\n" + "\n\n".join(qa_rep['minor_issues']))

                                # If no issues
                                if not qa_rep.get('critical_issues') and not qa_rep.get('minor_issues'):
                                    st.success("✅ No issues found!")
                            except json.JSONDecodeError:
                                st.error("❌ Error parsing QA report")
                        else:
                            if status == 'needs_review':
                                st.warning("⚠️ **NEEDS REVIEW**\n\nНажмите ✓ QA для просмотра деталей проблем или пересчитайте проверку.")
                            elif status == 'failed':
                                st.error("❌ **FAILED QA**\n\nПересчитайте проверку для получения деталей.")
                            elif status == 'qa_done':
                                st.success("✅ **QA Passed** — No issues found!")
                            else:
                                st.info("📋 No QA report yet. Click ✓ to run QA check.")

                    # Back-check Report Tab
                    with tab_back:
                        if seg.get('back_translation_report'):
                            bt_rep = json.loads(seg['back_translation_report'])

                            col_bt1, col_bt2 = st.columns(2)
                            with col_bt1:
                                semantic = bt_rep.get('semantic_score', 0)
                                if semantic >= 90:
                                    st.success(f"**Semantic Score: {semantic:.0f}**")
                                elif semantic >= 75:
                                    st.warning(f"**Semantic Score: {semantic:.0f}**")
                                else:
                                    st.error(f"**Semantic Score: {semantic:.0f}**")

                            with col_bt2:
                                verdict = bt_rep.get('verdict', 'unknown')
                                if verdict == 'pass':
                                    st.success("✅ **PASS**")
                                elif verdict == 'warning':
                                    st.warning("⚠️ **WARNING**")
                                else:
                                    st.error("❌ **FAILED**")

                            if bt_rep.get('back_translation'):
                                st.info(f"**Back-translation:**\n\n{bt_rep['back_translation']}")

                            if bt_rep.get('meaning_drift'):
                                st.error(f"🔴 **Meaning Drift:**\n\n{bt_rep['meaning_drift']}")
                            if bt_rep.get('omissions'):
                                st.warning(f"🟡 **Omissions:**\n\n{bt_rep['omissions']}")
                            if bt_rep.get('additions'):
                                st.warning(f"🟡 **Additions:**\n\n{bt_rep['additions']}")

                            if not bt_rep.get('meaning_drift') and not bt_rep.get('omissions') and not bt_rep.get('additions'):
                                st.success("✅ No issues found!")
                        else:
                            st.info("Click ⤴️ to run back-check.")

# ── TAB 2: Glossary ───────────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("📚 Glossary")
    projects = get_projects()
    if projects:
        labels = {f"#{p['id']} — {p['title']}": p['id'] for p in projects}
        pid = labels[st.selectbox("Glossary project", list(labels.keys()))]

        col1, col2, col3 = st.columns(3)
        with col1:
            source_term = st.text_input("Source term (Russian)")
        with col2:
            target_term = st.text_input("Target term (English)")
        with col3:
            category = st.text_input("Category")

        notes = st.text_area("Notes", height=80)

        if st.button("➕ Add glossary term") and source_term and target_term:
            add_glossary_term(pid, source_term, target_term, category, notes)
            st.success("✅ Added")

        # Display glossary
        terms = get_glossary(pid)
        if terms:
            st.subheader("Approved Terms")
            st.dataframe(pd.DataFrame(terms))
            st.subheader("For Prompts (copy/paste):")
            st.code(glossary_prompt(pid))

# ── TAB 3: TM ─────────────────────────────────────────────────────────────────
with tabs[3]:
    st.subheader("🔁 Translation Memory")
    txt = st.text_area("TM data: source | target (one per line)", height=200)
    if st.button("📥 Import TM"):
        rows = []
        for line in txt.splitlines():
            if '|' in line:
                parts = line.split('|', 1)
            elif '\t' in line:
                parts = line.split('\t', 1)
            else:
                continue
            if len(parts) == 2:
                rows.append((parts[0].strip(), parts[1].strip()))
        if rows:
            import_tm_rows(rows)
            st.success(f"✅ Imported {len(rows)} rows")

# ── TAB 4: Export ─────────────────────────────────────────────────────────────
with tabs[4]:
    st.subheader("📤 Export Project")
    projects = get_projects()
    if projects:
        labels = {f"#{p['id']} — {p['title']}": p['id'] for p in projects}
        pid = labels[st.selectbox("Export project", list(labels.keys()))]
        segs = get_segments(pid)

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Segments", len(segs))
        with col2:
            translated = len([s for s in segs if s.get('target_text')])
            st.metric("Translated", translated)

        if st.button("📥 Generate DOCX"):
            path = export_translated_docx(pid)
            st.success(f"✅ Exported: {path}")
            with open(path, 'rb') as f:
                st.download_button('⬇️ Download DOCX', f, file_name=Path(path).name)

# ── TAB 5: Backlog ────────────────────────────────────────────────────────────
with tabs[5]:
    st.subheader("📋 Backlog")
    backlog_path = Path("BACKLOG.md")
    if backlog_path.exists():
        st.markdown(backlog_path.read_text(encoding='utf-8'))
    else:
        st.info("BACKLOG.md not found")

# ── TAB 6: Stats ──────────────────────────────────────────────────────────────
with tabs[6]:
    st.subheader("📊 Statistics")
    projects = get_projects()
    if projects:
        stats = []
        for p in projects:
            segs = get_segments(p['id'])
            confirmed = len([s for s in segs if s.get('status') == 'confirmed'])
            translated = len([s for s in segs if s.get('target_text')])
            stats.append({
                'Project': f"{p['title']}",
                'Segments': len(segs),
                'Translated': translated,
                'Confirmed': confirmed,
                'Progress': f"{int(confirmed/max(len(segs),1)*100)}%",
            })
        st.dataframe(pd.DataFrame(stats))

# Footer
st.markdown("---")
st.caption(
    f"Medical CAT Translator v{APP_VERSION} | "
    f"Powered by OpenAI (translation) + Anthropic (glossary) | "
    f"DOCX CAT workflow with QA, back-check, safety review"
)
