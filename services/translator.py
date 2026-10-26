import hashlib
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from .db import get_conn, get_settings
from .nlp_engine import (
    analyze_english_word,
    analyze_russian_word,
    analyze_sentence_structure,
    annotate_russian_text_stress,
    detect_lang,
    strip_stress,
)


def _cache_key(text: str, sl: str, tl: str, engine: str) -> str:
    raw = f"{engine}|{sl}|{tl}|{text.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_cached_translation(key: str) -> Optional[str]:
    conn = get_conn()
    row = conn.execute(
        "SELECT translated_text FROM translation_cache WHERE cache_key = ?", (key,)
    ).fetchone()
    conn.close()
    return row["translated_text"] if row else None


def _save_cached_translation(key: str, sl: str, tl: str, text: str, engine: str = "gtx") -> None:
    if not text.strip():
        return
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO translation_cache (cache_key, src_lang, tgt_lang, translated_text, engine, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (key, sl, tl, text, engine, time.time()),
    )
    conn.commit()
    conn.close()


def gtx_translate(text: str, sl: str = "auto", tl: str = "zh-CN") -> Dict[str, Any]:
    """
    Free, fast translation + dictionary + transliteration via Google GTX endpoint.
    """
    clean = strip_stress(text).strip()
    if not clean:
        return {"text": "", "translit": "", "dict": []}

    try:
        resp = httpx.get(
            "https://translate.googleapis.com/translate_a/single",
            params=[
                ("client", "gtx"),
                ("sl", sl),
                ("tl", tl),
                ("dj", "1"),
                ("dt", "t"),
                ("dt", "bd"),
                ("dt", "rm"),
                ("q", clean),
            ],
            timeout=10.0,
        )
        if resp.status_code != 200:
            return {"text": "", "translit": "", "dict": []}
        data = resp.json()
        sentences = data.get("sentences", [])
        trans_parts = [s.get("trans", "") for s in sentences if "trans" in s]
        translit = ""
        for s in sentences:
            if s.get("src_translit"):
                translit = s["src_translit"]
                break
        dict_entries = []
        for d in data.get("dict", []) or []:
            dict_entries.append({
                "pos": d.get("pos", ""),
                "terms": d.get("terms", [])[:8],
            })
        return {
            "text": "".join(trans_parts).strip(),
            "translit": translit,
            "dict": dict_entries,
            "src": data.get("src", sl),
        }
    except Exception:
        return {"text": "", "translit": "", "dict": []}


def youdao_chinese_gloss(word: str) -> List[str]:
    """Fetch rich Chinese concise glosses from Youdao suggest endpoint."""
    try:
        r = httpx.get(
            "https://dict.youdao.com/suggest",
            params={"num": 3, "doctype": "json", "q": word},
            timeout=4.0,
        )
        if r.status_code == 200:
            entries = r.json().get("data", {}).get("entries", []) or []
            out = []
            for e in entries:
                if (e.get("entry") or "").lower() == word.lower() and e.get("explain"):
                    out.append(e["explain"])
            if not out and entries and entries[0].get("explain"):
                out.append(f"{entries[0].get('entry')}: {entries[0].get('explain')}")
            return out
    except Exception:
        pass
    return []


def _call_llm_chat(messages: List[Dict[str, str]], settings: Optional[Dict[str, Any]] = None, timeout: float = 28.0) -> str:
    cfg = settings or get_settings()
    base_url = (cfg.get("llm_base_url") or "").rstrip("/")
    api_key = (cfg.get("llm_api_key") or "").strip()
    model = (cfg.get("llm_model") or "deepseek-chat").strip()

    if not base_url:
        raise ValueError("未配置大模型 API Base URL")

    url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.25,
    }
    resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"LLM 接口返回错误 ({resp.status_code}): {resp.text[:240]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def test_llm_connection(cfg: Dict[str, Any]) -> Dict[str, Any]:
    try:
        reply = _call_llm_chat(
            [
                {"role": "system", "content": "You are a concise assistant."},
                {"role": "user", "content": "请用中文回复「连接成功」四个字。"},
            ],
            settings=cfg,
            timeout=12.0,
        )
        return {"ok": True, "reply": reply}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def translate_text(
    text: str,
    src_lang: str = "auto",
    tgt_lang: str = "zh-CN",
    prefer_llm: Optional[bool] = None,
    force_refresh: bool = False,
    owner_id: str = "default",
) -> Dict[str, Any]:
    clean = strip_stress(text).strip()
    if not clean:
        return {"translated": "", "engine": "none"}

    if src_lang == "auto":
        src_lang = detect_lang(clean)

    cfg = get_settings(owner_id=owner_id, mask_secret=False)
    use_llm = prefer_llm if prefer_llm is not None else bool(cfg.get("llm_enabled") and (cfg.get("llm_api_key") or "11434" in str(cfg.get("llm_base_url"))))
    engine_tag = f"llm:{owner_id}:{cfg.get('llm_model')}" if use_llm else "gtx"

    ckey = _cache_key(clean, src_lang, tgt_lang, engine_tag)
    if not force_refresh:
        cached = _get_cached_translation(ckey)
        if cached:
            return {"translated": cached, "engine": engine_tag, "cached": True}

    if use_llm and tgt_lang.startswith("zh"):
        try:
            lang_name = "俄语" if src_lang == "ru" else "英语"
            ans = _call_llm_chat(
                [
                    {
                        "role": "system",
                        "content": (
                            f"你是一位精通{lang_name}与中文的资深学术论文翻译专家。"
                            "请将用户提供的学术段落准确、严谨、流畅地翻译为学术中文。"
                            "保留专业术语准确性，理顺俄语形动词短语/属格链或英语后置定语从句语序。只输出译文正文，不要额外寒暄。"
                        ),
                    },
                    {"role": "user", "content": clean},
                ],
                settings=cfg,
            )
            if ans:
                _save_cached_translation(ckey, src_lang, tgt_lang, ans, engine=engine_tag)
                return {"translated": ans, "engine": engine_tag, "cached": False}
        except Exception:
            # Fallback gracefully to GTX
            pass

    res = gtx_translate(clean, sl=src_lang, tl=tgt_lang)
    translated = res.get("text", "")
    if translated:
        _save_cached_translation(_cache_key(clean, src_lang, tgt_lang, "gtx"), src_lang, tgt_lang, translated, engine="gtx")
    return {"translated": translated, "engine": "gtx", "cached": False}


def lookup_word_trilingual(word: str, lang_hint: Optional[str] = None, context_sentence: str = "") -> Dict[str, Any]:
    """
    Comprehensive word inspection bridging Russian <-> English <-> Chinese!
    """
    clean = strip_stress(word).strip(".,;:!?«»\"'()[]{}—–-")
    lang = lang_hint if lang_hint in ("ru", "en") else detect_lang(clean)

    if lang == "ru":
        morph_info = analyze_russian_word(clean)
        lemma = morph_info["lemma"]

        # 1. RU -> ZH on lemma and surface word
        zh_lemma_res = gtx_translate(lemma, sl="ru", tl="zh-CN")
        zh_surf_res = gtx_translate(clean, sl="ru", tl="zh-CN") if clean.lower() != lemma.lower() else zh_lemma_res

        # 2. RU -> EN dictionary (gives rich multi-POS academic English synonyms!)
        en_bridge_res = gtx_translate(lemma, sl="ru", tl="en")
        en_terms: List[str] = []
        if en_bridge_res.get("text"):
            en_terms.append(en_bridge_res["text"])

        # For reflexive -ся/-сь verbs, also inspect the active verb base for accurate academic meanings
        active_base = ""
        if lemma.endswith("ться"):
            active_base = lemma[:-2]
        elif lemma.endswith("тись") or lemma.endswith("чься"):
            active_base = lemma[:-2]

        if active_base:
            active_en = gtx_translate(active_base, sl="ru", tl="en")
            for d in active_en.get("dict", []):
                for t in d.get("terms", [])[:4]:
                    if " " not in t:
                        en_terms.append(f"(主动: {t})")
        else:
            for d in en_bridge_res.get("dict", []):
                en_terms.extend(d.get("terms", [])[:5])

        en_terms = list(dict.fromkeys([t for t in en_terms if t]))[:6]

        # 3. Enrich Chinese glosses via single-word English primary equivalent in Youdao + GTX dict
        zh_glosses: List[str] = []
        for d in zh_lemma_res.get("dict", []):
            pos = d.get("pos", "")
            terms = "；".join(d.get("terms", [])[:5])
            if terms:
                zh_glosses.append(f"{pos}: {terms}" if pos else terms)

        yd_probe = (en_bridge_res.get("text") or "").strip()
        if " " in yd_probe and active_base:
            yd_probe = gtx_translate(active_base, sl="ru", tl="en").get("text", "").strip()
        if yd_probe and " " not in yd_probe:
            yd = youdao_chinese_gloss(yd_probe)
            for g in yd[:1]:
                zh_glosses.append(f"拓展释义：{g}")

        primary_zh = zh_lemma_res.get("text") or ""
        surf_zh = zh_surf_res.get("text") or ""
        if surf_zh and surf_zh != primary_zh:
            meaning_zh = f"{primary_zh}（当前词形直译：{surf_zh}）"
        else:
            meaning_zh = primary_zh
        if zh_glosses:
            meaning_zh = meaning_zh + " ｜ " + "；".join(zh_glosses[:2])

        return {
            **morph_info,
            "translit": zh_surf_res.get("translit") or zh_lemma_res.get("translit") or "",
            "meaning_zh": meaning_zh.strip(" ｜"),
            "primary_zh": primary_zh,
            "surface_zh": surf_zh,
            "bridge_lang": "en",
            "bridge_label": "🇬🇧 对应英语学术词 (RU → EN 互学)",
            "bridge_meaning": ", ".join(en_terms) if en_terms else en_bridge_res.get("text", ""),
            "bridge_terms": en_terms,
            "context_sentence": context_sentence,
        }

    else:
        morph_info = analyze_english_word(clean)
        lemma = morph_info["lemma"]

        # 1. EN -> ZH via Youdao + GTX
        yd_glosses = youdao_chinese_gloss(lemma) or youdao_chinese_gloss(clean)
        zh_res = gtx_translate(lemma, sl="en", tl="zh-CN")
        zh_terms = []
        for d in zh_res.get("dict", []):
            pos = d.get("pos", "")
            t = "、".join(d.get("terms", [])[:5])
            if t:
                zh_terms.append(f"{pos}. {t}" if pos else t)

        if yd_glosses:
            meaning_zh = "；".join(yd_glosses[:2])
        elif zh_terms:
            meaning_zh = "；".join(zh_terms[:2])
        else:
            meaning_zh = zh_res.get("text", "")

        # 2. EN -> RU bridge with automatic Russian stress marks!
        ru_res = gtx_translate(lemma, sl="en", tl="ru")
        ru_candidates = []
        for d in ru_res.get("dict", []):
            ru_candidates.extend(d.get("terms", [])[:4])
        if not ru_candidates and ru_res.get("text"):
            ru_candidates = [ru_res["text"]]
        ru_candidates = list(dict.fromkeys(ru_candidates))[:5]
        stressed_ru_terms = [annotate_russian_text_stress(w) for w in ru_candidates if w]

        return {
            **morph_info,
            "translit": morph_info.get("ipa", ""),
            "meaning_zh": meaning_zh,
            "primary_zh": zh_res.get("text", ""),
            "surface_zh": "",
            "bridge_lang": "ru",
            "bridge_label": "🇷🇺 对应俄语学术词 (EN → RU 互学·含重音)",
            "bridge_meaning": " · ".join(stressed_ru_terms),
            "bridge_terms": stressed_ru_terms,
            "context_sentence": context_sentence,
        }


def analyze_and_explain_sentence(
    sentence: str,
    lang: Optional[str] = None,
    use_llm: Optional[bool] = None,
    user_question: str = "",
    owner_id: str = "default",
) -> Dict[str, Any]:
    """
    Full sentence coaching:
    1. Chinese academic translation
    2. Cross-language academic translation (RU -> EN or EN -> RU with stress!)
    3. Local deterministic syntactic chunking & token POS/Case ribbon
    4. Optional LLM deep syntax & grammar commentary (or rich built-in heuristic report if no LLM key)
    """
    clean = strip_stress(sentence).strip()
    lang = lang if lang in ("ru", "en") else detect_lang(clean)

    # 1. Chinese translation
    zh_trans = translate_text(clean, src_lang=lang, tgt_lang="zh-CN", prefer_llm=use_llm, owner_id=owner_id)["translated"]

    # 2. Cross-language bridge translation (RU -> EN or EN -> RU)
    if lang == "ru":
        cross_raw = translate_text(clean, src_lang="ru", tgt_lang="en", prefer_llm=False, owner_id=owner_id)["translated"]
        cross_lang = "en"
        cross_label = "🇬🇧 英语学术等价表达 (RU → EN 对照学习)"
        cross_text = cross_raw
        stressed_original = annotate_russian_text_stress(clean)
    else:
        cross_raw = translate_text(clean, src_lang="en", tgt_lang="ru", prefer_llm=False, owner_id=owner_id)["translated"]
        cross_lang = "ru"
        cross_label = "🇷🇺 俄语学术等价表达 (EN → RU 对照学习·带重音)"
        cross_text = annotate_russian_text_stress(cross_raw) if cross_raw else ""
        stressed_original = clean

    # 3. Structural parse
    structure = analyze_sentence_structure(clean, lang=lang)

    # 4. Deep explanation (LLM if configured/requested, else rich local grammatical guide)
    cfg = get_settings(owner_id=owner_id, mask_secret=False)
    llm_ready = bool(cfg.get("llm_enabled") and (cfg.get("llm_api_key") or "11434" in str(cfg.get("llm_base_url"))))
    should_call_llm = llm_ready if use_llm is None else (use_llm and llm_ready)

    ai_explanation = ""
    ai_source = "builtin"

    if should_call_llm or (user_question and llm_ready):
        try:
            lang_zh = "俄语" if lang == "ru" else "英语"
            prompt_extra = (
                f"\n\n用户的具体追问：{user_question}\n请重点回答用户的追问，并结合原句语法解释。"
                if user_question
                else ""
            )
            sys_msg = (
                f"你是一位专门辅导中国科研人员阅读{lang_zh}论文、同时对比习得英语与俄语的双语语言学导师。"
                "请用清晰简洁的 Markdown 对给定学术句子做精讲，包含：\n"
                "1. **句子主干提炼**（找出主语、谓语、核心宾语/表语）；\n"
                "2. **核心语法难点拆解**（若是俄语，重点指出变格支配、形动词/副动词短语、无人称或 -ся 被动结构及重音/词源注意点；若是英语，重点指出长后置定语、分词状语、学术虚拟或被动句式，并给出对应俄语表达思路）；\n"
                "3. **值得积累的学术写作句型**（提炼 1~2 个可迁移的英/俄双语论文句式模板）。"
            )
            ai_explanation = _call_llm_chat(
                [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": f"论文原句：{clean}{prompt_extra}"},
                ],
                settings=cfg,
            )
            ai_source = f"llm ({cfg.get('llm_model')})"
        except Exception as e:
            ai_explanation = f"*(大模型接口调用未成功：{e}，已自动切换为内置语法分析引擎)*\n\n"
            ai_source = "builtin_fallback"

    if not ai_explanation or ai_source == "builtin_fallback":
        # Generate a genuinely insightful local grammatical guide!
        lines = []
        if ai_explanation:
            lines.append(ai_explanation)
        if lang == "ru":
            participles = [t for t in structure["tokens"] if t["role"] == "participle"]
            genitives = [t for t in structure["tokens"] if t["role"] == "genitive"]
            verbs = [t for t in structure["tokens"] if t["role"] == "verb"]
            lines.append("### 🔬 内置俄语学术语法诊断")
            if verbs:
                v_str = "、".join(f"**{v['stressed']}**（原形 `{v['lemma']}`）" for v in verbs[:3])
                lines.append(f"- **谓语核心定位**：句中核心谓语成分为 {v_str}。阅读俄语长句时，请先锁定变位动词或短尾被动形动词，再向左/右寻找第一格主语。")
            if participles:
                p_str = "、".join(f"**{p['stressed']}**（← `{p['lemma']}`）" for p in participles[:3])
                lines.append(f"- **形动词/副动词结构**：检测到 {p_str}。俄语科技文献常将英语的 `which/that` 从句浓缩为形动词短语并注意性数格与被修饰词一致；汉译时建议将其前置为「……的」。")
            if len(genitives) >= 2:
                g_str = " → ".join(f"`{g['stressed']}`" for g in genitives[:4])
                lines.append(f"- **学术二格（属格）名词链**：句中出现多个第二格词形（{g_str}），形成科技俄语典型的紧凑概念修饰链（类似英语连续 `of` 结构），理解时从右向左逐层修饰。")
            if user_question:
                lines.append(f"\n> 💡 **提示**：你在追问「*{user_question}*」。如需自由对话式深度答疑，可在右上角 **⚙️ 引擎设置** 中填入 DeepSeek / OpenAI / Qwen 或本地 Ollama 接口。")
        else:
            participles = [t for t in structure["tokens"] if t["role"] == "participle"]
            connectors = [t for t in structure["tokens"] if t["role"] == "connector" and t["badge"] == "从句/逻辑词"]
            awl = [t for t in structure["tokens"] if t["badge"] == "AWL 学术词"]
            lines.append("### 🔬 内置英语学术长难句诊断")
            if connectors:
                c_str = "、".join(f"**{c['text']}**" for c in connectors[:4])
                lines.append(f"- **从句与逻辑枢纽**：句中由 {c_str} 引导从属结构或逻辑转折，建议在阅读时以此为断点切分意群。")
            if participles:
                p_str = "、".join(f"**{p['text']}**" for p in participles[:3])
                lines.append(f"- **非谓语 `-ing` 成分**：检测到 {p_str}，在学术英语中常作后置定语或伴随/结果状语（对比俄语：此类结构在俄语论文中常对应 **причастие 形动词** 或 **деепричастие 副动词**）。")
            if awl:
                a_str = "、".join(f"`{a['text']}`" for a in list({x['text']: x for x in awl}.values())[:5])
                lines.append(f"- **AWL 学术核心词汇**：本句包含高频学术词 {a_str}，点击上方彩色词块即可查看中文释义及对应俄语学术词。")
            if user_question:
                lines.append(f"\n> 💡 **提示**：你在追问「*{user_question}*」。如需自由对话式 AI 语法答疑，可在右上角 **⚙️ 引擎设置** 中开启 DeepSeek / OpenAI / Qwen 接口。")

        ai_explanation = "\n".join(lines)

    return {
        "sentence": clean,
        "stressed_sentence": stressed_original,
        "lang": lang,
        "zh_translation": zh_trans,
        "cross_lang": cross_lang,
        "cross_label": cross_label,
        "cross_translation": cross_text,
        "structure": structure,
        "explanation_md": ai_explanation,
        "ai_source": ai_source,
        "llm_configured": llm_ready,
    }
