"""Insights and analysis functions for thematic exploration."""

import numpy as np
from config import BIOMETRIC_FIELDS


def cluster_characteristics_from_phrases(
    cluster_to_phrases: dict[int, list[str]],
    rows: list[dict],
    oura_by_date: dict[str, dict],
) -> dict[int, dict]:
    """For each phrase-dendrogram cluster, gather moods, feelings, and biometrics."""
    entries = [
        {
            "content_lc": (r.get("content") or "").lower(),
            "date": r.get("entry_date"),
            "mood": r.get("mood"),
            "feelings": r.get("feelings") or [],
            "keywords": r.get("keywords") or [],
        }
        for r in rows
    ]

    out: dict[int, dict] = {}
    for cid, phrases in cluster_to_phrases.items():
        needles = [p.lower().strip() for p in phrases if p and p.strip()]
        if not needles:
            out[int(cid)] = {
                "n_entries": 0, "n_phrases": len(phrases),
                "mood_avg": None, "mood_std": None,
                "sleep_avg": None, "readiness_avg": None,
                "hrv_avg": None, "rhr_avg": None,
                "top_feelings": [], "top_keywords": [],
            }
            continue

        matched_dates: set[str] = set()
        matched_entries: list[dict] = []
        for e in entries:
            if e["date"] in matched_dates:
                continue
            if any(needle in e["content_lc"] for needle in needles):
                matched_dates.add(e["date"])
                matched_entries.append(e)

        moods = [float(e["mood"]) for e in matched_entries if e.get("mood") is not None]
        mood_avg = float(np.mean(moods)) if moods else None
        mood_std = float(np.std(moods)) if len(moods) > 1 else None

        bio_lists: dict[str, list[float]] = {
            "sleep_score": [], "readiness_score": [], "hrv_avg": [], "resting_hr": [],
        }
        for e in matched_entries:
            oura_row = oura_by_date.get(e["date"]) or {}
            for field in bio_lists:
                v = oura_row.get(field)
                if v is not None:
                    bio_lists[field].append(float(v))

        def _avg(vals: list[float]) -> float | None:
            return float(np.mean(vals)) if vals else None

        feeling_counts: dict[str, int] = {}
        for e in matched_entries:
            for f in e["feelings"]:
                name = (f.get("name") or "").lower().strip()
                if name:
                    feeling_counts[name] = feeling_counts.get(name, 0) + 1
        top_feelings = sorted(feeling_counts.items(), key=lambda kv: -kv[1])[:4]

        kw_counts: dict[str, int] = {}
        for e in matched_entries:
            for k in e["keywords"]:
                kl = (k or "").lower().strip()
                if kl:
                    kw_counts[kl] = kw_counts.get(kl, 0) + 1
        top_keywords = [k for k, _ in sorted(kw_counts.items(), key=lambda kv: -kv[1])[:5]]

        out[int(cid)] = {
            "n_entries": len(matched_entries),
            "n_phrases": len(phrases),
            "mood_avg": mood_avg,
            "mood_std": mood_std,
            "sleep_avg":     _avg(bio_lists["sleep_score"]),
            "readiness_avg": _avg(bio_lists["readiness_score"]),
            "hrv_avg":       _avg(bio_lists["hrv_avg"]),
            "rhr_avg":       _avg(bio_lists["resting_hr"]),
            "top_feelings":  top_feelings,
            "top_keywords":  top_keywords,
        }
    return out


def describe_cluster_in_words(profile: dict) -> str:
    """Turn a cluster profile dict into a short one-sentence description."""
    if profile["n_entries"] == 0:
        return "No matching reflections found for these phrases."

    bits: list[str] = []

    mood = profile["mood_avg"]
    if mood is not None:
        if mood >= 7.5:
            bits.append(f"high mood ({mood:.1f}/10)")
        elif mood >= 5.5:
            bits.append(f"moderate mood ({mood:.1f}/10)")
        elif mood >= 3.5:
            bits.append(f"low-moderate mood ({mood:.1f}/10)")
        else:
            bits.append(f"low mood ({mood:.1f}/10)")

    if profile["top_feelings"]:
        feels = ", ".join(name for name, _ in profile["top_feelings"][:2])
        bits.append(f"{feels}-leaning")

    biometric_bits = []
    if profile["sleep_avg"] is not None:
        if profile["sleep_avg"] >= 80:
            biometric_bits.append("good sleep")
        elif profile["sleep_avg"] < 65:
            biometric_bits.append("poor sleep")
    if profile["hrv_avg"] is not None:
        if profile["hrv_avg"] >= 50:
            biometric_bits.append("strong HRV recovery")
        elif profile["hrv_avg"] < 30:
            biometric_bits.append("suppressed HRV")
    if profile["rhr_avg"] is not None:
        if profile["rhr_avg"] >= 70:
            biometric_bits.append("elevated resting HR")
        elif profile["rhr_avg"] < 55:
            biometric_bits.append("low resting HR")
    if biometric_bits:
        bits.append("with " + " and ".join(biometric_bits[:2]))

    return ", ".join(bits).capitalize() + "."


def _entries_matching_phrases(
    phrases: list[str],
    rows: list[dict],
) -> list[dict]:
    """Return unique reflections where ANY phrase appears."""
    needles = [p.lower().strip() for p in phrases if p and p.strip()]
    if not needles:
        return []
    seen: set = set()
    out: list[dict] = []
    for r in rows:
        d = r.get("entry_date")
        if d in seen:
            continue
        content_lc = (r.get("content") or "").lower()
        if any(n in content_lc for n in needles):
            seen.add(d)
            row_copy = dict(r)
            row_copy["_content_lc"] = content_lc
            out.append(row_copy)
    return out


def _discriminating_phrases(
    high_entries: list[dict],
    low_entries: list[dict],
    candidate_phrases: list[str],
    min_appearances: int = 2,
) -> list[tuple[str, int, int, float]]:
    """Compute how much more often each phrase appears in high vs low entries."""
    if not high_entries and not low_entries:
        return []
    n_high = max(1, len(high_entries))
    n_low = max(1, len(low_entries))

    out: list[tuple[str, int, int, float]] = []
    for phrase in candidate_phrases:
        needle = phrase.lower().strip()
        if not needle:
            continue
        hi = sum(1 for e in high_entries if needle in e["_content_lc"])
        lo = sum(1 for e in low_entries if needle in e["_content_lc"])
        if hi + lo < min_appearances:
            continue
        score = (hi / n_high) - (lo / n_low)
        out.append((phrase, hi, lo, score))
    return sorted(out, key=lambda t: t[3], reverse=True)


def _build_corpus_phrase_pool(
    rows: list[dict],
    theme_entries: list[dict],
    seed_phrases: list[str],
    top_n: int = 80,
) -> list[str]:
    """Build candidate phrase pool for discriminating cuts."""
    from sklearn.feature_extraction.text import CountVectorizer

    pool: set[str] = {p.lower().strip() for p in seed_phrases if p and p.strip()}

    theme_texts = [e.get("content") or "" for e in theme_entries if e.get("content")]
    if len(theme_texts) >= 2:
        try:
            vec = CountVectorizer(
                ngram_range=(2, 3),
                stop_words="english",
                max_features=top_n,
                min_df=1,
                token_pattern=r"[a-zA-Z]{3,}",
            )
            vec.fit(theme_texts)
            for p in vec.get_feature_names_out():
                pool.add(p.lower().strip())
        except Exception:
            pass

    return sorted(pool)


def compute_thematic_insights(
    seed_phrases: list[str],
    cluster_to_phrases: dict[int, list[str]],
    rows: list[dict],
    oura_by_date: dict[str, dict],
) -> dict:
    """Compute the four insight cuts for the dendrogram's theme view."""
    theme_entries = _entries_matching_phrases(seed_phrases, rows)

    out: dict = {
        "theme_entries": theme_entries,
        "n_theme": len(theme_entries),
        "mood_split": None,
        "biometric_splits": {},
        "cooccurrence": [],
        "cluster_mood_ranking": [],
    }

    # ── Mood split ──────────────────────────────────────────────────────────
    moods_with_rows = [(e, e["mood"]) for e in theme_entries if e.get("mood") is not None]
    if len(moods_with_rows) >= 4:
        mood_median = float(np.median([m for _, m in moods_with_rows]))
        high = [e for e, m in moods_with_rows if m >= mood_median]
        low = [e for e, m in moods_with_rows if m < mood_median]
        if high and low:
            phrase_pool = _build_corpus_phrase_pool(rows, theme_entries, seed_phrases)
            discr = _discriminating_phrases(high, low, phrase_pool, min_appearances=2)
            top_high = [t for t in discr if t[3] >= 0.10][:5]
            top_low = [t for t in reversed(discr) if t[3] <= -0.10][:5]
            out["mood_split"] = {
                "median": mood_median,
                "mood_high_avg": float(np.mean([m for _, m in moods_with_rows if m >= mood_median])),
                "mood_low_avg":  float(np.mean([m for _, m in moods_with_rows if m < mood_median])),
                "n_high": len(high),
                "n_low": len(low),
                "top_high_phrases": top_high,
                "top_low_phrases": top_low,
            }
        else:
            out["mood_split"] = {"skip": True, "reason": "All theme entries have the same mood — no contrast."}
    else:
        out["mood_split"] = {"skip": True, "reason": f"Only {len(moods_with_rows)} entries with mood — need 4+."}

    # ── Biometric splits ────────────────────────────────────────────────────
    bio_fields = [
        ("sleep_score",     "sleep score",  "higher = better"),
        ("readiness_score", "readiness",    "higher = better"),
        ("hrv_avg",         "HRV",          "higher = better recovery"),
        ("resting_hr",      "resting HR",   "lower = better"),
    ]
    phrase_pool_cached: list[str] | None = None
    for field, label, direction in bio_fields:
        paired = [
            (e, (oura_by_date.get(e.get("entry_date")) or {}).get(field))
            for e in theme_entries
        ]
        paired = [(e, v) for e, v in paired if v is not None]
        if len(paired) < 4:
            out["biometric_splits"][field] = {
                "skip": True, "label": label, "direction": direction,
                "reason": f"Only {len(paired)} entries with {label} — need 4+.",
            }
            continue
        med = float(np.median([v for _, v in paired]))
        hi_rows = [e for e, v in paired if v >= med]
        lo_rows = [e for e, v in paired if v < med]
        if not hi_rows or not lo_rows:
            out["biometric_splits"][field] = {
                "skip": True, "label": label, "direction": direction,
                "reason": f"No variation in {label}.",
            }
            continue
        if phrase_pool_cached is None:
            phrase_pool_cached = _build_corpus_phrase_pool(rows, theme_entries, seed_phrases)
        discr = _discriminating_phrases(hi_rows, lo_rows, phrase_pool_cached, min_appearances=2)
        top_hi = [t for t in discr if t[3] >= 0.10][:4]
        top_lo = [t for t in reversed(discr) if t[3] <= -0.10][:4]
        out["biometric_splits"][field] = {
            "skip": False, "label": label, "direction": direction,
            "median": med,
            "hi_avg": float(np.mean([v for _, v in paired if v >= med])),
            "lo_avg": float(np.mean([v for _, v in paired if v < med])),
            "n_hi": len(hi_rows), "n_lo": len(lo_rows),
            "top_hi_phrases": top_hi,
            "top_lo_phrases": top_lo,
        }

    # ── Co-occurrence ───────────────────────────────────────────────────────
    pair_counts: dict[tuple[str, str], int] = {}
    seeds_lc = [p.lower().strip() for p in seed_phrases if p and p.strip()]
    for entry in theme_entries:
        present = [p for p in seeds_lc if p in entry["_content_lc"]]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                a, b = sorted([present[i], present[j]])
                pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1
    out["cooccurrence"] = sorted(
        [(a, b, c) for (a, b), c in pair_counts.items() if c >= 2],
        key=lambda t: -t[2],
    )[:6]

    # ── Cluster mood ranking ────────────────────────────────────────────────
    cluster_ranking: list[tuple[int, int, float]] = []
    for cid, phs in cluster_to_phrases.items():
        cluster_entries = _entries_matching_phrases(phs, rows)
        cluster_moods = [e["mood"] for e in cluster_entries if e.get("mood") is not None]
        if not cluster_moods:
            continue
        cluster_ranking.append((int(cid), len(cluster_entries), float(np.mean(cluster_moods))))
    out["cluster_mood_ranking"] = sorted(cluster_ranking, key=lambda t: -t[2])

    return out
