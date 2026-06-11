import streamlit as st, pandas as pd, json
from pathlib import Path
from config import AVAILABLE_MODELS,DEFAULT_TRANSLATION_MODEL,DEFAULT_REVIEW_MODEL
from db import *
from docx_cat import import_docx_project,export_translated_docx
from pipeline import translate_segment,qa_segment,extract_terms_from_segment,back_translate_check
from tm import find_tm_suggestion
init_db(); st.set_page_config(page_title='Medical CAT Translator v5.1',layout='wide'); st.title('Medical CAT Translator v5.1')
with st.sidebar:
    translation_model=st.selectbox('Translation model',AVAILABLE_MODELS,index=0)
    review_model=st.selectbox('Review / QA model',AVAILABLE_MODELS,index=0)
    st.caption('Use gpt-5.5, not gpt-5.5-thinking')
tabs = st.tabs(["Import DOCX", "Segment Editor", "Glossary", "TM", "Export", "Backlog", "Token Policy"])
with tabs[0]:
    up=st.file_uploader('Upload DOCX',type=['docx']); title=st.text_input('Project title'); sl=st.text_input('Source language',value='Russian'); tl=st.text_input('Target language',value='English')
    if up and st.button('Create project'):
        pid,count=import_docx_project(up,title or up.name,sl,tl); st.success(f'Project #{pid}; segments: {count}')
    ps=get_projects();
    if ps: st.dataframe(pd.DataFrame(ps))
with tabs[1]:
    ps=get_projects()
    if not ps: st.info('Import DOCX first')
    else:
        labels={f"#{p['id']} — {p['title']}":p['id'] for p in ps}; pid=labels[st.selectbox('Project',list(labels.keys()))]; project=get_project(pid)
        status=st.selectbox('Status',['all','new','translated','qa_done','back_checked','confirmed','needs_review','failed']); segs=get_segments(pid,status)
        if segs: st.dataframe(pd.DataFrame(segs)[['id','segment_order','block_type','source_text','target_text','status','qa_score','back_translation_score']],height=260)
        sid=st.number_input('Segment ID',min_value=1,step=1); seg=get_segment(int(sid))
        if seg and seg['project_id']==pid:
            left,right=st.columns(2)
            with left: st.text_area('Source',seg['source_text'],height=220,disabled=True)
            with right:
                current=st.text_area('Target',seg.get('target_text') or '',height=220)
                if st.button('Save edited translation'): update_segment(seg['id'],target_text=current,status='translated'); st.success('Saved')
            c1,c2,c3,c4,c5,c6=st.columns(6)
            if c1.button('Find TM'):
                m=find_tm_suggestion(seg['source_text']); st.write(m or 'No match')
            if c2.button('Translate'):
                m=find_tm_suggestion(seg['source_text']); tm='' if not m else m['target_text']; res=translate_segment(seg['source_text'],glossary_prompt(pid),translation_model,tm); update_segment(seg['id'],target_text=res,status='translated'); st.success('Translated')
            if c3.button('QA'):
                fresh=get_segment(seg['id']); target=fresh.get('target_text') or current; rep=qa_segment(fresh['source_text'],target,glossary_prompt(pid),review_model); ns='qa_done' if rep.get('verdict')=='pass' else 'needs_review' if rep.get('verdict')=='warning' else 'failed'; update_segment(seg['id'],target_text=rep.get('corrected_translation') or target,qa_report=json.dumps(rep,ensure_ascii=False,indent=2),qa_score=rep.get('overall_score'),status=ns); st.success(f"QA: {rep.get('verdict')} / {rep.get('overall_score')}")
            if c4.button('Back-check'):
                fresh=get_segment(seg['id']); target=fresh.get('target_text') or current; rep=back_translate_check(fresh['source_text'],target,project.get('source_language') or 'Russian',review_model); ns='back_checked' if rep.get('verdict')=='pass' else 'needs_review' if rep.get('verdict')=='warning' else 'failed'; update_segment(seg['id'],back_translation=rep.get('back_translation'),back_translation_report=json.dumps(rep,ensure_ascii=False,indent=2),back_translation_score=rep.get('semantic_score'),status=ns); st.success(f"Back-check: {rep.get('verdict')} / {rep.get('semantic_score')}")
            if c5.button('Confirm'): confirm_segment(seg['id']); st.success('Confirmed')
            if c6.button('Needs review'): update_segment(seg['id'],status='needs_review')
            fresh=get_segment(seg['id'])
            if fresh.get('qa_report'):
                with st.expander('QA report'): st.json(json.loads(fresh['qa_report']))
            if fresh.get('back_translation_report'):
                with st.expander('Back-translation report'): st.json(json.loads(fresh['back_translation_report']))
with tabs[2]:
    ps=get_projects()
    if ps:
        labels={f"#{p['id']} — {p['title']}":p['id'] for p in ps}; pid=labels[st.selectbox('Glossary project',list(labels.keys()))]
        s=st.text_input('Source term'); t=st.text_input('Target term'); cat=st.text_input('Category'); notes=st.text_area('Notes')
        if st.button('Add glossary term') and s and t: add_glossary_term(pid,s,t,cat,notes); st.success('Added')
        terms=get_glossary(pid);
        if terms: st.dataframe(pd.DataFrame(terms)); st.code(glossary_prompt(pid))
with tabs[3]:
    txt=st.text_area('TM data: source | target',height=260)
    if st.button('Import TM'):
        rows=[]
        for line in txt.splitlines():
            parts=line.split('|',1) if '|' in line else line.split('\t',1) if '\t' in line else []
            if len(parts)==2: rows.append((parts[0].strip(),parts[1].strip()))
        import_tm_rows(rows); st.success(f'Imported {len(rows)} rows')
with tabs[4]:
    ps=get_projects()
    if ps:
        labels={f"#{p['id']} — {p['title']}":p['id'] for p in ps}; pid=labels[st.selectbox('Export project',list(labels.keys()))]
        segs=get_segments(pid); st.metric('Segments',len(segs)); st.metric('Translated',len([s for s in segs if s.get('target_text')]))
        if st.button('Export DOCX'):
            path=export_translated_docx(pid); st.success(path)
            with open(path,'rb') as f: st.download_button('Download DOCX',f,file_name=Path(path).name)
with tabs[5]: st.markdown(Path('BACKLOG.md').read_text(encoding='utf-8'))


with tabs[6]:
    st.subheader("Token Policy")
    path = Path("TOKEN_POLICY.md")
    if path.exists():
        st.markdown(path.read_text(encoding="utf-8"))
    else:
        st.info("TOKEN_POLICY.md not found.")
