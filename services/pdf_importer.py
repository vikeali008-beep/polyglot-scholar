from concurrent.futures import ThreadPoolExecutor
import html
import re
import time
import unicodedata
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

try:
    import pymupdf as fitz  # PyMuPDF 2.0+
except Exception:
    try:
        import fitz
    except Exception:
        fitz = None

from .db import DATA_DIR
from .nlp_engine import detect_lang

UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

SCHOLAR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PolyglotScholar/1.3; mailto:scholar@example.org)"
}

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
}

HEADING_PATTERN = re.compile(
    r"^(?:"
    r"(?:[0-9]+(?:\.[0-9]+)*\.?\s+[A-ZА-ЯЁ][^\n]{2,85})|"
    r"(?:[IVX]+\.\s+[A-ZА-ЯЁ][^\n]{2,85})|"
    r"(?:Abstract|Introduction|Related Work|Background|Methodology|Methods|Experiments|Results|Discussion|Conclusion|Conclusions|Acknowledgments|References|"
    r"Аннотация|Введение|Обзор литературы|Постановка задачи|Методология|Методы исследования|Экспериментальная часть|Результаты и обсуждение|Результаты|Обсуждение|Заключение|Выводы|Список литературы)"
    r")$",
    re.IGNORECASE,
)


def _clean_line_hyphenation(text: str) -> str:
    text = text.replace("\u00ad", "")

    def repl(m: re.Match) -> str:
        left, right = m.group(1), m.group(2)
        if left.lower() in (
            "self", "cross", "multi", "non", "co", "pre", "post", "re", "state",
            "квантово", "физико", "научно", "низко", "высоко",
        ):
            return f"{left}-{right}"
        return f"{left}{right}"

    text = re.sub(r"([a-zA-Zа-яА-ЯёЁ]{2,})-\s*\n\s*([a-zа-яё]{2,})", repl, text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def segment_text_to_paragraphs(raw_text: str, max_paragraphs: int = 95) -> List[Dict[str, Any]]:
    chunks = re.split(r"\n\s*\n+", raw_text.replace("\r\n", "\n"))
    paragraphs: List[Dict[str, Any]] = []
    pid = 1

    for raw in chunks:
        cleaned = _clean_line_hyphenation(raw)
        if not cleaned:
            continue
        if re.match(r"^(?:Page\s*)?\d{1,4}$", cleaned, re.IGNORECASE):
            continue
        is_heading = bool(HEADING_PATTERN.match(cleaned)) or (
            len(cleaned) < 75
            and not cleaned.endswith((".", ";", ":", ","))
            and cleaned[0].isupper()
            and len(cleaned.split()) <= 9
        )
        if (
            is_heading
            and re.match(r"^(?:References|Список литературы|Литература|Библиографический список)$", cleaned, re.IGNORECASE)
            and len(paragraphs) >= 5
        ):
            break

        paragraphs.append({
            "id": f"p{pid}",
            "type": "heading" if is_heading else "paragraph",
            "text": cleaned,
            "zh_text": "",
            "stressed_text": "",
        })
        pid += 1
        if len(paragraphs) >= max_paragraphs:
            break

    return paragraphs


def extract_pdf_paper(file_bytes: bytes, original_filename: str, max_pages: int = 25) -> Dict[str, Any]:
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) 未安装，无法解析 PDF")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(original_filename).suffix.lower() or ".pdf"
    safe_name = f"{uuid.uuid4().hex[:12]}{ext}"
    saved_path = UPLOADS_DIR / safe_name
    saved_path.write_bytes(file_bytes)

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    meta_title = (doc.metadata or {}).get("title") or ""
    meta_author = (doc.metadata or {}).get("author") or ""

    raw_blocks: List[str] = []
    first_page_candidates: List[Tuple[float, str]] = []

    page_limit = min(len(doc), max_pages)
    for page_idx in range(page_limit):
        page = doc[page_idx]
        page_h = float(page.rect.height or 800.0)
        p_dict = page.get_text("dict")
        for b in p_dict.get("blocks", []):
            if b.get("type") != 0:
                continue
            bbox = b.get("bbox", [0, 0, 0, 0])
            if page_idx > 0 and (bbox[3] < page_h * 0.055 or bbox[1] > page_h * 0.95):
                continue

            lines_txt = []
            max_size = 0.0
            for ln in b.get("lines", []):
                spans_txt = []
                for sp in ln.get("spans", []):
                    t = sp.get("text", "")
                    if t.strip():
                        max_size = max(max_size, float(sp.get("size", 10.0)))
                    spans_txt.append(t)
                line_joined = "".join(spans_txt).strip()
                if line_joined:
                    lines_txt.append(line_joined)
            if not lines_txt:
                continue
            block_str = "\n".join(lines_txt)
            cleaned_block = _clean_line_hyphenation(block_str)
            if len(cleaned_block) <= 2 or re.match(r"^\d+$", cleaned_block):
                continue
            if page_idx == 0 and 10 <= len(cleaned_block) <= 220:
                first_page_candidates.append((max_size, cleaned_block))
            raw_blocks.append(block_str)

    doc.close()

    inferred_title = meta_title.strip()
    if (not inferred_title or len(inferred_title) < 5 or inferred_title.lower().endswith(".pdf")) and first_page_candidates:
        first_page_candidates.sort(key=lambda x: x[0], reverse=True)
        inferred_title = first_page_candidates[0][1]
    if not inferred_title:
        inferred_title = Path(original_filename).stem

    joined_raw = "\n\n".join(raw_blocks)
    lang = detect_lang(joined_raw)
    paragraphs = segment_text_to_paragraphs(joined_raw, max_paragraphs=95)

    if paragraphs and paragraphs[0]["text"].strip() == inferred_title.strip() and len(paragraphs) > 1:
        paragraphs = paragraphs[1:]

    return {
        "title": inferred_title,
        "authors": meta_author.strip(),
        "source": f"PDF 导入 ({original_filename})",
        "lang": lang,
        "pdf_filename": safe_name,
        "paragraphs": paragraphs,
    }


def fetch_arxiv_paper(arxiv_input: str, prefer_fulltext: bool = False) -> Dict[str, Any]:
    m = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+/\d{7})", arxiv_input.strip(), re.IGNORECASE)
    if not m:
        raise ValueError("未能识别有效的 arXiv 编号（示例：1706.03762 或 https://arxiv.org/abs/1706.03762）")
    arxiv_id = m.group(1)

    resp = httpx.get(
        "https://export.arxiv.org/api/query",
        params={"id_list": arxiv_id},
        timeout=httpx.Timeout(connect=4.0, read=8.0, write=4.0, pool=4.0),
        follow_redirects=True,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"arXiv 接口请求失败 ({resp.status_code})")

    root = ET.fromstring(resp.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ValueError(f"未找到 arXiv 论文：{arxiv_id}")

    title_el = entry.find("atom:title", ns)
    summary_el = entry.find("atom:summary", ns)
    title = re.sub(r"\s+", " ", (title_el.text if title_el is not None else "")).strip()
    summary = re.sub(r"\s+", " ", (summary_el.text if summary_el is not None else "")).strip()
    authors = [
        (a.find("atom:name", ns).text or "").strip()
        for a in entry.findall("atom:author", ns)
        if a.find("atom:name", ns) is not None
    ]
    if not summary and not title:
        raise ValueError(f"arXiv 编号 {arxiv_id} 返回内容为空")

    if prefer_fulltext:
        pdf_bytes = _try_download_pdf(f"https://arxiv.org/pdf/{arxiv_id}.pdf")
        if pdf_bytes:
            pdf_parsed = extract_pdf_paper(pdf_bytes, f"arxiv_{arxiv_id.replace('/', '_')}.pdf")
            if pdf_parsed["paragraphs"]:
                return {
                    "title": title or pdf_parsed["title"],
                    "authors": ", ".join(authors[:6]) or pdf_parsed["authors"],
                    "source": f"arXiv:{arxiv_id} (全文 PDF)",
                    "lang": pdf_parsed["lang"],
                    "pdf_filename": pdf_parsed["pdf_filename"],
                    "paragraphs": pdf_parsed["paragraphs"],
                    "import_mode": "full_pdf",
                }

    lang = detect_lang(title + " " + summary)
    paragraphs = [
        {"id": "p1", "type": "heading", "text": "Abstract" if lang == "en" else "Аннотация", "zh_text": "摘要", "stressed_text": ""},
        {"id": "p2", "type": "paragraph", "text": summary, "zh_text": "", "stressed_text": ""},
    ]
    return {
        "title": title or f"arXiv:{arxiv_id}",
        "authors": ", ".join(authors[:6]),
        "source": f"arXiv:{arxiv_id}",
        "lang": lang,
        "pdf_filename": "",
        "paragraphs": paragraphs,
        "import_mode": "abstract",
    }


# ==================== DOI MULTI-SOURCE FAST RESOLVER ====================

def normalize_doi(raw_input: str) -> str:
    """
    Robust DOI normalizer handling:
    - Full-width characters & Chinese colons: 'DOI：１０．１０３８／nature14539'
    - Copy-paste invisible zero-width spaces & line-break spaces around '/'
    - Full URLs: 'https://doi.org/10.18653/v1/N19-1423', 'https://dx.doi.org/...'
    - Balanced parentheses in older Wiley/SICI DOIs: '10.1002/(SICI)1097-0258...'
    """
    s = unicodedata.normalize("NFKC", raw_input or "")
    s = urllib.parse.unquote(s)
    # Remove invisible zero-width chars
    s = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", s).strip()
    # Collapse accidental spaces around '10.xxxx / yyyy' from PDF copy-paste
    s = re.sub(r"(10\s*\.\s*\d{4,9})\s*/\s*", lambda m: re.sub(r"\s+", "", m.group(1)) + "/", s)
    s = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", "", s, flags=re.IGNORECASE).strip()

    m = re.search(r"(10\.\d{4,9}/[^\s\"'<>?#]+)", s)
    if not m:
        raise ValueError(
            "未能识别有效的 DOI 编号（格式示例：10.60797/IRJ.2026.170.43、10.18653/v1/N19-1423 或 https://doi.org/10.1038/nature14539）"
        )
    doi = m.group(1).rstrip(".,;]}>")
    # Strip trailing ')' only if unmatched
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1]
    return doi


def _strip_jats_xml(raw_abstract: str) -> str:
    if not raw_abstract:
        return ""
    cleaned = re.sub(r"<(?:jats:)?title[^>]*>.*?</(?:jats:)?title>", " ", raw_abstract, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"</(?:jats:)?p>", "\n\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _reconstruct_openalex_abstract(inv_idx: Optional[Dict[str, List[int]]]) -> str:
    if not inv_idx or not isinstance(inv_idx, dict):
        return ""
    pos_map: Dict[int, str] = {}
    for word, positions in inv_idx.items():
        if isinstance(positions, list):
            for p in positions:
                pos_map[int(p)] = word
    if not pos_map:
        return ""
    return " ".join(pos_map[i] for i in sorted(pos_map.keys())).strip()


def _parse_landing_meta_tags(html_text: str, base_url: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "title": "",
        "alt_title": "",
        "authors_ru": [],
        "authors_any": [],
        "journal": "",
        "year": "",
        "pdf_urls": [],
        "abstract_ru": "",
        "abstract_en": "",
        "abstract_any": "",
        "keywords_ru": [],
        "keywords_en": [],
    }

    for tag_match in re.finditer(r"<meta\s+[^>]*>", html_text, re.IGNORECASE):
        tag = tag_match.group(0)
        name_m = re.search(r'(?:name|property)\s*=\s*(?:["\']([^"\']+)["\']|([^\s>"\'/]+))', tag, re.IGNORECASE)
        content_m = re.search(r'content\s*=\s*(?:["\']([^"\']+)["\']|([^\s>"\']+))', tag, re.IGNORECASE)
        if not name_m or not content_m:
            continue
        key = (name_m.group(1) or name_m.group(2) or "").strip().lower()
        val = html.unescape((content_m.group(1) or content_m.group(2) or "")).strip()
        if not val:
            continue
        lang_m = re.search(r'(?:xml:lang|lang)\s*=\s*(?:["\']([^"\']+)["\']|([^\s>"\'/]+))', tag, re.IGNORECASE)
        tag_lang = ((lang_m.group(1) or lang_m.group(2)) if lang_m else "").lower()

        if key in ("citation_pdf_url", "bepress_citation_pdf_url"):
            full_pdf = urllib.parse.urljoin(base_url, val)
            if full_pdf not in info["pdf_urls"]:
                info["pdf_urls"].append(full_pdf)
        elif key in ("citation_title", "dc.title") and not info["title"]:
            info["title"] = val
        elif key == "dc.title.alternative" and not info["alt_title"]:
            info["alt_title"] = val
        elif key in ("citation_author", "dc.creator.personalname", "dc.creator"):
            if tag_lang.startswith("ru") or re.search(r"[а-яА-ЯёЁ]", val):
                if val not in info["authors_ru"]:
                    info["authors_ru"].append(val)
            if val not in info["authors_any"]:
                info["authors_any"].append(val)
        elif key in ("citation_journal_title", "dc.source") and not info["journal"]:
            if tag_lang.startswith("ru") or not info["journal"]:
                info["journal"] = val
        elif key in ("citation_publication_date", "citation_date", "dc.date.issued") and not info["year"]:
            ym = re.search(r"(19|20)\d{2}", val)
            if ym:
                info["year"] = ym.group(0)
        elif key in ("citation_abstract", "dc.description", "description", "og:description"):
            clean_v = _strip_jats_xml(val)
            if len(clean_v) < 35:
                continue
            if tag_lang.startswith("ru") or detect_lang(clean_v) == "ru":
                if len(clean_v) > len(info["abstract_ru"]):
                    info["abstract_ru"] = clean_v
            elif tag_lang.startswith("en"):
                if len(clean_v) > len(info["abstract_en"]):
                    info["abstract_en"] = clean_v
            else:
                if len(clean_v) > len(info["abstract_any"]):
                    info["abstract_any"] = clean_v
        elif key in ("dc.subject", "citation_keywords"):
            parts = [k.strip() for k in re.split(r"[;,]", val) if k.strip()]
            for kw in parts:
                if tag_lang.startswith("ru") or re.search(r"[а-яА-ЯёЁ]", kw):
                    if kw not in info["keywords_ru"]:
                        info["keywords_ru"].append(kw)
                else:
                    if kw not in info["keywords_en"]:
                        info["keywords_en"].append(kw)

    return info


def _try_download_pdf(url: str, max_seconds: float = 10.0) -> Optional[bytes]:
    """Stream-download an Open Access PDF, aborting immediately if first bytes are not %PDF-."""
    if not url:
        return None
    deadline = time.monotonic() + max_seconds
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=3.5, read=6.0, write=3.5, pool=3.5),
            headers={**BROWSER_HEADERS, "Accept": "application/pdf,*/*;q=0.8"},
        ) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return None
                buf = bytearray()
                checked_magic = False
                for chunk in resp.iter_bytes(chunk_size=16384):
                    buf.extend(chunk)
                    if not checked_magic and len(buf) >= 5:
                        checked_magic = True
                        if bytes(buf[:5]) != b"%PDF-":
                            return None
                    if len(buf) > 25 * 1024 * 1024 or time.monotonic() > deadline:
                        return None
                if len(buf) > 800 and bytes(buf[:5]) == b"%PDF-":
                    return bytes(buf)
    except Exception:
        return None
    return None


def _fetch_landing_head_or_pdf(doi: str) -> Dict[str, Any]:
    """
    Follow https://doi.org/{doi} with streaming cap (reads at most 140 KB for HTML meta tags,
    or captures direct PDF if doi.org redirects straight to a PDF). Never hangs on slow sites.
    """
    out: Dict[str, Any] = {"ok": False, "pdf_bytes": None, "meta": None}
    deadline = time.monotonic() + 5.5
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=3.2, read=4.0, write=3.0, pool=3.0),
            headers=BROWSER_HEADERS,
        ) as client:
            with client.stream("GET", f"https://doi.org/{doi}") as resp:
                if resp.status_code != 200:
                    return out
                out["ok"] = True
                ctype = (resp.headers.get("content-type") or "").lower()
                buf = bytearray()
                is_pdf = "application/pdf" in ctype
                for chunk in resp.iter_bytes(chunk_size=16384):
                    buf.extend(chunk)
                    if len(buf) >= 5 and bytes(buf[:5]) == b"%PDF-":
                        is_pdf = True
                    if not is_pdf and (len(buf) >= 140_000 or b"</head>" in buf.lower()):
                        break
                    if is_pdf and len(buf) > 25 * 1024 * 1024:
                        return out
                    if time.monotonic() > deadline:
                        break
                if is_pdf and len(buf) > 800 and bytes(buf[:5]) == b"%PDF-":
                    out["pdf_bytes"] = bytes(buf)
                else:
                    text = buf.decode(resp.encoding or "utf-8", errors="replace")
                    out["meta"] = _parse_landing_meta_tags(text, str(resp.url))
    except Exception:
        pass
    return out


def fetch_doi_paper(doi_input: str, prefer_fulltext: bool = True) -> Dict[str, Any]:
    """
    High-speed parallel DOI resolver:
    Runs Crossref + OpenAlex + Semantic Scholar + DOI Landing Page concurrently (~1.5–4s total!).
    """
    doi = normalize_doi(doi_input)

    # 1. Fast-path for arXiv DOIs (e.g. 10.48550/arXiv.1706.03762)
    arxiv_m = re.match(r"^10\.48550/arxiv\.(.+)$", doi, flags=re.IGNORECASE)
    if arxiv_m:
        res = fetch_arxiv_paper(arxiv_m.group(1), prefer_fulltext=prefer_fulltext)
        res["source"] = f"DOI: {doi} · {res.get('source', '')}".strip(" ·")
        res["doi"] = doi
        return res

    api_timeout = httpx.Timeout(connect=3.5, read=5.0, write=3.5, pool=3.5)

    def _task_crossref() -> Optional[Dict[str, Any]]:
        try:
            r = httpx.get(
                f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}",
                headers=SCHOLAR_HEADERS,
                timeout=api_timeout,
            )
            return r.json().get("message") if r.status_code == 200 else None
        except Exception:
            return None

    def _task_openalex() -> Optional[Dict[str, Any]]:
        try:
            r = httpx.get(
                f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi, safe='/')}",
                headers=SCHOLAR_HEADERS,
                timeout=api_timeout,
            )
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    def _task_s2() -> Optional[Dict[str, Any]]:
        try:
            r = httpx.get(
                f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi, safe='/')}",
                params={"fields": "title,abstract,authors,venue,year,openAccessPdf"},
                headers=SCHOLAR_HEADERS,
                timeout=api_timeout,
            )
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_cr = pool.submit(_task_crossref)
        f_oa = pool.submit(_task_openalex)
        f_s2 = pool.submit(_task_s2)
        f_land = pool.submit(_fetch_landing_head_or_pdf, doi)

        cr_msg = f_cr.result()
        oad = f_oa.result()
        sd = f_s2.result()
        land = f_land.result()

    title = ""
    authors: List[str] = []
    journal = ""
    year = ""
    abstract_primary = ""
    abstract_ru = ""
    abstract_en = ""
    keywords_ru: List[str] = []
    keywords_en: List[str] = []
    pdf_candidates: List[str] = []
    found_any_record = bool(cr_msg or oad or sd or land.get("ok"))

    if cr_msg:
        titles = cr_msg.get("title") or []
        if titles:
            title = re.sub(r"\s+", " ", _strip_jats_xml(titles[0])).strip()
        for a in (cr_msg.get("author") or [])[:8]:
            full = f"{a.get('given', '')} {a.get('family', '')}".strip() or a.get("name", "").strip()
            if full:
                authors.append(full)
        containers = cr_msg.get("container-title") or []
        if containers:
            journal = containers[0].strip()
        pub_parts = (
            (cr_msg.get("published-print") or {}).get("date-parts")
            or (cr_msg.get("published-online") or {}).get("date-parts")
            or (cr_msg.get("issued") or {}).get("date-parts")
            or []
        )
        if pub_parts and pub_parts[0]:
            year = str(pub_parts[0][0])
        if cr_msg.get("abstract"):
            abstract_primary = _strip_jats_xml(cr_msg["abstract"])
        for lnk in cr_msg.get("link") or []:
            ctype = (lnk.get("content-type") or "").lower()
            lurl = lnk.get("URL") or ""
            if lurl and ("pdf" in ctype or lurl.lower().endswith(".pdf")):
                pdf_candidates.append(lurl)

    if oad:
        if not title and oad.get("title"):
            title = str(oad["title"]).strip()
        if not authors:
            for au in (oad.get("authorships") or [])[:8]:
                dn = ((au.get("author") or {}).get("display_name") or "").strip()
                if dn:
                    authors.append(dn)
        if not year and oad.get("publication_year"):
            year = str(oad["publication_year"])
        best_oa = oad.get("best_oa_location") or {}
        if not journal:
            journal = ((best_oa.get("source") or {}).get("display_name") or "").strip()
        if best_oa.get("pdf_url"):
            pdf_candidates.insert(0, best_oa["pdf_url"])
        oa_info = oad.get("open_access") or {}
        if oa_info.get("oa_url") and str(oa_info["oa_url"]).lower().endswith(".pdf"):
            pdf_candidates.append(oa_info["oa_url"])
        oa_abs = _reconstruct_openalex_abstract(oad.get("abstract_inverted_index"))
        if len(oa_abs) > len(abstract_primary):
            abstract_primary = oa_abs

    if sd:
        if not title and sd.get("title"):
            title = sd["title"].strip()
        if not authors and sd.get("authors"):
            authors = [a.get("name", "").strip() for a in sd["authors"][:8] if a.get("name")]
        if not journal and sd.get("venue"):
            journal = sd["venue"].strip()
        if not year and sd.get("year"):
            year = str(sd["year"])
        if len(sd.get("abstract") or "") > len(abstract_primary):
            abstract_primary = (sd.get("abstract") or "").strip()
        oa_pdf = (sd.get("openAccessPdf") or {}).get("url")
        if oa_pdf:
            pdf_candidates.append(oa_pdf)

    if land.get("pdf_bytes") and prefer_fulltext:
        pdf_parsed = extract_pdf_paper(land["pdf_bytes"], f"doi_{doi.replace('/', '_')}.pdf")
        if pdf_parsed["paragraphs"]:
            return {
                "title": title or pdf_parsed["title"],
                "authors": ", ".join(authors) or pdf_parsed["authors"],
                "source": " · ".join(x for x in [journal, year, f"DOI: {doi} (开放全文 PDF)"] if x),
                "lang": pdf_parsed["lang"],
                "pdf_filename": pdf_parsed["pdf_filename"],
                "paragraphs": pdf_parsed["paragraphs"],
                "import_mode": "full_pdf",
                "doi": doi,
            }

    meta = land.get("meta")
    if meta:
        for u in meta["pdf_urls"]:
            if u not in pdf_candidates:
                pdf_candidates.insert(0, u)
        if not title and meta["title"]:
            title = meta["title"]
        if meta["authors_ru"]:
            authors = meta["authors_ru"][:8]
        elif not authors and meta["authors_any"]:
            authors = meta["authors_any"][:8]
        if meta["journal"] and (not journal or re.search(r"[а-яА-ЯёЁ]", meta["journal"])):
            journal = meta["journal"]
        if not year and meta["year"]:
            year = meta["year"]
        abstract_ru = meta["abstract_ru"]
        abstract_en = meta["abstract_en"]
        if not abstract_primary:
            abstract_primary = abstract_ru or abstract_en or meta["abstract_any"]
        keywords_ru = meta["keywords_ru"][:12]
        keywords_en = meta["keywords_en"][:12]

    if not found_any_record and not title:
        raise ValueError(f"未能在 Crossref / OpenAlex / DOI 注册库中找到编号「{doi}」，请检查 DOI 是否拼写正确。")

    if title and title.isupper() and len(title) > 15:
        title = title[0] + title[1:].lower()

    source_str = " · ".join(x for x in [journal, year, f"DOI: {doi}"] if x)

    # Try downloading up to 2 best OA PDF candidates if prefer_fulltext=True
    if prefer_fulltext and pdf_candidates:
        seen_urls = set()
        for pdf_url in pdf_candidates[:3]:
            if not pdf_url or pdf_url in seen_urls:
                continue
            seen_urls.add(pdf_url)
            pdf_bytes = _try_download_pdf(pdf_url, max_seconds=9.5)
            if pdf_bytes:
                try:
                    pdf_parsed = extract_pdf_paper(pdf_bytes, f"doi_{doi.replace('/', '_')}.pdf")
                    if len(pdf_parsed["paragraphs"]) >= 2:
                        final_lang = detect_lang((title or "") + " " + " ".join(p["text"] for p in pdf_parsed["paragraphs"][:5]))
                        return {
                            "title": title or pdf_parsed["title"],
                            "authors": ", ".join(authors) or pdf_parsed["authors"],
                            "source": f"{source_str} (开放获取 PDF 全文)",
                            "lang": final_lang,
                            "pdf_filename": pdf_parsed["pdf_filename"],
                            "paragraphs": pdf_parsed["paragraphs"],
                            "import_mode": "full_pdf",
                            "doi": doi,
                        }
                except Exception:
                    continue

    # Structured Metadata + Abstract + Parallel Abstract + Keywords
    combined_sample = " ".join([title, abstract_ru or abstract_primary, " ".join(keywords_ru)])
    lang = detect_lang(combined_sample)

    paragraphs: List[Dict[str, Any]] = []
    pid = 1

    def _add_p(ptype: str, txt: str, zh: str = "") -> None:
        nonlocal pid
        if not txt.strip():
            return
        paragraphs.append({
            "id": f"p{pid}",
            "type": ptype,
            "text": txt.strip(),
            "zh_text": zh,
            "stressed_text": "",
        })
        pid += 1

    main_abs = abstract_ru if (lang == "ru" and abstract_ru) else (abstract_primary or abstract_en)
    if main_abs:
        _add_p("heading", "Аннотация" if lang == "ru" else "Abstract", "摘要")
        for seg in segment_text_to_paragraphs(main_abs, max_paragraphs=15):
            _add_p("paragraph", seg["text"])

        if lang == "ru" and abstract_en and abstract_en != main_abs:
            _add_p("heading", "Abstract (Author Parallel English)", "英文对照摘要（原刊附带，可对比学习英俄学术表达）")
            _add_p("paragraph", abstract_en)
    else:
        notice = (
            f"Метаданные статьи успешно загружены по DOI {doi} ({journal or 'Научное издание'} {year}). "
            "Полный текст и аннотация закрыты издательством (подписной доступ). Если у вас есть PDF-файл этой статьи, загрузите его во вкладке «上传 PDF 论文»."
            if lang == "ru"
            else f"Bibliographic metadata for DOI {doi} ({journal or 'Academic Publisher'} {year}) was resolved successfully. "
            "Full text and abstract are restricted by publisher subscription access; if you have the PDF locally, you can upload it via the PDF tab."
        )
        _add_p("heading", "Информация о публикации" if lang == "ru" else "Publication Notice", "文献题录说明")
        _add_p("paragraph", notice)

    if keywords_ru or keywords_en:
        _add_p("heading", "Ключевые слова / Keywords" if lang == "ru" else "Keywords", "学术关键词")
        kw_lines = []
        if keywords_ru:
            kw_lines.append("RU: " + " · ".join(keywords_ru))
        if keywords_en:
            kw_lines.append("EN: " + " · ".join(keywords_en))
        _add_p("paragraph", " | ".join(kw_lines))

    return {
        "title": title or f"DOI: {doi}",
        "authors": ", ".join(authors),
        "source": source_str,
        "lang": lang,
        "pdf_filename": "",
        "paragraphs": paragraphs,
        "import_mode": "abstract" if main_abs else "metadata_only",
        "doi": doi,
    }
