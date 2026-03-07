from bisect import bisect_right
from pypdf import PdfReader
from markdown_it import MarkdownIt
from openai import OpenAI
from pydantic import BaseModel, Field

import json
import re

_enrichment_client = OpenAI()
ENRICHMENT_MODEL = "gpt-4.1-mini"

_INPUT_COST_PER_TOKEN = 0.40 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 1.60 / 1_000_000


def _chat_cost_usd(usage) -> float:
    if not usage:
        return 0.0
    return (
        usage.prompt_tokens * _INPUT_COST_PER_TOKEN
        + usage.completion_tokens * _OUTPUT_COST_PER_TOKEN
    )

CHAPTER_PATTERNS = [
    re.compile(r"^#{1,3}\s*chapter\s+\w+", re.IGNORECASE),
    re.compile(r"^#{1,3}\s*part\s+\w+", re.IGNORECASE),
    re.compile(r"^chapter\s+\d+", re.IGNORECASE),
    re.compile(r"^CHAPTER\s+[IVXLCDM]+"),
]
_PAGE_MARKER_RE = re.compile(r"<!--\s*Page\s+(\d+)\s*-->")


class ChapterEntry(BaseModel):
    title: str = Field(..., description="Exact heading text that marks a chapter boundary.")
    content_index: int = Field(..., description="The content index of the heading in the contents list.")


class ChapterDetectionResponse(BaseModel):
    chapters: list[ChapterEntry] = Field(
        ...,
        description="List of chapter-level boundaries identified from the headings and content.",
    )

def clean_highlighted_query(query):
    try:
        allHighlight = re.finditer(r"(?<!\\)\*{1,10}(.+?)(?<!\\)\*{1,10}",query)

        if not allHighlight:
            print("No highlights found in query: ",query)
            return query
        for highlight in allHighlight:
                # print("unprocessed query:",query)
                # print(highlight.group(1))
                # print("Patern before: ",r"\*{1,10}("+highlight.group(1)+r")\*{1,10}",end="\n")
                content = re.escape(highlight.group(1))
                pattern = r"(?<!\\)\*{1,10}("+ content +r")(?<!\\)\*{1,10}"
                # print("Pattern after: ",pattern,end="\n")
                # print(re.match(pattern,query))

                query = re.sub(pattern,r"\1",query)

        return query
    except Exception as e:
        print("Original Query: ",query)
        print("Error in cleaning highlighted query: ",e)
        return query
    
def _build_page_marker_index(text: str) -> tuple[list[int], list[int]]:
    offsets: list[int] = []
    pages: list[int] = []
    for match in _PAGE_MARKER_RE.finditer(text):
        offsets.append(match.start())
        pages.append(int(match.group(1)))
    return offsets, pages


def clean_text(text: str) -> str:
    remove_special_chars = re.sub(r"[^a-zA-Z0-9 ]+", "", text)
    remove_spaces = re.sub(r"[\n\r\s\t]","", remove_special_chars).strip()
    return remove_spaces.lower()


def find_text_pages(pages, query, current_page):
    query = query.lower()
    if not query:
        return []

    results = []
    search_window = 10
    start_page = max(0, current_page - search_window)
    stop_page = min(len(pages), current_page + search_window)

    slice_count = 10
    query_len = len(query)
    slice_size = max(1, query_len // slice_count)
    slices = [query[i*slice_size:(i+1)*slice_size] for i in range(slice_count-1)]
    slices.append(query[(slice_count-1)*slice_size:])

    for i, page in enumerate(pages[start_page:stop_page], start=start_page+1):
        page_lower = page.lower()
        match_count = 0
        for s in slices:
            if s and re.search(re.escape(s), page_lower):
                match_count += 1
        if match_count >= 5:
            results.append(i)
    return results


def _page_for_offset(start: int | None, marker_offsets: list[int], marker_pages: list[int]) -> int | None:
    if start is None or start < 0 or not marker_offsets:
        return None

    marker_index = bisect_right(marker_offsets, start) - 1
    if marker_index < 0:
        return None
    return marker_pages[marker_index]

def extract_markdown_contents_with_ranges(path, pdf_path):
    unMatchCount = 0
    markerMatchCount = 0
    fuzzyMatchCount = 0
    pageNumber = 1
    md = MarkdownIt().enable("table")

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    marker_offsets, marker_pages = _build_page_marker_index(text)

    tokens = md.parse(text)

    contents = []
    headings = {}
    cursor = 0
    pdfPages: list[str] | None = None


    def locate_span(content):
        nonlocal cursor
        if not content:
            return None, None

        start = text.find(content, cursor)
        if start == -1:
            start = text.find(content)

        end = start + len(content) if start != -1 else -1
        cursor = max(cursor, end)
        return start, end

    def load_pdf_pages() -> list[str]:
        nonlocal pdfPages
        if pdfPages is None:
            pdf_file = PdfReader(pdf_path)
            pdfPages = [clean_text(page.extract_text()) or "" for page in pdf_file.pages]
        return pdfPages

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        content = None

        # ---- Headings ----
        if tok.type == "heading_open":
            inline = tokens[i + 1]
            content = inline.content.strip()
            start, end = locate_span(content)

            content = {
                "type": "heading",
                "level": int(tok.tag[-1]),
                "text": content,
                "start": start,
                "end": end,
            }
            i += 2

        # ---- Paragraphs ----
        elif tok.type == "paragraph_open":
            inline = tokens[i + 1]
            content = inline.content.strip()
            start, end = locate_span(content)
            type = "image" if re.match(r'!\[[^\]]*\]\((.+)\)', content) else "paragraph"
            content = {
                "type": type,
                "level": 0,
                "text": content,
                "start": start,
                "end": end,
            }
            i += 2

        # ---- Code Blocks ----
        elif tok.type == "fence":
            content = tok.content
            start, end = locate_span(content)

            content = {
                "type": "code_block",
                "language": tok.info or None,
                "text": content,
                "start": start,
                "end": end,
            }
            i += 1

        # ---- List Items ----
        elif tok.type == "list_item_open":
            if tokens[i+1].type == "paragraph_open":
                inline = tokens[i+2]
                step = 3
            else:
                inline = tokens[i+1]
                step = 2

            content = inline.content.strip()
            start, end = locate_span(content)

            content = {
                "type": "list_item",
                "text": content,
                "start": start,
                "end": end,
            }
            i += step

        # ---- Tables ----
        elif tok.type == "table_open":
            table_header = []
            table_rows = []

            current_row = []
            in_header = False

            # derive table-level range using min/max of cell ranges
            min_start, max_end = None, None

            j = i + 1
            while j < len(tokens) and tokens[j].type != "table_close":
                t = tokens[j]

                if t.type == "thead_open":
                    in_header = True

                elif t.type == "thead_close":
                    in_header = False

                elif t.type == "tr_open":
                    current_row = []

                elif t.type == "tr_close":
                    if in_header:
                        table_header.append(current_row)
                    else:
                        table_rows.append(current_row)
                    current_row = []

                elif t.type in ("th_open", "td_open"):
                    inline = tokens[j+1]
                    cell_text = inline.content.strip()

                    start, end = locate_span(cell_text)

                    # update table span bounds
                    if start is not None and start != -1:
                        min_start = start if min_start is None else min(min_start, start)
                        max_end = end if max_end is None else max(max_end, end)

                    current_row.append({
                        "text": cell_text,
                        "start": start,
                        "end": end,
                    })

                    j += 1  # skip inline

                j += 1

            # fallback if no cell range detected
            table_dict = {"header":table_header, "rows":table_rows}
            table_text_str = json.dumps(table_dict)
            content = {
                "type": "table",
                "text": table_text_str,
                "cleaned_text": table_text_str,
                "header": table_header,
                "rows": table_rows,
                "start": min_start,
                "end": max_end,
            }

            # jump outer loop to table_close
            i = j + 1
            # append happens after the if/elif chain
            # so we do NOT continue here

        else:
            i += 1
        # ---- append only once per loop ----
        if content is not None:
            content_start = content.get("start")
            if content_start in (None, -1):
                content_start = content.get("end")

            marker_page = _page_for_offset(content_start, marker_offsets, marker_pages)
            if marker_page is not None:
                pageNumber = marker_page
                markerMatchCount += 1
            elif content['type'] != "table":
                clean_query = clean_text(content["text"])
                pages = find_text_pages(load_pdf_pages(), clean_query, pageNumber)
                if pages:
                    tempPage = pageNumber
                    tempDif = float("inf")
                    for page in pages:
                        if abs(page - pageNumber) < tempDif:
                            tempDif = abs(page - pageNumber)
                            tempPage = page
                    pageNumber = tempPage
                    fuzzyMatchCount += 1
                else:
                    unMatchCount += 1

            if content['type']!="table":
                content['cleaned_text'] = clean_highlighted_query(content["text"])
                content['word_count']= len(content['text'].split())

            content['index']= len(contents)+1
            content['pageNumber']= pageNumber

            if content['type']=='heading':
                headings[content["cleaned_text"]] = {'pageNumber': pageNumber,    'contentIndex': content['index']}
            
            if content['text']!='':
                contents.append(content)

    matched_count = len(contents) - unMatchCount
    match_rate = (matched_count / len(contents) * 100) if contents else 0.0
    print(f"Page markers assigned for {markerMatchCount} contents")
    print(f"Fuzzy page fallback matched {fuzzyMatchCount} contents")
    print(f"Total Unmatched contents: {unMatchCount}/{len(contents)}")
    metadata = {"content_count": len(contents), "heading_count": len(headings),"contents": contents, "all_headings": headings,"chapters":{}, "unmatched_count": unMatchCount, "match_rate": match_rate}
    return metadata




def find_chapter_word_counts(chapters, contents):
    chapter_word_counts = {}
    for chapter_title, chapter_info in chapters.items():
        start_index = chapter_info['contentIndex']
        end_index = None

        # Find the next chapter's content index
        for other_title, other_info in chapters.items():
            if other_info['contentIndex'] > start_index:
                if end_index is None or other_info['contentIndex'] < end_index:
                    end_index = other_info['contentIndex']

        # Calculate word count for contents in this chapter
        word_count = 0
        for comp in contents:
            if comp['index'] >= start_index and (end_index is None or comp['index'] < end_index):
                word_count += comp.get('word_count', 0)

        chapter_word_counts[chapter_title] = word_count

    return chapter_word_counts

def detect_chapters(metadata: dict) -> tuple[dict, float]:
    """Multi-layer chapter detection. Runs unconditionally for every document.

    Returns (updated_metadata, llm_cost_usd).

    Layer 1: Marker TOC (already applied before this function is called)
    Layer 2: Heading-level analysis
    Layer 3: Regex pattern matching
    Layer 4: LLM-assisted refinement
    Layer 5: Page 1 guarantee
    """
    llm_cost = 0.0
    chapters = metadata.get("chapters", {})
    contents = metadata.get("contents", [])

    if not contents:
        return metadata, 0.0

    headings_in_contents = [
        c for c in contents if c.get("type") == "heading"
    ]

    heading_index_map = {}
    for c in headings_in_contents:
        cleaned = (c.get("cleaned_text") or c.get("text", "")).strip()
        if cleaned:
            heading_index_map[cleaned] = {
                "pageNumber": c.get("pageNumber", 1),
                "contentIndex": c.get("index", 1),
                "level": c.get("level", 1),
            }

    # --- Layer 2: Heading-level analysis ---
    if heading_index_map:
        h1_headings = {k: v for k, v in heading_index_map.items() if v["level"] == 1}
        h2_headings = {k: v for k, v in heading_index_map.items() if v["level"] == 2}

        target_headings = h1_headings if h1_headings else h2_headings

        for title, info in target_headings.items():
            if title not in chapters:
                chapters[title] = {
                    "pageNumber": info["pageNumber"],
                    "contentIndex": info["contentIndex"],
                    "level": info["level"],
                }

    # --- Layer 3: Regex pattern matching ---
    for c in contents:
        text = (c.get("cleaned_text") or c.get("text", "")).strip()
        if not text:
            continue
        for pattern in CHAPTER_PATTERNS:
            if pattern.search(text) and text not in chapters:
                chapters[text] = {
                    "pageNumber": c.get("pageNumber", 1),
                    "contentIndex": c.get("index", 1),
                    "level": c.get("level", 1) if c.get("type") == "heading" else 1,
                }
                break

    # --- Layer 4: LLM-assisted refinement ---
    try:
        words_collected = 0
        sample_texts = []
        for c in contents:
            if c.get("type") == "image":
                continue
            t = c.get("cleaned_text") or c.get("text", "")
            if t:
                sample_texts.append(t)
                words_collected += len(t.split())
                if words_collected >= 3000:
                    break

        heading_list = "\n".join(
            f"- [{info.get('contentIndex', '?')}] (H{info.get('level', '?')}, p{info.get('pageNumber', '?')}): {title}"
            for title, info in heading_index_map.items()
        )

        existing_chapter_list = "\n".join(
            f"- [{info.get('contentIndex', '?')}]: {title}"
            for title, info in chapters.items()
        )

        user_content = (
            f"=== BOOK CONTENT (first ~3000 words) ===\n{' '.join(sample_texts[:50])}\n\n"
            f"=== ALL HEADINGS ===\n{heading_list}\n\n"
            f"=== CHAPTERS FOUND SO FAR ===\n{existing_chapter_list or '(none)'}"
        )

        response = _enrichment_client.beta.chat.completions.parse(
            model=ENRICHMENT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are analyzing a book's structure. Given the book's content, all headings, "
                        "and chapters already detected, identify any additional chapter-level boundaries "
                        "that were missed. Only return headings that exist in the ALL HEADINGS list. "
                        "Each entry must include the exact heading text and its content_index from the list. "
                        "If no additional chapters are needed, return an empty list."
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            response_format=ChapterDetectionResponse,
        )

        llm_cost = _chat_cost_usd(response.usage)
        llm_chapters = response.choices[0].message.parsed.chapters
        for entry in llm_chapters:
            if entry.title not in chapters and entry.title in heading_index_map:
                info = heading_index_map[entry.title]
                chapters[entry.title] = {
                    "pageNumber": info["pageNumber"],
                    "contentIndex": info["contentIndex"],
                    "level": info["level"],
                }
        print(f"[chapters] LLM added {len(llm_chapters)} chapter candidates (cost=${llm_cost:.6f})")

    except Exception as e:
        print(f"[chapters] LLM chapter refinement failed: {e}")

    # --- Layer 5: Page 1 guarantee ---
    has_page_one = any(
        info.get("pageNumber") == 1 or info.get("contentIndex") == 1
        for info in chapters.values()
    )
    if not has_page_one and contents:
        chapters["Beginning"] = {
            "pageNumber": 1,
            "contentIndex": 1,
            "level": 0,
        }

    metadata["chapters"] = chapters

    word_counts = find_chapter_word_counts(chapters, contents)
    for chapter_title, word_count in word_counts.items():
        if chapter_title in metadata["chapters"]:
            metadata["chapters"][chapter_title]["word_count"] = word_count

    print(f"[chapters] Final chapter count: {len(chapters)}")
    return metadata, llm_cost


def create_md_metadata(md_path: str, pdf_path: str, existing_json: dict) -> dict:
    """Create metadata from markdown and PDF files.
    
    Args:
        md_path: Path to the markdown file
        pdf_path: Path to the PDF file
        existing_json: The existing marker metadata JSON (with table_of_contents)
    
    Returns:
        Dictionary containing the metadata
    """
    metadata = extract_markdown_contents_with_ranges(md_path, pdf_path)
    print(f"Total Contents Extracted: {metadata['content_count']}")

    for index, headings in enumerate(existing_json.get('table_of_contents', [])):
        title = headings['title'].replace('\n','').strip()
        if title in metadata['all_headings']:
            metadata['chapters'][title] = metadata['all_headings'][title]
            metadata['chapters'][title]['level'] = headings.get('level',1)

    word_counts = find_chapter_word_counts(metadata['chapters'], metadata['contents'])

    for chapter_title, word_count in word_counts.items():
        if chapter_title in metadata['chapters']:
            metadata['chapters'][chapter_title]['word_count'] = word_count

    metadata.pop('all_headings', None)
    return metadata
