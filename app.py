from concurrent.futures import ThreadPoolExecutor
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services.db import (
    add_or_update_vocab,
    create_paper,
    delete_paper,
    delete_vocab,
    get_owner_stats,
    get_paper,
    get_settings,
    get_user_by_token,
    init_db,
    list_papers,
    list_vocab,
    login_user,
    logout_token,
    register_user,
    review_vocab_sm2,
    save_settings,
    update_paper_notes,
    update_paper_paragraphs,
)
from services.nlp_engine import (
    EN_ACADEMIC_WORDS,
    RU_ACADEMIC_LEMMAS,
    annotate_russian_text_stress,
    detect_lang,
    split_into_sentences,
)
from services.pdf_importer import (
    UPLOADS_DIR,
    extract_pdf_paper,
    fetch_arxiv_paper,
    fetch_doi_paper,
    segment_text_to_paragraphs,
)
from services.seed_papers import ensure_owner_starter_vocab, ensure_seed_data
from services.translator import (
    analyze_and_explain_sentence,
    lookup_word_trilingual,
    test_llm_connection,
    translate_text,
)
from services.tts_service import synthesize_speech_mp3

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="智译学研 · Polyglot Scholar Online", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_static_cache(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path in ("/", "/manifest.json") or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    ensure_seed_data()


init_db()
ensure_seed_data()

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------- Identity & Workspace Resolver ----------
def _extract_bearer_token(request: Request, token_q: Optional[str] = None) -> str:
    auth_hdr = request.headers.get("Authorization", "")
    if auth_hdr.lower().startswith("bearer "):
        return auth_hdr[7:].strip()
    return (token_q or "").strip()


def _extract_guest_id(request: Request, guest_q: Optional[str] = None) -> str:
    raw = (request.headers.get("X-Guest-Id") or guest_q or "").strip()
    if raw and re.match(r"^guest_[a-zA-Z0-9_-]{6,48}$", raw):
        return raw
    return "default"


def get_actor(
    request: Request,
    token: Optional[str] = Query(None),
    guest_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    tok = _extract_bearer_token(request, token)
    user = get_user_by_token(tok) if tok else None
    if user:
        owner_id = user["owner_id"]
        ensure_owner_starter_vocab(owner_id)
        return {"owner_id": owner_id, "user": user, "authenticated": True, "token": tok}

    gid = _extract_guest_id(request, guest_id)
    ensure_owner_starter_vocab(gid)
    return {"owner_id": gid, "user": None, "authenticated": False, "token": ""}


# ---------- Pydantic Schemas ----------
class AuthRegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class AuthLoginRequest(BaseModel):
    username: str
    password: str


class ImportTextRequest(BaseModel):
    title: str = ""
    authors: str = ""
    text: str
    lang: str = "auto"
    auto_translate: bool = True


class ImportArxivRequest(BaseModel):
    arxiv_id: str
    prefer_fulltext: bool = False
    auto_translate: bool = True


class ImportDoiRequest(BaseModel):
    doi: str
    prefer_fulltext: bool = True
    auto_translate: bool = True


class TranslatePaperRequest(BaseModel):
    force_retranslate: bool = False
    prefer_llm: Optional[bool] = None
    paragraph_ids: Optional[List[str]] = None


class NotesUpdateRequest(BaseModel):
    notes: str


class WordLookupRequest(BaseModel):
    word: str
    lang: Optional[str] = None
    context_sentence: str = ""


class SentenceAnalyzeRequest(BaseModel):
    sentence: str
    lang: Optional[str] = None
    use_llm: Optional[bool] = None
    question: str = ""


class VocabCreateRequest(BaseModel):
    word: str
    lemma: str = ""
    lang: str
    stressed_or_ipa: str = ""
    pos_summary: str = ""
    meaning_zh: str
    bridge_meaning: str = ""
    grammar_note: str = ""
    context_sentence: str = ""
    context_zh: str = ""
    paper_id: Optional[int] = None
    paper_title: str = ""


class VocabReviewRequest(BaseModel):
    quality: int


# ---------- Helpers ----------
def _enrich_paper_payload(paper: Dict[str, Any]) -> Dict[str, Any]:
    for p in paper.get("paragraphs", []):
        p["sentences"] = split_into_sentences(p.get("text", ""))
        p["zh_sentences"] = split_into_sentences(p.get("zh_text", "")) if p.get("zh_text") else []
    paper["academic_words"] = sorted(list(RU_ACADEMIC_LEMMAS if paper["lang"] == "ru" else EN_ACADEMIC_WORDS))
    return paper


def _batch_translate_paragraphs(
    paragraphs: List[Dict[str, Any]],
    lang: str,
    owner_id: str = "default",
    force: bool = False,
    prefer_llm: Optional[bool] = None,
    limit_count: Optional[int] = None,
    only_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    targets = []
    for idx, p in enumerate(paragraphs):
        if only_ids and p.get("id") not in only_ids:
            continue
        if force or not (p.get("zh_text") or "").strip():
            targets.append(idx)
        if limit_count and len(targets) >= limit_count:
            break

    if not targets:
        return paragraphs

    def _work(i: int) -> str:
        txt = paragraphs[i].get("text", "")
        res = translate_text(
            txt,
            src_lang=lang,
            tgt_lang="zh-CN",
            prefer_llm=prefer_llm,
            force_refresh=force,
            owner_id=owner_id,
        )
        return res.get("translated", "")

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_work, targets))

    for i, zh in zip(targets, results):
        if zh:
            paragraphs[i]["zh_text"] = zh
    return paragraphs


# ---------- Entry & PWA Routes ----------
@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/manifest.json")
def serve_pwa_manifest() -> JSONResponse:
    return JSONResponse({
        "name": "智译学研 · Polyglot Scholar",
        "short_name": "智译学研",
        "description": "俄语与英语学术论文双语精读与语言双向习得在线网站",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f6f7f9",
        "theme_color": "#2b4c7e",
        "icons": [
            {
                "src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 128 128'%3E%3Crect width='128' height='128' rx='26' fill='%232b4c7e'/%3E%3Ctext x='64' y='88' text-anchor='middle' fill='white' font-family='serif' font-weight='bold' font-size='78'%3E%CE%A8%3C/text%3E%3C/svg%3E",
                "sizes": "192x192",
                "type": "image/svg+xml",
            }
        ],
    })


@app.get("/api/health")
def health_check(actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    cfg = get_settings(owner_id=actor["owner_id"], mask_secret=False)
    return {
        "status": "ok",
        "authenticated": actor["authenticated"],
        "llm_enabled": bool(cfg.get("llm_enabled") and (cfg.get("llm_api_key") or "11434" in str(cfg.get("llm_base_url")))),
        "llm_model": cfg.get("llm_model", ""),
    }


# ---------- Multi-User Authentication Routes ----------
@app.post("/api/auth/register")
def api_register(req: AuthRegisterRequest, request: Request) -> Dict[str, Any]:
    guest_id = _extract_guest_id(request)
    try:
        res = register_user(req.username, req.password, req.display_name, guest_owner_id=guest_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ensure_owner_starter_vocab(res["user"]["owner_id"])
    res["stats"] = get_owner_stats(res["user"]["owner_id"])
    return res


@app.post("/api/auth/login")
def api_login(req: AuthLoginRequest, request: Request) -> Dict[str, Any]:
    guest_id = _extract_guest_id(request)
    try:
        res = login_user(req.username, req.password, guest_owner_id=guest_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ensure_owner_starter_vocab(res["user"]["owner_id"])
    res["stats"] = get_owner_stats(res["user"]["owner_id"])
    return res


@app.post("/api/auth/logout")
def api_logout(actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    if actor["token"]:
        logout_token(actor["token"])
    return {"ok": True}


@app.get("/api/auth/me")
def api_me(actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    return {
        "authenticated": actor["authenticated"],
        "user": actor["user"],
        "owner_id": actor["owner_id"],
        "stats": get_owner_stats(actor["owner_id"]),
    }


# ---------- Paper Routes (Per-User Scoped) ----------
@app.get("/api/papers")
def api_list_papers(actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    return {"papers": list_papers(actor["owner_id"])}


@app.get("/api/papers/{paper_id}")
def api_get_paper(paper_id: int, actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    paper = get_paper(paper_id, owner_id=actor["owner_id"])
    if not paper:
        raise HTTPException(status_code=404, detail="未找到该论文或无访问权限")
    return _enrich_paper_payload(paper)


@app.post("/api/papers/import-text")
def api_import_text(req: ImportTextRequest, actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    raw = req.text.strip()
    if len(raw) < 10:
        raise HTTPException(status_code=400, detail="请输入至少一段有效的俄语或英语论文文本")

    owner_id = actor["owner_id"]
    lang = req.lang if req.lang in ("ru", "en") else detect_lang(raw)
    paragraphs = segment_text_to_paragraphs(raw, max_paragraphs=90)
    if not paragraphs:
        raise HTTPException(status_code=400, detail="未能解析出有效段落")

    title = req.title.strip()
    if not title:
        first_txt = paragraphs[0]["text"]
        title = first_txt[:90] + ("..." if len(first_txt) > 90 else "")

    title_zh = translate_text(title, src_lang=lang, tgt_lang="zh-CN", owner_id=owner_id)["translated"]
    if req.auto_translate:
        paragraphs = _batch_translate_paragraphs(paragraphs, lang=lang, owner_id=owner_id, limit_count=10)

    pid = create_paper(
        title=title,
        lang=lang,
        paragraphs=paragraphs,
        owner_id=owner_id,
        title_zh=title_zh,
        authors=req.authors.strip(),
        source="文本导入",
    )
    return _enrich_paper_payload(get_paper(pid, owner_id=owner_id))


@app.post("/api/papers/upload-pdf")
async def api_upload_pdf(
    file: UploadFile = File(...),
    auto_translate: bool = Form(True),
    actor: Dict[str, Any] = Depends(get_actor),
) -> Dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="请上传 .pdf 格式的学术论文文件")

    content = await file.read()
    if len(content) < 100:
        raise HTTPException(status_code=400, detail="上传的 PDF 文件为空或损坏")

    try:
        parsed = extract_pdf_paper(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF 解析失败: {e}")

    if not parsed["paragraphs"]:
        raise HTTPException(status_code=400, detail="该 PDF 未检测到可提取文本（可能是纯扫描图片版 PDF）")

    owner_id = actor["owner_id"]
    title_zh = translate_text(parsed["title"], src_lang=parsed["lang"], tgt_lang="zh-CN", owner_id=owner_id)["translated"]
    paragraphs = parsed["paragraphs"]
    if auto_translate:
        paragraphs = _batch_translate_paragraphs(paragraphs, lang=parsed["lang"], owner_id=owner_id, limit_count=8)

    pid = create_paper(
        title=parsed["title"],
        lang=parsed["lang"],
        paragraphs=paragraphs,
        owner_id=owner_id,
        title_zh=title_zh,
        authors=parsed["authors"],
        source=parsed["source"],
        pdf_filename=parsed["pdf_filename"],
    )
    return _enrich_paper_payload(get_paper(pid, owner_id=owner_id))


@app.post("/api/papers/import-arxiv")
def api_import_arxiv(req: ImportArxivRequest, actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    try:
        parsed = fetch_arxiv_paper(req.arxiv_id, prefer_fulltext=req.prefer_fulltext)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    owner_id = actor["owner_id"]
    title_zh = translate_text(parsed["title"], src_lang=parsed["lang"], tgt_lang="zh-CN", owner_id=owner_id)["translated"]
    paragraphs = parsed["paragraphs"]
    if req.auto_translate:
        paragraphs = _batch_translate_paragraphs(paragraphs, lang=parsed["lang"], owner_id=owner_id, limit_count=8)

    pid = create_paper(
        title=parsed["title"],
        lang=parsed["lang"],
        paragraphs=paragraphs,
        owner_id=owner_id,
        title_zh=title_zh,
        authors=parsed["authors"],
        source=parsed["source"],
        pdf_filename=parsed.get("pdf_filename", ""),
    )
    out = _enrich_paper_payload(get_paper(pid, owner_id=owner_id))
    out["import_mode"] = parsed.get("import_mode", "abstract")
    return out


@app.post("/api/papers/import-doi")
def api_import_doi(req: ImportDoiRequest, actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    try:
        parsed = fetch_doi_paper(req.doi, prefer_fulltext=req.prefer_fulltext)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    owner_id = actor["owner_id"]
    title_zh = translate_text(parsed["title"], src_lang=parsed["lang"], tgt_lang="zh-CN", owner_id=owner_id)["translated"]
    paragraphs = parsed["paragraphs"]
    if req.auto_translate:
        paragraphs = _batch_translate_paragraphs(paragraphs, lang=parsed["lang"], owner_id=owner_id, limit_count=6)

    if parsed["lang"] == "ru" and len(paragraphs) <= 4:
        for p in paragraphs:
            if not p.get("stressed_text"):
                p["stressed_text"] = annotate_russian_text_stress(p.get("text", ""))

    pid = create_paper(
        title=parsed["title"],
        lang=parsed["lang"],
        paragraphs=paragraphs,
        owner_id=owner_id,
        title_zh=title_zh,
        authors=parsed["authors"],
        source=parsed["source"],
        pdf_filename=parsed.get("pdf_filename", ""),
    )
    out = _enrich_paper_payload(get_paper(pid, owner_id=owner_id))
    out["import_mode"] = parsed.get("import_mode", "abstract")
    out["doi"] = parsed.get("doi", "")
    return out


@app.post("/api/papers/{paper_id}/translate")
def api_translate_paper(
    paper_id: int,
    req: TranslatePaperRequest,
    actor: Dict[str, Any] = Depends(get_actor),
) -> Dict[str, Any]:
    owner_id = actor["owner_id"]
    paper = get_paper(paper_id, owner_id=owner_id)
    if not paper:
        raise HTTPException(status_code=404, detail="未找到该论文")

    paragraphs = _batch_translate_paragraphs(
        paper["paragraphs"],
        lang=paper["lang"],
        owner_id=owner_id,
        force=req.force_retranslate,
        prefer_llm=req.prefer_llm,
        only_ids=req.paragraph_ids,
    )
    title_zh = paper["title_zh"]
    if req.force_retranslate or not title_zh:
        title_zh = translate_text(
            paper["title"],
            src_lang=paper["lang"],
            tgt_lang="zh-CN",
            prefer_llm=req.prefer_llm,
            force_refresh=req.force_retranslate,
            owner_id=owner_id,
        )["translated"]

    update_paper_paragraphs(paper_id, paragraphs, title_zh=title_zh)
    return _enrich_paper_payload(get_paper(paper_id, owner_id=owner_id))


@app.post("/api/papers/{paper_id}/stress")
def api_annotate_paper_stress(paper_id: int, actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    owner_id = actor["owner_id"]
    paper = get_paper(paper_id, owner_id=owner_id)
    if not paper:
        raise HTTPException(status_code=404, detail="未找到该论文")
    if paper["lang"] != "ru":
        return _enrich_paper_payload(paper)

    changed = False
    for p in paper["paragraphs"]:
        if not (p.get("stressed_text") or "").strip():
            p["stressed_text"] = annotate_russian_text_stress(p.get("text", ""))
            changed = True
    if changed:
        update_paper_paragraphs(paper_id, paper["paragraphs"])
    return _enrich_paper_payload(get_paper(paper_id, owner_id=owner_id))


@app.put("/api/papers/{paper_id}/notes")
def api_save_notes(
    paper_id: int,
    req: NotesUpdateRequest,
    actor: Dict[str, Any] = Depends(get_actor),
) -> Dict[str, Any]:
    paper = get_paper(paper_id, owner_id=actor["owner_id"])
    if not paper:
        raise HTTPException(status_code=404, detail="未找到该论文")
    update_paper_notes(paper_id, req.notes, owner_id=actor["owner_id"])
    return {"ok": True}


@app.delete("/api/papers/{paper_id}")
def api_delete_paper(paper_id: int, actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    ok = delete_paper(paper_id, owner_id=actor["owner_id"])
    if not ok:
        raise HTTPException(status_code=400, detail="内置精选示例文献不可删除（仅可删除你个人导入的文献）")
    return {"ok": True}


@app.get("/api/uploads/{filename}")
def api_serve_pdf(filename: str) -> Response:
    safe = Path(filename).name
    target = UPLOADS_DIR / safe
    if not target.exists():
        raise HTTPException(status_code=404, detail="PDF 文件不存在")
    headers = {
        "Content-Disposition": f'inline; filename="{safe}"',
        "Access-Control-Allow-Origin": "*",
    }
    return FileResponse(str(target), media_type="application/pdf", headers=headers)


# ---------- NLP & Speech Endpoints ----------
@app.post("/api/nlp/word")
def api_lookup_word(req: WordLookupRequest) -> Dict[str, Any]:
    if not req.word.strip():
        raise HTTPException(status_code=400, detail="查询词不能为空")
    return lookup_word_trilingual(req.word, lang_hint=req.lang, context_sentence=req.context_sentence)


@app.post("/api/nlp/sentence")
def api_analyze_sentence(req: SentenceAnalyzeRequest, actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    if not req.sentence.strip():
        raise HTTPException(status_code=400, detail="句子不能为空")
    return analyze_and_explain_sentence(
        req.sentence,
        lang=req.lang,
        use_llm=req.use_llm,
        user_question=req.question,
        owner_id=actor["owner_id"],
    )


@app.get("/api/tts")
async def api_tts(
    text: str = Query(..., min_length=1),
    lang: Optional[str] = Query(None),
    slow: int = Query(0),
    actor: Dict[str, Any] = Depends(get_actor),
) -> Response:
    try:
        audio = await synthesize_speech_mp3(text=text, lang=lang, slow=bool(slow), owner_id=actor["owner_id"])
        return Response(content=audio, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音合成失败: {e}")


# ---------- Per-User Vocabulary & Flashcards ----------
@app.get("/api/vocab")
def api_list_vocab(
    lang: Optional[str] = None,
    search: Optional[str] = None,
    actor: Dict[str, Any] = Depends(get_actor),
) -> Dict[str, Any]:
    items = list_vocab(owner_id=actor["owner_id"], lang=lang, search=search)
    return {"items": items, "total": len(items)}


@app.post("/api/vocab")
def api_add_vocab(req: VocabCreateRequest, actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    saved = add_or_update_vocab(req.model_dump(), owner_id=actor["owner_id"])
    return {"item": saved}


@app.post("/api/vocab/{vocab_id}/review")
def api_review_vocab(
    vocab_id: int,
    req: VocabReviewRequest,
    actor: Dict[str, Any] = Depends(get_actor),
) -> Dict[str, Any]:
    updated = review_vocab_sm2(vocab_id, req.quality, owner_id=actor["owner_id"])
    if not updated:
        raise HTTPException(status_code=404, detail="词条不存在")
    return {"item": updated}


@app.delete("/api/vocab/{vocab_id}")
def api_delete_vocab(vocab_id: int, actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    ok = delete_vocab(vocab_id, owner_id=actor["owner_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="词条不存在")
    return {"ok": True}


@app.get("/api/vocab/export")
def api_export_vocab(
    fmt: str = Query("anki"),
    lang: Optional[str] = Query(None),
    actor: Dict[str, Any] = Depends(get_actor),
) -> Response:
    items = list_vocab(owner_id=actor["owner_id"], lang=lang)
    if fmt == "anki":
        lines = ["#separator:tab", "#html:true", "#tags column:4"]
        for it in items:
            front = f"<b>{it['stressed_or_ipa'] or it['lemma']}</b> <small>({it['word']})</small>"
            bridge_tag = "EN" if it["lang"] == "ru" else "RU"
            back_parts = [f"<b>{it['meaning_zh']}</b>"]
            if it.get("pos_summary"):
                back_parts.append(f"<div><i>{it['pos_summary']}</i></div>")
            if it.get("bridge_meaning"):
                back_parts.append(f"<div>[{bridge_tag} 互学]: {it['bridge_meaning']}</div>")
            if it.get("grammar_note"):
                back_parts.append(f"<div><small>{it['grammar_note']}</small></div>")
            ctx = ""
            if it.get("context_sentence"):
                ctx = f"{it['context_sentence']}<br><small>{it.get('context_zh', '')}</small>"
            tag = f"PolyglotScholar lang_{it['lang']}"
            row = "\t".join(
                s.replace("\t", " ").replace("\n", "<br>")
                for s in [front, "".join(back_parts), ctx, tag]
            )
            lines.append(row)
        body = "\n".join(lines)
        return PlainTextResponse(
            content=body,
            headers={"Content-Disposition": 'attachment; filename="polyglot_scholar_anki.tsv"'},
        )
    else:
        md = ["# 智译学研 · 俄英学术论文核心词汇讲义\n"]
        for idx, it in enumerate(items, 1):
            flag = "🇷🇺 俄语" if it["lang"] == "ru" else "🇬🇧 英语"
            md.append(f"## {idx}. {it['stressed_or_ipa'] or it['lemma']} （文中词形：`{it['word']}`） [{flag}]")
            if it.get("pos_summary"):
                md.append(f"- **词法属性**：{it['pos_summary']}")
            md.append(f"- **中文释义**：{it['meaning_zh']}")
            if it.get("bridge_meaning"):
                md.append(f"- **跨语种互证**：{it['bridge_meaning']}")
            if it.get("grammar_note"):
                md.append(f"- **语法与搭配笔记**：{it['grammar_note']}")
            if it.get("context_sentence"):
                md.append(f"- **论文原句**：{it['context_sentence']}")
                if it.get("context_zh"):
                    md.append(f"  - *译文*：{it['context_zh']}")
            md.append("")
        return PlainTextResponse(
            content="\n".join(md),
            headers={"Content-Disposition": 'attachment; filename="polyglot_scholar_vocab.md"'},
        )


# ---------- Per-User Engine Settings ----------
@app.get("/api/settings")
def api_get_settings(actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    s = get_settings(owner_id=actor["owner_id"], mask_secret=True)
    return {"settings": s}


@app.post("/api/settings")
def api_save_settings(payload: Dict[str, Any], actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    updated = save_settings(payload, owner_id=actor["owner_id"])
    return {"settings": updated}


@app.post("/api/settings/test-llm")
def api_test_llm(payload: Dict[str, Any], actor: Dict[str, Any] = Depends(get_actor)) -> Dict[str, Any]:
    cfg = get_settings(owner_id=actor["owner_id"], mask_secret=False)
    for k, v in payload.items():
        if k == "llm_api_key" and isinstance(v, str) and "••••" in v:
            continue
        cfg[k] = v
    return test_llm_connection(cfg)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
