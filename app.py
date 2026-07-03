from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import os, requests, json, re, pickle, numpy as np
from dotenv import load_dotenv

try:
    from sklearn.metrics.pairwise import cosine_similarity
except Exception:
    cosine_similarity = None

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

# ── Auth blueprint ──────────────────────────────────────────────────────
from auth import auth_bp
app.register_blueprint(auth_bp)

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TMDB_BASE    = "https://api.themoviedb.org/3"

# ── Load ML models ─────────────────────────────────────────────────────
ML_READY     = False
xgb_model    = None
knn_model    = None
scaler       = None
feature_cols = None
film_db      = None

# TF-IDF vectorizer is loaded separately from the rest — it's a real relevance
# signal for scoring (see _semantic_similarity) but isn't required for the app's
# core prediction/search flow, so its absence shouldn't flip ML_READY off.
TFIDF_READY     = False
tfidf_vectorizer = None

def load_models():
    global ML_READY, xgb_model, knn_model, scaler, feature_cols, film_db
    try:
        with open("xgboost_model.pkl", "rb") as f: xgb_model    = pickle.load(f)
        with open("knn_model.pkl",     "rb") as f: knn_model    = pickle.load(f)
        with open("scaler.pkl",        "rb") as f: scaler       = pickle.load(f)
        with open("feature_cols.pkl",  "rb") as f: feature_cols = pickle.load(f)
        with open("film_database.pkl", "rb") as f: film_db      = pickle.load(f)
        ML_READY = True
        print("[ML] Models loaded successfully.")
    except FileNotFoundError as e:
        print(f"[ML] Model files not found ({e}). Using fallback scoring.")

def load_tfidf():
    global TFIDF_READY, tfidf_vectorizer
    if cosine_similarity is None:
        print("[TFIDF] scikit-learn cosine_similarity unavailable — using keyword-overlap fallback.")
        return
    try:
        with open("tfidf_vectorizer.pkl", "rb") as f:
            tfidf_vectorizer = pickle.load(f)
        TFIDF_READY = True
        print("[TFIDF] Vectorizer loaded — using trained semantic similarity for film matching.")
    except FileNotFoundError:
        print("[TFIDF] tfidf_vectorizer.pkl not found — using keyword-overlap fallback for matching.")
    except Exception as e:
        print(f"[TFIDF] Failed to load ({e}) — using keyword-overlap fallback.")

load_models()
load_tfidf()

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

    # Genre "natural budget zone" — what budget these genres normally need to succeed
    low_budget_genres  = {"Drama","Romance","Documentary","Horror","Mystery",
                          "Thriller","Slice of Life","Psychological","Philosophical",
                          "Social Commentary","Arthouse","Political Drama"}
    mid_budget_genres  = {"Comedy","Crime","Fantasy","Adventure","Science Fiction","War"}
    high_budget_genres = {"Action","Animation","Adventure","Science Fiction"}

    # Budget tiers as base score
    budget_base = {"Micro (<$1M)":40,"Low ($1M-$10M)":52,"Mid ($10M-$50M)":62,
                   "High ($50M-$150M)":70,"Blockbuster ($150M+)":78}.get(budget, 45)

    # Fit bonus/penalty: does the budget match what this genre needs?
    fit_bonus = 0
    for g in genres:
        if g in low_budget_genres:
            # Low-budget genres: Micro/Low budgets are efficient → bonus, high budget → waste
            if budget in ("Micro (<$1M)", "Low ($1M-$10M)"):   fit_bonus += 12
            elif budget == "Mid ($10M-$50M)":                    fit_bonus += 5
            elif budget in ("High ($50M-$150M)", "Blockbuster ($150M+)"): fit_bonus -= 8
        elif g in mid_budget_genres:
            if budget == "Mid ($10M-$50M)":                      fit_bonus += 8
            elif budget == "Low ($1M-$10M)":                     fit_bonus += 3
            elif budget == "Blockbuster ($150M+)":               fit_bonus -= 5
        elif g in high_budget_genres:
            if budget == "Blockbuster ($150M+)":                 fit_bonus += 10
            elif budget == "High ($50M-$150M)":                  fit_bonus += 8
            elif budget in ("Micro (<$1M)", "Low ($1M-$10M)"):  fit_bonus -= 10

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

# ── Overall score adjustment ───────────────────────────────────────────
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
    # Audience score below 50 means serious mismatch — drag overall score proportionally
    aud_score_val = sub_factors["audience"]["score"]
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

# ── Feature vector builder ─────────────────────────────────────────────
def build_feature_vector(form_data, is_filipino=False):
    """
    Builds a feature vector that ALWAYS matches the trained model shape.
    Uses feature_cols from the pkl to determine exact columns needed.
    Any column the model expects that we don't compute defaults to 0.

    is_filipino: when True, builds the query vector for a Filipino-market-scope search
    (sets is_filipino=1/is_english=0 in the vector) so KNN's distance calculation reflects
    what's actually being searched for, instead of always querying as if for an
    international film. Used by get_deep_films's Filipino branch.
    """
    genres = as_list(form_data.get("genre"))
    times  = as_list(form_data.get("time_period"))
    budget = form_data.get("budget_range","")
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

    # Use feature_cols from pkl to build exact vector — model gets exactly what it was trained on
    if feature_cols:
        vec = [row.get(c, 0) for c in feature_cols]
    else:
        vec = list(row.values())
    return np.array(vec, dtype=float).reshape(1, -1)

# ── XGBoost prediction ─────────────────────────────────────────────────
def predict_success_xgb(form_data):
    try:
        vec = build_feature_vector(form_data)
        raw = float(xgb_model.predict(vec)[0])
        return max(20, min(96, round(raw)))
    except ValueError as e:
        if "Feature shape mismatch" in str(e):
            # Model expects different number of features than we built.
            # This happens when feature_cols.pkl has more columns than XGBoost was trained on.
            # Safe fix: drop extra columns by trimming to what xgb_model expects.
            print(f"[XGB] Shape mismatch — attempting trim fix: {e}")
            try:
                n_expected = xgb_model.get_booster().num_features()
                vec = build_feature_vector(form_data)
                vec_trimmed = vec[:, :n_expected]
                raw = float(xgb_model.predict(vec_trimmed)[0])
                print(f"[XGB] Trim fix worked — used {n_expected} features")
                return max(20, min(96, round(raw)))
            except Exception as e2:
                print(f"[XGB] Trim fix also failed: {e2} — using heuristic")
                return predict_success_fallback(form_data)
        raise

# ── Fallback heuristic ─────────────────────────────────────────────────
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

# ── KNN score for a single TMDB result ────────────────────────────────
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
    film_vec        = np.array([row.get(c, 0) for c in feature_cols]).reshape(1, -1)
    film_vec_scaled = scaler.transform(film_vec)
    user_vec        = build_feature_vector(form_data)
    user_vec_scaled = scaler.transform(user_vec)
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
    removes that class of noise from the fallback scorer (used when the trained
    TF-IDF vectorizer isn't available).
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

# ── Real semantic similarity (TF-IDF cosine) ────────────────────────────
def _semantic_similarity(pitch_words, pitch_text, overview):
    """
    Measures actual content relevance between the pitch and a candidate film's
    overview. Uses the trained tfidf_vectorizer.pkl (fit on the training corpus)
    for a real cosine-similarity signal when available — this is a substantially
    stronger and harder-to-fool signal than raw substring word-overlap, since it
    weighs term rarity/importance rather than treating every shared word equally.
    Falls back to _keyword_overlap if the vectorizer isn't loaded.
    """
    if TFIDF_READY and overview and pitch_text:
        try:
            vecs = tfidf_vectorizer.transform([pitch_text, overview])
            return float(cosine_similarity(vecs[0], vecs[1])[0][0])
        except Exception as e:
            print(f"[TFIDF] Similarity computation failed, using fallback: {e}")
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
    try:
        result = _call_groq(prompt, max_tokens=500, fast=False)
        films = result.get("films", [])
        return [(f.get("title","").strip(), f.get("year")) for f in films if f.get("title")]
    except Exception as e:
        print(f"[Groq-suggest] {scope}/{flavor} failed: {e}")
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
    """Combines _groq_suggest_titles + _verify_tmdb_title into ready-to-score candidates."""
    exclude_ids = exclude_ids or set()
    suggestions = _groq_suggest_titles(pitch, theme, genres, scope, flavor, n=n)
    out = {}
    for title, year in suggestions:
        res = _verify_tmdb_title(title, year, require_filipino=(scope == "filipino"))
        if res and res.get("id") and res["id"] not in exclude_ids:
            out[res["id"]] = {"source": "groq_suggest", "query_rank": 0, "result": res}
    print(f"[Groq-suggest] {scope}/{flavor}: {len(suggestions)} suggested, {len(out)} verified on TMDB")
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

# ── Main hybrid similar-film search ───────────────────────────────────
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

# ── TMDB genre fallback ────────────────────────────────────────────────
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

# ── Industry trends ────────────────────────────────────────────────────
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

# ── Groq analysis ──────────────────────────────────────────────────────
def _call_groq(prompt, max_tokens=1800, fast=False):
    """Single Groq call with retry logic. Returns parsed dict or raises.
    fast=True uses llama-3.1-8b-instant (lower token cost, good for film reasons).
    fast=False uses llama-3.3-70b-versatile (better quality, for main analysis).
    """
    url     = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}
    model   = "llama-3.1-8b-instant" if fast else "llama-3.3-70b-versatile"
    payload = {"model": model,
               "messages":[{"role":"user","content":prompt}],
               "temperature":0.7,"max_tokens":max_tokens}
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
            f"★{f['vote_average']} — {(f.get('overview') or '')[:80]}"
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
        "Film consultant. Blunt. No filler phrases. No: steal/copy/borrow — use: adapt/study/build on.\n"
        + scope_instruction
        + f"PITCH: {pitch_short}\n"
        f"Theme: {theme} | Genre: {genre_label} | Tone: {tone_label}\n"
        f"Secondary Genre Hints: {normalize(film_data.get('secondary_genre',[]),'none')}\n"
        f"Audience: {audience_label} | Budget: {budget_label} | Purpose: {purpose_label}\n"
        f"Market: {market_label}\n"
        f"{mismatch_block}"
        f"SCORES: Overall={success_rate}% Financial={fin_score}% Audience={aud_score}% Cultural={cul_score}%\n"
        f"{ml_context}\n"
        + scope_films_block + "\n"
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
        f'"cultural_reason":"2 sentences on cultural legs for {genre_label}+{theme}"'
        "}"
    )

    ANALYSIS_DEFAULTS = {
        "overall_assessment":"","commercial_success_reason":"",
        "strengths":[],"risks":[],"strategic_suggestions":[],
        "alternative_routes":[],"market_insight":"",
        "financial_reason":"","audience_reason":"","cultural_reason":""
    }

    try:
        analysis = _call_groq(analysis_prompt, max_tokens=900)
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


def get_budget_recommendation(film_data, similar_films, sub_factors):
    """
    Groq call that generates a budget recommendation based on:
    - User's genre, tone, purpose, distribution goal, market scope
    - The financial sub-metric score and the budget they entered (or lack thereof)
    - Budget patterns visible in the gathered similar films
    Returns a dict with: recommended_range, rationale, comparable_film_budgets, caveats
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

    fin_score    = sub_factors["financial"]["score"]
    genre_label  = normalize(film_data.get("genre"))
    market_label = film_data.get("_market_label", "International market")

    # Build a reference list of similar films to give Groq context on what comparable projects cost
    film_lines = []
    for f in (similar_films or [])[:6]:
        film_lines.append(
            f"- \"{f['title']}\" ({f['release_date']}) ★{f['vote_average']}"
        )
    films_block = "\n".join(film_lines) if film_lines else "No comparable films available."

    budget_context = (
        f"User's stated budget: {budget_given}" if budget_given
        else "User has NOT specified a budget yet."
    )

    market_note = {
        "international": "Target market is International. Budget norms follow Hollywood/global indie benchmarks.",
        "filipino":      "Target market is the Philippine local market. Budget norms are significantly lower — mainstream Filipino films typically run PHP 10M–150M (~$200K–$3M USD). Blockbuster budgets are not viable for local-only release.",
        "mixed":         "Target market is both Philippine local and International. Recommend a budget range that is viable for both contexts.",
    }.get(market_scope, "")

    prompt = (
        "You are a film finance consultant. Give a direct, data-grounded budget recommendation.\n"
        "No filler phrases. No 'it depends'. Give a concrete recommended range and why.\n\n"
        f"PITCH: {pitch_short}\n"
        f"Theme: {theme} | Genre: {genre_label} | Tone: {normalize(film_data.get('tone'))}\n"
        f"Purpose: {normalize(purposes, 'unspecified')} | Distribution: {normalize(distribution, 'unspecified')}\n"
        f"Casting level: {normalize(casting, 'unspecified')} | Schedule: {schedule or 'unspecified'}\n"
        f"Market: {market_label}\n"
        f"{market_note}\n"
        f"{budget_context}\n"
        f"Financial success score: {fin_score}% (score reflects how well current budget fits genre/purpose)\n\n"
        f"COMPARABLE FILMS FOUND:\n{films_block}\n\n"
        "Based on all of the above, output valid JSON only:\n"
        '{"recommended_range":"one of: Micro (<$1M) | Low ($1M-$10M) | Mid ($10M-$50M) | High ($50M-$150M) | Blockbuster ($150M+)",'
        '"rationale":"2-3 sentences: why this range fits the genre+purpose+market, referencing the financial score",'
        '"comparable_film_budgets":"1 sentence noting what comparable films in the list typically cost or what that implies",'
        '"caveats":"1 sentence on the biggest financial risk or constraint to watch"}'
    )

    defaults = {
        "recommended_range": "",
        "rationale": "",
        "comparable_film_budgets": "",
        "caveats": ""
    }

    try:
        result = _call_groq(prompt, max_tokens=400, fast=False)
        for k, v in defaults.items():
            if k not in result or result[k] is None:
                result[k] = v
        print("[Groq] Budget recommendation call success")
        return result
    except Exception as e:
        print(f"[Groq] Budget recommendation call failed: {e}")
        return defaults


def get_story_advice(film_data, similar_films=None, success_rate=None, sub_factors=None):
    """
    Story consultant Groq call — honest creative feedback on the pitch.
    Uses ML scores and similar films as evidence to ground the advice in data.
    """
    pitch   = film_data.get("story_pitch", "")
    theme   = film_data.get("main_theme", "")
    genre   = normalize(film_data.get("genre"))
    tone    = normalize(film_data.get("tone"))
    budget  = film_data.get("budget_range", "")

    if not pitch or len(pitch.strip()) < 30:
        return None

    # Build ML context block — grounded facts the advisor can reference
    ml_block = ""
    if success_rate is not None and sub_factors:
        fin = sub_factors["financial"]["score"]
        aud = sub_factors["audience"]["score"]
        cul = sub_factors["cultural"]["score"]
        ml_block = (
            f"ML PREDICTION DATA (XGBoost + business logic):\n"
            f"Overall commercial success: {success_rate}% | "
            f"Financial: {fin}% | Audience: {aud}% | Cultural: {cul}%\n"
            f"Budget: {budget} | Genre: {genre}\n"
            f"Use these numbers to ground your advice — e.g. if financial is low despite "
            f"a high budget, that signals a budget-concept mismatch the story advisor should flag.\n\n"
        )

    # Build similar films block — what KNN found closest to this concept
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
        result = _call_groq(prompt, max_tokens=900)
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
    Surface-level: matches based on main character type, general storyline, premise.
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

        print(f"[Surface-filipino] {len(candidates)} candidates before adult filter")
        ranked = _score_and_rank(candidates, form_data, pitch, theme, n=6, strict_semantic=False)
        ph_only = [f for f in ranked if f.get("is_filipino")]
        print(f"[Surface-filipino] {len(ph_only)} confirmed Filipino films after filter")
        return ph_only[:6] if ph_only else ranked[:6]

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

    return _score_and_rank(candidates, form_data, pitch, theme, n=6, strict_semantic=False)


def get_deep_films(form_data, scope="international", exclude_ids=None):
    """
    Deep-level: matches based on thematic nuance, emotional subtext, specific scenes.
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

        print(f"[Deep-filipino] {len(candidates)} candidates before adult filter")
        ranked = _score_and_rank(candidates, form_data, pitch, theme, n=6, strict_semantic=False)
        ph_only = [f for f in ranked if f.get("is_filipino")]
        print(f"[Deep-filipino] {len(ph_only)} confirmed Filipino films after filter")
        return ph_only[:6] if ph_only else ranked[:6]


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
                        # distributions from the trained dataset. If fewer than 3 candidates
                        # survive the floor, we fall back to the best-available (unfiltered)
                        # results instead of returning too few/no matches — this was verified
                        # not to wrongly zero out common, well-covered pitches (e.g. foster-care
                        # stories), which score comfortably above the floor.

def _score_and_rank(candidates, form_data, pitch, theme, n=6, strict_semantic=True):
    """Shared scoring + ranking logic for both surface and deep film searches."""
    pitch_words = [w for w in re.sub(r"[^a-z0-9 ]"," ",(pitch+" "+theme).lower()).split()
                   if len(w) > 3 and w not in STOP_WORDS]
    scored = []
    for cand in candidates.values():
        r          = cand["result"]
        # Content-safety chokepoint: every candidate from every source/scope passes through
        # here before becoming a final result, so this is the single correct place to apply
        # the adult-content filter. Previously _is_adult_content existed but was only called
        # from get_similar_films_hybrid, a function never used by the live /analyze pipeline —
        # meaning NO adult-content filtering actually ran on real results despite the function
        # being fully built. This wires it into the path that's actually used.
        if _is_adult_content(r):
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
        else:
            raw_sem = _semantic_similarity(pitch_words, pitch + " " + theme, overview)

            RAW_OVERLAP_FLOOR = 0.12           # minimum genuine relevance required, any source.
                                                 # Was 0.03 — too permissive: a single stray shared
                                                 # word in a long overview (e.g. "self", "discovers")
                                                 # was enough to pass, which is how weakly/coincidentally
                                                 # matched Filipino films (Gasping for Air, etc.) kept
                                                 # leaking into results for unrelated pitches even after
                                                 # the source-bonus fix. This requires real, multi-word
                                                 # or strong single-concept overlap, not noise.
            KEYWORD_FLOOR      = 0.05           # TMDB keyword-ID matches carry some inherent
                                                 # thematic evidence even at lower text overlap,
                                                 # so they get a lower bar — but still a real one,
                                                 # not a free pass (was 0.01).
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
        combined      = round(0.65 * (sem_score * 100) + 0.35 * knn_sim + quality_bonus, 2)

        plot = overview.strip()

        poster_path = r.get("poster_path","")
        scored.append({
            "tmdb_id":      r.get("id"),
            "title":        r.get("title",""),
            "plot":         plot,
            "overview":     overview,
            "release_date": (r.get("release_date","") or "N/A")[:4],
            "vote_average": round(float(vote_avg), 1),
            "poster":       f"https://image.tmdb.org/t/p/w300{poster_path}" if poster_path else None,
            "similarity":   round(combined, 1),
            "is_filipino":  r.get("original_language","") in ("tl","fil") or r.get("origin_country","") == "PH" or "PH" in (r.get("production_countries") or []),
            "reason":       ""
        })

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
                result = _call_groq(prompt, max_tokens=450, fast=True)
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
    return jsonify({"ml_ready": ML_READY})

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

    base_score   = predict_success_xgb(data) if ML_READY else predict_success_fallback(data)
    method       = "xgboost" if ML_READY else "heuristic"
    sub_factors  = compute_sub_metrics(data)
    success_rate = adjust_score_for_market(base_score, sub_factors, data, market_scope)

    # ── Film search: surface + deep for each market scope ────────────
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
    all_films = intl_surface + intl_deep + ph_surface + ph_deep
    intl_films = intl_surface  # backward compat
    ph_films   = ph_surface    # backward compat

    # Profit flag — affects financial sub-metric display
    wants_profit = data.get("wants_profit", True)

    genres          = as_list(data.get("genre"))
    industry_trends = fetch_industry_trends(genres, normalize(data.get("tone")), data.get("main_theme",""))

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

    ai_analysis = get_ai_analysis(data, analysis_films, success_rate, ML_READY,
                                   industry_trends, sub_factors)

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

    story_advice = get_story_advice(
        data,
        similar_films=analysis_films,
        success_rate=success_rate,
        sub_factors=sub_factors
    )

    budget_recommendation = get_budget_recommendation(
        data,
        similar_films=analysis_films,
        sub_factors=sub_factors
    )

    return jsonify({
        "intl_surface":         intl_surface,
        "intl_deep":            intl_deep,
        "ph_surface":           ph_surface,
        "ph_deep":              ph_deep,
        "intl_films":           intl_films,
        "ph_films":             ph_films,
        "similar_films":        intl_films,
        "market_scope":         market_scope,
        "wants_profit":         wants_profit,
        "success_rate":         success_rate,
        "sub_scores":           sub_scores,
        "ai_analysis":          ai_analysis,
        "sub_reasons":          sub_reasons,
        "method":               method,
        "story_advice":         story_advice,
        "budget_recommendation": budget_recommendation
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