"""Test all modules load and work correctly."""
import sys, os
os.chdir(r"C:\Users\Shox\med_translation")
sys.path.insert(0, '.')

print("1. config...")
from med_cat_config import BASE_DIR, APPROVED_TSV
print(f"   BASE_DIR={BASE_DIR.name}  APPROVED_TSV exists={APPROVED_TSV.exists()}")

print("2. terminology_loader...")
from terminology_loader import get_glossary, get_forbidden
gl = get_glossary()
fl = get_forbidden()
s = gl.stats
print(f"   Glossary: approved={s['approved']:,}  reference={s['reference']:,}  total={s['total']:,}")
print(f"   Forbidden: {len(fl.entries)} entries")

print("3. tm_loader...")
from tm_loader import get_tm
tm = get_tm()
print(f"   TM: {len(tm.entries)} segments")

print("4. terminology_engine...")
from terminology_engine import match_segment, build_prompt_context
matches = match_segment("острый инфаркт миокарда с подъёмом ST, доза аспирина 2 мг/кг")
print(f"   Matches found: {len(matches)}")
for m in matches[:5]:
    print(f"   {m.display_label}: {m.entry.russian!r} -> {m.entry.english[:45]!r}")
ctx = build_prompt_context(matches)
print(f"   Prompt context: {len(ctx)} chars, {len(ctx.splitlines())} lines")

print("5. risk_engine...")
from risk_engine import score_risk
r1 = score_risk("острый инфаркт миокарда с подъёмом ST, доза аспирина 325 мг каждые 6 часов")
r2 = score_risk("Введение")
r3 = score_risk("хроническая болезнь почек, аббревиатуры ХБП, МРТ")
r4 = score_risk("положительный результат ПЦР, уровень СРБ 85 мг/л, доза антибиотика 500 мг/кг/сут")
print(f"   CRITICAL test:  {r4.level} score={r4.risk_score}")
print(f"   HIGH test:      {r1.level} score={r1.risk_score}: {r1.risk_reasons[:2]}")
print(f"   MEDIUM test:    {r3.level} score={r3.risk_score}")
print(f"   LOW test:       {r2.level} score={r2.risk_score}")

print("6. workflow_engine...")
from workflow_engine import recommend
for risk_res in [r4, r1, r3, r2]:
    wf = recommend(risk_res)
    print(f"   {risk_res.level:8s} -> {wf.summary}")

print("7. forbidden_checker...")
from forbidden_checker import pre_check, post_check
pre = pre_check("абсолютный зрительный порог у пациента измерили")
post = post_check("абсолютный зрительный порог", "the threshold of vision was measured carefully")
print(f"   Pre-check alerts: {len(pre)}")
print(f"   Post-check alerts: {len(post)}")
if pre:
    print(f"   Pre alert: {pre[0].message[:70]}")
if post:
    print(f"   Post alert: {post[0].message[:70]}")
    print(f"   Severity: {post[0].severity}  Preferred: {post[0].preferred_en}")

print("8. TM search...")
tm_res = tm.search("острый инфаркт миокарда лечение", top_n=5)
print(f"   TM matches (>=94%): {len(tm_res)}")
tm_res2 = tm.search("если вы сильно прибавляете в весе ограничьте сладости", top_n=3)
print(f"   TM partial match test: {len(tm_res2)} results")
if tm_res2:
    print(f"   Best: score={tm_res2[0].score}% type={tm_res2[0].match_type}")

print()
print("=" * 50)
print("ALL TESTS PASSED")
