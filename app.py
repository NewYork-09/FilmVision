from flask import Flask, render_template, request, jsonify
import os, requests, json, re, pickle, numpy as np
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

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

load_models()

# ── Genre mapping ──────────────────────────────────────────────────────
GENRE_MAP = {
    "Action":28,"Adventure":12,"Animation":16,"Comedy":35,
    "Crime":80,"Documentary":99,"Drama":18,"Fantasy":14,
    "Horror":27,"Mystery":9648,"Romance":10749,"Science Fiction":878,
    "Thriller":53,"War":10752,"Western":37
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

    # Financial
    fin = {"Micro (<$1M)":30,"Low ($1M-$10M)":45,"Mid ($10M-$50M)":60,
           "High ($50M-$150M)":72,"Blockbuster ($150M+)":82}.get(budget, 40)
    high_commercial   = {"Action","Comedy","Animation","Adventure","Science Fiction"}
    medium_commercial = {"Drama","Romance","Thriller","Fantasy"}
    low_commercial    = {"Documentary","War","Western","Horror","Crime","Mystery"}
    for g in genres:
        if g in high_commercial:     fin += 5
        elif g in medium_commercial: fin += 2
        elif g in low_commercial:    fin -= 3
    if "A-list Stars" in casting:              fin += 8
    elif "Established Mid-Tier" in casting:    fin += 4
    elif "Unknown/Non-professional" in casting: fin -= 5
    if "Major Theatrical Release" in distribution:    fin += 6
    elif "Streaming Platform" in distribution:        fin += 3
    elif "School / Academic Project" in distribution: fin = min(fin, 45)
    elif "Online / Social Media" in distribution:     fin -= 2
    if "Generate Profit" in purposes:                 fin += 5
    if "Just for Fun" in purposes:                    fin = min(fin, 50)
    if "Academic / School Requirement" in purposes:   fin = min(fin, 45)
    if schedule == "Under 3 months":                  fin -= 8
    elif schedule == "24+ months":                    fin -= 3
    mismatch_penalty, mismatch_flags = detect_mismatch(genres, tones, audiences, theme, pitch)
    fin -= mismatch_penalty // 2
    fin = max(10, min(95, fin))

    # Audience
    audience_base = {"General Audience":75,"Young Adults (18-25)":70,"Adults (26-45)":68,
                     "Families":72,"Teens":65,"Niche/Cult":52}
    aud = round(sum(audience_base.get(a,60) for a in audiences) / max(len(audiences),1)) if audiences else 55
    family_safe_tones = {"Uplifting","Humorous","Adventurous","Romantic","Nostalgic"}
    adult_tones_set   = {"Dark","Gritty","Experimental","Surreal","Satirical","Suspenseful"}
    family_auds = {"Families","Teens"}
    adult_auds  = {"Adults (26-45)","Young Adults (18-25)"}
    has_family_aud = any(a in family_auds for a in audiences)
    has_adult_aud  = any(a in adult_auds  for a in audiences)
    has_adult_tone = any(t in adult_tones_set for t in tones)
    has_safe_tone  = any(t in family_safe_tones for t in tones)
    if has_family_aud and has_adult_tone:  aud -= 22
    if has_adult_aud  and has_adult_tone:  aud += 8
    if has_family_aud and has_safe_tone:   aud += 8
    if has_adult_aud  and has_safe_tone:   aud += 3
    dark_genres  = {"Horror","Thriller","Crime","War"}
    light_genres = {"Comedy","Animation","Adventure","Romance","Fantasy"}
    if has_family_aud and any(g in dark_genres  for g in genres): aud -= 15
    if has_family_aud and any(g in light_genres for g in genres): aud += 8
    if has_adult_aud  and any(g in dark_genres  for g in genres): aud += 5
    explicit_kws = ["sex","sexual","explicit","gore","graphic violence","blood","drugs"]
    pitch_lower  = (pitch + " " + theme).lower()
    if has_family_aud and any(w in pitch_lower for w in explicit_kws): aud -= 20
    if "School / Academic Project" in distribution: aud = max(aud, 60)
    if "Niche Audience / Cult"     in distribution: aud += 5
    if "Online / Social Media"     in distribution: aud += 4
    aud = max(10, min(95, aud))

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
    culturally_rich_tones = {"Dramatic","Experimental","Surreal","Satirical","Nostalgic"}
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
    safe_tones  = {"Uplifting","Humorous","Adventurous","Romantic"}
    risky_tones = {"Experimental","Surreal"}
    safe_count  = sum(1 for t in tones if t in safe_tones)
    score += safe_count * 2
    score -= sum(3 for t in tones if t in risky_tones)

    # ── Purpose alignment bonus ───────────────────────────────────────
    if "Generate Profit" in purposes:           score += 3
    if "Send a Social Message" in purposes or "Artistic Expression" in purposes:
        score += 3  # festival circuit boost

    return max(15, min(96, round(score)))

# ── Feature vector builder ─────────────────────────────────────────────
def build_feature_vector(form_data):
    genres = as_list(form_data.get("genre"))
    times  = as_list(form_data.get("time_period"))
    budget = form_data.get("budget_range","")
    row    = {}
    for gname in GENRE_MAP:
        row[f"genre_{gname.replace(' ','_')}"] = 1 if gname in genres else 0
    budget_popularity = {"Micro (<$1M)":5,"Low ($1M-$10M)":15,"Mid ($10M-$50M)":40,
                         "High ($50M-$150M)":80,"Blockbuster ($150M+)":150}
    row["popularity"]     = budget_popularity.get(budget, 20)
    row["vote_count_log"] = np.log1p(500)
    decade_map = {"1970s":1970,"1980s":1980,"1990s":1990,"2000s":2000,
                  "2010s":2010,"2020s":2020,"Contemporary":2020,"Future/Sci-Fi":2025}
    row["release_decade"] = decade_map.get(times[0], 2020) if times else 2020
    row["is_english"]     = 1
    row["is_adult"]       = 0
    if feature_cols:
        vec = [row.get(c, 0) for c in feature_cols]
    else:
        vec = list(row.values())
    return np.array(vec).reshape(1, -1)

# ── XGBoost prediction ─────────────────────────────────────────────────
def predict_success_xgb(form_data):
    vec = build_feature_vector(form_data)
    raw = float(xgb_model.predict(vec)[0])
    return max(20, min(96, round(raw)))

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

# ── Keyword overlap score ──────────────────────────────────────────────
def _keyword_overlap(pitch_words, overview):
    if not pitch_words or not overview:
        return 0.0
    ov = overview.lower()
    hits = 0
    for w in pitch_words:
        if len(w) <= 3: continue
        if w in ov:                        hits += 1.0
        elif len(w) >= 6 and w[:6] in ov:  hits += 0.5
    return min(1.0, hits / max(len(pitch_words), 1))

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
    "divorce","pregnancy","adoption","grief","addiction","immigrant","refugee"
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
    "twist","ends","turns","become","becomes","became","between","among"
}

def _extract_anchor_words(pitch, theme, genres):
    raw   = (pitch + " " + theme).lower()
    raw   = re.sub(r"[^a-z0-9 ]", " ", raw)
    words = [w for w in raw.split() if len(w) > 3 and w not in STOP_WORDS]
    seen, unique = set(), []
    for w in words:
        if w not in seen: seen.add(w); unique.append(w)
    anchors = [w for w in unique if w in CINEMATIC_NOUNS]
    fillers = [w for w in unique if w not in CINEMATIC_NOUNS]
    return anchors, fillers

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

        knn_sim   = _knn_score_single(r, form_data)
        sem_score = _keyword_overlap(pitch_words, overview)

        # Source bonus
        if   source == "keyword": sem_score = min(1.0, sem_score + 0.55)
        elif source == "search":
            sem_score = min(1.0, sem_score + (0.35 if query_rank == 1 else 0.20))
        # Discover-only with zero overlap: skip
        elif source == "discover" and sem_score < 0.05:
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
def get_ai_analysis(film_data, similar_films, success_rate, ml_ready,
                    industry_trends, sub_factors):
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
    extra_flag = ["Explicit content in pitch/theme with family audience"] \
        if sub_factors["audience"]["pitch_has_explicit"] and has_family else []
    mismatches = sub_factors["financial"].get("mismatch_flags",[]) + extra_flag

    ml_context = (
        f"XGBoost predicted {success_rate}% from: genre={', '.join(genres)}, "
        f"budget={film_data.get('budget_range','')}, "
        f"decade={film_data.get('time_period','')}, language=English. "
        f"Trained on ~3,000 TMDB films."
        if ml_ready else f"Heuristic score: {success_rate}%."
    )

    film_lines = []
    for i, f in enumerate(similar_films[:6]):
        film_lines.append(
            f"FILM {i+1}: \"{f['title']}\" ({f['release_date']}) — "
            f"similarity {f.get('similarity','?')}% — "
            f"Plot: {f['overview'][:180]}..."
        )

    mismatch_block = ""
    if mismatches:
        mismatch_block = "DETECTED ISSUES:\n" + "\n".join(f"- {m}" for m in mismatches) + "\n\n"

    budget_label   = film_data.get("budget_range","this budget")
    genre_label    = normalize(film_data.get("genre"))
    tone_label     = normalize(film_data.get("tone"))
    audience_label = normalize(film_data.get("target_audience"))
    purpose_label  = normalize(film_data.get("film_purpose",[]),"unspecified")
    pitch_short    = pitch[:60]

    # Build varied film reason instructions — each film gets a DIFFERENT opening directive
    # so Groq cannot fall back to a single template
    reason_openers = [
        "Open with the specific plot mechanic in {t} that directly parallels the pitch's core conflict. Second sentence: the one concrete lesson this film offers the creator about execution.",
        "Name the character decision in {t} that echoes what the pitch's protagonist faces. Second sentence: what went right or wrong in {t} that the creator should replicate or avoid.",
        "Describe the scene or narrative device in {t} that is closest to the pitch's setting or tone. Second sentence: how the creator can apply that specific technique to their concept.",
        "Identify the genre tension in {t} — what it was trying to balance — and connect that directly to the pitch's challenge. Second sentence: what the creator can steal from its approach.",
        "Start with what {t} got right that most films in this genre fail at, and explain why it matters for the pitch. Second sentence: the specific production choice the creator should study.",
        "Point out the moment in {t} where the story diverges from the pitch's concept, and explain why that difference is instructive. Second sentence: what the creator should do differently.",
    ]
    film_reason_lines = []
    for _i, _film in enumerate(similar_films[:6]):
        _t = _film["title"]
        opener = reason_openers[_i % len(reason_openers)].replace("{t}", _t)
        film_reason_lines.append(
            "    " + '"' + f"FILM {_i+1}|{_t}" + '"' + ": " + '"' + opener + '",\n'
        )
    film_reason_block = "".join(film_reason_lines)

    overall_hint   = (f"2-3 sentences referencing the pitch ({pitch_short}...) "
                      f"and purpose ({purpose_label}). Lead with mismatches if any.")
    financial_hint = (f"2 sentences on ROI for {budget_label} in {genre_label} right now.")
    audience_hint  = (f"2 sentences addressing the {aud_score}% score. "
                      f"If mismatch, explain why {audience_label} is misaligned.")
    cultural_hint  = (f"2 sentences on why {genre_label} + {tone_label} + "
                      f"theme of {theme} does or does not have cultural legs.")

    prompt = (
        "You are a blunt, experienced film industry consultant. "
        "Write analysis that sounds like a human expert, not an AI.\n\n"
        "STRICT RULES:\n"
        "- NEVER say: it is worth noting, the film themes are closely tied, resonate with, align with.\n"
        "- Each film_reason must START with a specific narrative or character element from THAT film.\n"
        "- Vary sentence structures across film reasons.\n"
        "- Call out mismatches directly.\n"
        "- financial/audience/cultural reasons must each cover a DIFFERENT aspect.\n\n"
        f"PITCH: {pitch}\n"
        f"Theme: {theme} | Genre: {genre_label} | Tone: {tone_label}\n"
        f"Audience: {audience_label} | Budget: {budget_label}\n"
        f"Distribution: {normalize(film_data.get('distribution_goal',[]),'Not specified')}\n"
        f"Purpose: {purpose_label}\n\n"
        f"{mismatch_block}"
        f"ML SCORES — Overall: {success_rate}% | Financial: {fin_score}% | "
        f"Audience: {aud_score}% | Cultural: {cul_score}%\n"
        f"{ml_context}\n\n"
        "MATCHED FILMS:\n" + "\n".join(film_lines) + "\n\n"
        "LIVE TRENDS:\n" + f"{industry_trends}\n\n"
        "OUTPUT: valid JSON only.\n{\n"
        f'  "overall_assessment": "{overall_hint}",\n'
        '  "commercial_success_reason": "3 sentences: ML factors, then purpose/distribution reframe, then market trend evidence.",\n'
        '  "strengths": ["specific to THIS pitch"],\n'
        '  "risks": ["specific actual risk"],\n'
        '  "strategic_suggestions": [\n'
        '    {"title":"action","detail":"concrete step"},\n'
        '    {"title":"action","detail":"concrete step"},\n'
        '    {"title":"action","detail":"concrete step"}\n'
        '  ],\n'
        '  "alternative_routes": [{"route":"alt","rationale":"why for THIS film"}],\n'
        '  "market_insight": "one specific current pattern as evidence",\n'
        f'  "financial_reason": "{financial_hint}",\n'
        f'  "audience_reason": "{audience_hint}",\n'
        f'  "cultural_reason": "{cultural_hint}",\n'
        '  "film_reasons": {\n'
        + film_reason_block
        + "  }\n}\n"
    )

    url     = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}
    payload = {"model":"llama-3.3-70b-versatile",
               "messages":[{"role":"user","content":prompt}],
               "temperature":0.85,"max_tokens":2500}
    try:
        resp = requests.post(url, headers=headers, json=payload)
        data = resp.json()
        if resp.status_code != 200:
            raise Exception(data.get("error",{}).get("message",str(data)))
        text = data["choices"][0]["message"]["content"].strip()
        text = re.sub(r"^```(?:json)?\s*","",text)
        text = re.sub(r"\s*```$","",text).strip()
        print("[Groq] Success")
        result = json.loads(text)
        raw_reasons = result.pop("film_reasons",{})
        clean = {}
        for k,v in raw_reasons.items():
            title = k.split("|")[-1].strip() if "|" in k else k.strip()
            clean[title] = v
        result["film_reasons"] = clean
        return result
    except Exception as e:
        print(f"[Groq] Error: {e}")
        return {"overall_assessment":f"AI analysis unavailable: {str(e)}",
                "commercial_success_reason":"","strengths":[],"risks":[],
                "strategic_suggestions":[],"alternative_routes":[],"market_insight":"",
                "financial_reason":"","audience_reason":"","cultural_reason":"",
                "film_reasons":{}}

# ── Routes ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/ml_status")
def ml_status():
    return jsonify({"ml_ready": ML_READY})

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json

    base_score  = predict_success_xgb(data) if ML_READY else predict_success_fallback(data)
    method      = "xgboost" if ML_READY else "heuristic"
    sub_factors = compute_sub_metrics(data)
    success_rate= adjust_success_rate(base_score, sub_factors, data)

    # ── Always use hybrid search (works with or without ML) ────────────
    similar_films = get_similar_films_hybrid(data)

    genres          = as_list(data.get("genre"))
    industry_trends = fetch_industry_trends(genres, normalize(data.get("tone")), data.get("main_theme",""))

    ai_analysis = get_ai_analysis(data, similar_films, success_rate, ML_READY,
                                   industry_trends, sub_factors)

    film_reasons = ai_analysis.pop("film_reasons",{})
    for film in similar_films:
        film["reason"] = film_reasons.get(film["title"],"")

    sub_reasons = {
        "financial":          ai_analysis.pop("financial_reason",""),
        "audience":           ai_analysis.pop("audience_reason",""),
        "cultural":           ai_analysis.pop("cultural_reason",""),
        "commercial_success": ai_analysis.pop("commercial_success_reason","")
    }
    sub_scores = {
        "financial": sub_factors["financial"]["score"],
        "audience":  sub_factors["audience"]["score"],
        "cultural":  sub_factors["cultural"]["score"]
    }

    return jsonify({
        "similar_films": similar_films,
        "success_rate":  success_rate,
        "sub_scores":    sub_scores,
        "ai_analysis":   ai_analysis,
        "sub_reasons":   sub_reasons,
        "method":        method
    })

if __name__ == "__main__":
    app.run(debug=True)