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

# Preflight Analysis (v5.5-final)
try:
    from preflight_analyzer import run_preflight_analysis
    PREFLIGHT_AVAILABLE = True
except ImportError:
    PREFLIGHT_AVAILABLE = False

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
    "🔍 Preflight",
    "✔️ QA Dashboard",
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

        # Batch actions panel
        st.divider()
        st.subheader("⚙️ Batch Actions")
        batch_col1, batch_col2, batch_col3 = st.columns(3)

        with batch_col1:
            if st.button("🌐 Preview Google Batch", key="preview_google_batch", help="Preview segments eligible for Google batch translation"):
                try:
                    from google_batch import translate_google_batch
                    preview = translate_google_batch(pid, preview_only=True)

                    st.info(f"""
                    **GOOGLE_SAFE Batch Preview**

                    - **Eligible segments:** {preview['eligible_count']}
                    - **Batches needed:** {preview['batch_count']} (batch size: {preview['batch_size']})
                    - **Estimated Google cost:** ${preview['estimated_cost_usd']:.2f}
                    - **Estimated GPT savings:** ${preview['estimated_gpt_savings_usd']:.2f}

                    ⚠️ **Warning:** All translations will be saved as `google_draft` (not confirmed).
                    Run local QA after translation. No auto-confirm by default.
                    """)

                    if preview['examples_included']:
                        with st.expander("✅ Examples to be translated"):
                            for ex in preview['examples_included']:
                                st.write(f"**Segment #{ex['id']}** (risk: {ex['risk_level']}, confidence: {ex['confidence']})")
                                st.code(ex['source_text'], language='text')

                    if preview['examples_excluded']:
                        with st.expander("❌ Examples excluded (and why)"):
                            for ex in preview['examples_excluded']:
                                st.write(f"**Segment #{ex['id']}:** {ex['reason']}")

                except ImportError:
                    st.error("Google batch translator not available")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

        with batch_col2:
            if st.button("▶️ Run Google Batch", key="run_google_batch", help="Translate all eligible GOOGLE_SAFE segments"):
                try:
                    from google_batch import translate_google_batch

                    with st.spinner("⏳ Translating GOOGLE_SAFE segments with Google Cloud Translation..."):
                        results = translate_google_batch(pid, batch_size=50, preview_only=False)

                    st.success(f"""
                    ✅ **Translation Complete**
                    - Translated: {results['translated_count']} segments
                    - Failed: {results['failed_count']} segments
                    - Needs QA review: {results['qa_failed_count']} segments
                    - Total cost: ${results['total_cost_usd']:.2f}
                    """)

                    # Show summary of results
                    passed_qa = [r for r in results['results'] if r.get('status') == 'google_draft']
                    failed_qa = [r for r in results['results'] if r.get('status') == 'google_needs_review']
                    errors = [r for r in results['results'] if r.get('status') in ['error', 'failed']]

                    if failed_qa:
                        with st.expander("⚠️ Segments needing QA review"):
                            for r in failed_qa[:10]:
                                alerts_str = " | ".join([f"{a['type']}: {a['message']}" for a in r.get('qa_alerts', [])])
                                st.write(f"Segment #{r['segment_id']}: {alerts_str}")

                    if errors:
                        with st.expander("❌ Errors"):
                            for r in errors[:10]:
                                st.write(f"Segment #{r['segment_id']}: {r.get('error', 'Unknown error')}")

                except ImportError:
                    st.error("Google batch translator not available")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

        with batch_col3:
            batch_size = st.number_input("Batch size", min_value=10, max_value=500, value=50, step=10, label_visibility="collapsed", key="batch_size_input")

        # GPT batch actions
        st.subheader("🤖 GPT Batch Translation")
        gpt_col1, gpt_col2, gpt_col3 = st.columns(3)

        with gpt_col3:
            gpt_batch_model = st.selectbox(
                "GPT model",
                options=AVAILABLE_MODELS,
                index=0,
                label_visibility="collapsed",
                key="gpt_batch_model"
            )

        with gpt_col1:
            if st.button("📊 Preview GPT Batch", key="preview_gpt_batch", help="Preview segments eligible for GPT batch translation"):
                try:
                    from gpt_batch import translate_gpt_batch

                    # Preview GPT_REQUIRED segments
                    preview_gpt = translate_gpt_batch(pid, route='GPT_REQUIRED', model=gpt_batch_model, batch_size=batch_size, preview_only=True)

                    st.info(f"""
                    **GPT Batch Preview (GPT_REQUIRED)**

                    - **Eligible segments:** {preview_gpt['eligible_count']}
                    - **Batches needed:** {preview_gpt['batch_count']} (batch size: {preview_gpt['batch_size']})
                    - **Estimated tokens:** {preview_gpt['estimated_tokens']:,}
                    - **Estimated cost:** ${preview_gpt['estimated_usd']:.2f}
                    - **QA depth:** {preview_gpt['expected_qa_depth']}

                    ⚠️ **Warnings:**
                    """)

                    for warning in preview_gpt.get('warnings', []):
                        st.write(f"• {warning}")

                    if preview_gpt['examples_included']:
                        with st.expander("✅ Examples to be translated"):
                            for ex in preview_gpt['examples_included']:
                                st.write(f"**Segment #{ex['id']}** (risk: {ex['risk']}, intent: {ex['intent']})")
                                st.code(ex['source_text'][:150], language='text')

                except ImportError:
                    st.error("GPT batch translator not available")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

        with gpt_col2:
            if st.button("▶️ Run GPT Batch", key="run_gpt_batch", help="Translate all eligible GPT_REQUIRED segments"):
                try:
                    from gpt_batch import translate_gpt_batch

                    with st.spinner("⏳ Translating GPT_REQUIRED segments with OpenAI..."):
                        results = translate_gpt_batch(pid, route='GPT_REQUIRED', model=gpt_batch_model, batch_size=batch_size, preview_only=False)

                    st.success(f"""
                    ✅ **Translation Complete**
                    - Translated: {results['translated_count']} segments
                    - Failed: {results['failed_count']} segments
                    - Total tokens: {results['total_actual_tokens']:,}
                    - Total cost: ${results['total_actual_usd']:.2f}
                    """)

                    # Show summary of results
                    successful = [r for r in results['results'] if r.get('status') == 'translated']
                    failed = [r for r in results['results'] if r.get('status') == 'error']

                    if failed:
                        with st.expander("❌ Failed segments"):
                            for r in failed[:10]:
                                st.write(f"Segment #{r['segment_id']}: {r.get('error', 'Unknown error')}")

                except ImportError:
                    st.error("GPT batch translator not available")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

        # Auto-approval section
        st.subheader("✅ Auto-Approval (Low-Risk Only)")
        auto_col1, auto_col2 = st.columns(2)

        with auto_col1:
            if st.button("👁️ Preview Auto-Approval", key="preview_auto_approval", help="Preview which segments would be auto-approved"):
                try:
                    from auto_approval_engine import get_auto_approval_preview

                    preview = get_auto_approval_preview(pid)

                    st.info(f"""
                    **Auto-Approval Preview**

                    - **Candidates:** {preview['candidates_count']} segments eligible
                    - **Excluded:** {preview['excluded_count']} segments not eligible

                    **Exclusion Summary:**
                    """)

                    for reason, count in sorted(preview['exclusion_reasons'].items(), key=lambda x: -x[1])[:10]:
                        st.write(f"• {reason}: {count} segments")

                    if preview['example_candidates']:
                        with st.expander("✅ Examples to be auto-approved"):
                            for ex in preview['example_candidates']:
                                st.write(f"**#{ex['id']}** ({ex['route']}, {ex['risk']})")
                                st.code(ex['source'][:80], language='text')

                    if preview['example_excluded']:
                        with st.expander("❌ Examples excluded (and why)"):
                            for ex in preview['example_excluded']:
                                st.write(f"**#{ex['id']}:** {ex['reason']}")
                                st.caption(ex['source'][:80])

                except ImportError:
                    st.error("Auto-approval engine not available")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

        with auto_col2:
            if st.button("✅ Run Auto-Approval", key="run_auto_approval", help="Auto-approve LOW-risk segments meeting all criteria"):
                try:
                    from auto_approval_engine import run_auto_approval

                    with st.spinner("⏳ Auto-approving eligible segments..."):
                        results = run_auto_approval(pid, progress_callback=lambda msg: None)

                    st.success(f"""
                    ✅ **Auto-Approval Complete**
                    - Approved: {results['approved_count']} segments
                    - Excluded: {results['excluded_count']} segments
                    - Errors: {results['failed_count']} segments
                    """)

                    if results['approved_count'] > 0:
                        st.info(f"Added {results['approved_count']} translations to master TM")

                    if results['failed_count'] > 0:
                        with st.expander("⚠️ Errors"):
                            for err in results['errors'][:5]:
                                st.write(f"Segment #{err['segment_id']}: {err['error']}")

                except ImportError:
                    st.error("Auto-approval engine not available")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

        st.divider()

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

                # Table header (21 columns: 14 original + 7 new Preflight)
                header_cols = st.columns([0.8, 0.8, 3.5, 4, 1, 0.8, 0.8, 0.8, 0.8, 0.8, 1.2, 1.0, 0.8, 0.8, 0.8, 0.8, 0.6, 0.6, 0.8, 0.6, 0.6], gap="small")
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
                # Preflight columns (NEW)
                with header_cols[11]:
                    st.markdown("**Route**")
                with header_cols[12]:
                    st.markdown("**Risk**")
                with header_cols[13]:
                    st.markdown("**Prvdr**")
                with header_cols[14]:
                    st.markdown("**Est.$**")
                with header_cols[15]:
                    st.markdown("**Pf**")
                with header_cols[16]:
                    st.markdown("**Dupes**")
                with header_cols[17]:
                    st.markdown("**TM%**")
                with header_cols[18]:
                    st.markdown("**QA**")
                with header_cols[19]:
                    st.markdown("**Status**")
                with header_cols[20]:
                    st.markdown("")  # Empty column

                st.markdown("---")

                # Table rows - interactive
                for seg in page_segs:
                    row_cols = st.columns([0.8, 0.8, 3.5, 4, 1, 0.8, 0.8, 0.8, 0.8, 0.8, 1.2, 1.0, 0.8, 0.8, 0.8, 0.8, 0.6, 0.6, 0.8, 0.6, 0.6], gap="small")

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

                    # ───────────────────────────────────────────────
                    # PREFLIGHT COLUMNS (NEW) — 7 columns
                    # ───────────────────────────────────────────────

                    # Column 11: Route (Badge)
                    with row_cols[11]:
                        route = seg.get('route') or '─'
                        if route != '─':
                            route_colors = {
                                'EXACT_TM': ('🟢', '#90EE90'),
                                'DUPLICATE_REPRESENTATIVE': ('🔵', '#87CEEB'),
                                'DUPLICATE_PROPAGATION_PENDING': ('🟣', '#DDA0DD'),
                                'GOOGLE_SAFE': ('🟡', '#FFFF99'),
                                'GPT_REQUIRED': ('⚪', '#EEEEEE'),
                                'GPT_WITH_GLOSSARY_REQUIRED': ('🟠', '#FFB6B6'),
                                'HUMAN_REVIEW_REQUIRED': ('🔴', '#FF6B6B'),
                            }
                            emoji, color = route_colors.get(route, ('─', '#CCCCCC'))
                            # Truncate long route names
                            route_short = route[:4] if route and len(route) > 4 else route
                            st.markdown(f"<div style='text-align:center; background-color:{color}; padding:2px 4px; border-radius:3px; font-weight:bold; font-size:10px;'>{emoji}</div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div style='text-align:center'>─</div>", unsafe_allow_html=True)

                    # Column 12: Risk (Badge)
                    with row_cols[12]:
                        risk_level = seg.get('risk_level') or '─'
                        if risk_level != '─':
                            risk_colors = {
                                'CRITICAL': ('🔴', '#FF4444'),
                                'HIGH': ('🟠', '#FF9944'),
                                'MEDIUM': ('🟡', '#FFCC44'),
                                'LOW': ('🟢', '#44CC44'),
                            }
                            emoji, color = risk_colors.get(risk_level, ('─', '#CCCCCC'))
                            st.markdown(f"<div style='text-align:center; background-color:{color}; color:white; padding:2px 4px; border-radius:3px; font-weight:bold; font-size:10px;'>{emoji}</div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div style='text-align:center'>─</div>", unsafe_allow_html=True)

                    # Column 13: Provider hint (based on route)
                    with row_cols[13]:
                        route = seg.get('route') or '─'
                        provider_map = {
                            'EXACT_TM': 'TM',
                            'DUPLICATE_REPRESENTATIVE': 'GPT',
                            'DUPLICATE_PROPAGATION_PENDING': 'Cpy',
                            'GOOGLE_SAFE': 'Ggl',
                            'GPT_REQUIRED': 'GPT',
                            'GPT_WITH_GLOSSARY_REQUIRED': 'G+',
                            'HUMAN_REVIEW_REQUIRED': 'Hmn',
                        }
                        provider = provider_map.get(route, '─')
                        st.markdown(f"<div style='text-align:center; font-size:10px;'>{provider}</div>", unsafe_allow_html=True)

                    # Column 14: Est. $ (Estimated cost)
                    with row_cols[14]:
                        est_cost = seg.get('estimated_total_usd')
                        if est_cost is not None and est_cost > 0:
                            st.markdown(f"<div style='text-align:right; font-size:10px;'>${est_cost:.2f}</div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div style='text-align:center'>─</div>", unsafe_allow_html=True)

                    # Column 15: Preflight status
                    with row_cols[15]:
                        pf_status = seg.get('preflight_status') or '─'
                        status_emoji = {'done': '✅', 'analyzing': '⏳', 'failed': '❌', 'not_analyzed': '⏹'}
                        st.markdown(f"<div style='text-align:center; font-size:11px;'>{status_emoji.get(pf_status, '─')}</div>", unsafe_allow_html=True)

                    # Column 16: Duplicate count
                    with row_cols[16]:
                        dup_count = seg.get('duplicate_count', 0)
                        if dup_count and dup_count > 0:
                            st.markdown(f"<div style='text-align:center; font-weight:bold; font-size:11px;'>{dup_count}</div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div style='text-align:center'>─</div>", unsafe_allow_html=True)

                    # Column 17: TM% (Exact TM >= 99%)
                    with row_cols[17]:
                        tm_score = seg.get('tm_match_score', 0)
                        if tm_score and tm_score >= 99:
                            st.markdown(f"<div style='text-align:right; color:green; font-weight:bold; font-size:11px;'>{tm_score:.0f}%</div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div style='text-align:center'>─</div>", unsafe_allow_html=True)

                    # QA score (compact like Memsource)
                    with row_cols[18]:
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
                    with row_cols[19]:
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

                    # Placeholder for column 20 (empty)
                    with row_cols[20]:
                        st.empty()

            # End of table in left column

            # ═══════════════════════════════════════════════════════
            # RIGHT COLUMN: SUGGESTIONS + PREFLIGHT
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

                        # ═══════════════════════════════════════════════
                        # PREFLIGHT INFORMATION SECTION (NEW)
                        # ═══════════════════════════════════════════════
                        st.divider()
                        st.subheader("📍 Preflight Information")

                        # 1. Route
                        route = seg.get('route') or '─'
                        if route != '─':
                            route_colors_map = {
                                'EXACT_TM': ('🟢', '#90EE90'),
                                'DUPLICATE_REPRESENTATIVE': ('🔵', '#87CEEB'),
                                'DUPLICATE_PROPAGATION_PENDING': ('🟣', '#DDA0DD'),
                                'GOOGLE_SAFE': ('🟡', '#FFFF99'),
                                'GPT_REQUIRED': ('⚪', '#EEEEEE'),
                                'GPT_WITH_GLOSSARY_REQUIRED': ('🟠', '#FFB6B6'),
                                'HUMAN_REVIEW_REQUIRED': ('🔴', '#FF6B6B'),
                            }
                            emoji, color = route_colors_map.get(route, ('─', '#CCCCCC'))
                            st.markdown(f"**📌 Route:** <span style='background-color:{color}; padding:3px 8px; border-radius:4px; font-weight:bold; color:white' style='color:black'>{emoji} {route}</span>", unsafe_allow_html=True)
                        else:
                            st.markdown("**📌 Route:** ─ *Not analyzed*")

                        # 2. Risk Level
                        risk_level = seg.get('risk_level') or '─'
                        if risk_level != '─':
                            risk_colors = {
                                'CRITICAL': ('🔴', '#FF4444'),
                                'HIGH': ('🟠', '#FF9944'),
                                'MEDIUM': ('🟡', '#FFCC44'),
                                'LOW': ('🟢', '#44CC44'),
                            }
                            emoji, color = risk_colors.get(risk_level, ('─', '#CCCCCC'))
                            st.markdown(f"**⚠️ Risk:** <span style='background-color:{color}; padding:3px 8px; border-radius:4px; font-weight:bold; color:white'>{emoji} {risk_level}</span>", unsafe_allow_html=True)

                            # Risk reasons
                            risk_reasons = seg.get('risk_reasons', '[]')
                            if isinstance(risk_reasons, str):
                                import json
                                try:
                                    risk_reasons = json.loads(risk_reasons)
                                except:
                                    risk_reasons = []
                            if risk_reasons:
                                st.caption("Reasons: " + ", ".join(str(r) for r in risk_reasons))
                        else:
                            st.markdown("**⚠️ Risk:** ─ *Not analyzed*")

                        # 3. Intent & Features
                        intent = seg.get('segment_intent') or '─'
                        st.markdown(f"**📋 Intent:** {intent if intent != '─' else '─'}")

                        detected_features = seg.get('detected_features', '{}')
                        if isinstance(detected_features, str):
                            import json
                            try:
                                detected_features = json.loads(detected_features)
                            except:
                                detected_features = {}
                        if detected_features:
                            features_list = [k for k, v in detected_features.items() if v]
                            st.markdown(f"**🔍 Features:** {', '.join(features_list) if features_list else '─'}")
                        else:
                            st.markdown("**🔍 Features:** ─")

                        # 4. QA & Approval Policies
                        qa_policy = seg.get('qa_policy', '─')
                        approval_policy = seg.get('approval_policy', '─')
                        st.markdown(f"**✓ QA Policy:** {qa_policy if qa_policy else '─'}")
                        st.markdown(f"**✅ Approval:** {approval_policy if approval_policy else '─'}")

                        # 4b. Semantic Analysis Scores (NEW Phase 3)
                        def get_score_color(score):
                            """Return color based on score range."""
                            if score is None:
                                return '#CCCCCC', '─'
                            if score >= 0.85:
                                return '#90EE90', '🟢'  # Green
                            elif score >= 0.5:
                                return '#FFFF99', '🟡'  # Yellow
                            else:
                                return '#FF6B6B', '🔴'  # Red

                        # Collect semantic scores
                        semantic_density = seg.get('semantic_density_score')
                        medicality = seg.get('medicality_score')
                        entity_complexity = seg.get('entity_complexity_score')
                        reversibility_risk = seg.get('reversibility_risk_score')
                        clinical_criticality = seg.get('clinical_criticality_score')
                        google_safe_confidence = seg.get('google_safe_confidence')

                        # Show semantic scores if available
                        if any([semantic_density, medicality, entity_complexity, reversibility_risk, clinical_criticality, google_safe_confidence]):
                            with st.expander("🧠 Semantic Analysis Scores", expanded=False):
                                st.caption("Lightweight semantic analysis (0.0-1.0 scale)")

                                # Row 1: Density & Medicality
                                col_sem1, col_sem2 = st.columns(2)
                                with col_sem1:
                                    color, emoji = get_score_color(semantic_density)
                                    if semantic_density is not None:
                                        st.markdown(f"**{emoji} Semantic Density:** {semantic_density:.2f}", unsafe_allow_html=False)
                                        st.markdown(f"<div style='background-color:{color}; height:8px; border-radius:4px;'></div>", unsafe_allow_html=True)
                                    else:
                                        st.markdown("**🔲 Semantic Density:** ─")

                                with col_sem2:
                                    color, emoji = get_score_color(medicality)
                                    if medicality is not None:
                                        st.markdown(f"**{emoji} Medicality:** {medicality:.2f}", unsafe_allow_html=False)
                                        st.markdown(f"<div style='background-color:{color}; height:8px; border-radius:4px;'></div>", unsafe_allow_html=True)
                                    else:
                                        st.markdown("**🔲 Medicality:** ─")

                                # Row 2: Complexity & Reversibility
                                col_sem3, col_sem4 = st.columns(2)
                                with col_sem3:
                                    color, emoji = get_score_color(entity_complexity)
                                    if entity_complexity is not None:
                                        st.markdown(f"**{emoji} Entity Complexity:** {entity_complexity:.2f}", unsafe_allow_html=False)
                                        st.markdown(f"<div style='background-color:{color}; height:8px; border-radius:4px;'></div>", unsafe_allow_html=True)
                                    else:
                                        st.markdown("**🔲 Entity Complexity:** ─")

                                with col_sem4:
                                    # Reversibility risk is inverted (high score = high risk = red)
                                    if reversibility_risk is not None:
                                        # Invert for display: high risk = red, low risk = green
                                        inverted_reversibility = 1.0 - reversibility_risk
                                        color, emoji = get_score_color(inverted_reversibility)
                                        st.markdown(f"**{emoji} Reversibility (safe):** {inverted_reversibility:.2f}", unsafe_allow_html=False)
                                        st.markdown(f"<div style='background-color:{color}; height:8px; border-radius:4px;'></div>", unsafe_allow_html=True)
                                    else:
                                        st.markdown("**🔲 Reversibility (safe):** ─")

                                # Row 3: Criticality & Google Safety
                                col_sem5, col_sem6 = st.columns(2)
                                with col_sem5:
                                    # Clinical criticality is risk (high score = high risk = red)
                                    if clinical_criticality is not None:
                                        inverted_criticality = 1.0 - clinical_criticality
                                        color, emoji = get_score_color(inverted_criticality)
                                        st.markdown(f"**{emoji} Safety (non-critical):** {inverted_criticality:.2f}", unsafe_allow_html=False)
                                        st.markdown(f"<div style='background-color:{color}; height:8px; border-radius:4px;'></div>", unsafe_allow_html=True)
                                    else:
                                        st.markdown("**🔲 Safety (non-critical):** ─")

                                with col_sem6:
                                    # Google safe confidence is positive (high score = good, safe for Google)
                                    color, emoji = get_score_color(google_safe_confidence)
                                    if google_safe_confidence is not None:
                                        st.markdown(f"**{emoji} Google Safe (confidence):** {google_safe_confidence:.2f}", unsafe_allow_html=False)
                                        st.markdown(f"<div style='background-color:{color}; height:8px; border-radius:4px;'></div>", unsafe_allow_html=True)
                                        # Show explanation
                                        if google_safe_confidence >= 0.98:
                                            st.success("✅ Safe to use Google Translate API")
                                        elif google_safe_confidence >= 0.85:
                                            st.warning("⚠️ Uncertain — will route to GPT for safety")
                                        else:
                                            st.error("❌ Blocked from Google Translate — requires GPT")
                                    else:
                                        st.markdown("**🔲 Google Safe (confidence):** ─")

                        # 5. Cost Breakdown (Expander)
                        with st.expander("💰 Cost Breakdown", expanded=False):
                            col1, col2 = st.columns(2)
                            with col1:
                                trans_tokens = seg.get('estimated_translation_tokens', '─')
                                qa_tokens = seg.get('estimated_qa_tokens', '─')
                                st.metric("Translation", f"{trans_tokens} tk" if trans_tokens != '─' else '─', label_visibility="collapsed")
                                st.metric("QA", f"{qa_tokens} tk" if qa_tokens != '─' else '─', label_visibility="collapsed")
                            with col2:
                                back_tokens = seg.get('estimated_backcheck_tokens', '─')
                                safety_tokens = seg.get('estimated_safety_tokens', '─')
                                st.metric("Back-check", f"{back_tokens} tk" if back_tokens != '─' else '─', label_visibility="collapsed")
                                st.metric("Safety", f"{safety_tokens} tk" if safety_tokens != '─' else '─', label_visibility="collapsed")

                            col1, col2 = st.columns(2)
                            with col1:
                                total_tokens = seg.get('estimated_total_tokens', '─')
                                st.metric("Total Tokens", f"{total_tokens}" if total_tokens != '─' else '─', label_visibility="collapsed")
                            with col2:
                                total_cost = seg.get('estimated_total_usd', 0)
                                st.metric("Est. Cost", f"${total_cost:.2f}" if total_cost else '─', label_visibility="collapsed")

                        # 6. Duplicate Group Info (Enhanced for Zero-Token Optimization)
                        dup_group_id = seg.get('duplicate_group_id')
                        dup_count = seg.get('duplicate_count', 0)
                        dup_rep_id = seg.get('duplicate_representative_id')
                        is_rep = seg.get('duplicate_representative', False)

                        if dup_group_id and dup_count and dup_count > 0:
                            if is_rep:
                                st.info(f"""
                                👑 **Duplicate Representative**
                                - Group: {dup_group_id}
                                - Members in group: {dup_count + 1}
                                - Status: **Representative** (translate this, then propagate to others)
                                - Potential zero-token copies: {dup_count}
                                - Est. savings if confirmed: ${dup_count * 0.008:.2f}
                                """)
                            else:
                                st.info(f"""
                                👥 **Duplicate Member**
                                - Group: {dup_group_id}
                                - Members in group: {dup_count + 1}
                                - Status: **Pending** (copy from representative #{dup_rep_id} after confirmed)
                                - This translation can be auto-filled with zero tokens
                                """)
                        elif seg.get('status') == 'tm_prefilled':
                            st.success("💾 **Exact TM Prefilled** — This segment was auto-filled from Translation Memory.")

                        # 7. Exact TM Opportunity
                        tm_score = seg.get('tm_match_score', 0)
                        if tm_score and tm_score >= 99:
                            st.success(f"💯 **Exact TM Match:** {tm_score:.0f}% match found. This segment can be skipped.")

                        # 8. Google Safe Explanation
                        if seg.get('route') == 'GOOGLE_SAFE':
                            st.info("🌐 **Google Safe:** Low-risk segment suitable for Google Translate API (free tier).")

                        # Advisory notice
                        st.warning("⚠️ **Preflight is advisory.** Segment Editor remains the source of truth for translation and approval.")

                        # Display QA alerts from Google batch translation (if present)
                        qa_alerts = seg.get('qa_alerts')
                        if qa_alerts:
                            try:
                                import json
                                alerts = json.loads(qa_alerts) if isinstance(qa_alerts, str) else qa_alerts
                                if alerts:
                                    st.divider()
                                    st.subheader("🔍 QA Alerts (from Google translation)")
                                    for alert in alerts:
                                        alert_type = alert.get('type', 'unknown')
                                        severity = alert.get('severity', 'info')
                                        message = alert.get('message', '')

                                        if severity == 'critical':
                                            st.error(f"**{alert_type}**: {message}")
                                        elif severity == 'error':
                                            st.error(f"**{alert_type}**: {message}")
                                        elif severity == 'warning':
                                            st.warning(f"**{alert_type}**: {message}")
                                        else:
                                            st.info(f"**{alert_type}**: {message}")
                            except (json.JSONDecodeError, TypeError):
                                pass

                        st.divider()

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

        # ───────────────────────────────────────────────────────────────────────
        # REVIEW QUEUE SECTION
        # ───────────────────────────────────────────────────────────────────────
        st.divider()
        st.subheader("🔍 Review Queue")

        # Review Queue filters and display
        queue_col1, queue_col2, queue_col3, queue_col4 = st.columns(4)

        with queue_col1:
            queue_route_filter = st.selectbox("Route",
                options=['all', 'EXACT_TM', 'GOOGLE_SAFE', 'GPT_REQUIRED', 'GPT_WITH_GLOSSARY_REQUIRED', 'HUMAN_REVIEW_REQUIRED'],
                label_visibility="collapsed",
                key="queue_route")

        with queue_col2:
            queue_risk_filter = st.selectbox("Risk",
                options=['all', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'],
                label_visibility="collapsed",
                key="queue_risk")

        with queue_col3:
            queue_provider_filter = st.selectbox("Provider",
                options=['all', 'openai', 'google', 'tm'],
                label_visibility="collapsed",
                key="queue_provider")

        with queue_col4:
            queue_alert_filter = st.selectbox("Alert Type",
                options=['all', 'qa_warning', 'qa_failed', 'numeric_mismatch', 'consistency_conflict', 'glossary_conflict', 'forbidden_detected'],
                label_visibility="collapsed",
                key="queue_alert")

        # Get review queue
        try:
            from review_queue_engine import get_review_queue, get_segment_review_details, get_review_statistics

            filters = {}
            if queue_route_filter != 'all':
                filters['route'] = queue_route_filter
            if queue_risk_filter != 'all':
                filters['risk'] = queue_risk_filter
            if queue_provider_filter != 'all':
                filters['provider'] = queue_provider_filter
            if queue_alert_filter != 'all':
                filters['alert_type'] = queue_alert_filter

            queue_items = get_review_queue(segs, filters)
            stats = get_review_statistics(segs)

            if queue_items:
                st.info(f"**{len(queue_items)} segments need review** (Total in queue: {stats['total_in_queue']})")

                # Display queue as table
                queue_data = []
                for item in queue_items[:50]:  # Show top 50
                    queue_data.append({
                        'ID': item['id'],
                        'Source': item['source_text'][:40],
                        'Target': item['target_text'][:40] if item['target_text'] else '─',
                        'Route': item['route'],
                        'Risk': item['risk_level'],
                        'Status': item['qa_final_status'],
                        'Alert': item['top_alert'],
                        'Priority': '🔴' if item['priority'] > 80 else '🟠' if item['priority'] > 60 else '🟡',
                    })

                st.dataframe(pd.DataFrame(queue_data), use_container_width=True, height=300)

                # Select segment from queue
                selected_queue_id = st.selectbox(
                    "Select segment to review",
                    options=[item['id'] for item in queue_items],
                    format_func=lambda x: f"#{x} {next((i['source_text'][:30] for i in queue_items if i['id']==x), '...')}",
                    key="queue_selected"
                )

                if selected_queue_id:
                    seg_details = get_segment_review_details(segs, selected_queue_id)

                    st.markdown("---")
                    st.subheader(f"Reviewing Segment #{selected_queue_id}")

                    col_source, col_target = st.columns(2)

                    with col_source:
                        st.write("**Source (Russian)**")
                        st.code(seg_details['source_text'], language='text')

                    with col_target:
                        st.write("**Target (English) — EDITABLE**")
                        target_edit = st.text_area(
                            "Edit translation:",
                            value=seg_details['target_text'],
                            height=100,
                            label_visibility="collapsed",
                            key=f"target_edit_{selected_queue_id}"
                        )

                    # QA Alerts
                    if seg_details['qa_alerts']:
                        with st.expander("⚠️ QA Alerts"):
                            for alert in seg_details['qa_alerts']:
                                st.write(f"**{alert.get('type')}** ({alert.get('severity')}): {alert.get('message')}")

                    # Numerical Issues
                    if seg_details['numerical_issues']:
                        with st.expander("🔢 Numerical Issues"):
                            for issue in seg_details['numerical_issues']:
                                st.write(f"**{issue.get('type')}** ({issue.get('severity')}): {issue.get('message')}")

                    # Consistency Alerts
                    if seg_details['consistency_alerts']:
                        with st.expander("🔄 Consistency Issues"):
                            for conflict in seg_details['consistency_alerts']:
                                st.write(f"{conflict.get('message', 'Consistency conflict detected')}")

                    # Glossary Issues
                    if seg_details['glossary_conflicts']:
                        with st.expander("📖 Glossary Conflicts"):
                            for issue in seg_details['glossary_conflicts']:
                                st.write(f"• {issue.get('issue', 'Glossary mismatch')}")

                    # Forbidden Alerts
                    if seg_details['forbidden_alert']:
                        st.error("🚫 **Forbidden Term Detected** — Edit translation to remove or replace.")

                    # Back-check Report
                    if seg_details['back_translation_report']:
                        report = seg_details['back_translation_report']
                        with st.expander("↩️ Back-Check Report"):
                            st.write(f"**Verdict:** {report.get('verdict', '?')}")
                            if report.get('meaning_drift'):
                                st.warning(f"🟡 **Meaning Drift:** {report['meaning_drift']}")
                            if report.get('omissions'):
                                st.warning(f"🟡 **Omissions:** {report['omissions']}")
                            if report.get('additions'):
                                st.warning(f"🟡 **Additions:** {report['additions']}")

                    # Suggested Action
                    st.info(f"**Suggested Action:** {seg_details['suggested_action']}")

                    # Action Buttons
                    action_col1, action_col2, action_col3, action_col4, action_col5 = st.columns(5)

                    with action_col1:
                        if st.button("💾 Save Edit", key=f"save_edit_{selected_queue_id}"):
                            if target_edit != seg_details['target_text']:
                                update_segment(selected_queue_id, {
                                    'target_text': target_edit,
                                    'status': 'translated',  # Reset status after edit
                                })
                                st.success("✅ Translation updated")
                            else:
                                st.info("No changes made")

                    with action_col2:
                        if st.button("🔍 Local QA", key=f"local_qa_{selected_queue_id}"):
                            try:
                                from local_qa_engine import run_local_qa
                                qa_result = run_local_qa(seg_details['source_text'], target_edit)
                                if qa_result.passed:
                                    st.success("✅ Local QA passed")
                                else:
                                    st.warning("⚠️ Local QA found issues")
                                    for alert in qa_result.alerts:
                                        st.write(f"• {alert['message']}")
                            except Exception as e:
                                st.error(f"Error: {str(e)}")

                    with action_col3:
                        if st.button("✅ Confirm", key=f"confirm_{selected_queue_id}"):
                            if target_edit and target_edit.strip():
                                update_segment(selected_queue_id, {
                                    'target_text': target_edit,
                                    'status': 'confirmed',
                                })
                                st.success("✅ Segment confirmed and added to TM")
                            else:
                                st.error("Cannot confirm empty translation")

                    with action_col4:
                        if st.button("❌ Reject", key=f"reject_{selected_queue_id}"):
                            update_segment(selected_queue_id, {
                                'status': 'needs_review',
                                'target_text': '',
                            })
                            st.warning("⚠️ Translation rejected and cleared")

                    with action_col5:
                        if st.button("👤 Expert Review", key=f"expert_{selected_queue_id}"):
                            update_segment(selected_queue_id, {
                                'status': 'human_review_required',
                            })
                            st.info("🏷️ Marked for expert review")

            else:
                st.success("✅ No segments in review queue!")

        except ImportError:
            st.error("Review queue engine not available")
        except Exception as e:
            st.error(f"Error loading review queue: {str(e)}")

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

# ── TAB 5: Preflight / Cost + Safety Planner ──────────────────────────────────
with tabs[5]:
    st.subheader("🔍 Preflight / Cost + Safety Planner")

    if not PREFLIGHT_AVAILABLE:
        st.error("❌ Preflight modules not loaded. Check imports.")
    else:
        # Project selection
        projects = get_projects()
        if not projects:
            st.info("⚠️ Import a DOCX project first")
        else:
            labels = {f"#{p['id']} — {p['title']}": p['id'] for p in projects}
            pid = labels[st.selectbox("Project (for analysis)", list(labels.keys()), key="preflight_project")]

            # Initialize session state for preflight
            if 'preflight_analysis' not in st.session_state:
                st.session_state.preflight_analysis = None

            # [Analyze Only] Button
            if st.button("🔍 Analyze Only", key="preflight_analyze_btn", help="Run preflight analysis without translation"):
                with st.spinner("🔄 Analyzing all segments..."):
                    try:
                        result = run_preflight_analysis(pid)
                        st.session_state.preflight_analysis = result
                        if result.status == 'done':
                            st.success("✅ Preflight analysis complete!")
                        else:
                            st.error(f"❌ Analysis failed: {result.error_message}")
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")

            # Display results if available
            if st.session_state.preflight_analysis and st.session_state.preflight_analysis.status == 'done':
                result = st.session_state.preflight_analysis

                # Statistics
                st.subheader("📊 Statistics")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Segments", result.total_segments)
                with col2:
                    st.metric("Unique (normalized)", result.unique_normalized)
                with col3:
                    st.metric("Duplicate Groups", result.duplicate_groups)
                with col4:
                    st.metric("Exact TM (99%+)", result.exact_tm_opportunities)

                col5, col6 = st.columns(2)
                with col5:
                    st.metric("Glossary Coverage", f"{result.glossary_coverage_percent:.1f}%")
                with col6:
                    st.metric("Analysis Time", result.preflight_at[-8:])

                # Routing Summary
                st.subheader("📍 Routing Summary")
                if result.routing_summary:
                    routing_data = []
                    for route, count in sorted(result.routing_summary.items()):
                        routing_data.append({
                            'Route': route,
                            'Segments': count,
                            'Percentage': f"{count/result.total_segments*100:.1f}%"
                        })
                    st.dataframe(pd.DataFrame(routing_data), use_container_width=True)
                else:
                    st.info("No routing data available")

                # Risk Summary
                st.subheader("⚠️ Risk Summary")
                if result.risk_summary:
                    risk_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
                    risk_data = []
                    for level in risk_order:
                        count = result.risk_summary.get(level, 0)
                        if count > 0:
                            risk_data.append({
                                'Risk Level': level,
                                'Segments': count,
                                'Percentage': f"{count/result.total_segments*100:.1f}%"
                            })
                    if risk_data:
                        st.dataframe(pd.DataFrame(risk_data), use_container_width=True)
                    else:
                        st.info("No risk data")
                else:
                    st.info("No risk summary available")

                # Cost Analysis
                st.subheader("💰 Cost Estimate (USD)")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Baseline Cost\n(all via GPT)", f"${result.cost_baseline_usd:.2f}")
                with col2:
                    st.metric("Optimized Cost\n(with routing)", f"${result.cost_optimized_usd:.2f}")
                with col3:
                    st.metric("Potential Savings",
                             f"${result.cost_savings_usd:.2f}\n({result.cost_savings_percent:.1f}%)",
                             delta_color="inverse")

                # Cost Component Breakdown
                st.subheader("📊 Cost Components Breakdown")
                if result.cost_component_breakdown:
                    component_data = []
                    for component, costs in result.cost_component_breakdown.items():
                        component_data.append({
                            'Component': component,
                            'Baseline ($)': f"{costs.get('baseline', 0.0):.2f}",
                            'Optimized ($)': f"{costs.get('optimized', 0.0):.2f}",
                            'Savings ($)': f"{costs.get('baseline', 0.0) - costs.get('optimized', 0.0):.2f}",
                        })
                    st.dataframe(pd.DataFrame(component_data), use_container_width=True)

                # Route Cost Breakdown
                st.subheader("📍 Route Cost Breakdown")
                if result.route_cost_breakdown:
                    route_cost_data = []
                    for route, stats in result.route_cost_breakdown.items():
                        route_cost_data.append({
                            'Route': route,
                            'Segments': stats.get('count', 0),
                            'Tokens': stats.get('tokens', 0),
                            'Baseline ($)': f"{stats.get('baseline_usd', 0.0):.2f}",
                            'Optimized ($)': f"{stats.get('optimized_usd', 0.0):.2f}",
                            'Savings ($)': f"{stats.get('savings_usd', 0.0):.2f}",
                        })
                    st.dataframe(pd.DataFrame(route_cost_data), use_container_width=True)

                # Zero-Token Optimization
                st.subheader("⚡ Zero-Token Optimization")
                st.markdown("""
                **Reduce API calls before translation:**
                - **Exact TM**: Fill from trusted Translation Memory (0 tokens)
                - **Duplicates**: Copy confirmed translations to duplicates (0 tokens)
                """)

                col1, col2, col3 = st.columns(3)
                with col1:
                    apply_tm_btn = st.button("💾 Apply Exact TM", key="apply_tm_btn", help="Prefill segments from exact TM matches")
                with col2:
                    prep_reps_btn = st.button("📌 Prepare Representatives", key="prep_reps_btn", help="Mark duplicate representatives")
                with col3:
                    propagate_btn = st.button("🔀 Propagate Duplicates", key="propagate_btn", help="Copy from confirmed representatives")

                if apply_tm_btn:
                    with st.spinner("⏳ Applying exact TM prefill..."):
                        try:
                            from zero_token_optimizer import optimize_project
                            results = optimize_project(pid, apply_tm=True, auto_confirm=False)
                            tm_result = results.get('tm_prefill', {})
                            st.success(f"""
                            ✅ TM Prefill Complete:
                            - Prefilled: {tm_result.get('prefilled_count', 0)} segments
                            - Auto-confirmed: {tm_result.get('auto_confirmed_count', 0)} segments
                            - Estimated savings: ${tm_result.get('tm_savings_usd', 0):.2f}
                            """)
                        except Exception as e:
                            st.error(f"❌ Error: {str(e)}")

                if prep_reps_btn:
                    with st.spinner("⏳ Preparing duplicate representatives..."):
                        try:
                            from zero_token_optimizer import optimize_project
                            results = optimize_project(pid, prepare_reps=True)
                            rep_result = results.get('prepare_reps', {})
                            st.success(f"""
                            ✅ Representatives Ready:
                            - Representatives marked: {rep_result.get('representative_count', 0)}
                            - Pending propagation: {rep_result.get('pending_count', 0)}
                            """)
                        except Exception as e:
                            st.error(f"❌ Error: {str(e)}")

                if propagate_btn:
                    with st.spinner("⏳ Propagating to duplicates..."):
                        try:
                            from zero_token_optimizer import optimize_project
                            results = optimize_project(pid, propagate=True)
                            prop_result = results.get('propagation', {})
                            st.success(f"""
                            ✅ Propagation Complete:
                            - Propagated: {prop_result.get('propagated_count', 0)} segments
                            - Skipped: {prop_result.get('skipped_count', 0)} segments
                            - Estimated savings: ${prop_result.get('propagation_savings_usd', 0):.2f}
                            """)
                        except Exception as e:
                            st.error(f"❌ Error: {str(e)}")

                # Duplicate Groups Table
                if st.button("📊 Show Duplicate Groups", key="show_dup_groups"):
                    try:
                        from db import get_duplicate_groups
                        dup_groups = get_duplicate_groups(pid)
                        if dup_groups:
                            dup_data = []
                            total_dup_savings = 0
                            for g in dup_groups[:20]:  # Top 20
                                dup_data.append({
                                    'Group ID': g['group_id'],
                                    'Segments': g['count'],
                                    'Tokens': g.get('tokens', 0),
                                    'Est. Savings ($)': f"{g.get('savings_usd', 0):.2f}",
                                })
                                total_dup_savings += g.get('savings_usd', 0)

                            st.dataframe(pd.DataFrame(dup_data), use_container_width=True)
                            st.info(f"💰 Total potential savings from duplicates: ${total_dup_savings:.2f}")
                        else:
                            st.info("No duplicate groups found")
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")

                # Batch Order Recommendation
                st.subheader("📋 Recommended Batch Order")
                if result.batch_order_recommendation:
                    st.info(f"""
                    **Process segments in this order to optimize costs:**

                    Top 10 segment IDs: {', '.join(map(str, result.batch_order_recommendation[:10]))}

                    (Showing first 10 of {len(result.batch_order_recommendation)} recommended)
                    """)
                else:
                    st.info("No batch order recommendation available")

            else:
                st.info("👈 Click [Analyze Only] to compute routing, costs, and risks for all segments")

# ── TAB 6: QA Dashboard ───────────────────────────────────────────────────────
with tabs[6]:
    st.subheader("✔️ QA Dashboard")
    projects = get_projects()
    if not projects:
        st.info("⚠️ Import a DOCX project first")
    else:
        # Project selection
        labels = {f"#{p['id']} — {p['title']}": p['id'] for p in projects}
        pid = labels[st.selectbox("Project", list(labels.keys()), key="qa_project")]
        project = get_project(pid)

        st.divider()

        # QA Control buttons
        col_local, col_adaptive, col_backcheck = st.columns(3)

        with col_local:
            if st.button("🚀 Run Local QA All", key="run_local_qa_all", help="Run local QA checks on all translated segments (no API calls)"):
                try:
                    from qa_orchestrator import QAOrchestrator

                    with st.spinner("⏳ Running local QA on all segments..."):
                        orchestrator = QAOrchestrator(pid, translation_model)
                        stage1_results = orchestrator.stage1_local_qa_all()

                    passed = sum(1 for r in stage1_results.values() if r['local_qa_status'] == 'pass')
                    warning = sum(1 for r in stage1_results.values() if r['local_qa_status'] == 'warning')
                    failed = sum(1 for r in stage1_results.values() if r['local_qa_status'] == 'fail')

                    st.success(f"""
                    ✅ **Local QA Complete**
                    - Passed: {passed}
                    - Warnings: {warning}
                    - Failed: {failed}
                    """)

                except ImportError:
                    st.error("QA orchestrator not available")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

        with col_adaptive:
            if st.button("📊 Run Adaptive QA Plan", key="run_adaptive_qa", help="Create adaptive QA plan and estimate costs"):
                try:
                    from qa_orchestrator import QAOrchestrator

                    with st.spinner("⏳ Creating adaptive QA plan..."):
                        orchestrator = QAOrchestrator(pid, translation_model)
                        stage1_results = orchestrator.stage1_local_qa_all()
                        stage2_results = orchestrator.stage2_consistency_qa(stage1_results)
                        stage3_results = orchestrator.stage3_adaptive_qa_plan(stage1_results, stage2_results)
                        stage4_results = orchestrator.stage4_numerical_qa(stage3_results)

                    gpt_qa_needed = sum(1 for r in stage3_results.values() if r.get('should_run_gpt_qa', False))
                    back_check_needed = sum(1 for r in stage3_results.values() if r.get('should_run_back_check', False))

                    st.info(f"""
                    📊 **QA Plan Summary**

                    - **Local QA:** All segments (no cost)
                    - **GPT QA scheduled:** {gpt_qa_needed} segments
                    - **Back-check scheduled:** {back_check_needed} segments
                    - **Estimated QA tokens:** {sum(1 for r in stage3_results.values() if r.get('should_run_gpt_qa'))*1200:,}
                    - **Estimated QA cost:** ${gpt_qa_needed * 0.12:.2f}
                    """)

                except ImportError:
                    st.error("QA orchestrator not available")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

        with col_backcheck:
            model_for_qa = st.selectbox("QA model", AVAILABLE_MODELS, index=0, label_visibility="collapsed", key="qa_model")

        st.divider()

        # QA Statistics
        st.subheader("📈 QA Statistics")

        segs = get_segments(pid)
        if segs:
            # Count QA statuses
            translated = sum(1 for s in segs if s.get('status') in ['translated', 'confirmed'])
            local_pass = sum(1 for s in segs if s.get('local_qa_status') == 'pass')
            local_warning = sum(1 for s in segs if s.get('local_qa_status') == 'warning')
            local_fail = sum(1 for s in segs if s.get('local_qa_status') == 'fail')
            final_passed = sum(1 for s in segs if s.get('qa_final_status') == 'qa_passed')
            final_warning = sum(1 for s in segs if s.get('qa_final_status') == 'qa_warning')
            final_failed = sum(1 for s in segs if s.get('qa_final_status') == 'qa_failed')
            human_review = sum(1 for s in segs if s.get('qa_final_status') == 'human_review_required')

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Translated", translated)
            with col2:
                st.metric("Local QA Pass", local_pass)
            with col3:
                st.metric("QA Final Pass", final_passed)
            with col4:
                st.metric("Human Review", human_review)

            st.markdown("---")

            # QA Status breakdown
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Local QA Status")
                local_qa_data = {
                    'Status': ['Pass', 'Warning', 'Fail'],
                    'Count': [local_pass, local_warning, local_fail]
                }
                st.bar_chart(pd.DataFrame(local_qa_data).set_index('Status'))

            with col2:
                st.subheader("Final QA Status")
                final_qa_data = {
                    'Status': ['Passed', 'Warning', 'Failed', 'Human Review'],
                    'Count': [final_passed, final_warning, final_failed, human_review]
                }
                st.bar_chart(pd.DataFrame(final_qa_data).set_index('Status'))

            st.markdown("---")

            # Export QA Report
            if st.button("📥 Export QA Report (CSV)"):
                import csv
                import io

                csv_buffer = io.StringIO()
                writer = csv.writer(csv_buffer)

                # Headers
                writer.writerow([
                    'ID', 'Source', 'Target', 'Status', 'Local QA',
                    'Final QA', 'QA Depth', 'Risk Level', 'Route'
                ])

                # Rows
                for seg in segs:
                    if seg.get('status') in ['translated', 'confirmed']:
                        writer.writerow([
                            seg['id'],
                            seg.get('source_text', '')[:50],
                            seg.get('target_text', '')[:50] if seg.get('target_text') else '─',
                            seg.get('status', '─'),
                            seg.get('local_qa_status', '─'),
                            seg.get('qa_final_status', '─'),
                            seg.get('qa_depth_used', '─'),
                            seg.get('risk_level') or '─',
                            seg.get('route') or '─',
                        ])

                st.download_button(
                    label="📥 Download QA Report",
                    data=csv_buffer.getvalue(),
                    file_name=f"qa_report_{pid}.csv",
                    mime="text/csv"
                )

# ── TAB 7: Backlog ────────────────────────────────────────────────────────────
with tabs[7]:
    st.subheader("📋 Backlog")
    backlog_path = Path("BACKLOG.md")
    if backlog_path.exists():
        st.markdown(backlog_path.read_text(encoding='utf-8'))
    else:
        st.info("BACKLOG.md not found")

# ── TAB 7: Stats ──────────────────────────────────────────────────────────────
with tabs[7]:
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
