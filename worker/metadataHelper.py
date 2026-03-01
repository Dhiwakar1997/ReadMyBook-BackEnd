from pypdf import PdfReader
from markdown_it import MarkdownIt

import json
import re

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
    
def find_text_pages(pages, query, current_page):
    query = query.lower()
    results = []
    search_window = 10
    start_page = max(0, current_page - search_window)
    stop_page = min(len(pages), current_page + search_window)

    # Split the query into 5 slices
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
    # if not results:
    #     print(f"Query not found in PDF: {query}")
    #     print(f"Current Page: {current_page}, page text snippet: {pages[current_page-1]}")
    return results

def clean_text(text: str) -> str:
    remove_special_chars = re.sub(r"[^a-zA-Z0-9 ]+", "", text)
    remove_spaces = re.sub(r"[\n\r\s\t]","", remove_special_chars).strip()
    return remove_spaces.lower()

def extract_markdown_contents_with_ranges(path, pdf_path):
    pdf_file = PdfReader(pdf_path)
    pdfPages = [clean_text(page.extract_text()) or "" for page in pdf_file.pages]

    unMatchCount = 0
    pageNumber = 1
    md = MarkdownIt().enable("table")

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    tokens = md.parse(text)

    contents = []
    headings = {}
    cursor = 0


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
            type = "image" if re.match(r'\!\[\]\((.+)\)', content) else "paragraph"
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
            if content['type']!="table":
                clean_query = clean_text(content["text"])
                content['cleaned_text'] = clean_highlighted_query(content["text"])
                pages = find_text_pages(pdfPages, clean_query, pageNumber)

                if not pages:
                    unMatchCount+=1
                    #print("Unmatched content Count: ",unMatchCount)
                #print(pages, pageNumber)
                tempPage = pageNumber
                tempDif = float("inf")
                for page in pages:
                    if abs(page-pageNumber) < tempDif:
                        tempDif = abs(page-pageNumber)
                        tempPage = page
                pageNumber = tempPage
                content['word_count']= len(content['text'].split())

            content['index']= len(contents)+1
            content['pageNumber']= pageNumber

            if content['type']=='heading':
                headings[content["cleaned_text"]] = {'pageNumber': pageNumber,    'contentIndex': content['index']}
            
            if content['text']!='':
                contents.append(content)

    print(f"Total Unmatched contents: {unMatchCount}/{len(contents)}")
    print(f"Match Rate: {(len(contents)-unMatchCount)/len(contents)*100:.2f}%")
    metadata = {"content_count": len(contents), "heading_count": len(headings),"contents": contents, "all_headings": headings,"chapters":{}, "unmatched_count": unMatchCount, "match_rate": (len(contents)-unMatchCount)/len(contents)*100}
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

