# ══════════════════════════════════════════════════════════════════════════
# FILMVISION BACKEND — ARCHITECTURE OVERVIEW
# ══════════════════════════════════════════════════════════════════════════
# This file is one Flask app made of several independently-labeled parts.
# Search for the bracketed tags below (e.g. search this file for "[XGBOOST]")
# to jump straight to any part. This hierarchy matches the thesis paper's
# Conceptual Framework: Comparative Analysis (KNN) → real-world market check
# → Predictive Analysis (XGBoost) → Budget Recommendation → Groq synthesis.
#
#   [AUTH / STORAGE — EXTERNAL FILE]
#       Account login, sessions, and any saved/history analyses are handled
#       in auth.py (imported below as auth_bp), NOT in this file. Nothing in
#       app.py itself persists a user's past analyses — if that exists, it
#       lives in auth.py or a database module this file doesn't touch.
#
#   [KNN] — finds similar/comparable films for the pitch, blending a
#       trained K-Nearest-Neighbors model with live TMDB search results.
#       Runs FIRST in /analyze — the paper's "Comparative Analysis" stage.
#       See get_surface_films(), get_deep_films(), get_similar_films_hybrid(),
#       _knn_score_single().
#
#   [LIVE MARKET / INTERNET] — the only parts of this app that make live
#       calls to check "what's happening in the real market right now":
#       fetch_market_pulse() (numeric TMDB genre benchmark) and
#       fetch_industry_trends() (DuckDuckGo + TMDB fallback text). Runs
#       SECOND, after KNN retrieval.
#
#   [XGBOOST]  — the 4-pillar prediction model (Commercial/Financial/
#       Audience/Cultural) — the paper's "Predictive Analysis" stage. Runs
#       THIRD, after [KNN] and [LIVE MARKET]. Its own 4 independent pillar
#       scores are computed purely from the pitch text + structured form
#       fields (plus a real, leave-one-out-safe KNN-neighbor signal baked
#       into its own TRAINING — v14: build_feature_vector's neighbor_*
#       features). XGBoost's trained weights don't literally re-train per
#       request on this exact pitch's live KNN/market results — but the
#       PREDICTION METRIC this app actually returns is only ever finalized
#       by compute_live_market_adjustment(), which folds [KNN]'s comps and
#       [LIVE MARKET]'s pulse into a bounded correction on top of XGBoost's
#       independent read, before anything downstream sees it. See
#       predict_pillars_xgb(), predict_all_pillars(), and the PIPELINE ORDER
#       comment inside analyze() for the exact honesty note on this.
#
#   [XGBOOST + KNN, combined] — Budget Recommendation. Runs FOURTH.
#       _xgb_budget_tier_sweep() picks a tier via XGBoost's own Financial
#       pillar; cross_reference_budget_tier() then blends that against the
#       REAL reported budgets of the top KNN-retrieved comps (fetched live
#       via fetch_comp_budgets(), the same TMDB detail-endpoint approach the
#       training notebook validated in Step 15a/15b) — this is the paper's
#       stated "cross-referencing...with the budget levels of the similar
#       films retrieved through KNN," actually implemented.
#
#   [GROQ] — the LLM that writes all of the narrative text (AI Strategic
#       Analysis, Story Advisor, Budget Recommendation prose, per-film "How
#       it Connects" reasons). Runs LAST. Every Groq prompt is handed the
#       finished XGBoost + KNN + live-market + budget results as plain
#       text/JSON context — Groq never re-derives or overrides any number,
#       it only explains numbers it's given. See _call_groq() (the raw API
#       wrapper) and get_ai_analysis() / get_budget_recommendation() /
#       get_story_advice() / get_all_film_reasons() (the 4 places that
#       build a Groq prompt and hand it XGBoost+KNN+live-market results).
#
#   PIPELINE ORDER (see analyze(), the /analyze route, for the literal code):
#       1. KNN similar-film retrieval (blends trained KNN + live TMDB) —
#          Comparative Analysis
#       2. Live market pulse + industry trends (live internet calls)
#       3. XGBoost 4-pillar prediction (independent pillar scores), then
#          steps 1+2 combined into a bounded adjustment on top of that score
#          (compute_live_market_adjustment) → this finalizes the numeric
#          prediction metric that gets displayed — Predictive Analysis
#       4. Budget recommendation: XGBoost tier-sweep argmax, cross-referenced
#          against KNN comps' real TMDB budgets (cross_reference_budget_tier)
#       5. Groq narrative calls — AI Strategic Analysis, Story Advisor, and
#          per-film reasons — each one receives ALL of the above as context
# ══════════════════════════════════════════════════════════════════════════

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import os, requests, json, re, pickle, numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv

try:
    from sklearn.metrics.pairwise import cosine_similarity
except Exception:
    cosine_similarity = None

# v12: sentence-transformers powers real SEMANTIC (meaning-based) pitch/overview
# matching, replacing TF-IDF (a LEXICAL, literal-shared-word-only representation).
# This is an optional dependency the same way NLTK is below — if it can't be
# imported or the model can't be loaded (see load_text_embedder), everything that
# uses it degrades gracefully to _keyword_overlap, the original fallback.
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except Exception as e:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    print(f"[Embed] sentence-transformers unavailable, will use fallback matching: {e}")

# XGBoost is loaded explicitly now (v6): each of the 4 pillar models is saved in
# native JSON format (version-independent) and loaded via XGBRegressor().load_model(),
# rather than unpickled as a single opaque object like the old single-model version.
from xgboost import XGBRegressor

load_dotenv()

# ── NLTK (used for anchor-noun extraction — see _extract_anchor_words) ─
# Optional dependency: if NLTK or its data packages aren't available, anchor
# extraction falls back to the fixed CINEMATIC_NOUNS list so the app never
# crashes over this.
NLTK_AVAILABLE = False
try:
    import nltk
    from nltk import pos_tag, word_tokenize
    for _pkg_path, _pkg_name in [
        ("tokenizers/punkt", "punkt"),
        ("tokenizers/punkt_tab", "punkt_tab"),
        ("taggers/averaged_perceptron_tagger", "averaged_perceptron_tagger"),
        ("taggers/averaged_perceptron_tagger_eng", "averaged_perceptron_tagger_eng"),
    ]:
        try:
            nltk.data.find(_pkg_path)
        except LookupError:
            try:
                nltk.download(_pkg_name, quiet=True)
            except Exception:
                pass
    NLTK_AVAILABLE = True
except Exception as e:
    print(f"[NLTK] Unavailable, will use fallback anchor extraction: {e}")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fv-dev-secret-change-in-prod")
if app.secret_key == "fv-dev-secret-change-in-prod":
    print("[SECURITY WARNING] SECRET_KEY is not set — using an insecure default that's "
          "visible in this source file. Set a real SECRET_KEY environment variable on "
          "your host before deploying, or anyone who has seen this code can forge valid "
          "login sessions for any user.")

# Since frontend and backend are served from the same origin (Flask serves the built Vue
# app directly), cookies don't need cross-site handling — the default SameSite=Lax is
# correct. SESSION_COOKIE_SECURE is tied to FLASK_ENV so login still works over plain
# HTTP during local development, but requires HTTPS once FLASK_ENV=production is set on
# your host (browsers won't send a Secure cookie over HTTP, so hardcoding this True would
# silently break local testing).
IS_PRODUCTION = os.getenv("FLASK_ENV", "development") == "production"
app.config.update(
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    SESSION_COOKIE_SAMESITE="Lax",
)

CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173"], supports_credentials=True)

# ── [AUTH / STORAGE — EXTERNAL FILE] ────────────────────────────────────
# Account login, session/token handling, and any saved-analysis history all
# live in auth.py, not here. This line only wires that blueprint's routes
# (e.g. /auth/login, /auth/register — exact paths defined in auth.py) into
# this Flask app. If you need those parts commented too, that's a separate
# file this pass didn't touch.
from auth import auth_bp
app.register_blueprint(auth_bp)

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TMDB_BASE    = "https://api.themoviedb.org/3"

# ── [XGBOOST] + [KNN] — model artifact loading ──────────────────────────
# v6: Commercial/Financial/Audience/Cultural are now 4 INDEPENDENT XGBoost
# regressors (each its own target — see the v6 training notebook), not one
# model fanned out by rules. PILLAR_MODELS holds all 4 [XGBOOST]. Two
# additional artifacts (struct_cols, struct_scaler, neighbor_knn) support the
# neighbor-derived features described in build_feature_vector() below — this
# neighbor_knn is a SEPARATE, SMALLER [KNN] model used only to enrich
# XGBoost's own input features (distinct from knn_model below, the [KNN]
# model used for similar-film retrieval). pca_text supports the pitch/theme
# text features (v12: sentence-embedding + PCA, formerly TF-IDF +
# TruncatedSVD — see load_text_embedder). All are treated as one atomic set —
# if any are missing, ML_READY stays False and everything falls back to the
# original rule-based/heuristic scoring, unchanged.
ML_READY      = False
PILLAR_MODELS = {}          # [XGBOOST] {"commercial":..,"financial":..,"audience":..,"cultural":..}
knn_model     = None        # [KNN] similar-FILM retrieval model (see get_similar_films_hybrid)
scaler        = None
feature_cols  = None        # expanded: structured + text_i + neighbor_* (order matters)
struct_cols   = None        # the structured-only subset of feature_cols
struct_scaler = None        # fit on struct_cols only — feeds neighbor_knn
neighbor_knn  = None        # [KNN] used ONLY to enrich XGBoost's feature vector (not for
                             # similar-film retrieval — that's knn_model above)
pca_text      = None        # v12: PCA reducer: sentence-embedding(pitch+theme) -> N_TEXT_EMB
                             # dims. Replaces the old TF-IDF+TruncatedSVD reducer (svd_text) —
                             # same role in the pipeline (shrink the text representation down
                             # before it enters the XGBoost feature vector), different, semantic
                             # source representation (see load_text_embedder / build_feature_vector).
N_TEXT_EMB    = 32
film_db       = None
FILM_EMBEDDINGS = None      # v12: (n_films, 384) raw sentence-embedding matrix, ONE row per
                             # film_db row (same order — see the v12 notebook Step 16). Lets
                             # app.py search the app's OWN curated training corpus directly by
                             # meaning, instead of only via live TMDB text search or Groq's
                             # memory of real film titles — see _corpus_semantic_candidates.
PILLAR_MASKS  = {}          # v9: {"financial":["popularity","vote_count_log"],"cultural":["vote_count_log"],...}
                             # — columns to zero out per pillar to prevent target leakage; MUST match
                             # training exactly (see v9 notebook Step 8/16). Defaults to no masking
                             # for any pillar not listed, so older model files without this artifact
                             # still work (just without the leakage fix).

PILLAR_FILES = {             # [XGBOOST] the 4 independent pillar model files
    "commercial": "xgb_commercial.json",
    "financial":  "xgb_financial.json",
    "audience":   "xgb_audience.json",
    "cultural":   "xgb_cultural.json",
}

# v12: the sentence-embedding model is loaded separately from the rest — it's a
# real relevance signal for scoring (see _semantic_similarity) but isn't required
# for the app's core prediction/search flow, so its absence shouldn't flip
# ML_READY off. It's ALSO used inside build_feature_vector for the text features
# when available; if unavailable, those dims just default to 0, same graceful
# degradation philosophy as before (formerly TF-IDF's role — see load_text_embedder).
EMBEDDER_READY   = False
text_embedder    = None
EMBEDDER_NAME    = "all-MiniLM-L6-v2"   # MUST match the model used in the training
                                          # notebook's Step 6 — a different model
                                          # produces a different, incompatible vector
                                          # space, silently corrupting every embedding
                                          # comparison. Loaded locally (no API key /
                                          # network call per-request); first boot on a
                                          # fresh host downloads ~90MB from huggingface.co
                                          # and caches it, so expect a slower cold start.

def load_models():
    """
    Loads every model artifact this app needs from disk, once, at startup:
      - [XGBOOST] the 4 pillar regressors (loaded_pillars, from PILLAR_FILES)
      - [KNN] knn_model.pkl (similar-film retrieval) and neighbor_knn.pkl
        (XGBoost's own internal feature-enrichment KNN — a different model)
    If any single file is missing/corrupt, ML_READY stays False and the whole
    app degrades to rule-based fallbacks — see the ML_READY comment above.
    """
    global ML_READY, PILLAR_MODELS, knn_model, scaler, feature_cols
    global struct_cols, struct_scaler, neighbor_knn, pca_text, N_TEXT_EMB, film_db, PILLAR_MASKS
    global FILM_EMBEDDINGS
    try:
        loaded_pillars = {}
        for pillar, fname in PILLAR_FILES.items():        # [XGBOOST] load all 4 pillar models
            m = XGBRegressor()
            m.load_model(fname)
            loaded_pillars[pillar] = m
        with open("knn_model.pkl",      "rb") as f: knn_model     = pickle.load(f)  # [KNN] similar-film retrieval
        with open("scaler.pkl",         "rb") as f: scaler        = pickle.load(f)
        with open("feature_cols.pkl",   "rb") as f: feature_cols  = pickle.load(f)
        with open("struct_cols.pkl",    "rb") as f: struct_cols   = pickle.load(f)
        with open("struct_scaler.pkl",  "rb") as f: struct_scaler = pickle.load(f)
        with open("neighbor_knn.pkl",   "rb") as f: neighbor_knn  = pickle.load(f)
        with open("pca_text.pkl",       "rb") as f: pca_text      = pickle.load(f)
        with open("film_database.pkl",  "rb") as f: film_db       = pickle.load(f)

        # v12: raw per-film embedding matrix for direct corpus semantic search
        # (_corpus_semantic_candidates). Non-fatal if missing/misaligned — that
        # search path just stays disabled, same graceful-degradation philosophy
        # as everything else here, rather than blocking ML_READY over it.
        try:
            with open("film_overview_embeddings.pkl", "rb") as f:
                FILM_EMBEDDINGS = pickle.load(f)
            if film_db is not None and len(FILM_EMBEDDINGS) != len(film_db):
                print(f"[Embed] film_overview_embeddings.pkl has {len(FILM_EMBEDDINGS)} rows but "
                      f"film_db has {len(film_db)} — these must come from the SAME training run. "
                      f"Disabling corpus semantic search to avoid scoring the wrong film.")
                FILM_EMBEDDINGS = None
        except FileNotFoundError:
            print("[Embed] film_overview_embeddings.pkl not found — corpus semantic search "
                  "disabled (falls back to live TMDB search + Groq suggestions only).")
        except Exception as e:
            print(f"[Embed] Failed to load film_overview_embeddings.pkl ({e}) — corpus semantic "
                  f"search disabled.")

        # v9: pillar_feature_masks.pkl is loaded separately and non-fatally — an
        # older model bundle (pre-leakage-fix) simply won't have it, and rather
        # than block ML_READY entirely over a file that's new as of this version,
        # we fall back to "no masking" (PILLAR_MASKS stays {}), which reproduces
        # the old (leaky) behavior for that bundle rather than crashing. If you
        # trained with the v9 notebook, this file WILL exist and load normally.
        try:
            with open("pillar_feature_masks.pkl", "rb") as f: PILLAR_MASKS = pickle.load(f)
        except FileNotFoundError:
            PILLAR_MASKS = {}
            print("[ML] pillar_feature_masks.pkl not found — proceeding without pillar "
                  "feature masking (fine for pre-v9 model bundles, but Financial/Cultural "
                  "predictions won't have the target-leakage fix applied).")

        PILLAR_MODELS = loaded_pillars
        N_TEXT_EMB = getattr(pca_text, "n_components", 32)
        ML_READY = True
        print(f"[ML] All 4 pillar models + retrieval artifacts loaded successfully "
              f"({len(feature_cols)} total features). Pillar masks: {PILLAR_MASKS}")
    except FileNotFoundError as e:
        print(f"[ML] Model files not found ({e}). Using fallback scoring.")
    except Exception as e:
        print(f"[ML] Unexpected error loading models ({e}). Using fallback scoring.")

def load_text_embedder():
    global EMBEDDER_READY, text_embedder
    if cosine_similarity is None:
        print("[Embed] scikit-learn cosine_similarity unavailable — using keyword-overlap fallback.")
        return
    if not SENTENCE_TRANSFORMERS_AVAILABLE:
        print("[Embed] sentence-transformers not installed — using keyword-overlap fallback. "
              "Add 'sentence-transformers' to requirements.txt to enable semantic matching.")
        return
    try:
        text_embedder = SentenceTransformer(EMBEDDER_NAME)
        EMBEDDER_READY = True
        print(f"[Embed] {EMBEDDER_NAME} loaded — using real semantic similarity for film matching.")
    except Exception as e:
        print(f"[Embed] Failed to load {EMBEDDER_NAME} ({e}) — using keyword-overlap fallback.")

load_models()
load_text_embedder()

# ── Corpus vocabulary frequency (for anchor-word rarity ranking) ───────
# Built from the trained dataset's own overviews so anchor nouns extracted from
# a pitch can be ranked by rarity — a rarer noun ("factory", "successor") is a
# more specific, more useful search anchor than a common one ("family", "man"),
# even when both are grammatically valid nouns.
_VOCAB_FREQ = {}
def _build_vocab_freq():
    global _VOCAB_FREQ
    if film_db is None:
        return
    try:
        from collections import Counter
        counter = Counter()
        overview_col = next((c for c in ("overview", "overviews", "plot")
                              if c in getattr(film_db, "columns", [])), None)
        if overview_col:
            for text in film_db[overview_col].dropna().astype(str):
                words = re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
                counter.update(w for w in words if len(w) > 3)
        _VOCAB_FREQ = dict(counter)
        print(f"[Vocab] Built rarity vocabulary: {len(_VOCAB_FREQ)} terms")
    except Exception as e:
        print(f"[Vocab] Failed to build frequency table: {e}")

_build_vocab_freq()

# ── Load Filipino film CSV ─────────────────────────────────────────────

# ── Genre mapping ──────────────────────────────────────────────────────
GENRE_MAP = {
    "Action":28,"Adventure":12,"Animation":16,"Comedy":35,
    "Crime":80,"Documentary":99,"Drama":18,"Fantasy":14,
    "Horror":27,"Mystery":9648,"Romance":10749,"Science Fiction":878,
    "Thriller":53,"War":10752,"Western":37,
    # Extended genres — mapped to closest TMDB equivalents
    "Political Drama":18,       # Drama
    "Slice of Life":18,         # Drama
    "Psychological":9648,       # Mystery
    "Philosophical":18,         # Drama
    "Social Commentary":99,     # Documentary
    "Arthouse":18,              # Drama
}

# ── [CULTURAL TRANSPARENCY] Origin-language/region classification ───────
# Addresses a real, named gap: prior to this, every retrieved comp was only
# ever tagged "Filipino" or implicitly lumped into an undifferentiated
# "everything else" bucket (is_english / is_filipino, nothing in between).
# A pitch drawing on, say, Korean, Nigerian, or Brazilian storytelling
# traditions was being compared against — and its cultural fit judged
# against — whatever TMDB's Western/English-skewed catalogue happened to
# retrieve, with no visibility into that skew anywhere in the output.
#
# What this fixes: every retrieved film is now tagged with its real
# original_language and a broad cultural/region grouping, computed from
# data TMDB's search/discover endpoints ALREADY return — no new API calls,
# no retraining. This makes the cultural composition of "similar films"
# visible in the API response and usable by Groq's narrative, instead of
# silently invisible.
#
# What this does NOT fix (stays a named, retrain-required limitation):
# the Cultural Impact pillar's own XGBoost TRAINING TARGET is still built
# from a genre-based cultural-affinity weighting only (see the training
# notebook's cultural_prior()) — it has no region/culture-specific signal
# baked into the model's learned weights. This transparency layer lets a
# user SEE what cultural context their comps are drawn from; it does not
# change what the trained Cultural Impact score itself was trained to
# measure. That requires retraining with richer per-film cultural features
# and is out of scope for an inference-only fix.
#
# Also a real, honest limitation of THIS fix itself: TMDB's language code
# alone can't distinguish, e.g., Spain from Mexico, or Portugal from
# Brazil (both report 'es'/'pt') — region grouping here is coarse by
# necessity, since finer geographic data (production_countries) isn't
# returned by the search/discover endpoints this app already calls, only
# by a per-film detail call this app doesn't make for every candidate.
CULTURAL_REGION_MAP = {
    "en": "English-language (US/UK/AU/etc.)",
    "tl": "Filipino", "fil": "Filipino",
    "ja": "East Asian (Japanese)", "ko": "East Asian (Korean)",
    "zh": "East Asian (Chinese)", "cn": "East Asian (Chinese)", "yue": "East Asian (Chinese)",
    "hi": "South Asian (Hindi)", "ta": "South Asian (Tamil)", "te": "South Asian (Telugu)",
    "ml": "South Asian (Malayalam)", "bn": "South Asian (Bengali)",
    "pa": "South Asian (Punjabi)", "ur": "South Asian (Urdu)",
    "th": "Southeast Asian (Thai)", "vi": "Southeast Asian (Vietnamese)",
    "id": "Southeast Asian (Indonesian)", "ms": "Southeast Asian (Malay)",
    "km": "Southeast Asian (Khmer)", "my": "Southeast Asian (Burmese)",
    "fr": "European (French)", "de": "European (German)", "it": "European (Italian)",
    "ru": "European (Russian)", "pl": "European (Polish)", "nl": "European (Dutch)",
    "sv": "European (Swedish)", "da": "European (Danish)", "no": "European (Norwegian)",
    "fi": "European (Finnish)", "el": "European (Greek)", "tr": "European/W. Asian (Turkish)",
    "cs": "European (Czech)", "hu": "European (Hungarian)", "ro": "European (Romanian)",
    "es": "Spanish-language (Spain/Latin America — language code doesn't distinguish)",
    "pt": "Portuguese-language (Portugal/Brazil — language code doesn't distinguish)",
    "ar": "Middle Eastern/N. African (Arabic)", "fa": "Middle Eastern (Persian)",
    "he": "Middle Eastern (Hebrew)",
    "sw": "African (Swahili)", "am": "African (Amharic)", "ha": "African (Hausa)",
    "yo": "African (Yoruba)", "zu": "African (Zulu)",
}

def classify_film_culture(tmdb_result):
    """
    [CULTURAL TRANSPARENCY] Returns (origin_language_code, region_label) for
    a single TMDB result, using only original_language — the one cultural
    signal reliably present on every search/discover response this app
    already receives, no extra API call needed. See the CULTURAL_REGION_MAP
    comment above for exactly what this does and doesn't capture.
    """
    lang = (tmdb_result.get("original_language") or "").lower()
    if not lang:
        return "", "Unknown"
    return lang, CULTURAL_REGION_MAP.get(lang, f"Other ({lang})")

# ── [CULTURAL TRANSPARENCY, v2] Real production-country classification ──
# classify_film_culture() above is a free, always-available guess from
# original_language alone — but language code can't distinguish Spain from
# Mexico, or Portugal from Brazil (both report "es"/"pt"), and says nothing
# about co-productions. production_countries fixes this, but TMDB only
# returns it from the per-film DETAIL endpoint (/movie/{id}), not the
# search/discover endpoints retrieval already calls — so getting it costs
# one extra live call per film. This upgrade is applied to a bounded number
# of the most relevant retrieved films per request (CULTURAL_COUNTRY_MAX_FETCH)
# rather than every film, to keep that cost predictable; films beyond the
# cap simply keep the free language-based guess, which is still correct
# more often than not, just coarser.
CULTURAL_COUNTRY_MAX_FETCH = 10   # extra live TMDB calls this adds, per /analyze request

CULTURAL_COUNTRY_REGION_MAP = {
    "US": "English-language (US)", "GB": "English-language (UK)", "AU": "English-language (Australia)",
    "CA": "English-language (Canada)", "NZ": "English-language (New Zealand)", "IE": "English-language (Ireland)",
    "PH": "Filipino",
    "JP": "East Asian (Japan)", "KR": "East Asian (South Korea)", "CN": "East Asian (China)",
    "HK": "East Asian (Hong Kong)", "TW": "East Asian (Taiwan)",
    "IN": "South Asian (India)", "PK": "South Asian (Pakistan)", "BD": "South Asian (Bangladesh)",
    "TH": "Southeast Asian (Thailand)", "VN": "Southeast Asian (Vietnam)", "ID": "Southeast Asian (Indonesia)",
    "MY": "Southeast Asian (Malaysia)", "SG": "Southeast Asian (Singapore)",
    "FR": "European (France)", "DE": "European (Germany)", "IT": "European (Italy)",
    "ES": "European (Spain)", "PT": "European (Portugal)", "RU": "European (Russia)",
    "PL": "European (Poland)", "NL": "European (Netherlands)", "SE": "European (Sweden)",
    "DK": "European (Denmark)", "NO": "European (Norway)", "FI": "European (Finland)",
    "GR": "European (Greece)", "TR": "European/W. Asian (Turkey)", "CZ": "European (Czechia)",
    "HU": "European (Hungary)", "RO": "European (Romania)",
    "MX": "Latin American (Mexico)", "BR": "Latin American (Brazil)", "AR": "Latin American (Argentina)",
    "CO": "Latin American (Colombia)", "CL": "Latin American (Chile)", "PE": "Latin American (Peru)",
    "EG": "Middle Eastern/N. African (Egypt)", "SA": "Middle Eastern (Saudi Arabia)",
    "AE": "Middle Eastern (UAE)", "IR": "Middle Eastern (Iran)", "IL": "Middle Eastern (Israel)",
    "NG": "African (Nigeria)", "ZA": "African (South Africa)", "KE": "African (Kenya)", "GH": "African (Ghana)",
}

def fetch_film_production_countries(tmdb_id):
    """
    [CULTURAL TRANSPARENCY, v2] Fetches real production_countries for one
    film via TMDB's detail endpoint. Returns a list of ISO 3166-1 country
    codes (e.g. ["US","MX"]), or [] if the film reports none or the fetch
    fails -- callers must treat [] as "no upgrade available," not "this
    film has no country," since a fetch failure looks the same as genuinely
    missing data at this point.
    """
    try:
        r = requests.get(f"{TMDB_BASE}/movie/{tmdb_id}",
                          params={"api_key": TMDB_API_KEY}, timeout=5)
        detail = r.json()
        return [c.get("iso_3166_1") for c in (detail.get("production_countries") or [])
                if c.get("iso_3166_1")]
    except Exception as e:
        print(f"[CulturalCountries] fetch failed for tmdb_id={tmdb_id}: {e}")
        return []

def classify_film_culture_precise(production_countries):
    """
    [CULTURAL TRANSPARENCY, v2] Turns a list of real ISO country codes into
    a region label. A co-production genuinely has multiple cultural
    origins -- e.g. a US/South-Korea co-production returns BOTH labels,
    joined, rather than collapsing to just one and misrepresenting it as
    single-origin. Unrecognized country codes still surface as "Other (XX)"
    rather than silently vanishing, so nothing is dropped without a trace.
    """
    if not production_countries:
        return "Unknown"
    labels, seen = [], set()
    for code in production_countries:
        label = CULTURAL_COUNTRY_REGION_MAP.get(code, f"Other ({code})")
        if label not in seen:
            seen.add(label); labels.append(label)
    return " / ".join(labels)

def enrich_films_with_precise_culture(films, max_fetch=CULTURAL_COUNTRY_MAX_FETCH):
    """
    [CULTURAL TRANSPARENCY, v2] Upgrades up to `max_fetch` DISTINCT films in
    `films` (deduped by tmdb_id) from the free language-code guess
    (classify_film_culture) to real production_countries data. Mutates each
    film dict IN PLACE -- intl_surface/intl_deep/ph_surface/ph_deep and
    all_films in analyze() all hold references to these SAME dict objects
    (list concatenation doesn't copy them), so one pass over any combined
    list updates every group that displays them. Films beyond the cap, or
    any whose detail fetch fails/returns nothing, simply keep whatever
    origin_region classify_film_culture already gave them in _score_and_rank
    -- this is a best-effort upgrade layered on top of an always-present
    fallback, never a replacement that can leave a film unlabeled.
    """
    seen_ids, fetched = set(), 0
    for f in films:
        tid = f.get("tmdb_id")
        if not tid or tid in seen_ids or tid < 0:
            continue
        seen_ids.add(tid)
        if fetched >= max_fetch:
            continue
        fetched += 1
        countries = fetch_film_production_countries(tid)
        if countries:
            f["origin_countries"] = countries
            f["origin_region"]    = classify_film_culture_precise(countries)
    return films

# Scoring classification for extended genres
GENRE_COMMERCIAL_CLASS = {
    "Political Drama": "medium", "Slice of Life": "medium",
    "Psychological": "medium",   "Philosophical": "low",
    "Social Commentary": "low",  "Arthouse": "low",
}

# ── Helpers ────────────────────────────────────────────────────────────
def normalize(val, fallback=""):
    if isinstance(val, list): return ", ".join(val) if val else fallback
    return val or fallback

def as_list(val):
    if isinstance(val, list): return val
    return [val] if val else []

# ── Audience/Content mismatch detector ────────────────────────────────
def detect_mismatch(genres, tones, audiences, theme, pitch):
    penalty = 0
    flags   = []
    adult_tones    = {"Dark","Gritty","Experimental","Surreal","Satirical","Suspenseful"}
    adult_genres   = {"Horror","Thriller","Crime","War"}
    adult_keywords = ["sex","sexual","violence","violent","gore","blood","explicit",
                      "drug","drugs","murder","kill","killing","sicario","assassination"]
    has_adult_tone    = any(t in adult_tones  for t in tones)
    has_adult_genre   = any(g in adult_genres for g in genres)
    pitch_lower       = (pitch + " " + theme).lower()
    has_adult_content = any(w in pitch_lower  for w in adult_keywords)
    family_audiences  = {"Families","Teens"}
    chosen_family     = [a for a in audiences if a in family_audiences]
    if chosen_family and (has_adult_tone or has_adult_genre or has_adult_content):
        penalty += 25
        parts = []
        if has_adult_content: parts.append("explicit keywords in pitch")
        if has_adult_genre:   parts.append("adult genre: " + ", ".join(g for g in genres if g in adult_genres))
        if has_adult_tone:    parts.append("adult tone: " + ", ".join(t for t in tones if t in adult_tones))
        flags.append(f"AUDIENCE MISMATCH: {', '.join(chosen_family)} audience with " + "; ".join(parts))
    return penalty, flags

def detect_purpose_mismatch(audiences, purposes, distribution, budget):
    penalty = 0
    flags   = []
    school_purposes  = {"Academic / School Requirement","Just for Fun","Build a Portfolio"}
    big_distribution = {"Major Theatrical Release"}
    big_budget       = {"Blockbuster ($150M+)","High ($50M-$150M)"}
    is_school   = any(p in school_purposes  for p in purposes)
    is_big_dist = any(d in big_distribution for d in distribution)
    if is_school and is_big_dist and budget in big_budget:
        penalty += 15
        flags.append("SCALE MISMATCH: School/portfolio project with major theatrical + high budget.")
    return penalty, flags

# ── Sub-metric scoring ─────────────────────────────────────────────────
# Genre "natural budget zone" — what budget these genres normally need to succeed
LOW_BUDGET_GENRES  = {"Drama","Romance","Documentary","Horror","Mystery",
                      "Thriller","Slice of Life","Psychological","Philosophical",
                      "Social Commentary","Arthouse","Political Drama"}
MID_BUDGET_GENRES  = {"Comedy","Crime","Fantasy","Adventure","Science Fiction","War"}
HIGH_BUDGET_GENRES = {"Action","Animation","Adventure","Science Fiction"}

def genre_budget_fit_bonus(genres, budget):
    """
    Extracted out of compute_sub_metrics's rule-based Financial score so it can be reused
    anywhere XGBoost's raw financial pillar is used — the final Financial sub-score
    (predict_all_pillars) AND the budget-tier sweep (_xgb_budget_tier_sweep).

    Why this is necessary: XGBoost's financial pillar leans heavily on the budget→
    popularity-proxy feature (see build_feature_vector: Micro=5 ... Blockbuster=150).
    That proxy isn't just correlated with the training target — popularity is literally
    one of the three weighted components financial_target was built from (see the
    validation-study notebook step). So the raw model has effectively learned "higher
    popularity-proxy in -> higher financial score out," almost independent of genre. Left
    uncorrected, a budget-tier sweep that holds genre/tone/pitch constant and only swaps
    budget will pick Blockbuster for nearly any pitch — it isn't reading the story, it's
    reading a number the model was trained to treat as its own answer.

    This reintroduces real domain knowledge XGBoost has no way to have learned on its own:
    whether a given budget tier is economically sane for a given genre. Same
    values/logic that were already in compute_sub_metrics — just callable from more than
    one place now, so nothing silently discards it when XGBoost overrides the score.
    """
    fit_bonus = 0
    for g in genres:
        if g in LOW_BUDGET_GENRES:
            # Low-budget genres: Micro/Low budgets are efficient -> bonus, high budget -> waste
            if budget in ("Micro (<$1M)", "Low ($1M-$10M)"):   fit_bonus += 12
            elif budget == "Mid ($10M-$50M)":                    fit_bonus += 5
            elif budget in ("High ($50M-$150M)", "Blockbuster ($150M+)"): fit_bonus -= 8
        elif g in MID_BUDGET_GENRES:
            if budget == "Mid ($10M-$50M)":                      fit_bonus += 8
            elif budget == "Low ($1M-$10M)":                     fit_bonus += 3
            elif budget == "Blockbuster ($150M+)":               fit_bonus -= 5
        elif g in HIGH_BUDGET_GENRES:
            if budget == "Blockbuster ($150M+)":                 fit_bonus += 10
            elif budget == "High ($50M-$150M)":                  fit_bonus += 8
            elif budget in ("Micro (<$1M)", "Low ($1M-$10M)"):  fit_bonus -= 10
    return fit_bonus


def compute_sub_metrics(data):
    genres      = as_list(data.get("genre"))
    tones       = as_list(data.get("tone"))
    audiences   = as_list(data.get("target_audience"))
    budget      = data.get("budget_range","")
    casting     = as_list(data.get("casting_category"))
    schedule    = data.get("production_schedule","")
    purposes    = as_list(data.get("film_purpose",[]))
    distribution= as_list(data.get("distribution_goal",[]))
    pitch       = data.get("story_pitch","")
    theme       = data.get("main_theme","")

    # Financial — smart budget-genre fit scoring
    # Key insight: ROI depends on whether the budget matches what the film actually needs.
    # A low-budget intimate drama can have HIGHER financial success than an
    # over-budgeted action film, because its break-even is lower.

    # Budget tiers as base score
    budget_base = {"Micro (<$1M)":40,"Low ($1M-$10M)":52,"Mid ($10M-$50M)":62,
                   "High ($50M-$150M)":70,"Blockbuster ($150M+)":78}.get(budget, 45)

    # Fit bonus/penalty: does the budget match what this genre needs?
    fit_bonus = genre_budget_fit_bonus(genres, budget)

    fin = min(95, budget_base + fit_bonus)

    # Casting modifier
    if "A-list Stars" in casting:               fin += 8
    elif "Established Mid-Tier" in casting:     fin += 4
    elif "Unknown/Non-professional" in casting:
        # Unknown cast hurts big-budget films more than indie films
        if budget in ("Micro (<$1M)", "Low ($1M-$10M)"): fin -= 2  # less penalty for indie
        else:                                              fin -= 7

    # Distribution modifier
    if "Major Theatrical Release" in distribution:    fin += 6
    elif "Streaming Platform" in distribution:        fin += 4
    elif "School / Academic Project" in distribution: fin = min(fin, 45)
    elif "Online / Social Media" in distribution:     fin -= 2

    # Purpose modifier
    if "Just for Fun" in purposes:                    fin = min(fin, 50)
    if "Academic / School Requirement" in purposes:   fin = min(fin, 45)

    # Schedule risk
    if schedule == "Under 3 months":  fin -= 8
    elif schedule == "24+ months":    fin -= 3

    mismatch_penalty, mismatch_flags = detect_mismatch(genres, tones, audiences, theme, pitch)
    fin -= mismatch_penalty // 2
    if budget: fin = max(10, min(95, fin))
    else: fin = -1  # no budget = undecided

    # Audience
    audience_base = {"General Audience":75,"Young Adults (18-25)":70,"Adults (26-45)":68,
                     "Families":72,"Teens":65,"Niche/Cult":52}
    # If no audience selected, return -1 sentinel (undecided)
    if not audiences:
        aud = -1
    else:
        aud = round(sum(audience_base.get(a,60) for a in audiences) / max(len(audiences),1))
    family_safe_tones = {"Uplifting","Humorous","Adventurous","Romantic","Nostalgic","Whimsical","Intimate","Poetic"}
    adult_tones_set   = {"Dark","Gritty","Experimental","Surreal","Satirical","Suspenseful","Ambiguous","Unsettling","Cynical","Tense"}
    family_auds = {"Families","Teens"}
    adult_auds  = {"Adults (26-45)","Young Adults (18-25)"}
    has_family_aud = any(a in family_auds for a in audiences)
    has_adult_aud  = any(a in adult_auds  for a in audiences)
    has_adult_tone = any(t in adult_tones_set for t in tones)
    has_safe_tone  = any(t in family_safe_tones for t in tones)
    # Define these outside the block so they're always available for pitch_has_explicit check
    explicit_kws = ["sex","sexual","explicit","gore","graphic violence","blood","drugs"]
    pitch_lower  = (pitch + " " + theme).lower()

    if audiences:
        if has_family_aud and has_adult_tone:  aud -= 22
        if has_adult_aud  and has_adult_tone:  aud += 8
        if has_family_aud and has_safe_tone:   aud += 8
        if has_adult_aud  and has_safe_tone:   aud += 3
        dark_genres  = {"Horror","Thriller","Crime","War"}
        light_genres = {"Comedy","Animation","Adventure","Romance","Fantasy"}
        if has_family_aud and any(g in dark_genres  for g in genres): aud -= 15
        if has_family_aud and any(g in light_genres for g in genres): aud += 8
        if has_adult_aud  and any(g in dark_genres  for g in genres): aud += 5
        if has_family_aud and any(w in pitch_lower for w in explicit_kws): aud -= 20
        if "School / Academic Project" in distribution: aud = max(aud, 60)
        if "Niche Audience / Cult"     in distribution: aud += 5
        if "Online / Social Media"     in distribution: aud += 4
    if audiences: aud = max(10, min(95, aud))
    else: aud = -1  # no audience = undecided

    # Cultural — measures LASTING resonance, not just thematic intensity
    # High scores require: depth of theme + artistic intent + distribution that reaches cultural discourse
    cult = 30  # lower base — cultural impact is hard to achieve
    # Genre cultural weight (only genres that historically spark discourse)
    high_cultural = {"Drama","Science Fiction","Documentary","Crime","Fantasy"}
    medium_cultural = {"War","Thriller","Mystery","Animation"}
    low_cultural = {"Comedy","Romance","Action","Adventure","Horror","Western"}
    for g in genres:
        if g in high_cultural:    cult += 7
        elif g in medium_cultural: cult += 4
        elif g in low_cultural:    cult += 1  # these rarely have long cultural legs alone
    # Tone — gritty/dark alone does NOT equal cultural impact
    # It needs to be paired with artistic intent
    culturally_rich_tones = {"Dramatic","Experimental","Surreal","Satirical","Nostalgic","Thought-provoking","Melancholic","Poetic","Ambiguous","Realistic","Cynical"}
    shock_tones = {"Dark","Gritty"}  # intense but not inherently culturally lasting
    for t in tones:
        if t in culturally_rich_tones: cult += 6
        elif t in shock_tones:         cult += 2  # reduced — shock value fades
    # Theme specificity — vague themes like 'violence' or 'survival' score less
    generic_themes = {"violence","survival","action","happy","sad","love","war"}
    theme_lower = theme.lower().strip() if theme else ""
    if theme_lower and theme_lower not in generic_themes and len(theme_lower) > 4:
        cult += 12  # specific nuanced theme = real cultural potential
    elif theme_lower in generic_themes:
        cult += 3   # generic theme = minimal cultural contribution
    # Pitch depth
    if len(pitch) > 120:         cult += 7
    elif len(pitch) > 60:        cult += 3
    # Purpose is the strongest signal — artistic intent drives cultural longevity
    if "Send a Social Message" in purposes: cult += 14
    if "Artistic Expression"   in purposes: cult += 12
    if "Raise Awareness"       in purposes: cult += 12
    if "Just for Fun"          in purposes: cult -= 8
    if "Generate Profit"       in purposes and len(purposes) == 1: cult -= 5  # pure profit motive
    if "Academic / School Requirement" in purposes: cult -= 4
    # Distribution — festival/indie circuit signals cultural seriousness
    if "Indie / Film Festival"    in distribution: cult += 10
    if "Major Theatrical Release" in distribution: cult += 3
    if "Online / Social Media"    in distribution: cult -= 3  # social content rarely has cultural legs
    cult = max(10, min(92, cult))  # cap at 92 — 95%+ cultural impact is extremely rare

    return {
        "financial": {"score":fin,"budget":budget,"genres":genres,"casting":casting,
                      "distribution":distribution,"purposes":purposes,"schedule":schedule,
                      "mismatch_flags":mismatch_flags},
        "audience":  {"score":aud,"audiences":audiences,"tones":tones,"genres":genres,
                      "mismatch_penalty":mismatch_penalty,
                      "pitch_has_explicit":any(w in pitch_lower for w in explicit_kws),
                      "distribution":distribution},
        "cultural":  {"score":cult,"genres":genres,"tones":tones,"theme":theme,
                      "pitch_length":len(pitch),"purposes":purposes,"distribution":distribution}
    }

# ── [RULE-BASED CORRECTION — not XGBoost, not KNN, not Groq] Overall score
# adjustment. This is hand-written business logic (mismatch penalties, purpose
# caps, etc.) applied AFTER [XGBOOST]'s prediction — it's the layer that
# catches things a trained model has no way to know on its own. ───────────
def adjust_success_rate(base_score, sub_factors, data):
    """
    Applies business-logic adjustments on top of the XGBoost base score.
    XGBoost captures genre/budget/popularity signals from training data.
    This layer adds real-world factors the model cannot see:
    distribution strategy, casting tier, purpose alignment, content mismatches.
    Documented separately from XGBoost output for academic transparency.
    """
    score        = base_score
    purposes     = as_list(data.get("film_purpose",[]))
    distribution = as_list(data.get("distribution_goal",[]))
    audiences    = as_list(data.get("target_audience"))
    tones        = as_list(data.get("tone"))
    genres       = as_list(data.get("genre"))
    casting      = as_list(data.get("casting_category"))
    budget       = data.get("budget_range","")
    pitch        = data.get("story_pitch","")
    theme        = data.get("main_theme","")

    # ── Mismatch penalties (always applied first) ─────────────────────
    # Audience score below 50 means serious mismatch — drag overall score proportionally.
    # Guarded against -1 (the "target audience not yet selected" sentinel) — without this
    # check, -1 was being treated as a genuinely terrible audience-fit score and dragging
    # the overall Commercial score down by (50-(-1))*0.5 = 25.5 points, purely because the
    # user hadn't selected a target audience yet, not because of any real mismatch.
    aud_score_val = sub_factors["audience"]["score"]
    if aud_score_val != -1:
        score -= sub_factors["audience"]["mismatch_penalty"] * 0.6
        if aud_score_val < 50:
            # Each point below 50 drags overall down by 0.5 — bad audience fit = bad film
            score -= (50 - aud_score_val) * 0.5
        elif aud_score_val >= 80:
            # Great audience alignment gets a small bonus
            score += (aud_score_val - 80) * 0.2
    explicit_kws = ["sex","sexual","explicit","gore","graphic violence","blood","drugs"]
    pitch_lower  = (pitch + " " + theme).lower()
    family_auds  = {"Families","Teens"}
    if any(a in family_auds for a in audiences) and any(w in pitch_lower for w in explicit_kws):
        score -= 15

    # ── Purpose ceiling for non-commercial films ──────────────────────
    if "Academic / School Requirement" in purposes or "Just for Fun" in purposes:
        score = min(score, 68)

    # ── Distribution channel bonus ────────────────────────────────────
    if "Major Theatrical Release" in distribution:    score += 6
    elif "School / Academic Project" in distribution: score = min(score, 65)
    elif "Online / Social Media" in distribution:     score += 2
    if "Streaming Platform" in distribution:          score += 2

    # ── Genre commercial strength ─────────────────────────────────────
    high_commercial = {"Comedy","Action","Animation","Adventure"}
    mid_commercial  = {"Science Fiction","Fantasy","Romance","Thriller"}
    dark_risky      = {"Horror","War","Documentary"}
    commercial_count = sum(1 for g in genres if g in high_commercial)
    score += commercial_count * 5          # each commercial genre adds 5
    score += sum(2 for g in genres if g in mid_commercial)
    score -= sum(4 for g in genres if g in dark_risky)

    # ── Budget tier bonus (on top of XGBoost which already sees budget) ─
    # XGBoost uses budget as a popularity proxy; here we add distribution/marketing power
    budget_bonus = {
        "Micro (<$1M)": -3,
        "Low ($1M-$10M)": 0,
        "Mid ($10M-$50M)": 3,
        "High ($50M-$150M)": 7,
        "Blockbuster ($150M+)": 12
    }
    score += budget_bonus.get(budget, 0)

    # ── Casting tier bonus ────────────────────────────────────────────
    if "A-list Stars" in casting:               score += 8
    elif "Established Mid-Tier" in casting:     score += 4
    elif "Mixed (Stars + Newcomers)" in casting: score += 5
    elif "Unknown/Non-professional" in casting:  score -= 4

    # ── Tone alignment ────────────────────────────────────────────────
    safe_tones  = {"Uplifting","Humorous","Adventurous","Romantic","Whimsical","Poetic"}
    risky_tones = {"Experimental","Surreal","Ambiguous","Cynical"}
    safe_count  = sum(1 for t in tones if t in safe_tones)
    score += safe_count * 2
    score -= sum(3 for t in tones if t in risky_tones)

    # ── Purpose alignment bonus ───────────────────────────────────────
    if "Generate Profit" in purposes:           score += 3
    if "Send a Social Message" in purposes or "Artistic Expression" in purposes:
        score += 3  # festival circuit boost

    return max(15, min(96, round(score)))

# ── [XGBOOST] Feature vector builder — turns the pitch form into numbers ──
# This is what XGBoost actually "sees": pitch/theme text (via sentence
# embeddings + PCA) + structured fields (genre, tone, budget, etc.) + the
# neighbor_knn-derived enrichment features. NOTE: budget_range is converted
# to a popularity-proxy number here (Micro=5 ... Blockbuster=150) — see
# genre_budget_fit_bonus()'s docstring for why that specific choice is the
# root cause of the "always recommends Blockbuster" issue and how it's
# corrected downstream, not here.
def build_feature_vector(form_data, is_filipino=False):
    """
    Builds a feature vector that ALWAYS matches the trained model shape.
    Uses feature_cols from the pkl to determine exact columns needed.
    Any column the model expects that we don't compute defaults to 0.

    is_filipino: when True, builds the query vector for a Filipino-market-scope search
    (sets is_filipino=1/is_english=0 in the vector) so KNN's distance calculation reflects
    what's actually being searched for, instead of always querying as if for an
    international film. Used by get_deep_films's Filipino branch.

    v6: the vector is now structured (21) + text (N_TEXT_EMB, from the pitch/theme
    text itself) + neighbor-derived (16 as of v14, was 4 — summary stats of this
    film's nearest neighbors, PER PILLAR's own target, not just Commercial). This
    is what lets the 4 independent XGBoost pillar models actually "read" the
    pitch/theme content and the KNN neighborhood, not just genre/budget/decade
    metadata. Both additions degrade gracefully to zeros if their supporting
    artifacts (pca_text / neighbor_knn) aren't loaded, so the app never crashes
    over this — it just falls back toward the old, purely-structured behavior
    for those dims.

    v12: the text block is now a sentence-embedding of the pitch/theme, reduced
    via PCA to N_TEXT_EMB dims — previously it was TF-IDF(pitch+theme) reduced
    via TruncatedSVD. Same shape and role in the vector, semantic source instead
    of lexical (see load_text_embedder and the v12 training notebook Step 6).

    v14: neighbor-derived features expanded from 4 columns (one shared set,
    based only on Commercial/success_score) to 16 columns (4 pillars x 4
    stats, each from that pillar's own real target — financial_target,
    audience_target, cultural_target, success_score). This is the actual fix
    for "XGBoost never sees KNN's results" — each pillar model now genuinely
    reads what structurally similar films scored on THAT exact dimension, not
    a borrowed proxy. See genre_budget_fit_bonus() and the "always Blockbuster"
    fix for how this interacts with the budget->popularity proxy — this v14
    change does NOT replace that fix, it's a separate, deeper improvement to
    the same feature vector. Requires a model retrained with the matching v14
    notebook (Step 7) — mismatched feature_cols.pkl/model files will crash or
    silently misbehave, exactly like a PILLAR_MASKS mismatch would.
    """
    genres = as_list(form_data.get("genre"))
    times  = as_list(form_data.get("time_period"))
    budget = form_data.get("budget_range","")
    pitch  = form_data.get("story_pitch","")
    theme  = form_data.get("main_theme","")
    row    = {}

    # Genre one-hot (covers all genres in GENRE_MAP)
    for gname in GENRE_MAP:
        row[f"genre_{gname.replace(' ','_')}"] = 1 if gname in genres else 0

    # Numeric features
    budget_popularity = {"Micro (<$1M)":5,"Low ($1M-$10M)":15,"Mid ($10M-$50M)":40,
                         "High ($50M-$150M)":80,"Blockbuster ($150M+)":150}
    row["popularity"]     = budget_popularity.get(budget, 20)
    row["vote_count_log"] = np.log1p(500)

    decade_map = {"1970s":1970,"1980s":1980,"1990s":1990,"2000s":2000,
                  "2010s":2010,"2020s":2020,"Contemporary":2020,"Future/Sci-Fi":2025,"Post-Apocalyptic":2025,"Alternate World / Universe":2020}
    row["release_decade"] = decade_map.get(times[0], 2020) if times else 2020

    # Language/type flags — include ALL possible flags; feature_cols will select the right ones
    row["is_english"]  = 0 if is_filipino else 1
    row["is_filipino"] = 1 if is_filipino else 0
    row["is_adult"]    = 0

    # ── v12: Text features — sentence-embedding(pitch + theme) reduced to
    # N_TEXT_EMB dims via the SAME pca_text reducer fit on film overviews during
    # training (see load_text_embedder/load_models), so the user's pitch lands
    # in the same reduced space the pillar models were trained on. Was TF-IDF+
    # TruncatedSVD (lexical) — see build_feature_vector's docstring.
    text_input = f"{pitch} {theme}".strip()
    text_vec = np.zeros(N_TEXT_EMB)
    if EMBEDDER_READY and pca_text is not None and text_input:
        try:
            emb = _embed_text(text_input)
            if emb is not None:
                text_vec = np.asarray(pca_text.transform(emb.reshape(1, -1))).reshape(-1)
        except Exception as e:
            print(f"[FeatureVec] text transform failed, using zeros: {e}")
    for i in range(N_TEXT_EMB):
        row[f"text_{i}"] = float(text_vec[i]) if i < len(text_vec) else 0.0

    # ── v14: Neighbor-derived features — PILLAR-SPECIFIC mean/std/max/min of
    # this film-concept's K nearest neighbors in STRUCTURED feature space.
    # This is literally "XGBoost reading the KNN results" — the thesis's
    # original pseudocode intent (feature_set <- merge(similar_films, ...)),
    # now actually wired into the model's own inputs, not just Groq's prompt.
    # v14 change: previously this computed ONE shared set of stats based only
    # on Commercial (success_score), and every pillar saw that same signal.
    # Now each pillar gets its OWN neighbor stats from its OWN real target —
    # MUST exactly match the training notebook's Step 7 (NEIGHBOR_TARGETS),
    # both the column names below and n_neighbors=10 (== K_RET at training
    # time) — a mismatch here silently feeds the model garbage, the same way
    # a PILLAR_MASKS mismatch would. ──────────────────────────────────────
    NEIGHBOR_PILLAR_TARGET_COLS = {
        "commercial": "success_score",
        "financial":  "financial_target",
        "audience":   "audience_target",
        "cultural":   "cultural_target",
    }
    neigh_stats = {}
    for pname in NEIGHBOR_PILLAR_TARGET_COLS:
        neigh_stats[f"neighbor_{pname}_mean"] = 0.0
        neigh_stats[f"neighbor_{pname}_std"]  = 0.0
        neigh_stats[f"neighbor_{pname}_max"]  = 0.0
        neigh_stats[f"neighbor_{pname}_min"]  = 0.0
    if neighbor_knn is not None and struct_scaler is not None and struct_cols and film_db is not None:
        try:
            struct_row  = {c: row.get(c, 0) for c in struct_cols}
            struct_vec  = np.array([struct_row[c] for c in struct_cols], dtype=float).reshape(1, -1)
            struct_vec_sc = struct_scaler.transform(struct_vec)
            _, idxs = neighbor_knn.kneighbors(struct_vec_sc, n_neighbors=10)   # 10 == K_RET at training time
            neighbor_rows = film_db.iloc[idxs[0]]
            for pname, target_col in NEIGHBOR_PILLAR_TARGET_COLS.items():
                vals = neighbor_rows[target_col].values
                neigh_stats[f"neighbor_{pname}_mean"] = float(np.mean(vals))
                neigh_stats[f"neighbor_{pname}_std"]  = float(np.std(vals))
                neigh_stats[f"neighbor_{pname}_max"]  = float(np.max(vals))
                neigh_stats[f"neighbor_{pname}_min"]  = float(np.min(vals))
        except Exception as e:
            print(f"[FeatureVec] neighbor lookup failed, using zeros: {e}")
    row.update(neigh_stats)

    # Use feature_cols from pkl to build exact vector — model gets exactly what it was trained on
    if feature_cols:
        vec = [row.get(c, 0) for c in feature_cols]
    else:
        vec = list(row.values())
    return np.array(vec, dtype=float).reshape(1, -1)

# ── [XGBOOST] Runs the 4 independent pillar models — Commercial, Financial,
# Audience, Cultural — on ONE feature vector (built above). This is the
# FIRST model to run in the whole /analyze pipeline (see analyze()'s
# PIPELINE ORDER comment) and it runs completely independently: it never
# sees KNN-retrieved similar films or any live market data. Its raw output
# is what predict_all_pillars() below corrects and hands off to everything
# else (KNN retrieval, live market adjustment, then Groq).
def predict_pillars_xgb(form_data):
    """
    Runs the SAME base feature vector through all 4 independent XGBoost regressors
    (Commercial/Financial/Audience/Cultural — see the v9 training notebook).
    Each model was trained on its own target, so this is 4 real predictions,
    not one score fanned out by rules. Returns None for any pillar whose
    prediction fails, so callers can fall back to the rule-based score for
    just that pillar without losing the others.

    v9: before predicting with a given pillar's model, columns listed in
    PILLAR_MASKS[pillar] are zeroed out — this MUST mirror what the training
    notebook did (Step 8/16), because Financial/Cultural's target formulas were
    built from those exact columns, and the model was trained with them masked
    to prevent trivially reconstructing its own answer. Getting this wrong
    (masking at inference but not training, or vice versa) silently produces
    garbage predictions for those two pillars, so this must stay in sync with
    the notebook if PILLAR_MASKS ever changes.
    """
    vec = build_feature_vector(form_data)
    out = {}
    for pillar, model in PILLAR_MODELS.items():
        pillar_vec = vec
        mask_cols = PILLAR_MASKS.get(pillar) or []
        if mask_cols and feature_cols:
            pillar_vec = vec.copy()
            for c in mask_cols:
                if c in feature_cols:
                    pillar_vec[0, feature_cols.index(c)] = 0.0
        try:
            raw = float(model.predict(pillar_vec)[0])
            out[pillar] = max(10, min(96, round(raw)))
        except ValueError as e:
            if "Feature shape mismatch" in str(e):
                # Same trim-fix as the old single-model version, per pillar model.
                print(f"[XGB:{pillar}] Shape mismatch — attempting trim fix: {e}")
                try:
                    n_expected = model.get_booster().num_features()
                    vec_trimmed = pillar_vec[:, :n_expected]
                    raw = float(model.predict(vec_trimmed)[0])
                    out[pillar] = max(10, min(96, round(raw)))
                    print(f"[XGB:{pillar}] Trim fix worked — used {n_expected} features")
                except Exception as e2:
                    print(f"[XGB:{pillar}] Trim fix also failed: {e2}")
                    out[pillar] = None
            else:
                print(f"[XGB:{pillar}] prediction failed: {e}")
                out[pillar] = None
        except Exception as e:
            print(f"[XGB:{pillar}] prediction failed: {e}")
            out[pillar] = None
    return out

# ── [XGBOOST] Orchestrator — this is "Model 2" finishing its job ───────
# (Model 2 = XGBoost, Model 1 = KNN retrieval — naming matches the training
# notebook's own Step 9/Step 13 labels, independent of execution order.)
# Combines the 4 independent ML pillars with the existing rule-based
# sub_factors metadata (mismatch flags, genre lists, etc. — all of which
# downstream Groq prompts and adjust_score_for_market still need unchanged).
# When ML_READY, each pillar's "score" is overridden by its own independent
# model's prediction, then corrected with rule-based business logic XGBoost
# has no way to have learned (genre-budget fit, family/tone mismatch —
# see genre_budget_fit_bonus / detect_mismatch). Every other field in
# sub_factors (and the -1 "undecided" sentinel behavior for missing
# budget/audience) is untouched.
#
# THIS FUNCTION'S RETURN VALUE (base_score, sub_factors) IS "MODEL 2's
# (XGBoost's) OUTPUT" — analyze() now calls this THIRD (after [KNN] and
# [LIVE MARKET] have already run — see the PIPELINE ORDER comment at the
# top of the file), then hands its result to compute_live_market_adjustment()
# to be combined with [KNN] + [LIVE MARKET] results, then into every [GROQ]
# prompt as context.
def predict_all_pillars(data):
    sub_factors = compute_sub_metrics(data)   # unchanged — still the source of all metadata
    if ML_READY:
        pillar_scores = predict_pillars_xgb(data)   # [XGBOOST] the actual model inference call
        base_score = pillar_scores.get("commercial")
        if base_score is None:
            base_score = predict_success_fallback(data)
        if pillar_scores.get("financial") is not None and sub_factors["financial"]["score"] != -1:
            xgb_financial_score = pillar_scores["financial"]
            # Same fix as the audience one above: reintroduce the genre-budget economic
            # fit that XGBoost's raw financial pillar has no way to have learned, since
            # its main budget signal is a popularity proxy that leaks part of its own
            # training target (see genre_budget_fit_bonus docstring). Without this, the
            # displayed Financial score — and, more importantly, the budget-tier sweep
            # that picks the recommended range — both lean almost entirely on budget size.
            fit_bonus = genre_budget_fit_bonus(as_list(data.get("genre")), data.get("budget_range",""))
            xgb_financial_score = max(10, min(96, round(xgb_financial_score + fit_bonus)))
            sub_factors["financial"]["score"] = xgb_financial_score
        if pillar_scores.get("audience") is not None and sub_factors["audience"]["score"] != -1:
            xgb_audience_score = pillar_scores["audience"]
            # XGBoost's audience pillar has no way to know a family-inappropriate mismatch
            # was selected — e.g. "Families" chosen alongside a Dark tone and a drug-cartel
            # violence pitch. That's a business rule (see detect_mismatch), not a trained
            # signal, so the raw model score can come back deceptively high for Families
            # on genuinely inappropriate content. compute_sub_metrics already detected this
            # mismatch (sub_factors["audience"]["mismatch_penalty"]) for the rule-based
            # score that's about to be overwritten below — re-apply it here so overwriting
            # with the ML prediction doesn't also erase the safety correction.
            mismatch_pen = sub_factors["audience"].get("mismatch_penalty", 0)
            if mismatch_pen:
                xgb_audience_score = max(10, round(xgb_audience_score - mismatch_pen))
            sub_factors["audience"]["score"] = xgb_audience_score
        if pillar_scores.get("cultural") is not None:
            sub_factors["cultural"]["score"] = pillar_scores["cultural"]
        method = "xgboost"
    else:
        base_score = predict_success_fallback(data)
        method = "heuristic"
    return base_score, sub_factors, method

# ── [XGBOOST] Fallback heuristic — used ONLY if ML_READY is False (model
# files missing/corrupt at startup). Rule-based stand-in for the Commercial
# pillar so the app can still return a number instead of crashing.
def predict_success_fallback(data):
    score = 48
    for g in as_list(data.get("genre")):
        if g in ["Action","Comedy","Animation","Adventure","Science Fiction"]: score += 9
        elif g in ["Drama","Romance","Thriller","Fantasy","Crime"]: score += 5
        elif g in ["Documentary","War","Western"]: score += 1
    for a in as_list(data.get("target_audience")):
        score += {"General Audience":10,"Young Adults (18-25)":8,"Families":9,
                  "Adults (26-45)":7,"Teens":7,"Niche/Cult":2}.get(a, 3)
    score += {"Micro (<$1M)":3,"Low ($1M-$10M)":7,"Mid ($10M-$50M)":12,
              "High ($50M-$150M)":15,"Blockbuster ($150M+)":18}.get(data.get("budget_range",""), 5)
    for t in as_list(data.get("tone")):
        if t in ["Uplifting","Humorous","Adventurous","Romantic"]: score += 5
        elif t in ["Dark","Experimental","Satirical","Surreal"]: score += 1
        elif t in ["Gritty","Suspenseful"]: score += 3
    if data.get("story_pitch","").strip(): score += 3
    if data.get("main_theme","").strip():  score += 3
    if as_list(data.get("casting_category")): score += 3
    return max(20, min(96, score))

# ── [KNN] Scores one live TMDB candidate against the pitch using the
# trained knn_model (structured-feature distance) — one ingredient of the
# hybrid similar-film ranking (see _score_and_rank, which blends this with
# semantic/keyword scoring).
def _knn_score_single(tmdb_result, form_data):
    if not ML_READY:
        user_genre_ids = set(GENRE_MAP[g] for g in as_list(form_data.get("genre")) if g in GENRE_MAP)
        film_genre_ids = set(tmdb_result.get("genre_ids", []))
        if not user_genre_ids: return 50.0
        overlap = len(user_genre_ids & film_genre_ids) / len(user_genre_ids)
        return round(50 + overlap * 40, 1)
    row = {}
    film_genre_ids = tmdb_result.get("genre_ids", [])
    for gname, gid in GENRE_MAP.items():
        row[f"genre_{gname.replace(' ','_')}"] = 1 if gid in film_genre_ids else 0
    row["popularity"]     = float(tmdb_result.get("popularity", 10))
    row["vote_count_log"] = np.log1p(tmdb_result.get("vote_count", 100))
    release = tmdb_result.get("release_date","2000-01-01")
    try:    decade = (int(release[:4]) // 10) * 10
    except: decade = 2000
    row["release_decade"] = decade
    row["is_english"]     = 1 if tmdb_result.get("original_language","en") == "en" else 0
    row["is_adult"]       = 1 if tmdb_result.get("adult") else 0
    # v6 note: this `row` only has structured fields — it has no way to know this
    # single TMDB result's text/neighbor features the way build_feature_vector does
    # for the user's own pitch, so those ~19 expanded dims would sit at 0 here while
    # the user's vector has real values. Comparing the FULL scaled vector would let
    # that mismatch dominate the distance. Instead, slice both vectors down to just
    # the structured-column positions after scaling (per-dimension standardization
    # means slicing post-transform is still valid) — this restores exactly the
    # original "does structured metadata match" comparison this function always did.
    film_vec        = np.array([row.get(c, 0) for c in feature_cols]).reshape(1, -1)
    film_vec_scaled = scaler.transform(film_vec)
    user_vec        = build_feature_vector(form_data)
    user_vec_scaled = scaler.transform(user_vec)
    if feature_cols and struct_cols:
        struct_positions = [i for i, c in enumerate(feature_cols) if c in struct_cols]
        dist = float(np.linalg.norm(user_vec_scaled[0, struct_positions] - film_vec_scaled[0, struct_positions]))
    else:
        dist = float(np.linalg.norm(user_vec_scaled - film_vec_scaled))
    return round(max(0, 100 - dist * 8), 1)

# ── Keyword overlap score (fallback) ────────────────────────────────────
def _keyword_overlap(pitch_words, overview):
    """
    Word-boundary-aware overlap between pitch words and a film's overview.
    Previously used plain substring containment (`word in overview_text`) plus a
    6-character prefix match — both of which produced false positives, e.g. the
    pitch word "self" matching inside "himself", or a rare word's 6-letter prefix
    coincidentally matching an unrelated word. Whole-word matching via regex
    removes that class of noise from the fallback scorer (used when the sentence
    embedder isn't available).
    """
    if not pitch_words or not overview:
        return 0.0
    ov = overview.lower()
    hits = 0
    for w in pitch_words:
        if len(w) <= 3: continue
        if re.search(r"\b" + re.escape(w) + r"\b", ov):
            hits += 1.0
    return min(1.0, hits / max(len(pitch_words), 1))

# ── v12: Sentence-embedding helpers ─────────────────────────────────────
def _embed_text(text):
    """
    Encodes a single text string to its embedding vector (np.ndarray, shape
    (384,) for the default model), or None if the embedder isn't available or
    the text is empty. Wrapped in try/except so a transient encode failure
    degrades to the keyword-overlap fallback rather than crashing the request.
    """
    if not (EMBEDDER_READY and text_embedder is not None and text and text.strip()):
        return None
    try:
        return text_embedder.encode([text], convert_to_numpy=True, show_progress_bar=False)[0]
    except Exception as e:
        print(f"[Embed] encode failed, using fallback: {e}")
        return None

def _embed_texts(texts):
    """
    Batch-encodes a list of text strings in ONE model call. _score_and_rank
    scores up to a few dozen TMDB candidates per request — encoding each
    overview one at a time would mean a model call per candidate, which is
    real latency in a live demo; one batched call is much cheaper. Returns
    None (not a list of Nones) on any failure, so callers can check once.
    """
    if not (EMBEDDER_READY and text_embedder is not None) or not texts:
        return None
    try:
        return text_embedder.encode(texts, convert_to_numpy=True, show_progress_bar=False, batch_size=32)
    except Exception as e:
        print(f"[Embed] batch encode failed, using fallback: {e}")
        return None

def _cosine(a, b):
    """Plain cosine similarity between two 1-D vectors, clipped to [0,1] — the
    rest of the scoring pipeline (SOURCE_BOOST multipliers, the 0-1 floors in
    _score_and_rank) was written assuming a [0,1]-ish similarity range, same as
    TF-IDF cosine always produced; embedding cosine can go slightly negative
    for very dissimilar pairs, so this clips rather than passing that through."""
    if cosine_similarity is None:
        return 0.0
    return max(0.0, float(cosine_similarity(a.reshape(1, -1), b.reshape(1, -1))[0][0]))

# ── Real semantic similarity (sentence-embedding cosine) ────────────────
def _semantic_similarity(pitch_words, pitch_text, overview, pitch_emb=None, overview_emb=None):
    """
    Measures actual content relevance between the pitch and a candidate film's
    overview using sentence-embedding cosine similarity — a SEMANTIC (meaning-
    based) signal, replacing the old TF-IDF cosine (LEXICAL, literal-shared-
    word-only) similarity. This is what lets a paraphrased pitch, or one with
    names/specifics stripped out, still score as similar to a film's real
    overview even when they share almost no literal vocabulary — TF-IDF
    structurally could not do this (see the v12 training notebook Step 6 for
    the empirical case — a full Wikipedia plot matched, but a short natural
    pitch or an anonymized version of the identical story did not).

    pitch_emb/overview_emb let a caller pass in PRE-COMPUTED embeddings (see
    _embed_texts) to avoid re-encoding the same pitch text once per candidate
    when scoring many candidates in a loop — see _score_and_rank. Falls back
    to _keyword_overlap if the embedder isn't loaded or embedding fails.
    """
    if EMBEDDER_READY and overview and pitch_text:
        try:
            pe = pitch_emb if pitch_emb is not None else _embed_text(pitch_text)
            oe = overview_emb if overview_emb is not None else _embed_text(overview)
            if pe is not None and oe is not None:
                return _cosine(pe, oe)
        except Exception as e:
            print(f"[Embed] Similarity computation failed, using fallback: {e}")
    return _keyword_overlap(pitch_words, overview)

# ── TMDB keyword ID lookup ─────────────────────────────────────────────
def _lookup_keyword_ids(words):
    known_genres = {"comedy","drama","action","horror","thriller","animation",
                    "romance","fantasy","crime","mystery","documentary",
                    "adventure","western","war","science fiction"}
    ids = {}
    for w in words:
        if not w or len(w) < 4 or w in known_genres: continue
        try:
            r = requests.get(f"{TMDB_BASE}/search/keyword",
                             params={"api_key":TMDB_API_KEY,"query":w}, timeout=4)
            results = r.json().get("results",[])
            if results:
                # prefer exact match
                for res in results:
                    if res.get("name","").lower() == w:
                        ids[w] = res["id"]; break
                else:
                    ids[w] = results[0]["id"]
        except Exception:
            pass
    return ids

# ── TMDB per-word movie search ─────────────────────────────────────────
def _search_movie_multi(words, extra_params=None, per_word_limit=8, timeout=6):
    """
    Issues one TMDB /search/movie call PER word instead of one combined multi-word
    query. TMDB's search endpoint matches primarily against movie TITLES (it does not
    do full-text plot search), so a long abstract phrase like "factory owner successor
    poverty discovery" almost never matches any real title and returns nothing — even
    when a strong match exists (e.g. "Charlie and the Chocolate Factory" for a
    toy-factory-succession pitch never gets found by that combined phrase, but a search
    on "factory" alone has a real chance of surfacing it). This trades a few extra API
    calls for meaningfully better recall on exactly the pitches that need it most —
    ones whose anchor words are abstract/thematic rather than literal title words.
    Returns {tmdb_id: (matched_word, result_dict)}, deduplicated across words.
    """
    found = {}
    for w in words:
        if not w or len(w) < 4:
            continue
        try:
            params = {"api_key": TMDB_API_KEY, "query": w, "language": "en-US", "page": 1}
            if extra_params: params.update(extra_params)
            r = requests.get(f"{TMDB_BASE}/search/movie", params=params, timeout=timeout)
            for res in r.json().get("results", [])[:per_word_limit]:
                rid = res.get("id")
                if rid and rid not in found:
                    found[rid] = (w, res)
        except Exception as e:
            print(f"[Search] '{w}' failed: {e}")
    return found

# ── Groq-suggested titles + TMDB verification ───────────────────────────
def _groq_suggest_titles(pitch, theme, genres, scope, flavor, n=8):
    """
    [GROQ used INSIDE the KNN/retrieval stage — NOT a narrative-writing call]
    Asks Groq for REAL, existing film titles similar to the pitch — this is the fix for
    the core limitation of keyword/text-based retrieval: TMDB's own overview text often
    shares almost no literal vocabulary with an abstract pitch even for a genuinely
    strong match (e.g. "Charlie and the Chocolate Factory"'s overview talks about an
    "eccentric candy manufacturer", not "toy factory owner" or "successor" — no keyword
    search or overlap score can bridge that gap, but a model that has actually seen the
    film can). This only asks for titles, never trusts any other claim the model makes
    about them — every suggestion gets verified against real TMDB data before use, and
    anything TMDB can't confirm is discarded (see _verify_tmdb_title).
    """
    scope_note = ("Filipino-produced films only (Tagalog/Filipino-language, made in the "
                   "Philippines)" if scope == "filipino" else
                   "films from any country, any language")
    flavor_note = ("similar in PREMISE and PLOT MECHANICS — the core story setup" if flavor == "surface"
                   else "similar in THEME, TONE, or EMOTIONAL SUBTEXT — not necessarily the same plot, "
                        "but the same underlying feeling or question")
    prompt = f"""You are a film-literate assistant helping a filmmaker find real reference films.

Pitch: {pitch}
Main theme: {theme}
Genre(s): {', '.join(genres) if genres else 'unspecified'}

List {n} REAL, ACTUALLY EXISTING films that are {flavor_note}.
Scope: {scope_note}.

CRITICAL: Only list films you are confident actually exist. Do not invent titles. If you
are unsure whether a film is real, leave it out rather than guess.

Return ONLY this JSON, no other text:
{{"films": [{{"title": "exact film title", "year": 2020}}, ...]}}"""
    # temperature=0.3: this is a factual-recall task ("name real films that exist"),
    # not creative writing — the default 0.7 used elsewhere (for the "how it connects"
    # blurbs, which benefit from variety) was causing real, observed inconsistency here:
    # the identical prompt for the identical pitch returned 8 real suggestions one run
    # and 0 the next, purely from sampling randomness. Lower temperature makes this
    # call much more consistently non-empty without affecting any other Groq call.
    for attempt in range(2):
        try:
            result = _call_groq(prompt, max_tokens=500, fast=False, temperature=0.3)
            films = result.get("films", [])
            if films:
                return [(f.get("title","").strip(), f.get("year")) for f in films if f.get("title")]
            print(f"[Groq-suggest] {scope}/{flavor}: got 0 films on attempt {attempt+1}, "
                  f"{'retrying' if attempt == 0 else 'giving up'}")
        except Exception as e:
            print(f"[Groq-suggest] {scope}/{flavor} failed: {e}")
            return []
    return []

def _verify_tmdb_title(title, year=None, require_filipino=False, timeout=6):
    """
    Confirms a Groq-suggested title actually exists on TMDB and fetches its real
    metadata — this is what prevents hallucinated titles from ever reaching the user.
    If require_filipino, also confirms the match is actually Filipino (original
    language tl/fil or origin country PH); Groq's sense of "Filipino film" isn't
    trusted any more than its plot claims are.
    """
    try:
        params = {"api_key": TMDB_API_KEY, "query": title, "language": "en-US", "page": 1}
        r = requests.get(f"{TMDB_BASE}/search/movie", params=params, timeout=timeout)
        results = r.json().get("results", [])
        if not results:
            return None
        candidate = None
        if year:
            for res in results:
                rd = res.get("release_date", "")
                if rd and rd[:4] == str(year):
                    candidate = res; break
        if not candidate:
            # Fall back to closest title match rather than blindly taking result[0]
            tl = title.lower().strip()
            for res in results:
                if res.get("title","").lower().strip() == tl:
                    candidate = res; break
            candidate = candidate or results[0]
        if require_filipino:
            lang = candidate.get("original_language", "")
            origin_ok = lang in ("tl", "fil")
            if not origin_ok:
                # original_language alone can be wrong/missing for some entries — check
                # production countries as a second signal before rejecting
                try:
                    rd = requests.get(f"{TMDB_BASE}/movie/{candidate['id']}",
                                       params={"api_key": TMDB_API_KEY}, timeout=4).json()
                    countries = [c.get("iso_3166_1") for c in rd.get("production_countries", [])]
                    origin_ok = "PH" in countries
                except Exception:
                    pass
            if not origin_ok:
                return None
            # Some legitimately Filipino TMDB entries don't have original_language set to
            # tl/fil in the search response itself (only visible via the detail-endpoint
            # production_countries check above) — tag explicitly so downstream is_filipino
            # detection (which checks origin_country) doesn't miss a film we just verified.
            candidate["origin_country"] = "PH"
        return candidate
    except Exception as e:
        print(f"[Verify] '{title}' failed: {e}")
        return None

def _groq_candidates(pitch, theme, genres, scope, flavor, exclude_ids=None, n=8):
    """[GROQ + LIVE TMDB, part of the [KNN]/retrieval stage] Combines
    _groq_suggest_titles + _verify_tmdb_title into ready-to-score candidates —
    these candidates then go through the same [KNN] _score_and_rank as every
    other candidate source."""
    exclude_ids = exclude_ids or set()
    suggestions = _groq_suggest_titles(pitch, theme, genres, scope, flavor, n=n)
    out = {}
    verified_titles = []
    for title, year in suggestions:
        res = _verify_tmdb_title(title, year, require_filipino=(scope == "filipino"))
        if res and res.get("id") and res["id"] not in exclude_ids:
            out[res["id"]] = {"source": "groq_suggest", "query_rank": 0, "result": res}
            verified_titles.append(res.get("title", title))
    print(f"[Groq-suggest] {scope}/{flavor}: {len(suggestions)} suggested, {len(out)} verified on TMDB")
    if suggestions:
        # Full visibility into what Groq actually proposed and what TMDB rejected —
        # aggregate counts alone can't answer "did it even suggest X" or "why didn't
        # X show up", which otherwise requires guessing at which of three stages
        # (suggestion / TMDB verification / relevance scoring) dropped a given film.
        suggested_names = [t for t, y in suggestions]
        rejected_names  = [t for t in suggested_names if t not in verified_titles]
        print(f"[Groq-suggest] {scope}/{flavor} suggested: {suggested_names}")
        if rejected_names:
            print(f"[Groq-suggest] {scope}/{flavor} rejected by TMDB verify: {rejected_names}")
    return out

# ── v12: Direct semantic search against OUR OWN curated training corpus ────
CORPUS_SEMANTIC_FLOOR = 0.30
# Placeholder, NOT empirically calibrated — my sandbox can't reach
# huggingface.co to download the real embedding model and check actual
# cosine-similarity numbers against this app's own film_db. This is a
# principled starting point for all-MiniLM-L6-v2 (genuinely related sentence
# pairs typically land ~0.3-0.6+, unrelated pairs ~0.0-0.2), not a measured
# one. _corpus_semantic_candidates prints the raw top scores on every call —
# after a few real requests (or a quick test cell in the notebook using known
# pitch/anchor-film pairs), look at those numbers and move this floor to
# wherever it actually separates real matches from noise. Expect to change it.

def _corpus_semantic_candidates(pitch, theme, top_k=10, min_similarity=CORPUS_SEMANTIC_FLOOR,
                                 filipino_only=False, exclude_ids=None):
    """
    Embeds the pitch+theme ONCE and cosine-matches it directly against every
    film's precomputed overview embedding in film_db (film_overview_embeddings.pkl)
    — a single matrix multiply, no external API call.

    This exists because retrieval failure and scoring failure are different
    problems. TMDB's /search/movie endpoint matches primarily on TITLES, not
    plot text (see _search_movie_multi), and _groq_candidates depends on the
    LLM correctly recognizing an anonymized or paraphrased pitch as a specific
    real film it has memorized — neither guarantees that a pitch matching one
    of THIS APP'S own curated/anchor training films (e.g. Five Feet Apart,
    Heat — see the v11 anchor-title fetch in the training notebook) actually
    surfaces as a candidate at all. A candidate that's never fetched can't be
    rescued by better scoring downstream. This closes that gap deterministically
    for anything already in the training corpus, independent of live TMDB/Groq
    behavior — see _score_and_rank for how these candidates are then scored
    (they skip the lexical floor logic the same way groq_suggest does, using
    this real cosine score instead of a flat credit).
    """
    if not (EMBEDDER_READY and FILM_EMBEDDINGS is not None and film_db is not None):
        return {}
    pitch_text = f"{pitch} {theme}".strip()
    if not pitch_text:
        return {}
    pitch_emb = _embed_text(pitch_text)
    if pitch_emb is None:
        return {}

    exclude_ids = exclude_ids or set()
    try:
        sims = cosine_similarity(pitch_emb.reshape(1, -1), FILM_EMBEDDINGS)[0]
    except Exception as e:
        print(f"[Embed-Corpus] similarity computation failed: {e}")
        return {}

    overfetch = np.argsort(-sims)[:max(top_k * 3, 30)]
    print(f"[Embed-Corpus] top raw cosine scores: "
          f"{[round(float(sims[i]), 3) for i in overfetch[:8]]}")

    out = {}
    for idx in overfetch:
        score = float(sims[idx])
        if score < min_similarity:
            break   # overfetch list is sorted descending — nothing after this clears the floor
        row = film_db.iloc[idx]
        if filipino_only and not int(row.get("is_filipino", 0)):
            continue
        tid = int(row.get("tmdb_id", 0))
        if not tid or tid in out or tid in exclude_ids:
            continue
        genre_ids = [gid for gname, gid in GENRE_MAP.items()
                     if int(row.get(f"genre_{gname.replace(' ','_')}", 0)) == 1]
        vote_count = int(round(np.expm1(float(row.get("vote_count_log", 0)))))
        fake = {
            "id":                tid,
            "title":             str(row.get("title", "")),
            "overview":          str(row.get("overview", "")),
            "vote_average":      float(row.get("vote_average", 0)),
            "vote_count":        vote_count,
            "release_date":      str(row.get("release_date", "")),
            "poster_path":       row.get("poster_path", ""),
            "genre_ids":         genre_ids,
            "original_language": "tl" if int(row.get("is_filipino", 0)) else "en",
            "popularity":        float(row.get("popularity", 20)),
            "adult":             bool(row.get("is_adult", 0)),
        }
        out[tid] = {"source": "corpus_semantic", "query_rank": 0, "result": fake,
                     "_semantic_score": score}
        if len(out) >= top_k:
            break
    print(f"[Embed-Corpus] {len(out)} corpus film(s) above floor {min_similarity}: "
          f"{[c['result']['title'] for c in out.values()]}")
    return out

# ── Cinematic noun detector ────────────────────────────────────────────
CINEMATIC_NOUNS = {
    "christmas","holiday","wedding","school","college","office","workplace",
    "hospital","prison","police","military","army","war","space","alien",
    "zombie","vampire","ghost","murder","detective","heist","race","racing",
    "driver","dancer","singer","athlete","chef","teacher","doctor","lawyer",
    "family","father","mother","brother","sister","friend","lover","killer",
    "assassin","sicario","hitman","spy","agent","superhero","princess","king",
    "island","jungle","forest","desert","city","town","village","amazon",
    "robot","dinosaur","monster","dragon","witch","wizard","angel","demon",
    "revenge","redemption","survival","identity","corruption","betrayal",
    "restaurant","hotel","theater","circus","carnival","festival","parade",
    "student","journalist","soldier","rebel","outlaw","survivor","orphan",
    "divorce","pregnancy","adoption","grief","addiction","immigrant","refugee","apocalyptic","apocalypse","alternate","parallel","dystopia","dystopian",
    # Parenting / family
    "foster","parenting","custody","orphan","guardian","caregiver","stepfather",
    "stepmother","stepchild","siblings","children","teenager","toddler","infant",
    # Romance / relationships
    "couple","romance","affair","breakup","heartbreak","dating","marriage",
    "jealousy","infidelity","soulmate","reunion","proposal","divorce",
    # Crime / thriller specific
    "kidnapping","hostage","trafficking","blackmail","conspiracy","assassin",
    "fugitive","bounty","gangster","cartel","undercover","informant","heist",
    # Workplace / professional
    "startup","corporation","politics","election","campaign","president",
    "senator","lawyer","courtroom","trial","verdict","jury","prosecutor",
    # Journey / adventure
    "expedition","voyage","quest","pilgrimage","escape","exile","wanderer",
    # Loss / healing
    "widower","widow","mourning","terminal","illness","cancer","disability",
    "recovery","rehabilitation","therapy","depression","anxiety",
}

STOP_WORDS = {
    "a","an","the","and","or","but","in","on","at","to","for","of","with",
    "that","this","as","is","are","was","were","be","been","being","have",
    "has","had","do","does","did","will","would","could","should","may",
    "might","shall","about","from","by","not","just","all","its","his",
    "her","their","our","who","what","which","when","where","how","very",
    "also","both","each","through","during","before","after","between",
    "into","up","out","then","than","so","if","while","although","because",
    "film","movie","story","tries","decides","comes","goes","turns","makes",
    "they","them","some","more","most","over","only","even","such","same",
    "want","wants","take","takes","find","finds","gets","puts","lead","leads",
    "save","saved","saves","help","helps","helped","start","starts","started",
    "spend","spends","spent","leave","leaves","left","know","known","knew",
    "never","always","every","many","much","long","back","away","around",
    "funny","light","hearted","pure","bloody","normal","highly","random",
    "different","good","great","really","quite","dark","gritty","dramatic",
    "uplifting","humorous","satirical","heartwarming","emotional","intense",
    "twist","ends","turns","become","becomes","became","between","among",
    # Extra filler words that pollute TMDB search
    "young","couple","people","person","story","tales","based","true","real",
    "foreign","country","staying","breaking","discover","discovers","finds",
    "eventually","together","apart","decide","decided","after","their","film",
    "about","where","when","which","there","here","then","than","them","they"
}

def _extract_anchor_words(pitch, theme, genres):
    """
    Extracts anchor nouns from a pitch to drive keyword/search-based film
    matching. Previously this only matched words against a fixed ~150-word
    CINEMATIC_NOUNS list, so any pitch whose key nouns weren't hand-curated
    into that list got zero anchors and zero relevant results — e.g. "a toy
    factory owner picks a successor" matches nothing in that list even though
    "factory" and "successor" are exactly the anchors a human would pick.

    Now: NLTK POS-tags the pitch, pulls out all nouns (not just pre-listed
    ones), and ranks them by rarity against the trained dataset's vocabulary
    (rarer nouns are more specific, more useful search anchors than common
    ones). If NLTK or its data packages aren't available at runtime, this
    falls back to the original CINEMATIC_NOUNS matching so the app still
    works, just with the old, narrower behavior.
    """
    raw   = (pitch + " " + theme).lower()
    raw   = re.sub(r"[^a-z0-9 ]", " ", raw)
    words = [w for w in raw.split() if len(w) > 3 and w not in STOP_WORDS]
    seen, unique = set(), []
    for w in words:
        if w not in seen: seen.add(w); unique.append(w)

    nouns = []
    if NLTK_AVAILABLE:
        try:
            tagged     = pos_tag(word_tokenize(pitch + " " + theme))
            noun_tags  = {"NN", "NNS", "NNP", "NNPS"}
            seen_nouns = set()
            for word, tag in tagged:
                wl = re.sub(r"[^a-z0-9]", "", word.lower())
                if (tag in noun_tags and len(wl) > 3
                        and wl not in STOP_WORDS and wl not in seen_nouns):
                    seen_nouns.add(wl)
                    nouns.append(wl)
        except Exception as e:
            print(f"[Anchor] NLTK POS tagging failed, using fallback: {e}")
            nouns = []

    if not nouns:
        # Fallback: original fixed-list behavior
        nouns = [w for w in unique if w in CINEMATIC_NOUNS]

    if nouns:
        # Rank by rarity in the trained dataset's vocabulary (unseen/rare terms
        # sort first — treated as maximally rare via a large default).
        nouns = sorted(nouns, key=lambda w: _VOCAB_FREQ.get(w, 10**9))

    fillers = [w for w in unique if w not in nouns]
    return nouns, fillers

# ── [KNN] Main hybrid similar-film search — this is "Model 1" ───────────
# Part of Comparative Analysis, which now runs FIRST in the pipeline (see
# the top-of-file banner). Blends the trained knn_model
# (_knn_score_single) with live TMDB search results, semantic-embedding
# similarity, and keyword overlap into one ranked list of comparable films.
# Its output (similar films with real, current TMDB data attached) feeds
# forward into: (1) compute_live_market_adjustment() — a [LIVE MARKET]
# numeric input, (2) budget cross-referencing (fetch_comp_budgets), and
# (3) every [GROQ] prompt as context.
def get_similar_films_hybrid(form_data):
    genres    = as_list(form_data.get("genre"))
    times     = as_list(form_data.get("time_period"))
    pitch     = form_data.get("story_pitch","")
    theme     = form_data.get("main_theme","")
    tones     = as_list(form_data.get("tone"))
    genre_ids = [GENRE_MAP[g] for g in genres if g in GENRE_MAP]

    anchors, fillers = _extract_anchor_words(pitch, theme, genres)
    print(f"[Hybrid] Anchors: {anchors}  Fillers: {fillers[:4]}")

    decade_map = {
        "1970s":("1970-01-01","1979-12-31"), "1980s":("1980-01-01","1989-12-31"),
        "1990s":("1990-01-01","1999-12-31"), "2000s":("2000-01-01","2009-12-31"),
        "2010s":("2010-01-01","2019-12-31"), "2020s":("2020-01-01","2029-12-31"),
        "Contemporary":("2015-01-01","2025-12-31"),
    }
    date_filter = {}
    for t in times:
        if t in decade_map:
            date_filter["primary_release_date.gte"] = decade_map[t][0]
            date_filter["primary_release_date.lte"] = decade_map[t][1]
            break

    candidates = {}

    # ── PASS 1: TMDB keyword-ID discover (best thematic match) ────────
    if anchors:
        kw_ids = _lookup_keyword_ids(anchors[:3])
        print(f"[Hybrid] Keyword IDs: {kw_ids}")
        if kw_ids:
            try:
                params = {"api_key":TMDB_API_KEY,"with_keywords":"|".join(str(v) for v in kw_ids.values()),
                          "sort_by":"popularity.desc","vote_count.gte":20,"language":"en-US","page":1}
                if genre_ids: params["with_genres"] = "|".join(str(g) for g in genre_ids)
                params.update(date_filter)
                r = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=6)
                for res in r.json().get("results",[])[:15]:
                    if res.get("id") and res["id"] not in candidates:
                        candidates[res["id"]] = {"source":"keyword","query_rank":0,"result":res}
                print(f"[Hybrid] Pass 1 keyword discover: {len(candidates)} results")
            except Exception as e:
                print(f"[Hybrid] Pass 1 failed: {e}")

    # ── PASS 2: text search — anchor words only, no genre words ───────
    known_genres_lower = {"comedy","drama","action","horror","thriller","animation",
                          "romance","fantasy","crime","mystery","documentary","adventure","western","war"}
    for qi, words in enumerate([anchors[:3], fillers[:3]]):
        if len(candidates) >= 20: break
        clean_q = " ".join(w for w in words if w not in known_genres_lower)
        if not clean_q.strip() or len(clean_q) < 4: continue
        try:
            r = requests.get(f"{TMDB_BASE}/search/movie",
                             params={"api_key":TMDB_API_KEY,"query":clean_q,
                                     "language":"en-US","page":1}, timeout=6)
            new_n = 0
            for res in r.json().get("results",[])[:12]:
                if res.get("id") and res.get("vote_count",0) >= 20 and res["id"] not in candidates:
                    candidates[res["id"]] = {"source":"search","query_rank":qi+1,"result":res}
                    new_n += 1
            print(f"[Hybrid] Pass 2 query '{clean_q}': {new_n} new")
        except Exception as e:
            print(f"[Hybrid] Pass 2 failed '{clean_q}': {e}")

    # ── PASS 3: genre discover (safety net) ───────────────────────────
    try:
        params = {"api_key":TMDB_API_KEY,"sort_by":"vote_average.desc",
                  "vote_count.gte":80,"language":"en-US","page":1}
        if genre_ids: params["with_genres"] = "|".join(str(g) for g in genre_ids)
        params.update(date_filter)
        r = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=6)
        new_n = 0
        for res in r.json().get("results",[])[:15]:
            if res.get("id") and res["id"] not in candidates:
                candidates[res["id"]] = {"source":"discover","query_rank":99,"result":res}
                new_n += 1
        print(f"[Hybrid] Pass 3 genre discover: {new_n} new, total={len(candidates)}")
    except Exception as e:
        print(f"[Hybrid] Pass 3 failed: {e}")

    if not candidates:
        print("[Hybrid] No candidates — using TMDB fallback")
        return get_similar_films_tmdb(form_data)

    # ── Score and rank ─────────────────────────────────────────────────
    pitch_words = [w for w in re.sub(r"[^a-z0-9 ]"," ",(pitch+" "+theme).lower()).split()
                   if len(w) > 3 and w not in STOP_WORDS]

    scored = []
    for cand in candidates.values():
        r          = cand["result"]
        overview   = r.get("overview","")
        source     = cand["source"]
        query_rank = cand.get("query_rank", 99)

        # Skip adult/sexually explicit content
        if _is_adult_content(r):
            print(f"[Filter] Skipped adult content: {r.get('title','?')}")
            continue

        knn_sim   = _knn_score_single(r, form_data)
        sem_score = _keyword_overlap(pitch_words, overview)

        # Source bonus
        if   source == "keyword": sem_score = min(1.0, sem_score + 0.55)
        elif source == "search":
            sem_score = min(1.0, sem_score + (0.35 if query_rank == 1 else 0.20))
        # Discover-only with zero overlap: skip
        elif source == "discover":
            # Surface search: keep genre-based discover results even with low keyword overlap
            # Deep search: be strict — discover films must have some thematic connection
            if strict_semantic and sem_score < 0.05:
                continue

        vote_avg      = r.get("vote_average", 0)
        quality_bonus = 5 if vote_avg >= 7.5 else (2 if vote_avg >= 6.0 else 0)
        combined      = round(0.65 * (sem_score * 100) + 0.35 * knn_sim + quality_bonus, 2)

        sentences = re.split(r'(?<=[.!?])\s+', overview.strip())
        plot      = sentences[0] if sentences else overview[:120]

        scored.append({
            "tmdb_id":      r.get("id"),
            "title":        r.get("title",""),
            "plot":         plot,
            "overview":     overview,
            "release_date": (r.get("release_date","") or "N/A")[:4],
            "vote_average": round(float(vote_avg), 1),
            "poster":       f"https://image.tmdb.org/t/p/w300{r['poster_path']}" if r.get("poster_path") else None,
            "similarity":   round(combined, 1),
            "reason":       ""
        })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    seen_titles, final = set(), []
    for film in scored:
        if film["title"] not in seen_titles:
            seen_titles.add(film["title"])
            final.append(film)
        if len(final) >= 6: break

    # If we still ended up with fewer than 3, pad with genre discover
    if len(final) < 3:
        print("[Hybrid] Too few results — padding with genre discover")
        return get_similar_films_tmdb(form_data)

    print(f"[Hybrid] Final matches: {[f['title'] for f in final]}")
    return final

# ── [KNN] TMDB genre fallback — used when the hybrid search above can't
# find enough matches; a simpler live TMDB genre-based query, still counts
# as part of the [KNN]/retrieval stage of the pipeline.
def get_similar_films_tmdb(form_data):
    genres    = as_list(form_data.get("genre"))
    times     = as_list(form_data.get("time_period"))
    genre_ids = [GENRE_MAP[g] for g in genres if g in GENRE_MAP]
    params    = {"api_key":TMDB_API_KEY,"sort_by":"vote_average.desc",
                 "vote_count.gte":100,"language":"en-US","page":1}
    if genre_ids: params["with_genres"] = "|".join(str(g) for g in genre_ids)
    decade_map = {"1970s":("1970-01-01","1979-12-31"),"1980s":("1980-01-01","1989-12-31"),
                  "1990s":("1990-01-01","1999-12-31"),"2000s":("2000-01-01","2009-12-31"),
                  "2010s":("2010-01-01","2019-12-31"),"2020s":("2020-01-01","2029-12-31"),
                  "Contemporary":("2015-01-01","2024-12-31")}
    for t in times:
        if t in decade_map:
            params["primary_release_date.gte"] = decade_map[t][0]
            params["primary_release_date.lte"] = decade_map[t][1]
            break
    resp  = requests.get(f"{TMDB_BASE}/discover/movie", params=params)
    films = []
    for r in resp.json().get("results",[])[:6]:
        overview  = r.get("overview","")
        sentences = re.split(r'(?<=[.!?])\s+', overview.strip())
        plot      = sentences[0] if sentences else overview[:120]
        films.append({
            "tmdb_id":      r.get("id"),
            "title":        r.get("title",""),
            "plot":         plot,
            "overview":     overview,
            "release_date": r.get("release_date","N/A")[:4],
            "vote_average": round(r.get("vote_average",0),1),
            "poster":       f"https://image.tmdb.org/t/p/w300{r['poster_path']}" if r.get("poster_path") else None,
            "similarity":   None,
            "reason":       ""
        })
    return films

# ── [LIVE MARKET / INTERNET] Industry trends — text narrative half ──────
# Live DuckDuckGo search (falls back to a live TMDB query if DDG returns
# nothing usable) for "what's happening in this genre right now." Runs
# THIRD in the pipeline, after [XGBOOST] and [KNN]. Its text output is fed
# directly into the [GROQ] AI Strategic Analysis prompt (get_ai_analysis) —
# it does NOT feed any number into the score; see fetch_market_pulse below
# for the numeric counterpart that does.
def fetch_industry_trends(genres, tone, theme):
    genre_str = ", ".join(genres[:2]) if genres else "film"
    try:
        resp = requests.get("https://api.duckduckgo.com/",
                            params={"q":f"{genre_str} film box office trends 2025 2026",
                                    "format":"json","no_redirect":1,"no_html":1}, timeout=5)
        data     = resp.json()
        snippets = []
        if data.get("AbstractText"): snippets.append(data["AbstractText"][:300])
        for topic in data.get("RelatedTopics",[])[:4]:
            text = topic.get("Text","") if isinstance(topic,dict) else ""
            if text and len(text) > 30: snippets.append(text[:200])
        if snippets: return "\n".join(f"- {s}" for s in snippets[:4])
    except Exception as e:
        print(f"[Trends] DDG failed: {e}")
    try:
        genre_ids = [GENRE_MAP[g] for g in genres if g in GENRE_MAP]
        if genre_ids:
            params = {"api_key":TMDB_API_KEY,"with_genres":str(genre_ids[0]),
                      "sort_by":"popularity.desc","primary_release_date.gte":"2024-01-01","page":1}
            resp    = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=5)
            results = resp.json().get("results",[])[:4]
            if results:
                return "\n".join(
                    f"- Recent popular {genre_str} film: '{r['title']}' "
                    f"(popularity: {r.get('popularity',0):.0f}, rating: {r.get('vote_average',0):.1f})"
                    for r in results)
    except Exception as e:
        print(f"[Trends] TMDB fallback failed: {e}")
    return f"No live trend data available for {genre_str}."


# ── [LIVE MARKET / INTERNET] Live market pulse — numeric half ───────────
# Dedicated, always-attempted TMDB call (independent of whether the DDG
# text search above succeeded) that produces a real number: the current
# average rating/popularity of recently-released films in this genre. This
# is the numeric input compute_live_market_adjustment() below needs.
def fetch_market_pulse(genres):
    """
    A dedicated, always-attempted numeric benchmark of "what's actually happening in
    this genre right now" — separate from fetch_industry_trends, which is text-only and
    depends on DuckDuckGo succeeding. This function exists specifically so
    compute_live_market_adjustment() always has a real number to compare against,
    regardless of whether the DDG call above returned anything usable.

    Pulls a sample of recently-released (last 2 years), currently-popular films in the
    pitch's primary genre from TMDB's live /discover endpoint, and averages their real
    vote_average/popularity. vote_count.gte=20 filters out obscure titles with only a
    handful of ratings, so the benchmark reflects films the market has actually judged.

    Returns {"avg_vote_average": float|None, "avg_popularity": float|None, "sample_size": int}.
    None values mean "no live signal available" — callers must treat that as "skip the
    adjustment," never as "assume 0", since 0 would read as a bad market rather than an
    absent one.
    """
    genre_ids = [GENRE_MAP[g] for g in genres if g in GENRE_MAP]
    if not genre_ids:
        return {"avg_vote_average": None, "avg_popularity": None, "sample_size": 0}
    try:
        two_years_ago = (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%d")
        params = {
            "api_key": TMDB_API_KEY, "with_genres": str(genre_ids[0]),
            "sort_by": "popularity.desc", "primary_release_date.gte": two_years_ago,
            "vote_count.gte": 20, "page": 1
        }
        resp = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=5)
        results = resp.json().get("results", [])[:15]
        if not results:
            return {"avg_vote_average": None, "avg_popularity": None, "sample_size": 0}
        avg_vote = sum(r.get("vote_average", 0) for r in results) / len(results)
        avg_pop  = sum(r.get("popularity", 0) for r in results) / len(results)
        return {"avg_vote_average": round(avg_vote, 2), "avg_popularity": round(avg_pop, 1),
                "sample_size": len(results)}
    except Exception as e:
        print(f"[MarketPulse] TMDB fetch failed: {e}")
        return {"avg_vote_average": None, "avg_popularity": None, "sample_size": 0}


# ── [XGBOOST + KNN + LIVE MARKET → combined] This is the "sends results to
# the next stage" handoff point: takes [KNN]'s similar_films (real, current
# TMDB data) and [LIVE MARKET]'s market_pulse, and turns both into ONE
# bounded number that gets added on top of [XGBOOST]'s independent base
# score in analyze() — instead of letting both pieces of live data reach
# only Groq's narrative (which, before this fix, is genuinely all they
# reached — see the thesis note on adjust_score_for_market / adjust_success_
# rate: neither one touched anything but static form fields) ────────────
def compute_live_market_adjustment(similar_films, market_pulse):
    """
    This is the piece that makes "the system looks for similar films through KNN, then
    looks at the real-world market... then with both of those in mind, creates a
    prediction metric" literally true of the code, not just the pitch description.

    similar_films: the KNN+semantic-ranked films already retrieved by
    get_surface_films/get_deep_films for this pitch — real, current TMDB data.
    market_pulse: the live genre benchmark from fetch_market_pulse() above.

    Logic: weight each retrieved comp's real current vote_average by how strong its
    KNN/semantic match was (similarity), and compare that weighted average against the
    live genre benchmark. If this pitch's own real-world comp set is currently
    outperforming what's typical for the genre right now, that's genuine evidence of
    live market alignment — nudge the score up. If its comps are underperforming
    the genre's current baseline, nudge down.

    Deliberately bounded to +/-8 points: this SUPPLEMENTS the independent XGBoost
    4-pillar prediction, it does not override it. XGBoost's own pillar models are
    untouched by this function and keep predicting purely from the pitch/structured
    inputs, exactly as before — per the "keep XGBoost independent" requirement.

    Returns (adjustment: float, detail: dict). detail is surfaced in the /analyze
    response so the live signal is visible and citable, not baked in silently.
    """
    if not similar_films or market_pulse.get("avg_vote_average") is None:
        return 0.0, {"applied": False, "reason": "insufficient live data"}

    weighted_sum, weight_total = 0.0, 0.0
    for f in similar_films:
        w = max(f.get("similarity", 0), 1)  # similarity is 0-100; floor at 1 so no comp gets zero weight
        weighted_sum += f.get("vote_average", 0) * w
        weight_total += w
    if weight_total == 0:
        return 0.0, {"applied": False, "reason": "no comp weight"}

    comp_avg_vote  = weighted_sum / weight_total       # 0-10 scale, real current TMDB rating
    genre_avg_vote = market_pulse["avg_vote_average"]  # 0-10 scale, real current TMDB rating

    delta      = (comp_avg_vote - genre_avg_vote) * 4  # scaled to a meaningful point range
    adjustment = max(-8, min(8, round(delta, 1)))

    return adjustment, {
        "applied": True,
        "comp_avg_vote_average":  round(comp_avg_vote, 2),
        "genre_avg_vote_average": genre_avg_vote,
        "genre_sample_size":      market_pulse.get("sample_size", 0),
        "adjustment":             adjustment
    }


# ── [GROQ] Everything below this line talks to the Groq LLM API ─────────
# Groq runs LAST in the pipeline (see the top-of-file PIPELINE ORDER
# comment). It never computes a score or picks a film itself — every
# function below hands it the already-finished [XGBOOST] + [KNN] +
# [LIVE MARKET] results as plain text/JSON in the prompt, and Groq's only
# job is to write the narrative (analysis text, story advice, budget
# usage guidance, per-film "how it connects" reasons) that explains those
# results. _call_groq() is the raw API wrapper every other Groq function
# below calls; the actual prompt text is where "the results of the other
# models" get handed over — search for "SCORES:" / "COMPARABLE FILMS" /
# "PITCH:" inside each prompt string to see exactly what data each Groq
# call receives.
def _call_groq(prompt, max_tokens=1800, fast=False, temperature=0.7, reasoning_effort="low"):
    """Single Groq call with retry logic. Returns parsed dict or raises.
    fast=True uses openai/gpt-oss-20b (lower token cost, good for film reasons).
    fast=False uses openai/gpt-oss-120b (better quality, for main analysis).
    Groq deprecated llama-3.1-8b-instant and llama-3.3-70b-versatile on
    June 17, 2026, recommending these exact replacements — see
    https://console.groq.com/docs/deprecations

    reasoning_effort: "low" everywhere by default (see the note below on why),
    except _groq_suggest_titles explicitly passes "medium" — that's the one
    call in this app where correct factual recall of a specific real title
    (not fluent blurb-writing) is the entire point, and "low" was a plausible
    contributor to it reliably naming only the most generic comps (The Fault
    in Our Stars, A Walk to Remember) rather than a more specific match that
    exists but takes more effort to retrieve accurately.
    """
    url     = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}
    model   = "openai/gpt-oss-20b" if fast else "openai/gpt-oss-120b"
    payload = {"model": model,
               "messages":[{"role":"user","content":prompt}],
               "temperature":temperature,"max_completion_tokens":max_tokens,
               "reasoning_effort":reasoning_effort}
    # reasoning_effort=low (the default): the gpt-oss models spend part of their token budget on
    # hidden internal reasoning before writing the visible answer, and that hidden
    # reasoning counts against BOTH max_completion_tokens and the per-minute rate
    # limit — even though it's invisible in the output. Most of this app's Groq
    # calls don't need genuine multi-step reasoning (they're structured JSON extraction /
    # short blurb-writing tasks), so keeping this low leaves more of the token
    # budget for the actual visible output (reducing truncated/invalid JSON) and
    # reduces total tokens burned per call (easing rate-limit pressure across the
    # ~12-16 sequential calls one /analyze request makes).
    last_err = ""
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            raw  = resp.json()
            if resp.status_code != 200:
                raise Exception(raw.get("error",{}).get("message", str(raw)))
            text = raw["choices"][0]["message"]["content"].strip()
            text = re.sub(r"^```(?:json)?\s*","",text)
            text = re.sub(r"\s*```$","",text).strip()
            return json.loads(text)
        except Exception as e:
            last_err = str(e)
            print(f"[Groq] Attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                import time; time.sleep(1.5)
    raise Exception(f"All Groq retries failed: {last_err}")


def get_ai_analysis(film_data, similar_films, success_rate, ml_ready,
                    industry_trends, sub_factors):
    """
    [GROQ] Writes the "AI Strategic Analysis" narrative. This is the main place
    where [XGBOOST]'s finished scores (success_rate, sub_factors — financial/
    audience/cultural), [KNN]'s similar_films, and [LIVE MARKET]'s
    industry_trends text ALL get handed to Groq together as prompt context
    (see the "SCORES:", "COMPARABLE FILMS", and "CURRENT MARKET TRENDS" lines
    inside analysis_prompt below) — this is the literal answer to "the part
    that tells Groq to use what the results of the other models returned."

    Two separate Groq calls:
    1. Main analysis (overall, scores, strengths, risks, suggestions)
    2. Film reasons (one per film card)
    Splitting prevents JSON truncation from token overflow.
    """
    genres    = as_list(film_data.get("genre"))
    tones     = as_list(film_data.get("tone"))
    audiences = as_list(film_data.get("target_audience"))
    purposes  = as_list(film_data.get("film_purpose",[]))
    pitch     = film_data.get("story_pitch","(not provided)")
    theme     = film_data.get("main_theme","(not provided)")

    fin_score  = sub_factors["financial"]["score"]
    aud_score  = sub_factors["audience"]["score"]
    cul_score  = sub_factors["cultural"]["score"]
    has_family = any(a in {"Families","Teens"} for a in audiences)
    extra_flag = ["Explicit content with family audience"] \
        if sub_factors["audience"]["pitch_has_explicit"] and has_family else []
    mismatches = sub_factors["financial"].get("mismatch_flags",[]) + extra_flag

    ml_context = (
        f"XGBoost: {success_rate}% from genre={', '.join(genres)}, "
        f"budget={film_data.get('budget_range','')}, decade={film_data.get('time_period','')}."
        if ml_ready else f"Heuristic: {success_rate}%."
    )

    market_label  = film_data.get("_market_label","International market")
    budget_label  = film_data.get("budget_range","this budget")
    genre_label   = normalize(film_data.get("genre"))
    tone_label    = normalize(film_data.get("tone"))
    audience_label= normalize(film_data.get("target_audience"))
    purpose_label = normalize(film_data.get("film_purpose",[]),"unspecified")
    pitch_short   = pitch[:80]

    mismatch_block = ""
    if mismatches:
        mismatch_block = "ISSUES:\n" + "\n".join(f"- {m}" for m in mismatches[:3]) + "\n"

    # ── CALL 1: Main analysis (no film reasons) ───────────────────────
    # Build scope-appropriate film reference block so Groq only cites films
    # that match the user's chosen market scope
    market_scope_val = film_data.get("market_scope", "international")
    scope_film_lines = []
    for f in similar_films[:6]:
        is_ph = f.get("is_filipino", False)
        if market_scope_val == "filipino" and not is_ph:
            continue  # skip international films when Filipino scope
        if market_scope_val == "international" and is_ph:
            continue  # skip Filipino films when international scope
        scope_film_lines.append(
            f"- \"{f['title']}\" ({f['release_date']}) "
            f"★{f['vote_average']} [{f.get('origin_region','Unknown')}] — {(f.get('overview') or '')[:80]}"
        )
    if not scope_film_lines:
        # Fallback: use all films if filtering left nothing
        scope_film_lines = [
            f"- \"{f['title']}\" ({f['release_date']}) ★{f['vote_average']}"
            for f in similar_films[:4]
        ]

    scope_films_block = (
        f"BENCHMARK FILMS ({market_label} only — cite no others):\n"
        + "\n".join(scope_film_lines) + "\n"
    )

    scope_instruction = f"SCOPE: {market_label} ONLY. Only cite films from the list below. No other markets.\n"

    analysis_prompt = (
        # ↓↓↓ THIS is "the part that sends results to Groq" — everything below
        # this line packs [XGBOOST]'s scores (SCORES: line), [KNN]'s similar
        # films (scope_films_block), and [LIVE MARKET]'s trends text
        # (CURRENT MARKET TRENDS line) into the one prompt Groq receives.
        "Film consultant. Blunt. No filler phrases. No: steal/copy/borrow — use: adapt/study/build on.\n"
        + scope_instruction
        + f"PITCH: {pitch_short}\n"
        f"Theme: {theme} | Genre: {genre_label} | Tone: {tone_label}\n"
        f"Secondary Genre Hints: {normalize(film_data.get('secondary_genre',[]),'none')}\n"
        f"Audience: {audience_label} | Budget: {budget_label} | Purpose: {purpose_label}\n"
        f"Market: {market_label}\n"
        f"{mismatch_block}"
        f"CURRENT MARKET TRENDS (live, use to ground market_insight/strategic_suggestions):\n{industry_trends}\n"  # [LIVE MARKET] → Groq
        f"SCORES: Overall={success_rate}% Financial={fin_score}% Audience={aud_score}% Cultural={cul_score}%\n"  # [XGBOOST] → Groq
        f"{ml_context}\n"
        + scope_films_block   # [KNN] similar films → Groq (each tagged with its real cultural/region origin in brackets)
        + "Note: each film above is tagged with its real language/region origin in brackets — "
          "use this to ground cultural_reason in what culture(s) the comps actually draw from, "
          "not genre alone. If the comps skew toward one region/language (e.g. mostly "
          "English-language), name that skew plainly rather than treating it as neutral.\n\n"
        "OUTPUT valid JSON:\n"
        '{"overall_assessment":"2-3 sentences on viability in stated market",'
        '"commercial_success_reason":"3 sentences: ML factors, market reframe, one film from list as benchmark",'
        '"strengths":["pitch-specific strength"],'
        '"risks":["specific actual risk"],'
        '"strategic_suggestions":[{"title":"action","detail":"concrete step"},{"title":"action","detail":"step"},{"title":"action","detail":"step"}],'
        '"alternative_routes":[{"route":"alt","rationale":"why"}],'
        '"market_insight":"one sentence, cite a film from the list above only",'
        f'"financial_reason":"2 sentences on ROI for {budget_label} in {genre_label}",'
        f'"audience_reason":"2 sentences on {aud_score}% for {audience_label}",'
        f'"cultural_reason":"2 sentences on cultural legs for {genre_label}+{theme}, grounded in the actual cultural/regional origin of the comps listed above"'
        "}"
    )

    ANALYSIS_DEFAULTS = {
        "overall_assessment":"","commercial_success_reason":"",
        "strengths":[],"risks":[],"strategic_suggestions":[],
        "alternative_routes":[],"market_insight":"",
        "financial_reason":"","audience_reason":"","cultural_reason":""
    }

    try:
        analysis = _call_groq(analysis_prompt, max_tokens=900)   # [GROQ] the actual LLM call
        for k,v in ANALYSIS_DEFAULTS.items():
            if k not in analysis or analysis[k] is None:
                analysis[k] = v
        print("[Groq] Analysis call success")
    except Exception as e:
        print(f"[Groq] Analysis call failed: {e}")
        analysis = dict(ANALYSIS_DEFAULTS)
        analysis["overall_assessment"] = "AI analysis temporarily unavailable. Please try again."

    # ── CALL 2: Film reasons (separate call, smaller prompt) ──────────
    surface_openers = [
        "Name the plot mechanic in {t} that parallels the pitch's conflict. What can the creator learn from its execution?",
        "Name the character decision in {t} that echoes the protagonist's challenge. What can the creator adapt from it?",
        "Describe the scene in {t} closest to the pitch's tone. How can the creator draw inspiration from that approach?",
        "Identify what {t} balanced well that most genre films fail at. How can the creator be informed by that choice?",
        "Point to where {t} diverges from the pitch concept. What can the creator do differently as a result?",
        "Explain what {t} got right technically. What specific approach can the creator study and build on?",
    ]
    deep_openers = [
        "Identify the emotional undercurrent in {t} beneath the plot. How can the creator draw inspiration from its subtext?",
        "Name the scene in {t} where the tone resonates with the pitch. How can the creator adapt that tonal approach?",
        "Describe how {t} handled a moral tension similar to the pitch. What can the creator learn from its resolution?",
        "Point to the character arc in {t} that parallels the protagonist's internal journey. What writing technique can the creator study?",
        "Explain what {t} was really about under its genre surface. How can the creator build similar thematic depth?",
        "Identify the cultural theme {t} taps into. How can the creator be informed by that approach from a different angle?",
    ]

    def _build_reasons_prompt(films_batch, openers_list, label, offset=0):
        # [GROQ, DEAD CODE — see note at this function's only caller, _fetch_reasons,
        # a few lines down: this pair of helpers is defined but never actually used.
        # The real per-film "How it Connects" reasons come from the separate
        # get_all_film_reasons() function, called later in analyze(). Flagging this
        # rather than deleting it, since removing code wasn't asked for here.]
        # Builds the prompt for the per-film "How it Connects" blurbs — films_batch
        # here would be a chunk of [KNN]'s similar_films results (real TMDB
        # titles/overviews), handed to Groq 3 at a time to avoid JSON truncation.
        lines_r = []
        instructions = []
        output_keys  = []
        for i, f in enumerate(films_batch):
            t  = f["title"]
            ov = (f.get("overview") or "")[:60]
            lines_r.append(f'F{i+1}: "{t}" — {ov}')
            opener = openers_list[(i + offset) % len(openers_list)].replace("{t}", t)
            instructions.append(f'"F{i+1}|{t}": "{opener}"')
            output_keys.append('"F' + str(i+1) + '|' + t + '": "two sentences"')
        return (
            f"Film consultant. 2 sentences per film. No steal/copy/borrow — use: adapt, study, build on.\n"
            f"Start each reason with a specific element from THAT film.\n"
            f"Pitch: {pitch_short} | Genre: {genre_label}\n\n"
            "Films:\n" + "\n".join(lines_r) + "\n\n"
            "Write:\n" + "\n".join(instructions) + "\n\n"
            'OUTPUT JSON: {"film_reasons":{\n'
            + "\n".join(output_keys)
            + "\n}}"
        )

    def _fetch_reasons(films_batch, openers_list, label, offset=0):
        # [GROQ, DEAD CODE] — see note in _build_reasons_prompt above. This helper
        # is defined but its result is discarded: analysis["film_reasons"] is
        # unconditionally set to {} below, and _fetch_reasons is never actually
        # called anywhere in this file.
        if not films_batch:
            return {}
        out = {}
        for chunk_start in range(0, len(films_batch), 3):
            chunk = films_batch[chunk_start:chunk_start + 3]
            prompt = _build_reasons_prompt(chunk, openers_list, label, offset + chunk_start)
            try:
                result = _call_groq(prompt, max_tokens=450, fast=True)
                raw = result.get("film_reasons", {})
                for k, v in raw.items():
                    title = k.split("|")[-1].strip() if "|" in k else k.strip()
                    out[title] = v
                print(f"[Groq] {label} chunk {chunk_start//3+1}: {len(raw)} returned")
            except Exception as e:
                print(f"[Groq] {label} chunk {chunk_start//3+1} failed: {e}")
                for f in chunk:
                    out[f["title"]] = ""
        return out

    # Film reasons handled by get_all_film_reasons() in analyze() — covers all 4 groups
    analysis["film_reasons"] = {}
    return analysis


def _fmt_pillar_score(score):
    """
    Formats a pillar score for inclusion in a Groq prompt. sub_factors uses -1 as a
    sentinel meaning "not applicable yet" (financial when no budget selected, audience
    when no target audience selected) — that -1 was being interpolated directly into
    prompt text as "-1%", and Groq (having no way to know -1 was a sentinel rather
    than a real value) dutifully echoed it back verbatim in user-facing rationale text
    ("The -1% financial success score indicates..."). This converts the sentinel to
    a plain-language note instead, so Groq never sees a nonsensical negative percentage
    and can't repeat it.
    """
    if score is None or score == -1:
        return "not yet determined (not specified by the user)"
    return f"{score}%"

BUDGET_TIERS_ORDER = ["Micro (<$1M)", "Low ($1M-$10M)", "Mid ($10M-$50M)",
                       "High ($50M-$150M)", "Blockbuster ($150M+)"]

# ── [KNN + LIVE MARKET / INTERNET] Real comp-budget cross-referencing ───
# This is the literal mechanism the thesis paper describes for Budget
# Recommendation ("derived by cross-referencing the model's output with the
# budget levels of the similar films retrieved through KNN"). It could NOT
# be implemented before this pass: TMDB's /discover endpoint — the one
# get_surface_films/get_deep_films use for retrieval — never returns
# budget/revenue at all (confirmed in the training notebook's Step 15a note).
# The fix: fetch each top comp's REAL reported budget from TMDB's per-film
# /movie/{id} DETAIL endpoint — the exact same endpoint and methodology
# already validated in the training notebook (Step 15a/15b, financial proxy
# vs real revenue) — just called live, here, for a handful of comps instead
# of a training-time sample.
def fetch_comp_budgets(similar_films, max_films=6):
    """
    [LIVE MARKET / INTERNET] Fetches real, reported budgets for the top
    KNN-retrieved comps. TMDB's budget reporting is sparse (Step 15a found
    real budget+revenue on only a fraction of a general sample) — this
    returns whatever real figures ARE available and stays silent about the
    rest. Callers must treat a short/empty result as "no comp-budget signal
    available," never as "these comps cost $0."
    """
    budgets = []
    for f in (similar_films or [])[:max_films]:
        tmdb_id = f.get("tmdb_id")
        if not tmdb_id or tmdb_id < 0:   # negative ids are Filipino-CSV rows with no real TMDB id
            continue
        try:
            r = requests.get(f"{TMDB_BASE}/movie/{tmdb_id}",
                              params={"api_key": TMDB_API_KEY}, timeout=5)
            detail = r.json()
            budget = detail.get("budget", 0) or 0
            if budget > 0:
                budgets.append({"title": f.get("title", ""), "budget": budget})
        except Exception as e:
            print(f"[CompBudgets] fetch failed for tmdb_id={tmdb_id}: {e}")
    return budgets

def budget_amount_to_tier(amount):
    """Buckets a real dollar figure into this app's 5 budget tiers — same
    bounds used throughout the training notebook's budget-recommender eval
    (Step 15c: BUDGET_BOUNDS)."""
    if amount < 1_000_000:   return "Micro (<$1M)"
    if amount < 10_000_000:  return "Low ($1M-$10M)"
    if amount < 50_000_000:  return "Mid ($10M-$50M)"
    if amount < 150_000_000: return "High ($50M-$150M)"
    return "Blockbuster ($150M+)"

def cross_reference_budget_tier(xgb_tier, comp_budgets):
    """
    [XGBOOST + KNN, combined] Cross-references XGBoost's argmax tier (from
    _xgb_budget_tier_sweep) against the REAL reported budgets of the
    KNN-retrieved comps (fetch_comp_budgets) — this IS the paper's described
    Budget Recommendation mechanism, now actually implemented rather than
    just claimed.

    If no comp has reported budget data (common — TMDB budget reporting is
    sparse), this silently falls back to the pure XGBoost tier, which is
    always a safe, always-available baseline — the paper's mechanism becomes
    an enhancement on top of XGBoost, not a replacement for it, exactly
    because real comp budgets aren't guaranteed to exist for every pitch.

    When comp data IS available, the final tier is the ROUNDED AVERAGE of
    XGBoost's own tier index and the comps' median real-budget tier index —
    deliberately a blend, not a straight override: comps' raw dollar figures
    say nothing about whether that budget suits THIS pitch's genre/tone (see
    genre_budget_fit_bonus), so real comp data nudges the recommendation
    without being allowed to override XGBoost's own genre-aware read alone.
    """
    if not comp_budgets:
        return xgb_tier, {"applied": False, "reason": "no comp budget data available"}

    tiers_order     = BUDGET_TIERS_ORDER
    comp_tier_idxs  = [tiers_order.index(budget_amount_to_tier(c["budget"])) for c in comp_budgets]
    median_comp_idx = int(round(float(np.median(comp_tier_idxs))))
    xgb_idx         = tiers_order.index(xgb_tier)

    final_idx  = int(round((xgb_idx + median_comp_idx) / 2))
    final_idx  = max(0, min(len(tiers_order) - 1, final_idx))
    final_tier = tiers_order[final_idx]

    return final_tier, {
        "applied":           True,
        "xgb_tier":          xgb_tier,
        "comp_median_tier":  tiers_order[median_comp_idx],
        "comp_budgets_used": comp_budgets,
        "final_tier":        final_tier
    }

def _xgb_budget_tier_sweep(form_data):
    """
    [XGBOOST] v12: computes the REAL XGBoost-predicted Financial (and Commercial, for
    context) pillar scores at EVERY budget tier, holding genre/tone/pitch/
    theme/target audience/etc. all constant and only swapping budget_range —
    build_feature_vector reads budget_range to set the popularity-proxy
    feature (see budget_popularity there), so this is a legitimate what-if
    sweep through the actual trained model, not a heuristic.

    This exists so the budget recommendation can be a genuine DERIVED OUTPUT
    of XGBoost (the panelist-mandated correction: Budget Recommendation must
    be derived from XGBoost, not an independent/standalone prediction) —
    previously, Groq was told only the financial score for whichever ONE
    budget the user happened to have already selected, and asked to freely
    pick a "recommended_range" using its own genre-convention judgment. Groq
    never saw what the other 4 tiers would actually score, so nothing
    guaranteed its pick was actually the tier XGBoost rated best — and
    nothing let it explain that a modest score IS the ceiling for a given
    concept versus just being a bad choice among better options.

    Returns a list of {"budget_range","financial_score","commercial_score"}
    dicts, one per tier (in BUDGET_TIERS_ORDER, not sorted by score) — the
    caller decides the argmax and can show the full comparison. Empty list if
    ML isn't ready (caller falls back to the pre-v12 Groq-picks-freely
    behavior in that case, same graceful-degradation pattern as everywhere
    else in this file).
    """
    if not ML_READY:
        return []
    results = []
    genres = as_list(form_data.get("genre"))
    for tier in BUDGET_TIERS_ORDER:
        probe = dict(form_data)
        probe["budget_range"] = tier
        try:
            pillar_scores = predict_pillars_xgb(probe)
            raw_financial = pillar_scores.get("financial")
            corrected_financial = None
            if raw_financial is not None:
                # THE fix for "every recommendation is Blockbuster": the raw pillar score
                # here leans heavily on the budget->popularity proxy, which is close to
                # circular with the training target (see genre_budget_fit_bonus). Without
                # this correction, the argmax below picks Blockbuster for nearly any pitch
                # regardless of genre, because it's reading budget size, not the story.
                fit_bonus = genre_budget_fit_bonus(genres, tier)
                corrected_financial = max(10, min(96, round(raw_financial + fit_bonus)))
            results.append({
                "budget_range":          tier,
                "financial_score":       corrected_financial,
                "financial_score_raw_xgb": raw_financial,  # kept for transparency/thesis
                "commercial_score":      pillar_scores.get("commercial"),
            })
        except Exception as e:
            print(f"[BudgetSweep] tier '{tier}' prediction failed: {e}")
    return results

def get_budget_recommendation(film_data, similar_films, sub_factors):
    """
    [XGBOOST decides the number] + [KNN cross-references real comp budgets]
    + [GROQ writes the prose] — recommended_range starts as
    _xgb_budget_tier_sweep()'s argmax-by-Financial-score tier (WITH the
    genre_budget_fit_bonus correction applied), then cross_reference_budget_tier()
    blends it with the REAL reported budgets of the top KNN-retrieved comps
    (fetch_comp_budgets) when that data is available — this is the paper's
    stated Budget Recommendation mechanism, actually implemented. Groq is
    still used — but only to WRITE PROSE explaining a number it's given
    (usage_guidance/caveats), never to pick the number itself. If the tier
    sweep can't run (ML not ready), this falls back to the original pre-v12
    behavior of letting Groq choose freely, since there's no XGBoost result
    to derive a number from in that case.
    """
    genres       = as_list(film_data.get("genre"))
    tones        = as_list(film_data.get("tone"))
    purposes     = as_list(film_data.get("film_purpose", []))
    distribution = as_list(film_data.get("distribution_goal", []))
    market_scope = film_data.get("market_scope", "international")
    budget_given = film_data.get("budget_range", "")
    casting      = as_list(film_data.get("casting_category", []))
    schedule     = film_data.get("production_schedule", "")
    pitch_short  = film_data.get("story_pitch", "")[:80]
    theme        = film_data.get("main_theme", "")

    genre_label  = normalize(film_data.get("genre"))
    market_label = film_data.get("_market_label", "International market")

    budget_context = (
        f"User's stated budget: {budget_given}" if budget_given
        else "User has NOT specified a budget yet."
    )

    market_note = {
        "international": "Target market is International. Budget norms follow Hollywood/global indie benchmarks.",
        "filipino":      "Target market is the Philippine local market. Budget norms are significantly lower — mainstream Filipino films typically run PHP 10M–150M (~$200K–$3M USD). Blockbuster budgets are not viable for local-only release.",
        "mixed":         "Target market is both Philippine local and International. Recommend a budget range that is viable for both contexts.",
    }.get(market_scope, "")

    tier_sweep  = _xgb_budget_tier_sweep(film_data)   # [XGBOOST] the tier-by-tier sweep call
    valid_tiers = [t for t in tier_sweep if t["financial_score"] is not None]

    if valid_tiers:
        xgb_best = max(valid_tiers, key=lambda t: t["financial_score"])   # [XGBOOST] picks the number
        xgb_only_range = xgb_best["budget_range"]

        # ── [KNN + LIVE MARKET] cross-reference against comps' REAL budgets ──
        # This is the actual implementation of the paper's stated mechanism:
        # "derived by cross-referencing the model's output with the budget
        # levels of the similar films retrieved through KNN." See
        # fetch_comp_budgets/cross_reference_budget_tier for how this degrades
        # gracefully (falls back to the pure XGBoost tier) when no comp has
        # real, reported budget data on TMDB.
        comp_budgets = fetch_comp_budgets(similar_films)
        xgb_recommended_range, comp_crossref_detail = cross_reference_budget_tier(
            xgb_only_range, comp_budgets
        )
        # Tier scores are still computed and kept internally (xgb_tier_comparison, below)
        # for transparency/debugging — but they are NOT shown to Groq's prompt anymore, and
        # the prompt explicitly forbids numeric/comparison output. Per note: Groq should
        # only explain HOW to use this budget tier, never cite scores, dollar figures, or
        # what comparable films cost.
        prompt = (
            # ↓↓↓ [GROQ prompt] "the part that sends results to Groq" for budget —
            # XGBoost's decided tier (xgb_recommended_range) is handed over as a
            # fixed fact ("already decided"); Groq is only allowed to explain it.
            "You are a film production consultant writing practical guidance for how to USE "
            "an already-decided budget tier — the tier itself has been chosen by this app's "
            "trained XGBoost model, not by you. Your only job is to explain what that budget "
            "level practically means for how this film should be made.\n"
            "STRICT RULES:\n"
            "- Do NOT mention any dollar amounts, percentages, scores, or numeric comparisons.\n"
            "- Do NOT cite what any specific film cost or reference comparable-film budgets.\n"
            "- Do NOT say things like 'outperforms' or 'scored higher than' other tiers.\n"
            "- Focus only on practical allocation: cast tier, production scale, crew size, "
            "locations, VFX/practical effects, schedule implications, and marketing scope that "
            "this budget level realistically supports.\n"
            "No filler phrases. No 'it depends'. Be direct.\n\n"
            f"BUDGET TIER (already decided): {xgb_recommended_range}\n"
            f"PITCH: {pitch_short}\n"
            f"Theme: {theme} | Genre: {genre_label} | Tone: {normalize(film_data.get('tone'))}\n"
            f"Purpose: {normalize(purposes, 'unspecified')} | Distribution: {normalize(distribution, 'unspecified')}\n"
            f"Casting level: {normalize(casting, 'unspecified')} | Schedule: {schedule or 'unspecified'}\n"
            f"Market: {market_label}\n"
            f"{market_note}\n\n"
            "Output valid JSON only:\n"
            '{"rationale":"2-3 sentences on practically how to allocate and use this budget '
            'tier for this specific genre/purpose/market — cast, production scale, crew, locations, '
            'schedule, marketing — no numbers of any kind",'
            '"caveats":"1 sentence on the biggest non-financial production risk or constraint to watch at this budget level"}'
        )
    else:
        # ML not ready / sweep produced nothing usable — no XGBoost result exists to derive a
        # number from, so fall back to the pre-v12 behavior: Groq picks the range itself from
        # genre convention, same as this function always did before — still no numbers in output.
        xgb_recommended_range = None
        comp_crossref_detail  = {"applied": False, "reason": "no XGBoost tier to cross-reference"}
        prompt = (
            "You are a film production consultant. Pick a budget tier and explain practically "
            "how to use it — you are NOT given a pre-computed tier this time, so choose one.\n"
            "STRICT RULES:\n"
            "- Do NOT mention any dollar amounts, percentages, scores, or numeric comparisons.\n"
            "- Do NOT cite what any specific film cost or reference comparable-film budgets.\n"
            "- Focus only on practical allocation: cast tier, production scale, crew size, "
            "locations, VFX/practical effects, schedule implications, and marketing scope.\n"
            "No filler phrases. No 'it depends'. Be direct.\n\n"
            f"PITCH: {pitch_short}\n"
            f"Theme: {theme} | Genre: {genre_label} | Tone: {normalize(film_data.get('tone'))}\n"
            f"Purpose: {normalize(purposes, 'unspecified')} | Distribution: {normalize(distribution, 'unspecified')}\n"
            f"Casting level: {normalize(casting, 'unspecified')} | Schedule: {schedule or 'unspecified'}\n"
            f"Market: {market_label}\n"
            f"{market_note}\n"
            f"{budget_context}\n\n"
            "Output valid JSON only:\n"
            '{"recommended_range":"one of: Micro (<$1M) | Low ($1M-$10M) | Mid ($10M-$50M) | High ($50M-$150M) | Blockbuster ($150M+)",'
            '"rationale":"2-3 sentences on practically how to allocate and use this budget '
            'tier for this specific genre/purpose/market — cast, production scale, crew, locations, '
            'schedule, marketing — no numbers of any kind",'
            '"caveats":"1 sentence on the biggest non-financial production risk or constraint to watch at this budget level"}'
        )

    defaults = {
        "recommended_range": xgb_recommended_range or "",
        "rationale": "",
        "caveats": ""
    }

    try:
        result = _call_groq(prompt, max_tokens=400, fast=False)   # [GROQ] the actual LLM call
        for k, v in defaults.items():
            if k not in result or result[k] is None:
                result[k] = v
        if xgb_recommended_range:
            # The range is ALWAYS the cross-referenced tier in this branch — overwritten here
            # (not just requested in the prompt) so a model that ignores instructions and
            # echoes a different tier into this field can't silently desync the displayed
            # range from the number that's actually been computed.
            result["recommended_range"]   = xgb_recommended_range
            result["xgb_tier_comparison"] = valid_tiers            # additive field — frontend can ignore
            result["comp_budget_crossref"] = comp_crossref_detail  # [KNN+LIVE MARKET] transparency — see cross_reference_budget_tier
        print("[Groq] Budget recommendation call success")
        return result
    except Exception as e:
        print(f"[Groq] Budget recommendation call failed: {e}")
        return defaults


def get_story_advice(film_data, similar_films=None, success_rate=None, sub_factors=None):
    """
    [GROQ] Story consultant call — honest creative feedback on the pitch.
    Receives [XGBOOST]'s success_rate/sub_factors and [KNN]'s similar_films
    as evidence so the advice is grounded in the other models' results, not
    just Groq's own read of the pitch text.
    """
    pitch   = film_data.get("story_pitch", "")
    theme   = film_data.get("main_theme", "")
    genre   = normalize(film_data.get("genre"))
    tone    = normalize(film_data.get("tone"))
    budget  = film_data.get("budget_range", "")

    if not pitch or len(pitch.strip()) < 30:
        return None

    # [XGBOOST → GROQ] Build ML context block — grounded facts the advisor can reference
    ml_block = ""
    if success_rate is not None and sub_factors:
        fin = sub_factors["financial"]["score"]
        aud = sub_factors["audience"]["score"]
        cul = sub_factors["cultural"]["score"]
        ml_block = (
            f"ML PREDICTION DATA (XGBoost + business logic):\n"
            f"Overall commercial success: {success_rate}% | "
            f"Financial: {_fmt_pillar_score(fin)} | Audience: {_fmt_pillar_score(aud)} | Cultural: {_fmt_pillar_score(cul)}\n"
            f"Budget: {budget} | Genre: {genre}\n"
            f"Use these numbers to ground your advice — e.g. if financial is low despite "
            f"a high budget, that signals a budget-concept mismatch the story advisor should flag. "
            f"If financial or audience is 'not yet determined', that means the user hasn't specified "
            f"a budget or target audience yet — note that as a gap to fill in, not as a low score.\n\n"
        )

    # [KNN → GROQ] Build similar films block — what KNN found closest to this concept
    films_block = ""
    if similar_films:
        top_films = similar_films[:6]
        lines = []
        for f in top_films:
            title_s = f["title"]
            date_s  = f["release_date"]
            vote_s  = f["vote_average"]
            ov_s    = (f.get("overview") or "")[:100]
            lines.append(f"- \"{title_s}\" ({date_s}) \u2605{vote_s} \u2014 {ov_s}")
        films_block = (
            "SIMILAR FILMS (KNN + TMDB search matched these as closest to the pitch):\n"
            + "\n".join(lines) + "\n"
            "Reference these films when giving story advice — e.g. if Your Name appears, "
            "the advisor can note what that film did with similar material and what this pitch "
            "does differently or better.\n\n"
        )

    prompt = (
        # ↓↓↓ [GROQ prompt] — ml_block ([XGBOOST] results) and films_block ([KNN]
        # results) both get concatenated straight into this prompt below.
        "You are a script development consultant — the kind who reads thousands of pitches "
        "and gives honest, constructive notes backed by data. You are NOT a hype machine.\n\n"
        "RULES:\n"
        "- Be specific to THIS pitch. Never give generic advice.\n"
        "- Do NOT say: it is worth noting, this story has potential, compelling narrative.\n"
        "- Do NOT use: steal, copy, borrow, mirror, replicate. "
        "Use: draw inspiration from, study, adapt, build on, take cues from.\n"
        "- If there are plot holes or logic issues, name them directly.\n"
        "- Reference the ML scores and similar films in your advice — they are evidence, use them.\n"
        "- Tone: honest friend who is also a professional. Direct but not cruel.\n\n"
        f"PITCH:\n{pitch}\n\n"
        f"Theme: {theme} | Genre: {genre} | Tone: {tone}\n"
        f"Secondary genre hints: {normalize(film_data.get('secondary_genre',[]),'none')}\n\n"
        + ml_block
        + films_block +
        "OUTPUT valid JSON only:\n"
        '{"honest_take":"2-3 direct sentences on movie-worthiness, cite ML score",'
        '"what_works":["specific element that works and exactly why"],'
        '"what_needs_work":["specific problem, named directly"],'
        '"thematic_focus":"ONE anchor theme as a question or truth",'
        '"comparable_films":["Film Title — specific similarity in one sentence"],'
        '"story_suggestions":[{"title":"suggestion","detail":"pitch-specific advice"},'
        '{"title":"suggestion","detail":"advice"},{"title":"suggestion","detail":"advice"}],'
        '"verdict":"one punchy sentence on where this pitch stands"}\n'
    )
    try:
        result = _call_groq(prompt, max_tokens=900)   # [GROQ] the actual LLM call
        defaults = {
            "honest_take": "", "what_works": [], "what_needs_work": [],
            "thematic_focus": "", "comparable_films": [],
            "story_suggestions": [], "verdict": ""
        }
        for k, v in defaults.items():
            if k not in result or result[k] is None:
                result[k] = v
        print("[Groq] Story advice call success")
        return result
    except Exception as e:
        print(f"[Groq] Story advice call failed: {e}")
        return None

def adjust_score_for_market(base_score, sub_factors, data, market_scope):
    """
    [RULE-BASED CORRECTION — not XGBoost, not KNN, not Groq]
    Applies market-specific scoring on top of the base adjustment.
    Filipino market weights local cultural resonance differently:
    - Language matters: Filipino/Tagalog content gets local audience bonus
    - Genre popularity differs: local drama/romance/horror more bankable locally
    - Budget ceiling: PH market rarely supports blockbuster-level returns locally
    - Mixed: blended weighted average of both scoring systems
    """
    if market_scope == "international":
        return adjust_success_rate(base_score, sub_factors, data)

    genres    = as_list(data.get("genre"))
    purposes  = as_list(data.get("film_purpose", []))
    budget    = data.get("budget_range", "")
    audiences = as_list(data.get("target_audience"))
    tones     = as_list(data.get("tone"))

    if market_scope == "filipino":
        score = base_score

        # Filipino market genre weights (different from Hollywood)
        ph_strong = {"Drama", "Romance", "Horror", "Comedy", "Thriller"}
        ph_medium = {"Action", "Fantasy", "Crime", "Mystery"}
        ph_weak   = {"Science Fiction", "Animation", "Western", "War", "Documentary"}
        for g in genres:
            if g in ph_strong:  score += 7
            elif g in ph_medium: score += 3
            elif g in ph_weak:   score -= 2

        # Budget ceiling in PH market — blockbuster budgets don't recoup locally
        budget_ph = {
            "Micro (<$1M)":     5,   # indie Pinoy film sweet spot
            "Low ($1M-$10M)":   8,   # mainstream PH commercial
            "Mid ($10M-$50M)":  4,   # high for PH, needs regional play
            "High ($50M-$150M)":-3,  # PH box office can't recoup alone
            "Blockbuster ($150M+)":-10  # impossible to recoup in PH market alone
        }
        score += budget_ph.get(budget, 0)

        # Tone alignment with Filipino audience preferences
        ph_safe_tones = {"Uplifting", "Romantic", "Humorous", "Dramatic", "Nostalgic"}
        for t in tones:
            if t in ph_safe_tones: score += 3

        # Film purpose — social message films resonate strongly locally
        if "Send a Social Message" in purposes: score += 8
        if "Raise Awareness"       in purposes: score += 6
        if "Artistic Expression"   in purposes: score += 5
        if "Just for Fun"          in purposes: score += 3

        # Audience mismatch still applies
        mismatch_penalty = sub_factors["audience"]["mismatch_penalty"]
        score -= mismatch_penalty * 0.5

        return max(15, min(96, round(score)))

    if market_scope == "mixed":
        # Blend: 50% international score + 50% Filipino score
        intl_score = adjust_success_rate(base_score, sub_factors, data)
        ph_score   = adjust_score_for_market(base_score, sub_factors, data, "filipino")
        return max(15, min(96, round((intl_score + ph_score) / 2)))

    return adjust_success_rate(base_score, sub_factors, data)


# ── Filipino film search ───────────────────────────────────────────────
def get_filipino_films_hybrid(form_data):
    """
    Searches for Filipino similar films using:
    1. Curated CSV (local DB for films TMDB misses)
    2. TMDB with origin_country=PH filter
    Both are scored by keyword overlap with the pitch.
    """
    pitch     = form_data.get("story_pitch", "")
    theme     = form_data.get("main_theme", "")
    genres    = as_list(form_data.get("genre"))
    genre_ids = [GENRE_MAP[g] for g in genres if g in GENRE_MAP]

    pitch_words = [w for w in re.sub(r"[^a-z0-9 ]", " ", (pitch + " " + theme).lower()).split()
                   if len(w) > 3 and w not in STOP_WORDS]

    candidates = {}

    
    # Pass 2: TMDB with PH origin country filter
    try:
        params = {
            "api_key":            TMDB_API_KEY,
            "with_origin_country": "PH",
            "sort_by":            "vote_average.desc",
            "vote_count.gte":     20,
            "language":           "en-US",
            "page":               1
        }
        if genre_ids:
            params["with_genres"] = "|".join(str(g) for g in genre_ids)
        resp = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=6)
        for r in resp.json().get("results", [])[:15]:
            tid = r.get("id")
            if tid and tid not in candidates:
                sem = _keyword_overlap(pitch_words, r.get("overview", ""))
                candidates[tid] = {
                    "source":     "tmdb_ph",
                    "result":     r,
                    "sem_score":  sem,
                    "query_rank": 1,
                }
        print(f"[Filipino] TMDB PH pass: {len(candidates)} total candidates")
    except Exception as e:
        print(f"[Filipino] TMDB PH failed: {e}")

    if not candidates:
        return []

    # Score and rank
    scored = []
    for cand in candidates.values():
        r         = cand["result"]
        sem_score = cand["sem_score"]
        knn_sim   = _knn_score_single(r, form_data)
        vote_avg  = r.get("vote_average", 0)
        quality   = 5 if vote_avg >= 7.5 else (2 if vote_avg >= 6.0 else 0)
        combined  = round(0.65 * (sem_score * 100) + 0.35 * knn_sim + quality, 2)

        overview  = r.get("overview", "")
        sentences = re.split(r"(?<=[.!?])\s+", overview.strip())
        plot      = sentences[0] if sentences else overview[:120]

        scored.append({
            "tmdb_id":      r.get("id"),
            "title":        r.get("title", ""),
            "plot":         plot,
            "overview":     overview,
            "release_date": (r.get("release_date", "") or "")[:4],
            "vote_average": round(float(vote_avg), 1),
            "poster":       f"https://image.tmdb.org/t/p/w300{r['poster_path']}" if r.get("poster_path") else None,
            "similarity":   round(combined, 1),
            "is_filipino":  True,
            "reason":       ""
        })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    seen, final = set(), []
    for film in scored:
        if film["title"] not in seen:
            seen.add(film["title"])
            final.append(film)
        if len(final) >= 6: break

    print(f"[Filipino] Final: {[f['title'] for f in final]}")
    return final


# ── Routes ─────────────────────────────────────────────────────────────
def _surface_keywords(pitch, theme, genres, tones):
    """
    Surface-level: broad premise keywords — character type, setting, main conflict.
    These produce matches obvious at first glance (heist → heist, romance → romance).
    """
    anchors, fillers = _extract_anchor_words(pitch, theme, genres)
    known_genres_lower = {"comedy","drama","action","horror","thriller","animation",
                          "romance","fantasy","crime","mystery","documentary",
                          "adventure","western","war","science fiction"}
    # Use anchor words only — strongest narrative signals
    q1_parts = [w for w in anchors[:4] if w not in known_genres_lower]
    # Add genre as a semantic anchor for surface matching
    if genres:
        q1_parts.append(genres[0].lower())
    return " ".join(q1_parts[:5]) if q1_parts else normalize({"genre": genres}, "film")


def _deep_keywords(pitch, theme, genres, tones):
    """
    Deep-level: tonal and thematic nuance keywords — emotional subtext, specific scenes,
    character psychology, moral tension. These produce matches not obvious at first glance.
    """
    # Use theme words + tone words + filler pitch words (not cinematic nouns)
    anchors, fillers = _extract_anchor_words(pitch, theme, genres)
    theme_words = re.sub(r"[^a-z0-9 ]", " ", theme.lower()).split() if theme else []
    tone_map = {
        "Dark": ["grief","loss","despair","tragedy"],
        "Gritty": ["struggle","harsh","brutal","raw"],
        "Nostalgic": ["memory","past","longing","childhood"],
        "Romantic": ["passion","longing","desire","heartbreak"],
        "Satirical": ["absurd","irony","critique","commentary"],
        "Surreal": ["dream","reality","illusion","uncanny"],
        "Thought-provoking": ["question","dilemma","society","meaning"],
        "Melancholic": ["sorrow","bittersweet","isolation","quiet"],
        "Psychological": ["mind","sanity","perception","identity"],
        "Realistic": ["ordinary","everyday","slice","authentic"],
        "Ambiguous": ["unclear","moral","grey","open-ended"],
    }
    tone_words = []
    for t in tones:
        tone_words.extend(tone_map.get(t, [])[:2])

    # Combine: theme words + tone words + top fillers
    deep_parts = (theme_words[:2] + tone_words[:2] + fillers[:2])
    seen, unique = set(), []
    for w in deep_parts:
        if w and w not in seen and len(w) > 3:
            seen.add(w); unique.append(w)
    return " ".join(unique[:5]) if unique else theme


def get_surface_films(form_data, scope="international"):
    """
    [KNN + LIVE TMDB] Surface-level: matches based on main character type, general storyline, premise.
    For Filipino scope: ONLY returns Filipino-language (tl/fil) films.
    For international scope: keyword + text + genre discover.
    """
    genres    = as_list(form_data.get("genre"))
    tones     = as_list(form_data.get("tone"))
    times     = as_list(form_data.get("time_period"))
    pitch     = form_data.get("story_pitch", "")
    theme     = form_data.get("main_theme", "")
    genre_ids = [GENRE_MAP[g] for g in genres if g in GENRE_MAP]

    decade_map = {
        "1970s":("1970-01-01","1979-12-31"),"1980s":("1980-01-01","1989-12-31"),
        "1990s":("1990-01-01","1999-12-31"),"2000s":("2000-01-01","2009-12-31"),
        "2010s":("2010-01-01","2019-12-31"),"2020s":("2020-01-01","2029-12-31"),
        "Contemporary":("2015-01-01","2025-12-31"),
    }
    date_filter = {}
    for t in times:
        if t in decade_map:
            date_filter["primary_release_date.gte"] = decade_map[t][0]
            date_filter["primary_release_date.lte"] = decade_map[t][1]
            break

    candidates = {}

    # ── FILIPINO SCOPE: only search Filipino-language films ───────────
    if scope == "filipino":
        # Fetch many candidates across multiple pages and sort strategies
        # We need extras because adult content filter will remove some
        for lang_code in ("tl", "fil"):
            for sort_by in ("popularity.desc", "vote_average.desc", "vote_count.desc"):
                for page in (1, 2, 3):
                    try:
                        params = {
                            "api_key": TMDB_API_KEY,
                            "with_original_language": lang_code,
                            "sort_by": sort_by,
                            "vote_count.gte": 5,
                            "language": "en-US",
                            "page": page,
                            "without_companies": "149142",  # exclude Vivamax/VMX
                        }
                        # Only apply genre filter on first pass — too restrictive otherwise
                        if genre_ids and sort_by == "popularity.desc" and page == 1:
                            params["with_genres"] = "|".join(str(g) for g in genre_ids)
                        params.update(date_filter)
                        r = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=8)
                        results = r.json().get("results", [])
                        for res in results:
                            rid = res.get("id")
                            if rid and rid not in candidates:
                                candidates[rid] = {"source":"discover","query_rank":page,"result":res}
                        if not results:
                            break
                    except Exception as e:
                        print(f"[Surface-PH] lang={lang_code} sort={sort_by} p{page} failed: {e}")

        # Groq-suggested titles pass — fixes the core limitation above: a genuinely
        # strong Filipino match can have an overview that shares almost no literal
        # vocabulary with the pitch. Verified against real TMDB data before use.
        candidates.update(_groq_candidates(pitch, theme, genres, "filipino", "surface", n=8))

        # v12: direct semantic search against our OWN curated Filipino corpus —
        # guarantees a pitch matching a curated Filipino training film surfaces
        # even if TMDB discover/search and Groq's recall both miss it.
        candidates.update(_corpus_semantic_candidates(pitch, theme, top_k=8, filipino_only=True))

        print(f"[Surface-filipino] {len(candidates)} candidates before adult filter")
        # v15 fix: filter to Filipino-only BEFORE ranking/truncation (require_filipino=True),
        # instead of ranking everything then filtering top-6 afterward — the old order could
        # let a non-Filipino straggler occupy a slot, and its empty-fallback path could
        # silently hand back non-Filipino films under a "Filipino" results section.
        ranked = _score_and_rank(candidates, form_data, pitch, theme, n=6,
                                  strict_semantic=False, require_filipino=True)
        print(f"[Surface-filipino] {len(ranked)} confirmed Filipino films after filter")
        return ranked

    # ── INTERNATIONAL SCOPE ───────────────────────────────────────────
    known_genres_lower = {"comedy","drama","action","horror","thriller","animation",
                          "romance","fantasy","crime","mystery","documentary",
                          "adventure","western","war","science fiction","political drama",
                          "slice of life","psychological","philosophical","social commentary","arthouse"}
    anchors, fillers = _extract_anchor_words(pitch, theme, genres)
    anchor_words = [w for w in anchors[:3] if w not in known_genres_lower]

    if anchor_words:
        surface_q_parts = anchor_words + ([genres[0].lower()] if genres else [])
    else:
        meaningful_fillers = [w for w in fillers if w not in known_genres_lower and len(w) > 3][:4]
        surface_q_parts = meaningful_fillers + ([genres[0].lower()] if genres else [])
    surface_q = " ".join(surface_q_parts[:5])
    print(f"[Surface-intl] Query: '{surface_q}'")

    # Pass 1: keyword IDs
    if anchor_words:
        kw_ids = _lookup_keyword_ids(anchor_words)
        if kw_ids:
            try:
                params = {"api_key":TMDB_API_KEY,
                          "with_keywords":"|".join(str(v) for v in kw_ids.values()),
                          "sort_by":"popularity.desc","vote_count.gte":20,
                          "language":"en-US","page":1}
                if genre_ids: params["with_genres"] = "|".join(str(g) for g in genre_ids)
                params.update(date_filter)
                r = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=6)
                for res in r.json().get("results",[])[:12]:
                    if res.get("id") and res["id"] not in candidates:
                        candidates[res["id"]] = {"source":"keyword","query_rank":0,"result":res}
            except Exception as e:
                print(f"[Surface-intl] KW pass failed: {e}")

    # Pass 2: text search — one query PER anchor word/filler, not one combined phrase.
    # TMDB's /search/movie matches primarily against titles; a multi-word abstract
    # phrase like "factory owner successor poverty" almost never matches a real title.
    search_words = [w for w in surface_q_parts if w.lower() not in known_genres_lower][:4]
    if search_words:
        try:
            found = _search_movie_multi(search_words, per_word_limit=8)
            for rid, (w, res) in found.items():
                if res.get("vote_count",0) >= 10 and rid not in candidates:
                    candidates[rid] = {"source":"search","query_rank":1,"result":res}
        except Exception as e:
            print(f"[Surface-intl] Search failed: {e}")

    # Pass 3: genre discover fallback
    try:
        params = {"api_key":TMDB_API_KEY,"sort_by":"popularity.desc",
                  "vote_count.gte":30,"language":"en-US","page":1}
        if genre_ids: params["with_genres"] = "|".join(str(g) for g in genre_ids)
        params.update(date_filter)
        r = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=6)
        for res in r.json().get("results",[])[:20]:
            if res.get("id") and res["id"] not in candidates:
                candidates[res["id"]] = {"source":"discover","query_rank":99,"result":res}
    except Exception as e:
        print(f"[Surface-intl] Discover failed: {e}")

    # Pass 4: Groq-suggested titles, TMDB-verified — see _groq_candidates for why this
    # exists: keyword/text retrieval structurally cannot find matches whose overviews
    # don't share literal vocabulary with the pitch, no matter how the query is built.
    candidates.update(_groq_candidates(pitch, theme, genres, "international", "surface", n=8))

    # Pass 5 (v12): direct semantic search against our OWN curated training corpus —
    # see _corpus_semantic_candidates. Complements Pass 4: doesn't depend on an LLM
    # recalling the right title, and doesn't depend on TMDB's title-oriented search
    # surfacing the right film either.
    candidates.update(_corpus_semantic_candidates(pitch, theme, top_k=10))

    return _score_and_rank(candidates, form_data, pitch, theme, n=6, strict_semantic=False)


def get_deep_films(form_data, scope="international", exclude_ids=None):
    """
    [KNN + LIVE TMDB] Deep-level: matches based on thematic nuance, emotional subtext, specific scenes.
    Not obvious at first glance — digs into tonal and psychological similarities.
    For Filipino scope: only returns Filipino-language films.
    """
    genres    = as_list(form_data.get("genre"))
    tones     = as_list(form_data.get("tone"))
    times     = as_list(form_data.get("time_period"))
    pitch     = form_data.get("story_pitch", "")
    theme     = form_data.get("main_theme", "")
    genre_ids = [GENRE_MAP[g] for g in genres if g in GENRE_MAP]
    exclude_ids = set(exclude_ids or [])

    # ── FILIPINO SCOPE: only search Filipino-language films ───────────
    if scope == "filipino":
        candidates = {}

        # Trained-model pass (mirrors the international branch below): query knn_model with
        # a Filipino-aware vector (is_filipino=1) and only accept neighbors that are
        # ACTUALLY Filipino-flagged in film_db. Without this, Filipino-deep mode relied
        # purely on a TMDB discover call sorted by rating/popularity with NO relevance
        # filtering — it could only ever surface whatever's highest-rated in Tagalog
        # overall, regardless of the pitch, which is what let totally unrelated films
        # (e.g. a kids' fantasy-comedy, a 1970s historical drama) get forced into results
        # once nothing better existed in that unfiltered pool. This gives Filipino scope
        # the same trained-model relevance signal international scope already had.
        if ML_READY:
            try:
                vec        = build_feature_vector(form_data, is_filipino=True)
                vec_scaled = scaler.transform(vec)
                # Ask for more neighbors than needed since most of film_db is international —
                # we filter down to is_filipino==1 rows after retrieval.
                distances, indices = knn_model.kneighbors(vec_scaled, n_neighbors=200)
                for dist, idx in zip(distances[0], indices[0]):
                    row = film_db.iloc[idx]
                    if not int(row.get("is_filipino", 0)):
                        continue
                    tid = int(row.get("tmdb_id", 0))
                    if tid and tid not in candidates and tid not in exclude_ids:
                        fake = {
                            "id":           tid,
                            "title":        str(row.get("title","")),
                            "overview":     str(row.get("overview","")),
                            "vote_average": float(row.get("vote_average",0)),
                            "vote_count":   500,
                            "release_date": str(row.get("release_date","")),
                            "poster_path":  row.get("poster_path",""),
                            "genre_ids":    [],
                            "original_language": "tl",
                            "popularity":   20,
                        }
                        candidates[tid] = {"source":"knn","query_rank":0,"result":fake}
                        if len(candidates) >= 15:
                            break
            except Exception as e:
                print(f"[Deep-PH] KNN pass failed: {e}")

        for lang_code in ("tl", "fil"):
            for sort_by in ("vote_average.desc", "popularity.desc", "primary_release_date.desc"):
                for page in (1, 2, 3):
                    try:
                        params = {
                            "api_key": TMDB_API_KEY,
                            "with_original_language": lang_code,
                            "sort_by": sort_by,
                            "vote_count.gte": 5,
                            "language": "en-US",
                            "page": page,
                            "without_companies": "149142",  # exclude Vivamax/VMX
                        }
                        r = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=8)
                        results = r.json().get("results", [])
                        for res in results:
                            rid = res.get("id")
                            if rid and rid not in candidates and rid not in exclude_ids:
                                candidates[rid] = {"source":"discover","query_rank":page,"result":res}
                        if not results:
                            break
                    except Exception as e:
                        print(f"[Deep-PH] lang={lang_code} sort={sort_by} p{page} failed: {e}")

        candidates.update(_groq_candidates(pitch, theme, genres, "filipino", "deep",
                                            exclude_ids=exclude_ids, n=8))

        # v12: direct semantic search against our OWN curated Filipino corpus.
        candidates.update(_corpus_semantic_candidates(pitch, theme, top_k=8,
                                                        filipino_only=True, exclude_ids=exclude_ids))

        print(f"[Deep-filipino] {len(candidates)} candidates before adult filter")
        # v15 fix: same as Surface-filipino above — filter to Filipino-only before
        # ranking/truncation so a non-Filipino straggler can never occupy a slot or
        # leak through the empty-fallback path.
        ranked = _score_and_rank(candidates, form_data, pitch, theme, n=6,
                                  strict_semantic=False, require_filipino=True)
        print(f"[Deep-filipino] {len(ranked)} confirmed Filipino films after filter")
        return ranked


    deep_q = _deep_keywords(pitch, theme, genres, tones)
    print(f"[Deep-{scope}] Query: '{deep_q}'")

    candidates = {}
    decade_map = {
        "1970s":("1970-01-01","1979-12-31"),"1980s":("1980-01-01","1989-12-31"),
        "1990s":("1990-01-01","1999-12-31"),"2000s":("2000-01-01","2009-12-31"),
        "2010s":("2010-01-01","2019-12-31"),"2020s":("2020-01-01","2029-12-31"),
        "Contemporary":("2015-01-01","2025-12-31"),
    }
    date_filter = {}
    for t in times:
        if t in decade_map:
            date_filter["primary_release_date.gte"] = decade_map[t][0]
            date_filter["primary_release_date.lte"] = decade_map[t][1]
            break

    ph_filter = {}
    if scope == "filipino":
        ph_filter = {"with_origin_country": "PH"}

    # Deep search: theme + tone keyword search (no genre anchor — intentionally cross-genre)
    for qi, q in enumerate([deep_q, theme]):
        if not q or not q.strip(): continue
        try:
            params = {"api_key":TMDB_API_KEY,"query":q,"language":"en-US","page":1}
            params.update(ph_filter)
            r = requests.get(f"{TMDB_BASE}/search/movie", params=params, timeout=6)
            for res in r.json().get("results",[])[:12]:
                rid = res.get("id")
                if rid and res.get("vote_count",0)>=10 and rid not in candidates and rid not in exclude_ids:
                    candidates[rid] = {"source":"search","query_rank":qi,"result":res}
        except Exception as e:
            print(f"[Deep] Search '{q}' failed: {e}")

    # Also use KNN for tonal-feature similarity — different genres allowed
    if ML_READY:
        try:
            vec        = build_feature_vector(form_data)
            vec_scaled = scaler.transform(vec)
            distances, indices = knn_model.kneighbors(vec_scaled, n_neighbors=15)
            for dist, idx in zip(distances[0], indices[0]):
                row = film_db.iloc[idx]
                tid = int(row.get("tmdb_id", 0))
                if tid and tid not in candidates and tid not in exclude_ids:
                    # Build a fake TMDB result dict from film_db row
                    fake = {
                        "id":           tid,
                        "title":        str(row.get("title","")),
                        "overview":     str(row.get("overview","")),
                        "vote_average": float(row.get("vote_average",0)),
                        "vote_count":   500,
                        "release_date": str(row.get("release_date","")),
                        "poster_path":  row.get("poster_path",""),
                        "genre_ids":    [],
                        "original_language": "en",
                        "popularity":   20,
                    }
                    candidates[tid] = {"source":"knn","query_rank":0,"result":fake}
        except Exception as e:
            print(f"[Deep] KNN pass failed: {e}")

    # Fallback: cross-genre discover with different sort (by vote_average = quality picks)
    if len(candidates) < 6:
        try:
            params = {"api_key":TMDB_API_KEY,"sort_by":"vote_average.desc",
                      "vote_count.gte":200,"language":"en-US","page":1}
            params.update(date_filter)
            params.update(ph_filter)
            r = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=6)
            for res in r.json().get("results",[])[:12]:
                rid = res.get("id")
                if rid and rid not in candidates and rid not in exclude_ids:
                    candidates[rid] = {"source":"discover","query_rank":99,"result":res}
        except Exception as e:
            print(f"[Deep] Discover fallback failed: {e}")

    candidates.update(_groq_candidates(pitch, theme, genres, "international", "deep",
                                        exclude_ids=exclude_ids, n=8))

    # v12: direct semantic search against our OWN curated training corpus.
    candidates.update(_corpus_semantic_candidates(pitch, theme, top_k=10, exclude_ids=exclude_ids))

    return _score_and_rank(candidates, form_data, pitch, theme, n=6)



ADULT_KEYWORDS_FILTER = {
    # English explicit terms
    "erotic","erotica","explicit","pornographic","pornography","softcore",
    "adult film","adult movie","sex tape","nude","nudity","explicit sex",
    "sexual content","18+","xxx","adults only","adult entertainment",
    "sexually explicit","graphic sex","graphic nudity","sexual violence",
    "stripper","prostitut","escort","brothel","mistress","concubine","porno","porn",
    "one night stand","hook up","hookup","seductress","temptress",
    "lustful","carnal","sensual encounter","sexual affair",
    "sex scene","sex worker","call girl","gigolo","sugar daddy","sugar baby",
    # Filipino/Tagalog explicit terms that appear in TMDB titles/overviews
    "bold","boldstar","bold film","bold movie","bomba","tagalog bold",
    "pampagana","kalibugan","maselan","malibog","libog",
    "sabik","mainit","pakikiapid","kaapid","kerida","kabit",
    "bold star","hubad","telenovela bold","sexy film","sexy movie",
    "sexy star","star cinema bold","viva bold","regal bold",
    # Expanded (validated against the real 267-film TMDB Filipino fetch — see retraining
    # notebook for the same logic and the false-positive testing behind it):
    "sex","sexual","seduc","threesome","foursome","orgy","nympho",
    "massage parlor","kept woman","sex slave","sexually abused","sexually assaulted",
    "extramarital","infidelity","sex swap","sex games","sex acts",
    "making love","lovemaking","sexual fantasy","sexual relationship",
    "sexual satisfaction","selling her body","explore their bodies",
    "explore her body","companion of a wealthy","uses her body","scorpio nights",
}

# Ambiguous words have legitimate everyday non-sexual uses ("ambitions and passions",
# "desire to succeed") so they only flag the film when they co-occur with explicit/illicit
# context — a bare-word match against ADULT_KEYWORDS_FILTER would have wrongly excluded
# real, relevant films (confirmed empirically: "On the Job"'s overview uses "ambitions and
# passions" non-sexually and was a false positive before this fix was added).
ADULT_CONTEXT_PAIRS = [
    (r"\baffair\b",     r"steamy|illicit|secret|forbidden"),
    (r"\bdesire\b",     r"sexual|carnal|forbidden|illicit"),
    (r"\blust\b",       r"temptation|forbidden|illicit"),
    (r"\bpassion\b",    r"forbidden|illicit|steamy|secret affair"),
    (r"\btemptation\b", r"flesh|forbidden|illicit"),
    (r"\bsteamy\b",     r""),  # steamy alone is unambiguous enough in film-overview context
]

# Vivamax/VMX TMDB company ID — known adult content producer
# Source: https://www.themoviedb.org/company/149142-vivamax
VIVAMAX_COMPANY_IDS = {149142}
VIVAMAX_NETWORK_IDS = {4569}

# Explicit title blocklist — Filipino films that must never appear in results
BLOCKED_TITLES = {
    "gameboys",
    "serbis", "service",
    "daybreak",
    "antonio's secret",
    "the masseur",
    "no way out",
    "heavenly touch",
    "fuccbois",
    "tirador",
    "laman ekis",
    "segurista",
    "private show",
    "burlesk queen",
    "boatman",
    "scorpio nights 2",
    "takaw-tukso",
    "tuhog",
    "scorpio nights",
    "scorpio nights 3",
    "ang kabit ni mrs. montero",
    "totoy mola",
    "anakan mo ako",
    "ang magsasaging ni pacing",
    "arayyyy!",
    "balahibong pusa",
    "batuta ni dracula",
    "bibingka: apoy sa ilalim, apoy sa ibabaw",
    "diligin ng suka ang uhaw na lumpia",
    "itlog",
    "kainan sa highway",
    "kangkong",
    "kapag ang palay naging bigas…may bumayo",
    "kapag ang palay naging bigas may bumayo",
    "kesong puti",
    "masarap na pugad",
    "masikip mainit paraisong parisukat",
    "masarap habang mainit",
    "matamis hanggang dulo",
    "'pag dumikit kumakapit",
    "pag dumikit kumakapit",
    "pagsaluhan",
    "patikim ng pinya",
    "pila balde",
    "talong",
    "rigodon",
    # Title-only signal: some entries have a fully sanitized overview that reveals nothing
    # about actual content (e.g. "Nympho": "A woman seeking excitement meets a man who
    # brings light and meaning to her world." — only the title signals what it really is).
    "nympho","xxx","virgin","bomba","macho dancer",
}

def _is_adult_content(result):
    """Returns True if this film appears to be adult/sexual content, or has sexual content
    as its plot's core focus. Per explicit content policy, this is intentionally aggressive —
    it also excludes internationally respected films centered on sexual/exploitation themes
    (e.g. Macho Dancer, Serbis), not just exploitative content."""
    if result.get("adult"): return True

    # Block by explicit title blocklist (case-insensitive)
    title_lower = (result.get("title") or "").lower().strip()
    orig_title_lower = (result.get("original_title") or "").lower().strip()
    if title_lower in BLOCKED_TITLES or orig_title_lower in BLOCKED_TITLES:
        return True
    if any(flag in title_lower for flag in ("nympho","xxx","virgin","scorpio nights","bold","bomba")):
        return True

    # Block Vivamax/VMX productions by TMDB company ID
    for co in (result.get("production_companies") or []):
        if isinstance(co, dict) and co.get("id") in VIVAMAX_COMPANY_IDS:
            return True
    for net in (result.get("networks") or []):
        if isinstance(net, dict) and net.get("id") in VIVAMAX_NETWORK_IDS:
            return True

    overview = (result.get("overview") or "").lower()
    title    = (result.get("title") or "").lower()
    text     = overview + " " + title

    # Check keyword list (unambiguous terms — always flag on match)
    for kw in ADULT_KEYWORDS_FILTER:
        if kw in text: return True

    # Context-aware check for ambiguous words (only flag when paired with explicit context —
    # see ADULT_CONTEXT_PAIRS comment for why bare-word matching caused false positives)
    for word_pat, context_pat in ADULT_CONTEXT_PAIRS:
        if re.search(word_pat, text):
            if context_pat == "" or re.search(context_pat, text):
                return True

    # Filipino adult films often have NO overview and only Romance/Drama genre
    # with suspiciously low vote counts
    genre_ids  = result.get("genre_ids") or []
    vote_count = result.get("vote_count") or 0
    vote_avg   = result.get("vote_average") or 0
    no_overview = len(overview.strip()) < 20

    # Only romance or romance+drama with no overview and low votes = likely adult
    if set(genre_ids) <= {10749, 18} and no_overview and vote_count < 10:
        return True

    # Fake-rated: very high rating with very few votes and no description
    if vote_avg >= 9.0 and vote_count < 20 and no_overview:
        return True

    return False

SIMILARITY_FLOOR = 45  # Candidates scoring below this are dropped rather than padding
                        # results with weak/unrelated films. Calibrated against real score
                        # distributions from the TF-IDF-based trained dataset. If fewer than
                        # 3 candidates survive the floor, we fall back to the best-available
                        # (unfiltered) results instead of returning too few/no matches.
                        # v12 NOTE: this operates on the FINAL blended score (0.65*sem_score
                        # + 0.35*knn_sim + quality_bonus), not raw_sem directly, so it's less
                        # exposed to the TF-IDF->embedding scale shift than RAW_OVERLAP_FLOOR/
                        # KEYWORD_FLOOR were (see _score_and_rank) — left unchanged for now,
                        # but re-check it against real result quality once the embedding
                        # model is actually loadable and you can see real score distributions.

def _is_filipino_result(r):
    """
    [KNN] Single source of truth for "is this raw TMDB result Filipino" —
    previously this exact check was duplicated inline (once for filtering,
    once for output-dict tagging), which is how the two copies could drift
    out of sync. Used both to build the is_filipino output flag AND, as of
    v15, to filter Filipino-scope candidate pools BEFORE ranking (see
    _score_and_rank's require_filipino param) — the fix for Filipino-scope
    results silently including non-Filipino stragglers.
    """
    return (r.get("original_language","") in ("tl","fil")
            or r.get("origin_country","") == "PH"
            or "PH" in (r.get("production_countries") or []))

def _score_and_rank(candidates, form_data, pitch, theme, n=6, strict_semantic=True, require_filipino=False):
    """[KNN] Shared scoring + ranking logic for both surface and deep film searches —
    this is where _knn_score_single's output blends with semantic similarity and
    keyword overlap into the final similar-films list that later reaches Groq.

    require_filipino: v15 fix. When True, non-Filipino candidates are dropped
    BEFORE floor/dedupe/truncation, not after. Previously the Filipino-scope
    callers ranked the FULL candidate pool, truncated to top-n, THEN filtered
    for is_filipino — meaning if a non-Filipino straggler (e.g. from the
    genre-discover fallback pass) outranked a genuine Filipino candidate, it
    could occupy one of the n slots, and the fallback-when-empty path
    (`ranked[:n]`) could silently hand back non-Filipino films under a
    "Filipino" results section. Filtering first guarantees every slot in the
    output was actually a Filipino candidate to begin with.
    """
    pitch_words = [w for w in re.sub(r"[^a-z0-9 ]"," ",(pitch+" "+theme).lower()).split()
                   if len(w) > 3 and w not in STOP_WORDS]
    pitch_text_full = pitch + " " + theme

    # v12: batch-encode the pitch ONCE and every candidate's overview in ONE
    # model call, instead of letting _semantic_similarity re-encode the same
    # pitch text once per candidate inside the loop below — a single request
    # can score a few dozen candidates, and each embed call has real latency
    # in a live demo in front of the panel. If batching fails for any reason
    # (embedder not loaded, encode error), these come back None and every
    # candidate just falls through to _semantic_similarity's own per-call
    # encoding / keyword-overlap fallback — same end behavior, just slower.
    cand_list = list(candidates.values())
    pitch_emb = _embed_text(pitch_text_full)
    overview_embs = _embed_texts([c["result"].get("overview", "") for c in cand_list]) \
                    if pitch_emb is not None else None

    raw_sem_diagnostic = []   # (title, raw_sem) — see the summary print after the loop
    scored = []
    for i, cand in enumerate(cand_list):
        r          = cand["result"]
        # Content-safety chokepoint: every candidate from every source/scope passes through
        # here before becoming a final result, so this is the single correct place to apply
        # the adult-content filter. Previously _is_adult_content existed but was only called
        # from get_similar_films_hybrid, a function never used by the live /analyze pipeline —
        # meaning NO adult-content filtering actually ran on real results despite the function
        # being fully built. This wires it into the path that's actually used.
        if _is_adult_content(r):
            continue
        if require_filipino and not _is_filipino_result(r):
            continue
        overview   = r.get("overview","")
        source     = cand["source"]
        query_rank = cand.get("query_rank", 99)

        knn_sim = _knn_score_single(r, form_data)

        if source == "groq_suggest":
            # Groq was asked specifically "what real films are similar to this pitch" —
            # that's a semantic judgment call the floor below can't replicate (a genuinely
            # perfect match's TMDB overview often shares almost no literal vocabulary with
            # an abstract pitch — e.g. "eccentric candy manufacturer" vs "toy factory
            # owner"). The floor exists to catch UNJUDGED, blindly-retrieved candidates;
            # these already had judgment applied and were independently verified to exist
            # on TMDB (see _verify_tmdb_title), so they skip straight to a flat relevance
            # credit rather than being punished for low text overlap.
            sem_score = 0.75
        elif source == "corpus_semantic":
            # v12: this candidate came from a direct embedding-cosine search against OUR
            # OWN verified training corpus (see _corpus_semantic_candidates) — arguably the
            # most trustworthy signal available, since it's a deterministic vector
            # comparison against real, curated data rather than an LLM's recall or a
            # lexical text-search API.
            #
            # v15 fix: the boost multiplier below previously did NOT reflect that claim —
            # it was 1.15x, weaker than "keyword" (1.6x) and "search" (1.3x), even though
            # corpus_semantic's underlying signal (real cosine similarity) is the SAME kind
            # of number the other branches boost, just computed against a smaller, curated,
            # higher-confidence pool. That inversion is why a genuinely strong corpus match
            # (e.g. the real Titanic plot against its own curated corpus entry) could be
            # outranked by a weaker match from a more heavily-boosted source. Now matches
            # "keyword" as the joint-highest-trust boost, consistent with the docstring's
            # own claim rather than contradicting it.
            sem_score = min(1.0, cand.get("_semantic_score", 0.5) * 1.6)
        else:
            oe = overview_embs[i] if overview_embs is not None else None
            raw_sem = _semantic_similarity(pitch_words, pitch_text_full, overview,
                                            pitch_emb=pitch_emb, overview_emb=oe)
            raw_sem_diagnostic.append((r.get("title", "?"), source, round(raw_sem, 3)))

            # v12 CALIBRATION WARNING: these floors were tuned for TF-IDF cosine, which is
            # exactly 0 for texts with zero shared vocabulary and rarely exceeds ~0.3 even
            # for a strong match. Embedding cosine has a completely different scale — even
            # weakly/thematically-related text pairs commonly land ~0.15-0.35, and it's
            # almost never near 0. Reusing the old TF-IDF-calibrated floors here would let
            # nearly everything through, reopening exactly the "weakly/coincidentally
            # matched films leak into results" problem the floor was built to prevent (see
            # the original comment this replaced). These new values are a principled
            # starting point for all-MiniLM-L6-v2, NOT measured against this app's real
            # candidate pool — my sandbox can't reach huggingface.co to check actual
            # numbers. Watch the "[Semantic] raw_sem distribution" print below across a
            # few real requests and move these to wherever they actually separate real
            # matches from noise in practice.
            RAW_OVERLAP_FLOOR = 0.35   # was 0.12 under TF-IDF
            KEYWORD_FLOOR     = 0.25   # was 0.05 under TF-IDF — TMDB keyword-ID matches
                                        # still carry some inherent thematic evidence, so
                                        # they keep a lower bar than the rest, just a higher
                                        # ABSOLUTE one than before given the new scale.
            floor = KEYWORD_FLOOR if source == "keyword" else RAW_OVERLAP_FLOOR
            if raw_sem < floor:
                continue

            SOURCE_BOOST = {"keyword": 1.6, "knn": 1.35, "search": 1.3, "discover": 1.0}
            boost        = SOURCE_BOOST.get(source, 1.0)
            if source == "search" and query_rank != 0:
                boost = 1.15
            sem_score = min(1.0, raw_sem * boost)

        vote_avg      = r.get("vote_average", 0)
        quality_bonus = 5 if vote_avg >= 7.5 else (2 if vote_avg >= 6.0 else 0)
        # v15: rebalanced from 0.65/0.35 to 0.75/0.25. Users are explicitly asked to type
        # a detailed story pitch (often a full plot synopsis) specifically so the system
        # can find a matching film by CONTENT -- that's the evidence they're actually
        # supplying. The structured-metadata component (knn_sim: genre/budget-tier/decade/
        # language) reflects form fields the user picks somewhat independently of the real
        # film's actual attributes (e.g. selecting a different genre or budget tier than
        # the real film's own), so under the old 35% weight, a near-perfect text match
        # could still be dragged down by up to ~35 points purely from an unrelated
        # metadata mismatch. Keeping a smaller structured component (secondary refinement,
        # not a co-equal driver) still lets genre/tone act as a tiebreaker without letting
        # it override a strong content match.
        combined      = round(0.75 * (sem_score * 100) + 0.25 * knn_sim + quality_bonus, 2)

        plot = overview.strip()

        poster_path = r.get("poster_path","")
        origin_lang, origin_region = classify_film_culture(r)   # [CULTURAL TRANSPARENCY]
        scored.append({
            "tmdb_id":       r.get("id"),
            "title":         r.get("title",""),
            "plot":          plot,
            "overview":      overview,
            "release_date":  (r.get("release_date","") or "N/A")[:4],
            "vote_average":  round(float(vote_avg), 1),
            "poster":        f"https://image.tmdb.org/t/p/w300{poster_path}" if poster_path else None,
            "similarity":    round(combined, 1),
            "is_filipino":   _is_filipino_result(r),
            "origin_language": origin_lang,   # [CULTURAL TRANSPARENCY] e.g. "ko", "fr", "en"
            "origin_region":   origin_region, # [CULTURAL TRANSPARENCY] e.g. "East Asian (Korean)"
            "reason":        ""
        })

    if raw_sem_diagnostic:
        vals = [v for _, _, v in raw_sem_diagnostic]
        print(f"[Semantic] raw_sem distribution over {len(vals)} candidates: "
              f"min={min(vals):.3f} max={max(vals):.3f} mean={sum(vals)/len(vals):.3f}  |  "
              f"top 5: {sorted(raw_sem_diagnostic, key=lambda t: -t[2])[:5]}")

    scored.sort(key=lambda x: x["similarity"], reverse=True)

    def _dedupe_top(films, apply_floor):
        seen, out = set(), []
        for film in films:
            if apply_floor and film["similarity"] is not None and film["similarity"] < SIMILARITY_FLOOR:
                continue
            if film["title"] not in seen:
                seen.add(film["title"])
                out.append(film)
            if len(out) >= n:
                break
        return out

    final = _dedupe_top(scored, apply_floor=True)

    if len(final) < 3:
        print(f"[Ranked] Only {len(final)} passed the {SIMILARITY_FLOOR} floor — falling back to best-available")
        final = _dedupe_top(scored, apply_floor=False)

    print(f"[Ranked] Top {len(final)}: {[f['title'] for f in final]}")
    return final



def get_all_film_reasons(film_data, intl_surface=None, intl_deep=None, ph_surface=None, ph_deep=None):
    """
    [GROQ] This is the function that ACTUALLY generates the per-film "How it
    Connects" reasons shown in the UI (called from analyze()) — receives
    [KNN]'s 4 film groups (intl/PH x surface/deep) as input.
    Generates AI reasons for ALL film groups independently.
    Each group is processed in 3-film chunks to guarantee complete output.
    Returns a single dict of {film_title: reason}.
    """
    pitch   = film_data.get("story_pitch", "")
    theme   = film_data.get("main_theme", "")
    genre   = normalize(film_data.get("genre"))
    pitch_short = pitch[:80]

    surface_openers = [
        "Name the plot mechanic in {t} that parallels the pitch. What can the creator learn?",
        "Name the character decision in {t} that echoes the protagonist. What can be adapted?",
        "Describe the scene in {t} closest to the pitch's tone. How to draw inspiration?",
        "What did {t} balance well that others fail at? How can the creator build on this?",
        "Where does {t} diverge from the pitch? What should the creator do differently?",
        "What did {t} get right technically? What approach can the creator study?",
    ]
    deep_openers = [
        "What emotional undercurrent in {t} connects to the pitch's theme? How to draw inspiration?",
        "Which scene in {t} resonates with the pitch's tone? How can the creator adapt it?",
        "How did {t} handle a moral tension similar to the pitch? What can be learned?",
        "Which character arc in {t} parallels the protagonist's journey? What to study?",
        "What is {t} really about beneath its surface? How can the creator build similar depth?",
        "What cultural theme does {t} tap into that the pitch shares? How to be informed by it?",
    ]

    def _fetch_group_reasons(films, openers, group_label):
        if not films:
            return {}
        out = {}
        for chunk_start in range(0, len(films), 3):
            chunk = films[chunk_start:chunk_start + 3]
            lines_r, instructions, output_keys = [], [], []
            for i, f in enumerate(chunk):
                t  = f["title"]
                ov = (f.get("overview") or "")[:60]
                lines_r.append(f"F{i+1}: \"{t}\" — {ov}")
                opener = openers[(chunk_start + i) % len(openers)].replace("{t}", t)
                instructions.append(f"\"F{i+1}|{t}\": \"{opener}\"")
                output_keys.append(f"\"F{i+1}|{t}\": \"two sentences\"")
            prompt = (
                f"Film consultant. 2 sentences per film. No steal/copy/borrow — use: adapt, study, build on.\n"
                f"Start each reason with a specific element from THAT film.\n"
                f"Pitch: {pitch_short} | Genre: {genre}\n\n"
                "Films:\n" + "\n".join(lines_r) + "\n\n"
                "Write:\n" + "\n".join(instructions) + "\n\n"
                "OUTPUT JSON: {\"film_reasons\":{\n"
                + "\n".join(output_keys)
                + "\n}}"
            )
            try:
                result = _call_groq(prompt, max_tokens=450, fast=True)   # [GROQ] the actual LLM call — the real, USED per-film-reason call
                raw = result.get("film_reasons", {})
                for k, v in raw.items():
                    title = k.split("|")[-1].strip() if "|" in k else k.strip()
                    # Groq occasionally nests the answer under a sub-key instead of
                    # returning plain text directly (more likely on small chunks where
                    # the small fast model's output format gets less consistent). Without
                    # this check, a dict value gets stored as-is and the frontend renders
                    # it as the literal string "[object Object]" instead of real text.
                    if isinstance(v, dict):
                        v = " ".join(str(x) for x in v.values() if isinstance(x, (str, int, float))) or ""
                    elif not isinstance(v, str):
                        v = str(v) if v is not None else ""
                    out[title] = v
                print(f"[Groq] {group_label} chunk {chunk_start//3+1}: {len(raw)} reasons")
            except Exception as e:
                print(f"[Groq] {group_label} chunk {chunk_start//3+1} failed: {e}")
        return out

    all_reasons = {}
    all_reasons.update(_fetch_group_reasons(intl_surface or [], surface_openers, "intl_surface"))
    all_reasons.update(_fetch_group_reasons(intl_deep    or [], deep_openers,    "intl_deep"))
    all_reasons.update(_fetch_group_reasons(ph_surface   or [], surface_openers, "ph_surface"))
    all_reasons.update(_fetch_group_reasons(ph_deep      or [], deep_openers,    "ph_deep"))
    print(f"[Groq] Total reasons collected: {len(all_reasons)}")
    return all_reasons

@app.route("/ml_status")
def ml_status():
    return jsonify({
        "ml_ready": ML_READY,
        "embedder_ready": EMBEDDER_READY,          # v12: false means text similarity has
                                                     # silently fallen back to _keyword_overlap
        "corpus_semantic_ready": bool(EMBEDDER_READY and FILM_EMBEDDINGS is not None),
        "corpus_film_count": int(len(film_db)) if film_db is not None else 0,
    })

@app.route("/analyze", methods=["POST"])
def analyze():
  try:
    data         = request.json
    market_scope = data.get("market_scope", "international")  # international | filipino | mixed

    # Validate required fields server-side
    missing = []
    if not data.get("story_pitch","").strip(): missing.append("story_pitch")
    if not data.get("main_theme","").strip():  missing.append("main_theme")
    if not data.get("genre"):                  missing.append("genre")
    if not data.get("tone"):                   missing.append("tone")
    if missing:
        return jsonify({"error": f"Required fields missing: {', '.join(missing)}"}), 400

    # ══════════════════════════════════════════════════════════════════
    # PIPELINE ORDER — matches the thesis paper's Conceptual Framework:
    # Comparative Analysis (KNN) → real-world market check → Predictive
    # Analysis (XGBoost) produces the prediction metric informed by both →
    # Budget Recommendation (cross-referenced against KNN comps' real
    # budgets) → Groq synthesizes everything into professional narrative.
    # See the top-of-file ARCHITECTURE OVERVIEW banner for the full map.
    #
    # HONEST NOTE ON WHAT "INFORMED BY" MEANS HERE: XGBoost's own trained
    # weights are fixed at training time and are NOT retrained per-request —
    # they cannot literally ingest this exact pitch's live-retrieved KNN
    # films as brand-new inputs without a full retrain (a heavier, separate
    # undertaking). What IS true, and what "informed by" means in this code:
    # the FINAL prediction metric returned to the user — the number actually
    # displayed and handed to Groq — is only ever finalized AFTER KNN
    # retrieval and the live market check have both run, via a bounded,
    # documented adjustment (compute_live_market_adjustment). So the metric
    # you see is never "XGBoost alone" — it's XGBoost's independent read,
    # corrected using real KNN comps + real current market data, in that
    # order, before anything downstream (budget rec, Groq) ever sees it.
    # ══════════════════════════════════════════════════════════════════

    # STEP 1 — [KNN] similar + deep film retrieval, for each market scope.
    # Runs FIRST — this is the paper's "Comparative Analysis" stage. Blends
    # the trained knn_model with live TMDB search results. Its output
    # (all_films) feeds forward into STEP 2 (comp-budget cross-referencing
    # is deferred to the budget step), STEP 3 (live-market adjustment),
    # and every STEP 5/6 [GROQ] prompt.
    intl_surface, intl_deep, ph_surface, ph_deep = [], [], [], []

    if market_scope in ("international", "mixed"):
        intl_surface = get_surface_films(data, scope="international")
        intl_surface_ids = {f["tmdb_id"] for f in intl_surface}
        intl_deep    = get_deep_films(data, scope="international",
                                      exclude_ids=intl_surface_ids)

    if market_scope in ("filipino", "mixed"):
        ph_surface   = get_surface_films(data, scope="filipino")
        ph_surface_ids = {f["tmdb_id"] for f in ph_surface}
        ph_deep      = get_deep_films(data, scope="filipino",
                                      exclude_ids=ph_surface_ids)

    # Backward-compat + Groq gets all films
    all_films = intl_surface + intl_deep + ph_surface + ph_deep   # [KNN] combined output, sent to STEP 3 and STEP 5/6
    intl_films = intl_surface  # backward compat
    ph_films   = ph_surface    # backward compat

    # [CULTURAL TRANSPARENCY, v2] Upgrade the top comps from the free
    # language-code guess to real production_countries data (one extra live
    # TMDB call per film, bounded by CULTURAL_COUNTRY_MAX_FETCH). Mutates
    # the film dicts in place, so intl_surface/intl_deep/ph_surface/ph_deep
    # (which share these same objects) all pick up the upgrade too — this
    # must run BEFORE the composition tally below so the tally reflects the
    # upgraded, more precise labels wherever they were available.
    enrich_films_with_precise_culture(all_films)

    # [CULTURAL TRANSPARENCY] Summarize the cultural composition of every
    # retrieved comp in ONE place — directly answers "which cultures is
    # this pitch actually being compared against." Computed here (not
    # per-film) so it's a single, glanceable metric in the response and in
    # Groq's prompt, rather than something a reader has to reconstruct by
    # counting origin_region tags across every film card by hand.
    cultural_composition = {}
    for f in all_films:
        region = f.get("origin_region", "Unknown")
        cultural_composition[region] = cultural_composition.get(region, 0) + 1

    # STEP 2 — [LIVE MARKET / INTERNET] the only live "check the real world"
    # calls in this app. Runs SECOND, after KNN retrieval, matching the
    # paper's "checks current market conditions" stage. market_pulse is a
    # live TMDB numeric benchmark; industry_trends is live DDG/TMDB text.
    # Both get sent forward: market_pulse → STEP 3 (the number),
    # industry_trends → STEP 5 [GROQ] (the narrative).
    genres          = as_list(data.get("genre"))
    market_pulse    = fetch_market_pulse(genres)
    industry_trends = fetch_industry_trends(genres, normalize(data.get("tone")), data.get("main_theme",""))

    # STEP 3 — [XGBOOST] runs THIRD — this is the paper's "Predictive
    # Analysis" stage, and it now runs AFTER Comparative Analysis (STEP 1)
    # and the market check (STEP 2), matching the paper's stated sequence.
    # predict_all_pillars() itself still computes its 4 independent pillar
    # scores purely from the pitch/form fields (see the HONEST NOTE above
    # for why XGBoost's own weights can't literally consume STEP 1/2's
    # output without a retrain) — but the PREDICTION METRIC this function
    # returns to the user is only finalized immediately below, by folding
    # STEP 1's KNN comps + STEP 2's market pulse into a bounded adjustment
    # on top of XGBoost's independent read. This is the literal "with both
    # of those in mind, it creates a prediction metric" step.
    base_score, sub_factors, method = predict_all_pillars(data)

    live_adjustment, live_market_detail = compute_live_market_adjustment(all_films, market_pulse)
    base_score_live = max(10, min(96, round(base_score + live_adjustment)))

    success_rate = adjust_score_for_market(base_score_live, sub_factors, data, market_scope)  # [RULE-BASED CORRECTION] per-market rules, applied last

    # Profit flag — affects financial sub-metric display
    wants_profit = data.get("wants_profit", True)

    # Add market scope context to the prompt
    market_label = {
        "international": "International market",
        "filipino":      "Philippine local market",
        "mixed":         "Both Philippine local and international markets"
    }.get(market_scope, "International market")
    data["_market_label"] = market_label

    # For the main analysis prompt, use a representative sample of films
    # For reasons, we call get_ai_analysis which handles all groups separately
    if market_scope == 'mixed':
        analysis_films = intl_surface[:3] + ph_surface[:3] + intl_deep[:2] + ph_deep[:2]
    else:
        analysis_films = (intl_surface + ph_surface)[:6]

    # STEP 4 — [XGBOOST decides tier] + [KNN cross-references real comp
    # budgets] Budget Recommendation. Runs BEFORE any Groq call, so its
    # result is part of "all that information" Groq synthesizes in STEP 5 —
    # matches the paper's stated order (prediction metric → budget
    # recommendation → Groq). See get_budget_recommendation /
    # cross_reference_budget_tier for how XGBoost's tier-sweep argmax gets
    # blended with the real, reported budgets of the KNN comps.
    budget_recommendation = get_budget_recommendation(
        data,
        similar_films=analysis_films,
        sub_factors=sub_factors
    )

    # STEP 5 — [GROQ] runs LAST, after the prediction metric (STEP 3) and
    # budget recommendation (STEP 4) both exist. This call — "the part that
    # sends results to Groq" and "tells Groq to use what the other models
    # returned" — receives STEP 3's finished success_rate/sub_factors
    # ([XGBOOST]'s result, already corrected by STEP 1+2), STEP 1's
    # analysis_films ([KNN]'s result), and STEP 2's industry_trends
    # ([LIVE MARKET]'s result) all together as prompt context. See
    # get_ai_analysis()'s prompt-building code for exactly where each one
    # gets inserted into the text Groq actually reads.
    ai_analysis = get_ai_analysis(data, analysis_films, success_rate, ML_READY,
                                   industry_trends, sub_factors)

    # STEP 5b — [GROQ] per-film "How it Connects" reasons — a separate Groq
    # call per film group, still receiving STEP 1's [KNN] film groups as input.
    # Generate reasons for ALL films across all 4 groups separately
    # Each group calls Groq independently in 3-film chunks — guarantees complete coverage
    all_film_reasons = get_all_film_reasons(
        data,
        intl_surface=intl_surface,
        intl_deep=intl_deep,
        ph_surface=ph_surface,
        ph_deep=ph_deep
    )

    ai_analysis.pop("film_reasons", {})  # discard the analysis call's reasons

    def _match_reason(film_title, reasons_dict):
        if film_title in reasons_dict:
            return reasons_dict[film_title]
        film_lower = film_title.lower().strip()
        for key, reason in reasons_dict.items():
            key_lower = key.lower().strip()
            if film_lower.startswith(key_lower[:20]) or key_lower.startswith(film_lower[:20]):
                return reason
        return ""

    for film in intl_surface + intl_deep + ph_surface + ph_deep:
        film["reason"] = _match_reason(film["title"], all_film_reasons)

    sub_reasons = {
        "financial":          ai_analysis.pop("financial_reason", ""),
        "audience":           ai_analysis.pop("audience_reason", ""),
        "cultural":           ai_analysis.pop("cultural_reason", ""),
        "commercial_success": ai_analysis.pop("commercial_success_reason", "")
    }
    sub_scores = {
        "financial": sub_factors["financial"]["score"],
        "audience":  sub_factors["audience"]["score"],
        "cultural":  sub_factors["cultural"]["score"]
    }

    story_advice = get_story_advice(   # [GROQ] receives STEP 3's success_rate/sub_factors + STEP 1's analysis_films
        data,
        similar_films=analysis_films,
        success_rate=success_rate,
        sub_factors=sub_factors
    )

    # ══════════════════════════════════════════════════════════════════
    # FINAL RESPONSE — every field below traces back to one of the tagged
    # parts above; nothing here is computed fresh at this point.
    # ══════════════════════════════════════════════════════════════════
    return jsonify({
        "intl_surface":         intl_surface,          # [KNN] STEP 1 output
        "intl_deep":            intl_deep,              # [KNN] STEP 1 output
        "ph_surface":           ph_surface,              # [KNN] STEP 1 output
        "ph_deep":              ph_deep,                  # [KNN] STEP 1 output
        "intl_films":           intl_films,               # [KNN] alias, backward compat
        "ph_films":             ph_films,                  # [KNN] alias, backward compat
        "similar_films":        intl_films,                # [KNN] alias, backward compat
        "market_scope":         market_scope,
        "wants_profit":         wants_profit,
        "success_rate":         success_rate,          # [XGBOOST]+[KNN]+[LIVE MARKET]+[RULE-BASED CORRECTION] — the fully finalized STEP 3 metric
        "sub_scores":           sub_scores,             # [XGBOOST], corrected — financial/audience/cultural (see predict_all_pillars)
        "ai_analysis":          ai_analysis,             # [GROQ] STEP 5 output
        "sub_reasons":          sub_reasons,             # [GROQ] STEP 5 output (per-pillar reason text)
        "method":               method,
        "story_advice":         story_advice,           # [GROQ] output
        "budget_recommendation": budget_recommendation,  # [XGBOOST tier] + [KNN comp-budget crossref] + [GROQ] prose — STEP 4
        # Transparency for the live-market fix: shows exactly how the KNN-retrieved
        # comps + live genre benchmark nudged the XGBoost base score, so this is
        # citable in the thesis rather than a silent internal adjustment.
        "live_market": {                                # [XGBOOST]+[KNN]+[LIVE MARKET] transparency block — see STEP 3
            "base_score_xgboost":   base_score,             # [XGBOOST] STEP 3 raw pillar output, pre-adjustment
            "live_adjustment":      live_adjustment,         # [KNN]+[LIVE MARKET] STEP 3 computed nudge
            "base_score_after_live": base_score_live,         # STEP 3 result, before per-market rules
            "detail":               live_market_detail,        # STEP 3 breakdown (comp vote avg vs genre benchmark)
            "market_pulse":         market_pulse                # [LIVE MARKET] STEP 2 raw numbers
        },
        # [CULTURAL TRANSPARENCY] Which cultures/regions the retrieved comps
        # actually come from, at a glance — e.g. {"English-language (US/UK/...)": 5,
        # "East Asian (Korean)": 1}. Directly answers "which cultures are we
        # connecting to" without a reader having to tally origin_region across
        # every individual film card by hand. Each film's own tag is also
        # available at all_films[i]["origin_language"] / ["origin_region"].
        "cultural_composition": cultural_composition
    })
  except Exception as e:
    import traceback
    print("[ERROR in /analyze]:", traceback.format_exc())
    return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

# ── Serve the built Vue frontend (same-origin deploy) ───────────────────
# Assumes a project layout of:
#   app.py
#   frontend/
#     dist/            <- created by `npm run build` in your Vue project
#       index.html
#       assets/...
# Adjust FRONTEND_DIST below if your Vue project's build output lives elsewhere.
# This is registered LAST and only handles paths not already matched by a more
# specific route above (/analyze, /auth/*, /ml_status, etc.) — Flask/Werkzeug
# always prefers the most specific matching rule regardless of registration
# order, but keeping it last here matches the conventional pattern.
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIST, "index.html")

@app.route("/<path:path>")
def serve_frontend(path):
    """
    Serves built Vue static assets (JS/CSS/images) directly when the requested
    path matches a real file, and falls back to index.html otherwise — this is
    what makes Vue Router's client-side routes (e.g. /dashboard, /saved-results)
    work correctly on a hard refresh or a direct link, instead of 404ing, since
    the server doesn't actually have a route for those paths — Vue Router
    handles them entirely in the browser once index.html loads.
    """
    full_path = os.path.join(FRONTEND_DIST, path)
    if path and os.path.isfile(full_path):
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, "index.html")

if __name__ == "__main__":
    app.run(debug=True)