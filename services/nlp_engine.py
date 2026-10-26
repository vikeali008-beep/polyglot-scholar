import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

try:
    import pymorphy3
    MORPH = pymorphy3.MorphAnalyzer()
except Exception:
    MORPH = None

from .db import get_conn

WIKT_HEADERS = {
    "User-Agent": "PolyglotScholarReader/1.0 (https://scholar.arena.local; linguareader@example.org) httpx/0.27"
}

RU_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
COMBINING_ACUTE = "\u0301"
COMBINING_GRAVE = "\u0300"

# Built-in curated stress dictionary for frequent Russian academic words & function words
BUILTIN_RU_STRESS: Dict[str, str] = {
    "исследование": "иссле́дование",
    "исследования": "иссле́дования",
    "исследований": "иссле́дований",
    "исследовании": "иссле́довании",
    "исследованию": "иссле́дованию",
    "исследованием": "иссле́дованием",
    "метод": "ме́тод",
    "методы": "ме́тоды",
    "методов": "ме́тодов",
    "методология": "методоло́гия",
    "задача": "зада́ча",
    "задачи": "зада́чи",
    "задачах": "зада́чах",
    "модель": "моде́ль",
    "модели": "моде́ли",
    "моделей": "моде́лей",
    "система": "систе́ма",
    "системы": "систе́мы",
    "системах": "систе́мах",
    "анализ": "ана́лиз",
    "анализа": "ана́лиза",
    "результат": "результа́т",
    "результаты": "результа́ты",
    "результатов": "результа́тов",
    "данные": "да́нные",
    "данных": "да́нных",
    "обучение": "обуче́ние",
    "обучения": "обуче́ния",
    "обработка": "обрабо́тка",
    "обработки": "обрабо́тки",
    "перевод": "перево́д",
    "перевода": "перево́да",
    "алгоритм": "алгори́тм",
    "алгоритмы": "алгори́тмы",
    "структура": "структу́ра",
    "структуры": "структу́ры",
    "эффект": "эффе́кт",
    "эффекты": "эффе́кты",
    "эффектов": "эффе́ктов",
    "квантовый": "ква́нтовый",
    "квантовых": "ква́нтовых",
    "процесс": "проце́сс",
    "процессы": "проце́ссы",
    "работа": "рабо́та",
    "работе": "рабо́те",
    "работы": "рабо́ты",
    "статья": "статья́",
    "статье": "статье́",
    "автор": "а́втор",
    "авторы": "а́вторы",
    "авторами": "а́вторами",
    "подход": "подхо́д",
    "подхода": "подхо́да",
    "является": "явля́ется",
    "являются": "явля́ются",
    "позволяет": "позволя́ет",
    "позволяют": "позволя́ют",
    "представляет": "представля́ет",
    "рассматривается": "рассма́тривается",
    "рассматриваются": "рассма́триваются",
    "используется": "испо́льзуется",
    "используются": "испо́льзуются",
    "показано": "пока́зано",
    "установлено": "устано́влено",
    "однако": "одна́ко",
    "таким": "таки́м",
    "образом": "о́бразом",
    "следовательно": "сле́довательно",
    "поскольку": "поско́льку",
    "который": "кото́рый",
    "которая": "кото́рая",
    "которое": "кото́рое",
    "которые": "кото́рые",
    "которого": "кото́рого",
    "которых": "кото́рых",
    "данного": "да́нного",
    "данной": "да́нной",
    "данных": "да́нных",
    "высокий": "высо́кий",
    "высокая": "высо́кая",
    "глубокий": "глубо́кий",
    "глубокого": "глубо́кого",
    "естественный": "есте́ственный",
    "естественного": "есте́ственного",
    "машинный": "маши́нный",
    "машинного": "маши́нного",
    "нейронный": "нейро́нный",
    "нейронных": "нейро́нных",
    "сеть": "сеть",
    "сетей": "сете́й",
    "сети": "се́ти",
    "язык": "язы́к",
    "языка": "языка́",
    "внимание": "внима́ние",
    "внимания": "внима́ния",
    "качество": "ка́чество",
    "качества": "ка́чества",
    "точность": "то́чность",
    "точности": "то́чности",
    "основе": "осно́ве",
    "рамках": "ра́мках",
    "введение": "введе́ние",
    "заключение": "заключе́ние",
}

SCIENTIFIC_PREFIXES = [
    "низко", "высоко", "широко", "узко", "много", "мало", "полу", "микро",
    "макро", "сверх", "гипер", "супер", "квази", "псевдо", "само", "взаимо",
    "меж", "внутри", "электро", "квантово-", "квантово", "нейро", "био",
    "термо", "фото", "радио", "магнито", "обще", "противо", "одно", "двух",
]

POS_MAP_RU = {
    "NOUN": ("名词", "Существительное"),
    "ADJF": ("长尾形容词", "Прилагательное (полн.)"),
    "ADJS": ("短尾形容词", "Прилагательное (кратк.)"),
    "COMP": ("比较级", "Компаратив"),
    "VERB": ("动词（变位形式）", "Глагол (личная форма)"),
    "INFN": ("动词不定式（原形）", "Инфинитив"),
    "PRTF": ("长尾形动词", "Причастие (полн.)"),
    "PRTS": ("短尾被动形动词", "Причастие (кратк.)"),
    "GRND": ("副动词", "Деепричастие"),
    "NUMR": ("数词", "Числительное"),
    "ADVB": ("副词", "Наречие"),
    "NPRO": ("代词", "Местоимение"),
    "PRED": ("谓语副词/无人称谓语", "Предикатив"),
    "PREP": ("前置词（介词）", "Предлог"),
    "CONJ": ("连词", "Союз"),
    "PRCL": ("语气词", "Частица"),
    "INTJ": ("感叹词", "Междометие"),
}

CASE_MAP_RU = {
    "nomn": ("第一格·主格", "И.п.", "кто? что?（谁？什么？）"),
    "gent": ("第二格·属格", "Р.п.", "кого? чего?（谁的？什么的？）"),
    "datv": ("第三格·与格", "Д.п.", "кому? чему?（给谁？向什么？）"),
    "accs": ("第四格·宾格", "В.п.", "кого? что?（把谁？什么？）"),
    "ablt": ("第五格·工具格", "Т.п.", "кем? чем?（用什么？由谁？）"),
    "loct": ("第六格·前置格", "П.п.", "о ком? о чём?（关于/在什么中？）"),
    "voct": ("呼格", "Зв.п.", ""),
    "gen2": ("第二属格（部分格）", "Р.п.2", "чего?"),
    "loc2": ("第二前置格（方位格）", "П.п.2", "где? в чём?"),
}

GENDER_MAP_RU = {
    "masc": "阳性 (м.р.)",
    "femn": "阴性 (ж.р.)",
    "neut": "中性 (ср.р.)",
}

NUMBER_MAP_RU = {
    "sing": "单数 (ед.ч.)",
    "plur": "复数 (мн.ч.)",
}

ASPECT_MAP_RU = {
    "perf": "完成体 (СВ · совершенный вид)",
    "impf": "未完成体 (НСВ · несовершенный вид)",
}

TENSE_MAP_RU = {
    "pres": "现在时 (наст.вр.)",
    "past": "过去时 (прош.вр.)",
    "futr": "将来时 (буд.вр.)",
}

VOICE_MAP_RU = {
    "actv": "主动 (действ.)",
    "pssv": "被动 (страд.)",
}

# Russian Academic Discourse Phrases / Clichés
RU_ACADEMIC_PHRASES = [
    ("в рамках данного исследования", "在本研究框架内 / within the framework of this study"),
    ("в рамках настоящей работы", "在本文工作范围内 / within the scope of the present work"),
    ("таким образом", "因此，综上所述 / thus, consequently"),
    ("тем не менее", "然而，尽管如此 / nevertheless"),
    ("при этом", "与此同时，而且 / herewith, while doing so"),
    ("с одной стороны", "一方面 / on the one hand"),
    ("с другой стороны", "另一方面 / on the other hand"),
    ("в частности", "具体而言，尤其是 / in particular"),
    ("в результате", "结果，由此 / as a result"),
    ("в соответствии с", "根据，依照 / in accordance with"),
    ("на основе", "基于…… / on the basis of"),
    ("за счёт", "得益于，依靠……实现 / due to, by means of"),
    ("по сравнению с", "与……相比 / compared with"),
    ("следует отметить", "应当指出 / it should be noted"),
    ("особое внимание уделяется", "特别关注…… / special attention is paid to"),
    ("представляет собой", "本质上是，构成…… / represents, constitutes"),
    ("обусловлен тем, что", "归因于……，由……所决定 / is conditioned by the fact that"),
    ("играет ключевую роль", "起关键作用 / plays a key role"),
    ("в настоящее время", "目前，当今 / at present, currently"),
]

# High-value Russian academic root words for subtle reader highlighting
RU_ACADEMIC_LEMMAS = {
    "исследование", "методология", "метод", "модель", "алгоритм", "анализ",
    "параметр", "структура", "система", "эффективность", "результат", "гипотеза",
    "эксперимент", "распределение", "зависимость", "вероятность", "оптимизация",
    "архитектура", "обучение", "трансформер", "механизм", "аппроксимация",
    "концепция", "интерпретация", "корреляция", "классификация", "генерация",
    "квантовый", "полупроводниковый", "гетероструктура", "размерный", "эффект",
    "обусловить", "рассматриваться", "предполагать", "демонстрировать", "позволять",
    "обеспечивать", "определять", "характеризоваться", "свидетельствовать",
}

# English Academic Word List (Coxhead AWL core subset) & phrases
EN_ACADEMIC_WORDS = {
    "abstract", "accompany", "accumulate", "accurate", "achieve", "acknowledge", "acquire",
    "adapt", "adequate", "adjacent", "adjust", "aggression", "allocate", "alter", "alternative",
    "ambiguous", "analogous", "analyze", "analysis", "analytical", "empirical", "hypothesis",
    "hypothesize", "methodology", "methodological", "paradigm", "parameter", "phenomenon",
    "phenomena", "architecture", "mechanism", "transduction", "representation", "contextual",
    "correlation", "correlate", "demonstrate", "derive", "differentiate", "dimension", "discrete",
    "distribute", "distribution", "domain", "dominant", "dynamic", "eliminate", "emerge",
    "emphasis", "emphasize", "enable", "encounter", "enhance", "ensure", "equate", "equivalent",
    "establish", "evaluate", "evaluation", "evidence", "evolve", "explicit", "exploit", "extract",
    "facilitate", "feasible", "fluctuate", "formulate", "framework", "fundamental", "generate",
    "generation", "heterogeneous", "hierarchy", "hierarchical", "identical", "identify",
    "illustrate", "implement", "implementation", "implication", "implicit", "incorporate",
    "indicate", "induce", "inevitable", "infer", "inference", "inherent", "inhibit", "initial",
    "integrate", "integration", "interact", "interaction", "intermediate", "interpret",
    "interpretation", "intrinsic", "investigate", "investigation", "isolate", "layer",
    "lexical", "linguistic", "morphological", "morphology", "parallel", "parallelization",
    "perceive", "perspective", "predominant", "preliminary", "presume", "prevail", "principal",
    "prior", "proportion", "protocol", "qualitative", "quantitative", "radical", "random",
    "rational", "recurrence", "recurrent", "regime", "reinforce", "relevant", "reliable",
    "rely", "retain", "reveal", "rigorous", "robust", "scenario", "scheme", "sequence",
    "sequential", "significant", "significantly", "simulate", "simultaneous", "simultaneously",
    "specify", "stability", "subsequent", "subsequently", "substantial", "substantiate",
    "substitute", "sufficient", "supplement", "sustain", "synthesis", "synthesize", "systematic",
    "theoretical", "transfer", "transform", "transformation", "transition", "transmit",
    "underlying", "utilize", "valid", "validate", "validity", "variable", "variation", "whereas",
    "whereby", "notwithstanding", "consequently", "furthermore", "nevertheless", "predominantly",
}

EN_ACADEMIC_PHRASES = [
    ("in accordance with", "根据，依照 / в соотве́тствии с"),
    ("with respect to", "关于，就……而言 / по отноше́нию к"),
    ("in contrast to", "与……形成对比 / в отли́чие от"),
    ("play a pivotal role", "起中枢/关键作用 / игра́ть ключеву́ю роль"),
    ("play a crucial role", "起关键作用 / игра́ть ва́жную роль"),
    ("dispense with", "省去，摒弃 / обходи́ться без"),
    ("state-of-the-art", "当前最先进的 (SOTA) / передово́й у́ровень"),
    ("on the other hand", "另一方面 / с друго́й стороны́"),
    ("as a consequence", "因此，作为结果 / как сле́дствие"),
    ("empirical evidence", "实证证据 / эмпири́ческие да́нные"),
    ("to a large extent", "在很大程度上 / в значи́тельной сте́пени"),
    ("in light of", "鉴于，考虑到 / в све́те"),
    ("cross-linguistic transfer", "跨语言迁移 / межъязыково́й перено́с"),
]

EN_IRREGULAR_LEMMAS = {
    "was": "be", "were": "be", "been": "be", "being": "be", "is": "be", "are": "be", "am": "be",
    "had": "have", "has": "have", "having": "have",
    "did": "do", "does": "do", "done": "do",
    "went": "go", "gone": "go", "shown": "show", "showed": "show",
    "wrote": "write", "written": "write", "taken": "take", "took": "take",
    "given": "give", "gave": "give", "found": "find", "made": "make",
    "built": "build", "led": "lead", "held": "hold", "kept": "keep",
    "known": "know", "knew": "know", "seen": "see", "saw": "see",
    "arose": "arise", "arisen": "arise", "driven": "drive", "drove": "drive",
    "chosen": "choose", "chose": "choose", "spoken": "speak", "spoke": "speak",
    "phenomena": "phenomenon", "criteria": "criterion", "analyses": "analysis",
    "hypotheses": "hypothesis", "indices": "index", "matrices": "matrix",
    "children": "child", "studies": "study", "corpora": "corpus", "formulae": "formula",
}


def detect_lang(text: str) -> str:
    cyrillic = len(re.findall(r"[а-яА-ЯёЁ]", text))
    latin = len(re.findall(r"[a-zA-Z]", text))
    return "ru" if cyrillic > latin * 0.4 and cyrillic > 0 else "en"


def strip_stress(text: str) -> str:
    return text.replace(COMBINING_ACUTE, "").replace(COMBINING_GRAVE, "")


def count_ru_vowels(word: str) -> int:
    return sum(1 for ch in word if ch in RU_VOWELS)


def preserve_case(original: str, stressed_lower: str) -> str:
    """Project acute stress marks from stressed_lower onto original casing."""
    out = []
    orig_idx = 0
    for ch in stressed_lower:
        if ch in (COMBINING_ACUTE, COMBINING_GRAVE):
            if ch == COMBINING_ACUTE:
                out.append(COMBINING_ACUTE)
        else:
            if orig_idx < len(original):
                out.append(original[orig_idx])
                orig_idx += 1
            else:
                out.append(ch)
    while orig_idx < len(original):
        out.append(original[orig_idx])
        orig_idx += 1
    return "".join(out)


def _load_stress_from_db(words_lower: List[str]) -> Dict[str, Tuple[str, str]]:
    if not words_lower:
        return {}
    conn = get_conn()
    placeholders = ",".join("?" for _ in words_lower)
    rows = conn.execute(
        f"SELECT word_lower, stressed_word, syllables FROM stress_cache WHERE word_lower IN ({placeholders})",
        words_lower,
    ).fetchall()
    conn.close()
    return {r["word_lower"]: (r["stressed_word"], r["syllables"]) for r in rows}


def _save_stress_to_db(entries: Dict[str, Tuple[str, str]]) -> None:
    if not entries:
        return
    conn = get_conn()
    now = time.time()
    conn.executemany(
        "INSERT OR REPLACE INTO stress_cache (word_lower, stressed_word, syllables, updated_at) VALUES (?, ?, ?, ?)",
        [(w, sw, syl, now) for w, (sw, syl) in entries.items()],
    )
    conn.commit()
    conn.close()


def _fetch_wiktionary_stress_batch(words_lower: List[str]) -> Dict[str, Tuple[str, str]]:
    """Query up to 45 Russian words per batch on ru.wiktionary.org."""
    results: Dict[str, Tuple[str, str]] = {}
    unique = [w for w in dict.fromkeys(words_lower) if w and len(w) >= 2]
    if not unique:
        return results

    for i in range(0, len(unique), 40):
        chunk = unique[i : i + 40]
        try:
            resp = httpx.get(
                "https://ru.wiktionary.org/w/api.php",
                params={
                    "action": "query",
                    "titles": "|".join(chunk),
                    "prop": "revisions",
                    "rvprop": "content",
                    "rvslots": "main",
                    "format": "json",
                },
                headers=WIKT_HEADERS,
                timeout=6.0,
            )
            if resp.status_code != 200:
                continue
            pages = resp.json().get("query", {}).get("pages", {})
            for pdata in pages.values():
                title = (pdata.get("title") or "").lower()
                revs = pdata.get("revisions", [])
                if not revs:
                    continue
                content = revs[0].get("slots", {}).get("main", {}).get("*", "")
                m = re.search(r"\{\{по-слогам\|([^}]+)\}\}", content)
                if m:
                    raw = m.group(1).split("|наречие")[0].split("|прил")[0]
                    # Keep syllable parts clean
                    parts = [p for p in re.split(r"[|.]", raw) if p and "=" not in p]
                    stressed = "".join(parts).replace(COMBINING_GRAVE, "")
                    syllables = "-".join(parts).replace(COMBINING_GRAVE, "")
                    if COMBINING_ACUTE in stressed or "ё" in stressed:
                        results[title] = (stressed, syllables)
        except Exception:
            continue
    return results


def _project_lemma_stress(word_lower: str, stressed_lemma: str) -> Optional[str]:
    """If the acute stress in stressed_lemma falls inside the shared stem with word_lower, project it."""
    bare_lemma = strip_stress(stressed_lemma)
    # Find stressed character index in bare_lemma
    stress_char_idx = -1
    char_pos = -1
    for ch in stressed_lemma:
        if ch == COMBINING_ACUTE:
            stress_char_idx = char_pos
            break
        elif ch != COMBINING_GRAVE:
            char_pos += 1
    if stress_char_idx < 0:
        return None

    # Shared prefix length
    shared = 0
    for a, b in zip(word_lower, bare_lemma):
        if a == b:
            shared += 1
        else:
            break

    # Safe to transfer stem stress when shared stem includes the stressed vowel and at least 1 char or full stem
    if shared > stress_char_idx and shared >= max(3, len(bare_lemma) - 3):
        return (
            word_lower[: stress_char_idx + 1]
            + COMBINING_ACUTE
            + word_lower[stress_char_idx + 1 :]
        )
    return None


def get_russian_stress_map(words: List[str], allow_network: bool = True) -> Dict[str, Tuple[str, str]]:
    """
    Returns {word_lower: (stressed_word_lower, syllables)} for Russian words.
    """
    clean_words = list({strip_stress(w).lower() for w in words if re.search(r"[а-яА-ЯёЁ]", w)})
    result: Dict[str, Tuple[str, str]] = {}
    unresolved: List[str] = []

    for w in clean_words:
        if count_ru_vowels(w) <= 1 or "ё" in w:
            result[w] = (w, w)
        elif w in BUILTIN_RU_STRESS:
            result[w] = (BUILTIN_RU_STRESS[w], "")
        else:
            unresolved.append(w)

    if not unresolved:
        return result

    db_hits = _load_stress_from_db(unresolved)
    still_missing: List[str] = []
    for w in unresolved:
        if w in db_hits:
            result[w] = db_hits[w]
        else:
            still_missing.append(w)

    if not still_missing or not allow_network:
        return result

    # Also collect pymorphy3 lemmas and stripped compound roots for missing words
    lemma_for_word: Dict[str, str] = {}
    root_for_word: Dict[str, Tuple[str, str]] = {}  # w -> (prefix, rest_lemma)
    query_pool: List[str] = list(still_missing)

    for w in still_missing:
        lemma = w
        if MORPH:
            lemma = MORPH.parse(w)[0].normal_form.lower()
        lemma_for_word[w] = lemma
        if lemma not in result and lemma not in db_hits:
            query_pool.append(lemma)
        for pref in SCIENTIFIC_PREFIXES:
            if w.startswith(pref) and len(w) - len(pref) >= 4:
                rest = w[len(pref) :]
                rest_lemma = MORPH.parse(rest)[0].normal_form.lower() if MORPH else rest
                root_for_word[w] = (pref, rest_lemma)
                query_pool.append(rest_lemma)
                break

    wikt_hits = _fetch_wiktionary_stress_batch(query_pool)
    new_db_entries: Dict[str, Tuple[str, str]] = dict(wikt_hits)

    for w in still_missing:
        if w in wikt_hits:
            result[w] = wikt_hits[w]
            continue
        lemma = lemma_for_word.get(w, w)
        lemma_stressed = None
        if lemma in wikt_hits:
            lemma_stressed = wikt_hits[lemma][0]
        elif lemma in BUILTIN_RU_STRESS:
            lemma_stressed = BUILTIN_RU_STRESS[lemma]
        elif lemma in db_hits:
            lemma_stressed = db_hits[lemma][0]

        if lemma_stressed:
            proj = _project_lemma_stress(w, lemma_stressed)
            if proj:
                result[w] = (proj, "")
                new_db_entries[w] = (proj, "")
                continue

        if w in root_for_word:
            pref, rest_lemma = root_for_word[w]
            rest_stressed = wikt_hits.get(rest_lemma, (None, ""))[0] or BUILTIN_RU_STRESS.get(rest_lemma)
            if rest_stressed:
                rest_word = w[len(pref) :]
                proj_rest = _project_lemma_stress(rest_word, rest_stressed) or (
                    rest_stressed if rest_word == rest_lemma else None
                )
                if proj_rest:
                    combined = pref + proj_rest
                    result[w] = (combined, "")
                    new_db_entries[w] = (combined, "")

    _save_stress_to_db(new_db_entries)
    return result


def annotate_russian_text_stress(text: str) -> str:
    """Annotate acute stress marks onto a Russian paragraph/sentence."""
    tokens = re.findall(r"[а-яА-ЯёЁ]+|[^а-яА-ЯёЁ]+", text)
    ru_words = [t for t in tokens if re.match(r"^[а-яА-ЯёЁ]+$", t) and count_ru_vowels(t) >= 2]
    stress_map = get_russian_stress_map(ru_words, allow_network=True)
    out = []
    for tok in tokens:
        bare = strip_stress(tok)
        low = bare.lower()
        if low in stress_map and COMBINING_ACUTE in stress_map[low][0]:
            out.append(preserve_case(bare, stress_map[low][0]))
        else:
            out.append(tok)
    return "".join(out)


def _build_ru_paradigm(parse_obj: Any, surface_lower: str) -> Optional[Dict[str, Any]]:
    if not MORPH or not parse_obj:
        return None
    pos = parse_obj.tag.POS

    if pos == "NOUN":
        cases = ["nomn", "gent", "datv", "accs", "ablt", "loct"]
        rows = []
        for c in cases:
            c_zh, c_ru, c_q = CASE_MAP_RU[c]
            sing_inf = parse_obj.inflect({"sing", c})
            plur_inf = parse_obj.inflect({"plur", c})
            sw = sing_inf.word if sing_inf else "—"
            pw = plur_inf.word if plur_inf else "—"
            rows.append({
                "label": f"{c_ru} {c_zh}",
                "hint": c_q,
                "cells": [
                    {"text": sw, "active": sw == surface_lower},
                    {"text": pw, "active": pw == surface_lower},
                ],
            })
        return {
            "title": "俄语名词六格变化表 (Склонение существительного)",
            "headers": ["格 (Падеж)", "单数 (Ед.ч.)", "复数 (Мн.ч.)"],
            "rows": rows,
        }

    if pos in ("ADJF", "PRTF"):
        # Inflect from base adjective/participle form
        cases = ["nomn", "gent", "datv", "accs", "ablt", "loct"]
        rows = []
        for c in cases:
            c_zh, c_ru, _ = CASE_MAP_RU[c]
            cells = []
            for g_set in [{"sing", "masc", c}, {"sing", "femn", c}, {"sing", "neut", c}, {"plur", c}]:
                # Avoid animacy conflict on accusative
                inf = parse_obj.inflect(g_set)
                if not inf and c == "accs":
                    inf = parse_obj.inflect(g_set | {"inan"})
                w = inf.word if inf else "—"
                cells.append({"text": w, "active": w == surface_lower})
            rows.append({
                "label": f"{c_ru} {c_zh.split('·')[-1]}",
                "hint": "",
                "cells": cells,
            })
        title = (
            "形动词变格表 (Склонение причастия)"
            if pos == "PRTF"
            else "形容词变格表 (Склонение прилагательного)"
        )
        return {
            "title": title,
            "headers": ["格", "阳性 (м.)", "阴性 (ж.)", "中性 (ср.)", "复数 (мн.)"],
            "rows": rows,
        }

    if pos in ("VERB", "INFN", "GRND"):
        # Find infinitive or personal verb lexeme
        inf_parse = parse_obj
        for form in parse_obj.lexeme:
            if form.tag.POS == "VERB":
                inf_parse = form
                break
        tense_target = "futr" if "perf" in parse_obj.tag else "pres"
        tense_label = "将来时变位 (СВ)" if tense_target == "futr" else "现在时变位 (НСВ)"
        persons = [
            ("я (1人称单)", {"1per", "sing", tense_target}),
            ("ты (2人称单)", {"2per", "sing", tense_target}),
            ("он/она́ (3人称单)", {"3per", "sing", tense_target}),
            ("мы (1人称复)", {"1per", "plur", tense_target}),
            ("вы (2人称复)", {"2per", "plur", tense_target}),
            ("они́ (3人称复)", {"3per", "plur", tense_target}),
        ]
        past_forms = [
            ("过去·阳性 (он)", {"past", "masc", "sing"}),
            ("过去·阴性 (она́)", {"past", "femn", "sing"}),
            ("过去·中性 (оно́)", {"past", "neut", "sing"}),
            ("过去·复数 (они́)", {"past", "plur"}),
        ]
        rows = []
        for idx in range(6):
            p_label, p_tags = persons[idx]
            p_inf = inf_parse.inflect(p_tags)
            pw = p_inf.word if p_inf else "—"
            past_cell = {"text": "", "active": False}
            if idx < len(past_forms):
                past_label, past_tags = past_forms[idx]
                past_inf = inf_parse.inflect(past_tags)
                past_w = f"{past_label}: {past_inf.word}" if past_inf else "—"
                past_cell = {"text": past_w, "active": bool(past_inf and past_inf.word == surface_lower)}
            rows.append({
                "label": p_label,
                "hint": "",
                "cells": [
                    {"text": pw, "active": pw == surface_lower},
                    past_cell,
                ],
            })
        return {
            "title": f"俄语动词变位表 ({tense_label} + 过去时)",
            "headers": ["人称 (Лицо)", tense_label, "过去时 (Прош.вр.)"],
            "rows": rows,
        }

    return None


def analyze_russian_word(word: str) -> Dict[str, Any]:
    bare = strip_stress(word).strip(".,;:!?«»\"'()[]{}—–-")
    low = bare.lower()
    if not MORPH or not low:
        return {
            "word": bare,
            "lemma": low,
            "lang": "ru",
            "stressed_word": bare,
            "stressed_lemma": low,
            "syllables": "",
            "pos_zh": "俄语词汇",
            "pos_ru": "Слово",
            "tags": [],
            "academic_tip": "",
            "alt_parses": [],
            "paradigm": None,
        }

    parses = MORPH.parse(low)
    best = parses[0]
    lemma = best.normal_form
    # For participles, also find the nominative singular masculine participle form
    participle_base = None
    if best.tag.POS in ("PRTF", "PRTS"):
        nom_m = best.inflect({"PRTF", "sing", "masc", "nomn"}) if best.tag.POS == "PRTF" else None
        if nom_m:
            participle_base = nom_m.word

    stress_targets = [low, lemma] + ([participle_base] if participle_base else [])
    smap = get_russian_stress_map(stress_targets, allow_network=True)
    stressed_surface = preserve_case(bare, smap.get(low, (low, ""))[0])
    stressed_lemma, syllables = smap.get(lemma, (lemma, ""))
    if not syllables and lemma in smap:
        syllables = smap[lemma][1]

    pos_code = best.tag.POS or ""
    pos_zh, pos_ru = POS_MAP_RU.get(pos_code, ("词汇", pos_code))

    tags: List[str] = [f"{pos_zh} ({pos_ru})"]
    if best.tag.aspect in ASPECT_MAP_RU:
        tags.append(ASPECT_MAP_RU[best.tag.aspect])
    if best.tag.voice in VOICE_MAP_RU:
        tags.append(VOICE_MAP_RU[best.tag.voice])
    if best.tag.tense in TENSE_MAP_RU:
        tags.append(TENSE_MAP_RU[best.tag.tense])
    if best.tag.gender in GENDER_MAP_RU:
        tags.append(GENDER_MAP_RU[best.tag.gender])
    if best.tag.number in NUMBER_MAP_RU:
        tags.append(NUMBER_MAP_RU[best.tag.number])
    if best.tag.case in CASE_MAP_RU:
        c_zh, c_ru, c_q = CASE_MAP_RU[best.tag.case]
        tags.append(f"{c_zh} ({c_ru})")

    # Build intelligent academic Russian tip!
    tips: List[str] = []
    if pos_code == "PRTF":
        v_aspect = "完成体" if "perf" in best.tag else "未完成体"
        v_voice = "被动" if "pssv" in best.tag else "主动"
        part_str = f"（形动词原形：{smap.get(participle_base, (participle_base,''))[0]}）" if participle_base else ""
        tips.append(
            f"【学术高频·形动词】该词是由{v_aspect}动词「{stressed_lemma}」派生的{v_voice}形动词{part_str}。"
            f"俄语论文常用形动词短语作后置定语（相当于英语 which/that 从句或过去分词短语），翻译成中文时通常提到被修饰名词之前译为「……的」。"
        )
    elif pos_code == "PRTS":
        tips.append(
            f"【学术高频·短尾被动形动词】派生自动词「{stressed_lemma}」，在俄语论文中常充当无人称或被动句谓语（如 показано「已证明」、установлено「已确立」）。"
        )
    elif pos_code == "GRND":
        tips.append(
            f"【学术高频·副动词】派生自动词「{stressed_lemma}」，在句中表示伴随动作、方式或原因状语（相当于英语 -ing 分词状语），可译为「通过…… / 在……的同时」。"
        )
    elif low.endswith(("ся", "сь")) and pos_code in ("VERB", "INFN"):
        tips.append(
            "【科技俄语·带 -ся 被动/自复动词】俄语学术论文极少用第一人称「我们」，常使用未完成体动词加 -ся 构成被动表述（如 рассматривается「本文探讨 / 被考察」）。"
        )
    elif best.tag.case == "gent":
        tips.append(
            "【学术属格链】第二格（Родительный падеж）在俄语论文中最常用于「名词 + 二格名词」的定语修饰链（相当于英语 of 搭配，中文需逆序译为「……的……」）。"
        )
    elif best.tag.case == "ablt":
        tips.append(
            "【第五格·工具格】在学术语篇中常表示研究手段/工具（「通过……方法」）、被动结构的施事者（「由……提出」），或与 являться / служить 搭配作表语。"
        )

    # Secondary possible parses (crucial for homonymous case endings like -ия, -ых)
    alt_parses = []
    seen_sigs = {"|".join(tags)}
    for p in parses[1:4]:
        p_pos = POS_MAP_RU.get(p.tag.POS or "", ("词汇", ""))[0]
        p_case = CASE_MAP_RU.get(p.tag.case or "", ("", "", ""))[0]
        p_num = NUMBER_MAP_RU.get(p.tag.number or "", "")
        sig = " · ".join(x for x in [p_pos, p_num, p_case] if x)
        if sig and sig not in seen_sigs:
            seen_sigs.add(sig)
            alt_parses.append({"lemma": p.normal_form, "summary": sig})

    return {
        "word": bare,
        "lemma": lemma,
        "participle_base": participle_base,
        "lang": "ru",
        "stressed_word": stressed_surface,
        "stressed_lemma": stressed_lemma,
        "syllables": syllables,
        "pos_zh": pos_zh,
        "pos_ru": pos_ru,
        "pos_summary": " · ".join(tags[:4]),
        "tags": tags,
        "is_academic": lemma in RU_ACADEMIC_LEMMAS,
        "academic_tip": " ".join(tips),
        "alt_parses": alt_parses,
        "paradigm": _build_ru_paradigm(best, low),
    }


def english_lemmatize(word: str) -> str:
    low = word.lower().strip(".,;:!?\"'()[]{}—–-")
    if low in EN_IRREGULAR_LEMMAS:
        return EN_IRREGULAR_LEMMAS[low]
    if low in EN_ACADEMIC_WORDS or len(low) <= 3:
        return low
    if low.endswith("ies") and len(low) > 4:
        return low[:-3] + "y"
    if low.endswith("ves") and len(low) > 4:
        return low[:-3] + "f"
    if low.endswith("ing") and len(low) > 5:
        stem = low[:-3]
        if len(stem) >= 3 and stem[-1] == stem[-2]:
            return stem[:-1]
        if stem + "e" in EN_ACADEMIC_WORDS:
            return stem + "e"
        return stem
    if low.endswith("ed") and len(low) > 4:
        stem = low[:-2]
        if stem.endswith("i"):
            return stem[:-1] + "y"
        if len(stem) >= 3 and stem[-1] == stem[-2]:
            return stem[:-1]
        if stem + "e" in EN_ACADEMIC_WORDS or stem.endswith(("at", "iz", "is", "ut", "ud", "uc", "ir")):
            return stem + "e"
        return stem
    if low.endswith("es") and len(low) > 4 and low[-3] in "sxz" or low.endswith(("ches", "shes")):
        return low[:-2]
    if low.endswith("s") and not low.endswith(("ss", "us", "is", "os")) and len(low) > 3:
        return low[:-1]
    return low


EN_PREFIX_NOTES = {
    "inter": "inter-（在……之间、相互）",
    "intra": "intra-（在……内部）",
    "trans": "trans-（跨越、转换）",
    "sub": "sub-（在下、子级）",
    "super": "super-（超、在上）",
    "hyper": "hyper-（超、高维）",
    "multi": "multi-（多重的）",
    "cross": "cross-（跨领域的）",
    "hetero": "hetero-（异质的、不同的）",
    "homo": "homo-（同质的）",
    "auto": "auto-（自动、自身）",
    "semi": "semi-（半）",
    "pre": "pre-（预先、前）",
    "post": "post-（后置、在……之后）",
    "co": "co-（共同、协同）",
    "re": "re-（重新、再次）",
    "de": "de-（去除、逆向）",
    "dis": "dis-（否定、分离）",
    "un": "un-（否定、未）",
    "non": "non-（非）",
}

EN_SUFFIX_NOTES = {
    "tion": "-tion（名词后缀：过程、结果或状态）",
    "sion": "-sion（名词后缀：行为或状态）",
    "ment": "-ment（名词后缀：行为或产物）",
    "ity": "-ity（抽象名词后缀：性质、程度）",
    "ness": "-ness（名词后缀：性质、状态）",
    "ance": "-ance（名词后缀：状态或性质）",
    "ence": "-ence（名词后缀：性质或过程）",
    "ology": "-ology（学科、方法论体系）",
    "logical": "-logical（形容词后缀：……学理的）",
    "ization": "-ization（名词后缀：……化过程）",
    "ize": "-ize（动词后缀：使……化）",
    "ify": "-ify（动词后缀：使成为）",
    "ous": "-ous（形容词后缀：具有……特性的）",
    "ive": "-ive（形容词后缀：具有……倾向/功能的）",
    "al": "-al（形容词后缀：与……相关的）",
    "able": "-able（形容词后缀：可被……的）",
    "ible": "-ible（形容词后缀：可……的）",
    "ly": "-ly（副词后缀：以……方式）",
}


def analyze_english_word(word: str) -> Dict[str, Any]:
    clean = word.strip(".,;:!?«»\"'()[]{}—–-")
    low = clean.lower()
    lemma = english_lemmatize(low)
    is_awl = low in EN_ACADEMIC_WORDS or lemma in EN_ACADEMIC_WORDS

    affix_notes = []
    for p, note in EN_PREFIX_NOTES.items():
        if low.startswith(p) and len(low) - len(p) >= 4:
            affix_notes.append(note)
            break
    for s, note in EN_SUFFIX_NOTES.items():
        if low.endswith(s) and len(low) - len(s) >= 3:
            affix_notes.append(note)
            break

    # Fetch IPA + English definitions from DictionaryAPI
    ipa = ""
    en_defs: List[Dict[str, str]] = []
    pos_list: List[str] = []
    for candidate in dict.fromkeys([low, lemma]):
        try:
            r = httpx.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{candidate}", timeout=4.0)
            if r.status_code == 200:
                data = r.json()[0]
                ipa = data.get("phonetic") or ""
                if not ipa:
                    for ph in data.get("phonetics", []):
                        if ph.get("text"):
                            ipa = ph["text"]
                            break
                for m in data.get("meanings", [])[:3]:
                    pos = m.get("partOfSpeech", "")
                    if pos:
                        pos_list.append(pos)
                    for d in m.get("definitions", [])[:2]:
                        en_defs.append({
                            "pos": pos,
                            "definition": d.get("definition", ""),
                            "example": d.get("example", ""),
                        })
                break
        except Exception:
            continue

    tags = []
    if pos_list:
        tags.extend(dict.fromkeys(pos_list))
    if is_awl:
        tags.append("AWL 学术核心词汇")
    if lemma != low:
        tags.append(f"原形: {lemma}")

    tip_parts = []
    if is_awl:
        tip_parts.append("【AWL 学术高频核心词】该词属于国际学术论文高频核心词表（Academic Word List），建议重点掌握其搭配与派生词形。")
    if affix_notes:
        tip_parts.append("构词拆解：" + " + ".join(affix_notes) + "。")

    return {
        "word": clean,
        "lemma": lemma,
        "lang": "en",
        "stressed_word": clean,
        "stressed_lemma": lemma,
        "ipa": ipa,
        "pos_summary": " · ".join(tags) if tags else "英语词汇",
        "tags": tags,
        "is_academic": is_awl,
        "affix_notes": affix_notes,
        "en_definitions": en_defs[:4],
        "academic_tip": " ".join(tip_parts),
        "paradigm": None,
    }


def split_into_sentences(text: str) -> List[str]:
    """Academic-aware sentence splitter preserving abbreviations like e.g., i.e., Fig., Eq., т.е., т.д., др., г."""
    if not text.strip():
        return []
    protected = text
    abbrevs = [
        "e.g.", "i.e.", "et al.", "Fig.", "fig.", "Eq.", "eq.", "Ref.", "Dr.", "Prof.", "vs.", "cf.",
        "т.е.", "т. е.", "т.д.", "т. д.", "т.п.", "др.", "пр.", "рис.", "Рис.", "табл.", "Табл.", "гл.", "см.",
    ]
    placeholders = {}
    for idx, ab in enumerate(abbrevs):
        ph = f"__ABBR{idx}__"
        if ab in protected:
            protected = protected.replace(ab, ph)
            placeholders[ph] = ab

    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZА-ЯЁ0-9«\"(\[])", protected)
    out = []
    for p in parts:
        for ph, ab in placeholders.items():
            p = p.replace(ph, ab)
        p = p.strip()
        if p:
            out.append(p)
    return out if out else [text.strip()]


def analyze_sentence_structure(sentence: str, lang: Optional[str] = None) -> Dict[str, Any]:
    """
    Rule + morphological structural chunker for Russian & English academic long sentences.
    Works 100% locally & instantaneously!
    """
    lang = lang or detect_lang(sentence)
    tokens_out: List[Dict[str, Any]] = []
    clauses: List[Dict[str, str]] = []
    detected_phrases: List[Dict[str, str]] = []

    low_sent = strip_stress(sentence).lower()

    if lang == "ru":
        for phrase, gloss in RU_ACADEMIC_PHRASES:
            if phrase in low_sent:
                detected_phrases.append({"phrase": phrase, "meaning": gloss})

        # Token-level morphological ribbon
        words = re.findall(r"[а-яА-ЯёЁ-]+|[0-9]+(?:\.[0-9]+)?|[^\sа-яА-ЯёЁ0-9]+", sentence)
        ru_list = [w for w in words if re.match(r"^[а-яА-ЯёЁ]+$", strip_stress(w))]
        smap = get_russian_stress_map(ru_list, allow_network=True)

        for w in words:
            bare = strip_stress(w)
            if re.match(r"^[а-яА-ЯёЁ-]+$", bare) and MORPH:
                p = MORPH.parse(bare.lower())[0]
                pos = p.tag.POS or ""
                role = "other"
                badge = POS_MAP_RU.get(pos, ("词", ""))[0]
                if pos == "NOUN":
                    c_info = CASE_MAP_RU.get(p.tag.case or "", ("", "", ""))
                    badge = f"名·{c_info[1] or ''}"
                    role = "subj" if p.tag.case == "nomn" else ("genitive" if p.tag.case == "gent" else "noun")
                elif pos in ("VERB", "INFN", "PRTS", "PRED"):
                    role = "verb"
                    badge = "谓语动词" if pos == "VERB" else POS_MAP_RU.get(pos, ("动词", ""))[0]
                elif pos in ("PRTF", "GRND"):
                    role = "participle"
                    badge = "形动词" if pos == "PRTF" else "副动词"
                elif pos == "ADJF":
                    c_info = CASE_MAP_RU.get(p.tag.case or "", ("", "", ""))
                    role = "adj"
                    badge = f"形·{c_info[1] or ''}"
                elif pos in ("PREP", "CONJ"):
                    role = "connector"
                    badge = "前置词" if pos == "PREP" else "连词"

                sw = preserve_case(bare, smap.get(bare.lower(), (bare.lower(), ""))[0])
                tokens_out.append({
                    "text": w,
                    "stressed": sw,
                    "lemma": p.normal_form,
                    "role": role,
                    "badge": badge,
                    "is_word": True,
                })
            else:
                tokens_out.append({"text": w, "stressed": w, "lemma": "", "role": "punct", "badge": "", "is_word": False})

        # Clause chunking on commas & Russian subordinators / participial turns
        raw_chunks = [c.strip() for c in re.split(r",\s*(?=котор|что\b|чтобы\b|где\b|поскольку|так как|при этом|тогда как|[а-яё]+(?:ющий|ающий|ящий|ущий|вший|емый|имый|нный|тый)[а-яё]*\b|[а-яё]+(?:я|в|вши)\b)|;\s*", sentence, flags=re.IGNORECASE) if c.strip()]
        if len(raw_chunks) == 1 and "," in sentence:
            raw_chunks = [c.strip() for c in sentence.split(",") if c.strip()]

        for idx, ch in enumerate(raw_chunks):
            ch_low = strip_stress(ch).lower()
            label = "主句/核心陈述" if idx == 0 else "补充/并列分句"
            note = "关注第一格（主语）与变位动词/短尾形动词（谓语）构成的主干。"
            if re.match(r"^(в |на |при |для |по |с |за счёт|согласно|таким образом|однако)", ch_low) and idx == 0 and len(raw_chunks) > 1:
                label = "前置学术状语/语境框"
                note = "句首前置词短语或逻辑连接语，限定研究范围、条件或承上启下。"
            elif re.match(r"^(котор|где|куда|откуда)", ch_low):
                label = "который 定语从句"
                note = "关系代词 который 的性数与先行词一致，格由其在从句中的语法功能决定。"
            elif re.match(r"^(что\b|чтобы\b|поскольку|так как|если)", ch_low):
                label = "从属子句（宾语/原因/目的）"
                note = "由从属连词引导的展开说明从句。"
            elif MORPH:
                first_w = re.findall(r"[а-яА-ЯёЁ]+", ch_low)
                if first_w:
                    fp = MORPH.parse(first_w[0])[0]
                    if fp.tag.POS == "PRTF":
                        label = "形动词后置定语短语 (Причастный оборот)"
                        note = f"以形动词「{first_w[0]}」(← {fp.normal_form}) 引导，修饰前面的名词，汉译时建议前置译为「……的」或拆分为独立分句。"
                    elif fp.tag.POS == "GRND":
                        label = "副动词伴随/方式状语 (Деепричастный оборот)"
                        note = f"以副动词「{first_w[0]}」(← {fp.normal_form}) 引导，说明主句动作的方式、伴随动作或原因。"
            clauses.append({"text": ch, "label": label, "note": note})

    else:
        for phrase, gloss in EN_ACADEMIC_PHRASES:
            if phrase in low_sent:
                detected_phrases.append({"phrase": phrase, "meaning": gloss})

        words = re.findall(r"[a-zA-Z]+(?:-[a-zA-Z]+)*|[0-9]+(?:\.[0-9]+)?|[^\sa-zA-Z0-9]+", sentence)
        connectors = {
            "which", "that", "where", "whereas", "whereby", "while", "although", "though",
            "because", "since", "however", "therefore", "thus", "moreover", "furthermore", "despite",
        }
        preps = {"in", "on", "at", "of", "for", "with", "by", "from", "to", "into", "across", "between", "through", "under", "within", "without"}
        aux_verbs = {"is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "can", "could", "may", "might", "will", "would", "should", "must"}

        for w in words:
            if re.match(r"^[a-zA-Z]", w):
                lw = w.lower()
                lem = english_lemmatize(lw)
                role = "noun"
                badge = "词汇"
                if lw in connectors:
                    role = "connector"
                    badge = "从句/逻辑词"
                elif lw in preps:
                    role = "connector"
                    badge = "介词"
                elif lw in aux_verbs:
                    role = "verb"
                    badge = "助动词/系词"
                elif lw.endswith("ing") and len(lw) > 4:
                    role = "participle"
                    badge = "-ing 分词/动名词"
                elif lw.endswith("ed") and len(lw) > 4:
                    role = "verb"
                    badge = "-ed 过去/被动"
                elif lw.endswith("ly") and len(lw) > 4:
                    role = "adj"
                    badge = "副词"
                elif lem in EN_ACADEMIC_WORDS or lw in EN_ACADEMIC_WORDS:
                    role = "subj"
                    badge = "AWL 学术词"

                tokens_out.append({
                    "text": w,
                    "stressed": w,
                    "lemma": lem,
                    "role": role,
                    "badge": badge,
                    "is_word": True,
                })
            else:
                tokens_out.append({"text": w, "stressed": w, "lemma": "", "role": "punct", "badge": "", "is_word": False})

        raw_chunks = [c.strip() for c in re.split(r",\s*(?=which\b|where\b|whereas\b|whereby\b|while\b|although\b|resulting\b|allowing\b|enabling\b|suggesting\b|demonstrating\b|characterized\b|based\b)|;\s*|\s+(?=that\s+[a-z]+\s+[a-z]+)", sentence, flags=re.IGNORECASE) if c.strip()]
        if len(raw_chunks) == 1 and "," in sentence:
            raw_chunks = [c.strip() for c in sentence.split(",") if c.strip()]

        for idx, ch in enumerate(raw_chunks):
            cl = ch.lower()
            label = "主干核心分句 (Main Clause)" if idx == 0 else "扩展修饰成分"
            note = "提取主语核心词与谓语动词，忽略介词 of 短语链干扰。"
            if idx == 0 and len(raw_chunks) > 1 and re.match(r"^(in |on |with |by |despite |although |while |to |for |based on)", cl):
                label = "句首状语/背景限定框"
                note = "句首介词短语或让步/目的状语，交代研究前提或对比背景。"
            elif re.match(r"^(which|where|whereby|that)\b", cl):
                label = "定语/关系从句 (Relative Clause)"
                note = "后置修饰前面的概念或整个主句命题，汉译时长定语可独立成句。"
            elif re.match(r"^[a-z]+ing\b", cl):
                label = "现在分词结果/伴随状语 (-ing Clause)"
                note = "英语论文常用逗号 + -ing 分词补充自然结果或伴随机制（可译为「从而…… / 并……」）。"
            elif re.match(r"^(characterized|based|driven|motivated|proposed|compared)\b", cl):
                label = "过去分词后置修饰 (-ed Clause)"
                note = "表被动特征或研究依据的后置分词结构。"
            clauses.append({"text": ch, "label": label, "note": note})

    return {
        "lang": lang,
        "tokens": tokens_out,
        "clauses": clauses,
        "academic_phrases": detected_phrases,
    }
