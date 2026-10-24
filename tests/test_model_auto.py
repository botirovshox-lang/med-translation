# -*- coding: utf-8 -*-
"""Автоподбор моделей шагов (админка → «Модели и расход» → «Подбирать сами»).

Что сторожится и почему:

  1. Подбор — по ДАННЫМ (`model_policy.json` + ранги + цены каталога): шагу —
     самая дешёвая модель годной силы, при равной цене — сильнее.
  2. Пары шагов, которым нельзя одну модель (проверка себя — не проверка),
     не получают одну модель никогда.
  3. Поставщик с пустым счётом выбывает; «по порядку» берёт первого живого,
     «лучшее по цене» — дешевле среди всех живых.
  4. Закреплённый человеком шаг подбор не трогает.
  5. Запись — только при включённом подборе и только изменившегося; путь тот же,
     что у ручного сохранения (`systemModels` + журнал).
  6. Проба поставщика: пустой счёт и отказ по стране выключают его, сетевой
     сбой — нет; новая модель в списке поставщика называется, а не ставится.
  7. Дверь — только суперпользователю.

Ни одного настоящего вызова модели.
"""
import os, sys, types
os.environ["APP_PASSWORD"] = "test-modelauto-password"
os.environ["MODEL_AUTO"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
main.STATE["systemModels"] = {}
main.STATE["modelAuto"] = {}
main._apply_system_models()
main.tg_mod = None

fail = []


def check(ok, msg):
    print(("  OK   " if ok else "  FAIL ") + msg)
    if not ok:
        fail.append(msg)


POL = main._model_policy()
BOTH = {"anthropic": {"ok": True, "why": "ok", "ids": None}, "openai": {"ok": True, "why": "ok", "ids": None}}

print("(1) по порядку поставщиков, оба живы")
r = main._model_auto_pick(BOTH, {}, POL)
p = r["picks"]
print("     ", p)
check(all(main._provider_of(v) == "anthropic" for v in p.values()), "сперва Anthropic (решение владельца)")
check(p["translate"] == "claude-sonnet-5-5", "перевод — Sonnet 5.5 (та же цена, что Sonnet 5, сильнее)")
check(p["review"] != p["translate"], "ревизия — не модель перевода")
check(p["backcheck"] not in (p["translate"], p["review"]), "back-check — не автор текста")
check(main.model_rank(p["backcheck"]) <= POL["maxRank"]["backcheck"], "back-check — буквальная, не сильнейшая")
check(p["judge"] != p["backcheck"], "судья — не модель обратного перевода")
check(all(p[k] != p["translate"] for k in ("termcheck", "termaudit", "repair")), "термины и ремонт — не модель перевода")
check(p["termcross"] != p["review"], "кросс-проверка листа — не модель ревизии")
check(main.model_rank(p["ocr"]) >= POL["minRank"]["ocr"], "чтение надписей — модель нужной силы")
check("claude-opus-5" not in p.values(), "самая дорогая Opus 5 не выбрана ни для одного шага")
for a, b in POL["distinct"]:
    check(p[a] != p[b], "пара %s/%s различна" % (a, b))

print("(2) у Anthropic пустой счёт — всё уходит к OpenAI")
r = main._model_auto_pick({"anthropic": {"ok": False}, "openai": {"ok": True, "ids": None}}, {}, POL)
check(all(main._provider_of(v) == "openai" for k, v in r["picks"].items() if r["why"][k] == "auto"),
      "только живой поставщик: %s" % r["picks"])
check(r["why"]["ocr"] == "none", "надписям годной силы у OpenAI нет — шаг остаётся прежним, а не слабее")
check(all(main._auto_price(main._MODELS_BY_ID[v], POL) <= POL["maxPrice"]["*"] for v in r["picks"].values()),
      "флагманы дороже потолка (Sol, GPT-5.5) не берутся")
check(r["why"]["review"] == "conflict", "спор ролей назван, а не спрятан флагманом")

print("(3) лучшее по цене среди всех живых")
r = main._model_auto_pick(BOTH, {"strategy": "price"}, POL)
check(r["picks"]["translate"] == "claude-sonnet-5-5", "перевод — дешевле Terra")
check(r["picks"]["backcheck"] == "claude-haiku-5-5", "back-check — дешевле Luna")

print("(3б) pick: best — сильнейшая под потолком; autoOn по умолчанию")
pol2 = dict(POL, pick={"*": "cheapest", "review": "best"})
r = main._model_auto_pick(BOTH, {}, pol2)
check(r["picks"]["review"] == "claude-opus-5-5", "ревизия с best — Opus 5.5: %s" % r["picks"]["review"])
check(r["picks"]["translate"] == "claude-sonnet-5-5", "остальные — по цене")
main.STATE["modelAuto"] = {}
check(main._model_auto_conf()["on"] is bool(POL.get("autoOn")), "не трогал владелец — действует autoOn правил")
main.STATE["modelAuto"] = {"on": False}
check(main._model_auto_conf()["on"] is False, "выключил владелец — выключено")

print("(4) закреплённый шаг не трогается, и пары считаются от него")
r = main._model_auto_pick(BOTH, {"pinned": {"translate": "gpt-5.6-terra"}}, POL)
check(r["picks"]["translate"] == "gpt-5.6-terra" and r["why"]["translate"] == "pinned", "закреплённый на месте")

print("(5) список поставщика сужает выбор; новых называет")
h = {"anthropic": {"ok": True, "ids": ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5-5",
                                       "claude-mega-9", "claude-sonnet-5-20250101"]},
     "openai": {"ok": False}}
r = main._model_auto_pick(h, {}, POL)
check("claude-sonnet-5-5" not in r["picks"].values(), "модели, которой нет у поставщика, нет и в выборе")
check(main._model_new_ids(h) == {"anthropic": ["claude-mega-9"]}, "новая модель названа, датированная копия — нет")

print("(6) запись: выключено — только отчёт; включено — systemModels")
REAL_PROBE = main._model_probe
main._model_probe = lambda prov: dict(BOTH[prov])
main.STATE["modelAuto"] = {"on": False}
res = main._model_auto_run()
check(not res["applied"] and main.STATE["systemModels"] == {}, "выключено — ничего не записано")
main.STATE["modelAuto"] = {"on": True}
res = main._model_auto_run()
check(res["applied"] and main.STATE["systemModels"]["translate"] == "claude-sonnet-5-5", "включено — записано")
check(main.DEFAULT_OPENAI_MODEL == "claude-sonnet-5-5", "действует через умолчания шагов")
res = main._model_auto_run()
check(not res["applied"], "ничего не изменилось — повторной записи нет")
check(any(a.get("action") == "system.models" and a.get("how") == "auto"
          for a in main.STATE.get("audit", [])), "след в журнале с пометкой auto")
# Настоящий ответ двери — образцом для рендер-теста админки (закон
# «рендер-тест на своей заглушке прячет поломки формы»).
import json as _json
main.STATE["modelAuto"]["newModels"] = {"anthropic": ["claude-mega-9"]}
main.STATE["modelAuto"]["health"]["openai"] = {"ok": False, "why": "quota", "at": 1}
pay = {"ok": True, "models": main._catalog_brief(), "groups": main.USAGE_GROUPS,
       "steps": [{"key": k, "value": main.STATE["systemModels"].get(k),
                  "codeDefault": main._CODE_DEFAULT_MODELS[k], "effective": main._effective_model(k)}
                 for k in main.SYSTEM_MODEL_STEPS],
       "auto": main._model_auto_public()}
open("tests/fixtures/model_auto_payload.json", "w", encoding="utf-8").write(
    _json.dumps(pay, ensure_ascii=False, indent=1, default=str) + "\n")
main._model_probe = REAL_PROBE

print("(7) проба: пустой счёт выключает, сеть — нет")


class _Fake:
    def __init__(self, text=None):
        self.text = text
        self.models = types.SimpleNamespace(list=lambda: [types.SimpleNamespace(id="claude-haiku-5-5")])
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._c))

    def _c(self, **kw):
        if self.text:
            raise RuntimeError(self.text)
        return None


os.environ["ANTHROPIC_API_KEY"] = "sk-test"
fake = types.ModuleType("anthropic")
fake.Anthropic = lambda **kw: _Fake()
sys.modules["anthropic"] = fake
orig_client = main._llm_client
for text, want_ok, want in (("Your credit balance is too low to access the Anthropic API", False, "quota"),
                            ("Connection timed out", True, "error"), (None, True, "ok")):
    main._llm_client = lambda *a, _t=text, **k: _Fake(_t)
    h = main._model_probe("anthropic")
    check(h["ok"] is want_ok and h["why"] == want, "«%s» → %s" % (str(text)[:30], h["why"]))
check(h.get("probe") == "claude-haiku-5-5", "проба — самой дешёвой моделью из списка поставщика")
main._PROVIDER_ERR.update(text="", at=0.0)
main._llm_client = lambda *a, **k: (main._note_quota(RuntimeError("insufficient_quota")), _Fake("insufficient_quota"))[1]
h = main._model_probe("anthropic")
check(not main._quota_recent() and None not in main._QUOTA_SEEN,
      "проба на пустом счёте не включает общий признак «нет баланса» (здоровые переводы не рвутся)")
main._llm_client = lambda *a, **k: _Fake("Error code: 401 - invalid x-api-key")
check(main._model_probe("anthropic")["why"] == "auth", "отозванный ключ (401) — поставщик выбывает")
main._llm_client = orig_client
os.environ.pop("OPENAI_API_KEY", None)
h = main._model_probe("openai")
check(h["ok"] is False and h["why"] == "nokey", "нет ключа — поставщик выбывает")

print("(7б) датированные id, задача из очереди, пропавшая модель")
h = {"anthropic": {"ok": True, "ids": ["claude-sonnet-5-5-20261001", "claude-sonnet-5-20260601",
                                       "claude-haiku-5-5-20261001", "claude-opus-5-5-20261001"]},
     "openai": {"ok": False}}
r = main._model_auto_pick(h, {}, POL)
check(r["picks"]["translate"] == "claude-sonnet-5-5", "датированный id поставщика — та же модель")
check(main._model_new_ids(h) == {}, "датированная копия известной модели — не «новая»")
h2 = {"anthropic": {"ok": True, "ids": ["something-else"]}, "openai": {"ok": False}}
check(main._model_auto_pick(h2, {}, POL)["picks"]["translate"] == "claude-sonnet-5-5",
      "список не про наш каталог — «не знаю», живой поставщик не отброшен")
main.STATE["modelAuto"] = {"on": True, "health": {"openai": {"ok": False, "why": "quota"},
                                                  "anthropic": {"ok": True, "why": "ok"}}}
job = {"id": 1, "params": {}, "sysModels": dict(main._system_models_snapshot(), translate="gpt-5.6-terra")}
fixed = main._job_freeze_models(job)
check(fixed["translate"] == "claude-sonnet-5-5" and any("нет счёта" in x for x in job.get("modelsReplaced", [])),
      "задача из очереди уходит с поставщика без счёта на нынешнее назначение, и это названо")
main.STATE["systemModels"]["review"] = "gpt-удалённая"
res = main._model_auto_run(probe=False)
check(main.STATE["systemModels"].get("review") in main._MODELS_BY_ID, "модель, пропавшая из каталога, не ломает применение")

print("(8) дверь — только суперпользователю")
from starlette.testclient import TestClient
c = TestClient(main.app)
main.STATE["users"] = [main._make_user("ed", "pw-ed-123456", "editor", "default")] \
    if hasattr(main, "_make_user") else main.STATE.get("users", [])
r = c.post("/api/admin/system-models/auto", json={"on": True})
check(r.status_code in (401, 403), "без входа — отказ (%s)" % r.status_code)

print()
print("ВСЁ ПРОШЛО" if not fail else "FAILED: %d" % len(fail))
sys.exit(1 if fail else 0)
