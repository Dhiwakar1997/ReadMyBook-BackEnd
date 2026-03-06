from typing import Literal
from pydantic import BaseModel, Field, create_model
from openai import OpenAI

client = OpenAI()
ENRICHMENT_MODEL = "gpt-4.1-mini"

# gpt-4.1-mini pricing (USD per token)
_INPUT_COST_PER_TOKEN = 0.40 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 1.60 / 1_000_000


def _chat_cost_usd(usage) -> float:
    """Calculate USD cost from a chat completion usage object."""
    if not usage:
        return 0.0
    return (
        usage.prompt_tokens * _INPUT_COST_PER_TOKEN
        + usage.completion_tokens * _OUTPUT_COST_PER_TOKEN
    )

BOOK_CATEGORIES = {
    "technical_engineering": [
        "computer_science", "software_engineering", "artificial_intelligence",
        "data_science", "cybersecurity", "networking", "electronics",
        "mechanical_engineering", "civil_engineering", "robotics", "devops_cloud",
    ],
    "science_math": [
        "physics", "chemistry", "biology", "mathematics", "statistics",
        "astronomy", "earth_science", "environmental_science", "biotechnology",
    ],
    "business_economics": [
        "economics", "finance", "accounting", "marketing", "management",
        "entrepreneurship", "business_strategy", "operations_management", "startup_guides",
    ],
    "education_textbooks": [
        "school_textbooks", "university_textbooks", "exam_preparation",
        "study_guides", "reference_books", "curriculum_material",
    ],
    "research_papers": [
        "journal_articles", "conference_papers", "thesis_dissertations",
        "white_papers", "technical_reports", "survey_papers",
    ],
    "fiction_literature": [
        "novels", "short_stories", "fantasy", "science_fiction",
        "mystery_thriller", "historical_fiction", "romance", "drama",
        "poetry", "literary_fiction",
    ],
    "history_society": [
        "world_history", "political_science", "sociology", "anthropology",
        "cultural_studies", "geography", "biographies", "autobiographies",
    ],
    "law_policy": [
        "legal_textbooks", "case_law", "contracts", "government_policy",
        "regulations", "compliance_documents", "international_law",
    ],
    "manuals_documentation": [
        "software_documentation", "product_manuals", "user_guides",
        "installation_guides", "api_documentation", "technical_manuals", "how_to_guides",
    ],
    "self_help_psychology": [
        "self_improvement", "productivity", "psychology", "mental_health",
        "career_guides", "leadership", "motivation", "mindfulness",
    ],
}

CategoryKey = Literal[
    "technical_engineering",
    "science_math",
    "business_economics",
    "education_textbooks",
    "research_papers",
    "fiction_literature",
    "history_society",
    "law_policy",
    "manuals_documentation",
    "self_help_psychology",
]

CATEGORY_DESCRIPTIONS = {
    "technical_engineering": "Computer science, software engineering, AI, data science, cybersecurity, networking, electronics, mechanical/civil engineering, robotics, DevOps",
    "science_math": "Physics, chemistry, biology, mathematics, statistics, astronomy, earth science, environmental science, biotechnology",
    "business_economics": "Economics, finance, accounting, marketing, management, entrepreneurship, business strategy, operations, startup guides",
    "education_textbooks": "School/university textbooks, exam preparation, study guides, reference books, curriculum material",
    "research_papers": "Journal articles, conference papers, thesis/dissertations, white papers, technical reports, survey papers",
    "fiction_literature": "Novels, short stories, fantasy, science fiction, mystery/thriller, historical fiction, romance, drama, poetry, literary fiction",
    "history_society": "World history, political science, sociology, anthropology, cultural studies, geography, biographies, autobiographies",
    "law_policy": "Legal textbooks, case law, contracts, government policy, regulations, compliance documents, international law",
    "manuals_documentation": "Software documentation, product manuals, user guides, installation guides, API documentation, technical manuals, how-to guides",
    "self_help_psychology": "Self-improvement, productivity, psychology, mental health, career guides, leadership, motivation, mindfulness",
}

SUBCATEGORY_DESCRIPTIONS = {
    "technical_engineering": {
        "computer_science": "Algorithms, data structures, computation theory, programming fundamentals",
        "software_engineering": "Software design, development methodologies, testing, architecture",
        "artificial_intelligence": "Machine learning, deep learning, NLP, computer vision, neural networks",
        "data_science": "Data analysis, visualization, big data, data engineering, analytics",
        "cybersecurity": "Network security, cryptography, ethical hacking, information security",
        "networking": "Computer networks, protocols, distributed systems, telecommunications",
        "electronics": "Circuit design, embedded systems, signal processing, semiconductor devices",
        "mechanical_engineering": "Thermodynamics, fluid mechanics, materials science, manufacturing",
        "civil_engineering": "Structural engineering, construction, geotechnical, transportation",
        "robotics": "Robot design, control systems, autonomous systems, mechatronics",
        "devops_cloud": "Cloud computing, containerization, CI/CD, infrastructure as code",
    },
    "science_math": {
        "physics": "Classical mechanics, quantum physics, electromagnetism, relativity, optics",
        "chemistry": "Organic, inorganic, physical chemistry, biochemistry, analytical chemistry",
        "biology": "Cell biology, genetics, evolution, ecology, microbiology, anatomy",
        "mathematics": "Algebra, calculus, number theory, topology, discrete mathematics",
        "statistics": "Probability theory, statistical inference, regression, Bayesian analysis",
        "astronomy": "Astrophysics, cosmology, planetary science, observational astronomy",
        "earth_science": "Geology, meteorology, oceanography, seismology",
        "environmental_science": "Climate science, conservation, pollution, sustainability",
        "biotechnology": "Genetic engineering, bioprocessing, bioinformatics, pharmaceutical biotech",
    },
    "business_economics": {
        "economics": "Microeconomics, macroeconomics, econometrics, behavioral economics",
        "finance": "Corporate finance, investment, banking, financial markets, risk management",
        "accounting": "Financial accounting, managerial accounting, auditing, taxation",
        "marketing": "Digital marketing, branding, consumer behavior, market research",
        "management": "Organizational behavior, human resources, project management",
        "entrepreneurship": "Startup creation, venture capital, business models, innovation",
        "business_strategy": "Competitive strategy, business planning, strategic management",
        "operations_management": "Supply chain, logistics, quality management, process optimization",
        "startup_guides": "Lean startup methodology, fundraising, go-to-market strategy",
    },
    "education_textbooks": {
        "school_textbooks": "K-12 educational materials, primary and secondary school subjects",
        "university_textbooks": "Undergraduate and graduate course materials, academic textbooks",
        "exam_preparation": "Test prep materials, practice exams, competitive examination guides",
        "study_guides": "Summary guides, revision notes, learning aids, quick references",
        "reference_books": "Encyclopedias, dictionaries, handbooks, atlases, compilations",
        "curriculum_material": "Syllabi, lesson plans, educational standards, teaching materials",
    },
    "research_papers": {
        "journal_articles": "Peer-reviewed research articles from academic journals",
        "conference_papers": "Papers presented at academic or industry conferences",
        "thesis_dissertations": "Master's theses, PhD dissertations, academic research documents",
        "white_papers": "Industry white papers, position papers, authoritative reports",
        "technical_reports": "Technical documentation, research lab reports, institutional publications",
        "survey_papers": "Literature reviews, systematic surveys, state-of-the-art overviews",
    },
    "fiction_literature": {
        "novels": "Full-length fictional narratives, literary novels, popular fiction",
        "short_stories": "Short fiction collections, anthologies, novellas",
        "fantasy": "High fantasy, urban fantasy, magical realism, epic fantasy",
        "science_fiction": "Hard sci-fi, space opera, cyberpunk, dystopian fiction",
        "mystery_thriller": "Detective fiction, crime novels, psychological thrillers, suspense",
        "historical_fiction": "Fiction set in historical periods, reimagined historical events",
        "romance": "Love stories, contemporary romance, historical romance",
        "drama": "Literary drama, family sagas, character-driven narratives",
        "poetry": "Poetry collections, verse, spoken word, poetic forms",
        "literary_fiction": "Award-winning fiction, experimental prose, character studies",
    },
    "history_society": {
        "world_history": "Ancient, medieval, modern history, civilizations, world events",
        "political_science": "Government systems, political theory, international relations, public policy",
        "sociology": "Social structures, inequality, culture, social institutions, demographics",
        "anthropology": "Cultural anthropology, archaeology, human evolution, ethnography",
        "cultural_studies": "Media studies, gender studies, postcolonial studies, cultural theory",
        "geography": "Human geography, physical geography, geopolitics, cartography",
        "biographies": "Life stories of notable individuals, biographical accounts",
        "autobiographies": "Self-written life accounts, memoirs, personal narratives",
    },
    "law_policy": {
        "legal_textbooks": "Law school materials, legal theory, jurisprudence",
        "case_law": "Court decisions, legal precedents, case analyses",
        "contracts": "Contract law, drafting, commercial agreements, legal templates",
        "government_policy": "Public policy analysis, policy documents, government reports",
        "regulations": "Regulatory frameworks, compliance requirements, industry standards",
        "compliance_documents": "Corporate compliance, risk management, audit documentation",
        "international_law": "Treaties, international agreements, human rights law, trade law",
    },
    "manuals_documentation": {
        "software_documentation": "Code documentation, architecture docs, developer guides",
        "product_manuals": "Product operation guides, specification sheets, assembly instructions",
        "user_guides": "End-user documentation, tutorials, getting started guides",
        "installation_guides": "Setup instructions, deployment guides, configuration manuals",
        "api_documentation": "API references, endpoint documentation, integration guides",
        "technical_manuals": "Service manuals, maintenance guides, technical specifications",
        "how_to_guides": "Step-by-step instructions, tutorials, procedural documentation",
    },
    "self_help_psychology": {
        "self_improvement": "Personal development, habit formation, goal setting, life skills",
        "productivity": "Time management, efficiency, work optimization, focus techniques",
        "psychology": "Cognitive psychology, behavioral psychology, social psychology",
        "mental_health": "Anxiety, depression, therapy approaches, emotional wellbeing",
        "career_guides": "Job searching, career development, professional growth, networking",
        "leadership": "Management leadership, team building, executive development",
        "motivation": "Inspirational, achievement mindset, resilience, success principles",
        "mindfulness": "Meditation, mindful living, stress reduction, contemplative practices",
    },
}


class BookSummaryResponse(BaseModel):
    title: str = Field(..., description="The inferred title of the book, extracted from the content. Do not invent a title.")
    summary: str = Field(..., description="A 2-4 sentence factual summary of the book's content and themes, suitable for a library catalog entry.")


class CategoryResponse(BaseModel):
    category: CategoryKey = Field(..., description="The single best-matching category for this book.")


def build_book_sample(metadata: dict) -> str:
    """Extract a representative text sample from metadata contents (~3000 words)."""
    contents = metadata.get("contents", [])
    if not contents:
        return ""

    texts = []
    word_budget = 0

    for c in contents:
        if c.get("type") == "image":
            continue
        t = c.get("cleaned_text") or c.get("text", "")
        if t:
            texts.append(t)

    if not texts:
        return ""

    full_text_words = []
    for t in texts:
        full_text_words.extend(t.split())

    total_words = len(full_text_words)

    sample_parts = []

    head_limit = 1500
    sample_parts.append(" ".join(full_text_words[:head_limit]))
    word_budget += min(head_limit, total_words)

    chapters = metadata.get("chapters", {})
    if chapters:
        chapter_list = "Chapters: " + ", ".join(chapters.keys())
        sample_parts.append(chapter_list)

    if total_words > 3000:
        mid_start = total_words // 2 - 250
        mid_end = mid_start + 500
        sample_parts.append(" ".join(full_text_words[mid_start:mid_end]))

    if total_words > 2000:
        tail_start = max(total_words - 500, head_limit)
        sample_parts.append(" ".join(full_text_words[tail_start:]))

    return "\n\n---\n\n".join(sample_parts)


def generate_book_summary(metadata: dict) -> tuple[dict, float]:
    """LLM call 1: Generate title and summary. Returns (result_dict, cost_usd)."""
    sample = build_book_sample(metadata)
    if not sample:
        return {"title": "", "summary": ""}, 0.0

    try:
        response = client.beta.chat.completions.parse(
            model=ENRICHMENT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a librarian cataloging a book. Given sample text from a book, "
                        "extract the actual title and write a concise 2-4 sentence summary.\n\n"
                        "Rules:\n"
                        "- Extract the title as it appears in the content. Do not invent one.\n"
                        "- If no clear title is found, use the most prominent heading.\n"
                        "- The summary should be factual and describe what the book covers.\n"
                        "- Handle all document types: textbooks, novels, research papers, manuals, etc."
                    ),
                },
                {"role": "user", "content": sample},
            ],
            response_format=BookSummaryResponse,
        )
        cost = _chat_cost_usd(response.usage)
        result = response.choices[0].message.parsed
        print(f"[enrichment] Summary generated: title='{result.title}' (cost=${cost:.6f})")
        return {"title": result.title, "summary": result.summary}, cost
    except Exception as e:
        print(f"[enrichment] Summary generation failed: {e}")
        return {"title": "", "summary": ""}, 0.0


def classify_book_category(metadata: dict) -> tuple[str, float]:
    """LLM call 2: Classify category. Returns (category_key, cost_usd)."""
    sample = build_book_sample(metadata)
    if not sample:
        return "education_textbooks", 0.0

    cat_lines = [f"- {key}: {desc}" for key, desc in CATEGORY_DESCRIPTIONS.items()]
    system_prompt = (
        "Classify this book into exactly one category.\n\n"
        + "\n".join(cat_lines)
    )

    try:
        response = client.beta.chat.completions.parse(
            model=ENRICHMENT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": sample},
            ],
            response_format=CategoryResponse,
        )
        cost = _chat_cost_usd(response.usage)
        category = response.choices[0].message.parsed.category
        print(f"[enrichment] Category classified: {category} (cost=${cost:.6f})")
        return category, cost
    except Exception as e:
        print(f"[enrichment] Category classification failed: {e}")
        return "education_textbooks", 0.0


def _build_subcategory_model(category: str):
    """Build a Pydantic model with a Literal enum scoped to the resolved category."""
    valid_subs = tuple(BOOK_CATEGORIES[category])
    SubCatLiteral = Literal[valid_subs]  # type: ignore
    return create_model(
        "SubCategoryResponse",
        sub_categories=(list[SubCatLiteral], Field(
            ...,
            description=f"1-3 most relevant subcategories for this book within '{category}'.",
        )),
    )


def classify_sub_categories(metadata: dict, category: str) -> tuple[list[str], float]:
    """LLM call 3: Classify subcategories. Returns (sub_categories, cost_usd)."""
    if category not in BOOK_CATEGORIES:
        return [BOOK_CATEGORIES.get("education_textbooks", ["reference_books"])[0]], 0.0

    sample = build_book_sample(metadata)
    if not sample:
        return [BOOK_CATEGORIES[category][0]], 0.0

    descriptions = SUBCATEGORY_DESCRIPTIONS.get(category, {})
    sub_lines = [f"- {key}: {desc}" for key, desc in descriptions.items()]
    system_prompt = (
        f"This book belongs to the '{category}' category.\n"
        f"Pick 1-3 most relevant subcategories:\n\n"
        + "\n".join(sub_lines)
    )

    SubCategoryModel = _build_subcategory_model(category)

    try:
        response = client.beta.chat.completions.parse(
            model=ENRICHMENT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": sample},
            ],
            response_format=SubCategoryModel,
        )
        cost = _chat_cost_usd(response.usage)
        subs = response.choices[0].message.parsed.sub_categories
        print(f"[enrichment] Subcategories classified: {subs} (cost=${cost:.6f})")
        return list(subs), cost
    except Exception as e:
        print(f"[enrichment] Subcategory classification failed: {e}")
        return [BOOK_CATEGORIES[category][0]], 0.0
