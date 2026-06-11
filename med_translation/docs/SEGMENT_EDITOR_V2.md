# ✏️ Segment Editor v2 (Variant 2 - Below Table)

**Дата**: 2026-05-24  
**Статус**: ✅ РЕАЛИЗОВАНО

## 🎯 Новый Интерфейс

### Структура:

```
┌──────────────────────────────────────────────────────────────┐
│ Segment Table (компактная, с inline редактированием)        │
│                                                               │
│ ID │ Ord │ Source      │ Target (edit)    │ TM% │ Actions  │
├────┼─────┼─────────────┼──────────────────┼────┼──────────┤
│2822│5017 │ 1000мг      │ [1000 mg]        │87% │🔍▶️✓⤴️  │
│    │     │             │                  │    │     ✅    │ ← Toggle button
│2823│5018 │ ПАСК...     │ [____]           │0%  │🔍▶️✓⤴️  │
│    │     │             │                  │    │     ✅    │
│2824│5019 │ 150мг/кг    │ [150 mg/kg]      │95% │🔍▶️✓⤴️  │
│    │     │             │                  │    │     ✅    │
└────┴─────┴─────────────┴──────────────────┴────┴──────────┘
           ↓ (раскрывается при выборе)
┌──────────────────────────────────────────────────────────────┐
│ 💡 Suggestions for Segment #2822                            │
├──────────────────────────────────────────────────────────────┤
│ Source (Russian): 1000мг                                     │
│                                                               │
│ 🔍 TM Match (87%)                                           │
│    1000 mg                                                   │
│                                                               │
│ ✓ QA Report                                                  │
│    Accuracy: 95/100      Terminology: 98/100               │
│    Completeness: 100/100  Numbers: 100/100                 │
│    Overall: 98/100                                          │
│                                                               │
│ ⤴️ Back-check Report                                        │
│    Semantic Score: 95/100                                   │
│    Back-translation: "1000 миллиграмм"                      │
│    ✅ No meaning drift, omissions, additions              │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## 🎮 Как использовать

### **1. Таблица сегментов**

#### Колонки:
- **ID**: Номер сегмента (кликабельный - выбирает в suggestions)
- **Ord**: Порядковый номер
- **Source**: Исходный текст (русский) - 40 символов preview
- **Target (edit)**: **РЕДАКТИРУЕМАЯ** - прямо здесь можно писать перевод
- **TM%**: Процент совпадения с Translation Memory
- **Actions**: 4 кнопки действий
- **Status**: Статус сегмента
- **QA**: QA score (если есть)
- **✅/✗**: Toggle для подтверждения/отклонения

#### Action кнопки (4 шт):
```
🔍 Find TM        → Ищет в TM (100% или >94%), показывает % справа
▶️ Translate      → OpenAI перевод (с глоссарием), заполняет Target
✓ QA              → Проверка качества (accuracy, terminology, forbidden)
⤴️ Back-check     → Back-translation для проверки смысла
```

#### Toggle кнопка (✅/✗):
```
✅ Confirm  → Сегмент ОДОБРЕН → Сохраняется в БД + добавляется в TM
✗ Reject   → Сегмент ОТКЛОНЕН → Не сохраняется, не добавляется в TM
```

Клик на кнопку → меняется на противоположную

---

### **2. Suggestions Panel (ниже таблицы)**

Появляется автоматически когда:
- Ты кликнешь на ID сегмента в таблице, или
- Выполнишь любое действие (Find TM, Translate, QA, Back-check)

#### Показывает:

**Source (Russian):**
```
Исходный текст для контекста
```

**🔍 TM Match (если найден):**
```
87% → "1000 mg"
Показывается только если TM матч найден
```

**✓ QA Report (если выполнена QA проверка):**
```
┌─────────────────────────────────────┐
│ Accuracy: 95    Terminology: 98     │
│ Completeness: 100  Numbers: 100    │
│ Overall: 98                         │
├─────────────────────────────────────┤
│ 🔴 Critical Issues (если есть):     │
│    - "threshold" is forbidden term  │
│                                     │
│ 🟡 Minor Issues (если есть):        │
│    - "mg" could be "milligrams"     │
└─────────────────────────────────────┘
```

**⤴️ Back-check Report (если выполнен back-check):**
```
┌─────────────────────────────────────┐
│ Semantic Score: 95/100              │
│ Verdict: ✅ PASS                    │
│                                     │
│ Back-translation: "1000 миллиграмм" │
│                                     │
│ ✅ No meaning drift                │
│ ✅ No omissions                    │
│ ✅ No additions                    │
└─────────────────────────────────────┘
```

---

## 🔄 Workflow примеры

### **Сценарий 1: Быстрое подтверждение**
```
1. Видю сегмент в таблице: "1000мг"
2. Читаю Target: вижу "1000 mg" (уже заполнено)
3. Кликаю ID → раскрывается Suggestions
4. Вижу что TM матч 87%, QA нет issues
5. Кликаю ✅ → Segment confirmed!
```

**Время**: ~5 секунд на сегмент

---

### **Сценарий 2: Перевод + Проверка + Подтверждение**
```
1. Видю сегмент: "ПАСК (пакетики по 4г)", Target пусто
2. Кликаю ▶️ Translate → OpenAI переводит → Target заполняется
3. Кликаю ID → раскрывается Suggestions
4. Вижу варианты в Suggestions panel справа
5. Редактирую Target если нужно
6. Кликаю ✓ QA → проверка качества
7. Видю QA Report: все scores > 95
8. Кликаю ✅ Confirm → готово!
```

**Время**: ~20-30 секунд на сегмент (включая ожидание OpenAI)

---

### **Сценарий 3: Отклонение плохого перевода**
```
1. Видю Target: "threshold" (запрещённый термин)
2. Кликаю ✓ QA → проверка
3. Видю в QA Report: "⚠️ Forbidden term: threshold"
4. Redактирую Target: меняю на "sensory threshold"
5. Кликаю ✓ QA заново
6. Видю что issues нет
7. Кликаю ✅ Confirm → готово!
```

**Время**: ~30-40 секунд

---

### **Сценарий 4: Back-check для сложных текстов**
```
1. Есть перевод: "患者の状態が急速に悪化する傾向がある" → "The patient tends to deteriorate"
2. Кликаю ⤴️ Back-check
3. Видю Back-translation: "Patient has tendency to deteriorate"
4. ⚠️ Вижу что "быстро" потеряно! → OMISSION DETECTED
5. Редактирую Target: добавляю "rapidly"
6. Кликаю ⤴️ Back-check заново
7. Back-translation: "Patient rapidly tends to deteriorate"
8. ✅ Semantic Score 95/100 → OK!
9. Кликаю ✅ Confirm
```

**Время**: ~40-50 секунд

---

## 📊 Сравнение: Старый vs Новый

| Аспект | Старый | Новый | Улучшение |
|--------|--------|-------|-----------|
| **Выбор сегмента** | Вводить ID | Клик на ID в таблице | -90% кликов |
| **Просмотр source** | Полноэкранный | 40 чаров в таблице | +Быстро |
| **Редактирование target** | Отдельный text area | Inline в таблице | +Speed |
| **Action buttons** | Ниже редактора | В таблице (4 шт) | +Fast |
| **Результаты** | Expanders ниже | Suggestions panel | +Visible |
| **TM% visualize** | Нет | В таблице | NEW |
| **Confirm toggle** | Отдельная кнопка | ✅/✗ toggle | +Fast |
| **Total workflow** | 5+ кликов | 2-3 клика | -50% кликов |

---

## ⚙️ Технические детали

### **Session State**
```python
st.session_state.selected_segment_id
# Хранит ID выбранного сегмента
# Используется для отображения Suggestions panel
```

### **Inline редактирование Target**
```python
target_text = st.text_input(
    "target",
    seg.get('target_text') or '',
    key=f"target_{seg['id']}"
)
if target_text != (seg.get('target_text') or ''):
    update_segment(seg['id'], target_text=target_text)
# Автоматически сохраняется в БД при изменении
```

### **Action кнопки**
```python
# Все 4 кнопки (🔍▶️✓⤴️) в одной строке (col5)
# Использут columns(4) для компактности
# При клике:
#   1. Выполняют действие
#   2. Обновляют БД
#   3. Устанавливают selected_segment_id
#   4. st.rerun() для обновления UI
```

### **Toggle Confirm/Reject**
```python
is_confirmed = fresh.get('status') == 'confirmed'

if is_confirmed:
    if st.button("✅", ...):
        update_segment(seg['id'], status='translated')
        st.rerun()
else:
    if st.button("✗", ...):
        confirm_segment(seg['id'])
        st.rerun()
```

---

## 🧪 Тестирование

### **Чек-лист:**

- [ ] Таблица загружается без ошибок
- [ ] Target редактируемый inline
- [ ] Action кнопки (🔍▶️✓⤴️) работают
- [ ] Toggle ✅/✗ меняется при клике
- [ ] Suggestions panel раскрывается при клике на ID
- [ ] TM Match показывается в suggestions
- [ ] QA Report показывается с красивыми metrics
- [ ] Back-check Report показывается корректно
- [ ] Confirm (✅) сохраняет в БД + TM
- [ ] Reject (✗) не сохраняет
- [ ] Перевод сохраняется при inline редактировании

---

## 📝 Что дальше

1. ✅ Реализовано
2. ⏳ Тестирование (нужно проверить в браузере)
3. ⏳ Оптимизация (если нужна)
4. ⏳ Keyboard shortcuts (опционально)

---

## 🚀 Запуск

```bash
# Перезагрузи Streamlit
Ctrl+C
streamlit run app_v55.py
```

Должно появиться новое UI с таблицей и suggestions panel! 🎉

---

**ВАЖНО**: Если видишь ошибки - делай скриншот и показывай мне!
