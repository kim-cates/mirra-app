# Modular Architecture Summary

## Before Refactoring

```
app.py (2400+ lines)
├── Configuration & styling (200 lines)
├── Client initialization (50 lines)
├── Authentication (150 lines)
├── NLP functions (800 lines)
├── Data management (100 lines)
├── Insights computation (700 lines)
├── Visualization helpers (300 lines)
├── UI rendering functions (150 lines)
└── Main logic (mixed throughout)
```

**Problems:**
- Difficult to navigate and maintain
- Hard to test individual components
- Code reuse across projects is challenging
- Multiple developers would conflict frequently

---

## After Refactoring

```
mirra-app/
├── app.py (refactored, ~800 lines - UI + main logic)
├── config.py (200 lines - styling & constants)
├── auth.py (150 lines - authentication)
├── data_manager.py (60 lines - database ops)
├── nlp_utils.py (500 lines - text processing & ML)
├── insights.py (400 lines - analysis)
├── visualizations.py (350 lines - charting)
├── REFACTORING_GUIDE.md (documentation)
└── MODULAR_STRUCTURE.md (this file)
```

**Benefits:**
- Each module has a single responsibility
- Easy to locate and modify functionality
- Functions are independently testable
- Can be imported into other projects
- Clear dependencies between modules

---

## How to Use the Modules

### Example 1: Save a Reflection

**Before:**
```python
# Code was inline in app.py
today = user_today().isoformat()
supabase.table("reflections").upsert({
    "entry_date": today,
    "content": content,
    "mood": mood,
    "keywords": keywords,
    # ... more fields
}, on_conflict="user_id,entry_date").execute()
```

**After:**
```python
from data_manager import save_reflection

save_reflection(supabase, content, mood, keywords, user_id, feelings)
```

---

### Example 2: Extract Keywords

**Before:**
```python
# Complex logic scattered throughout app.py
from sklearn.feature_extraction.text import CountVectorizer
vec = CountVectorizer(...)
X = vec.fit_transform([text])
# ... processing
```

**After:**
```python
from nlp_utils import extract_keywords

keywords = extract_keywords(text)  # Returns list[str]
```

---

### Example 3: Compute Insights

**Before:**
```python
# 700+ lines of insight computation scattered in app.py
# Hard to follow and reuse
```

**After:**
```python
from insights import compute_thematic_insights

insights = compute_thematic_insights(
    seed_phrases, 
    cluster_to_phrases, 
    rows, 
    oura_by_date
)
```

---

## Module Dependencies

```
nlp_utils.py
├── imports: numpy, streamlit, sklearn, umap, scipy
└── no dependencies on other modules

insights.py
├── imports: numpy
└── depends on: (none directly, but used with nlp_utils results)

data_manager.py
├── imports: streamlit, datetime, oura
└── depends on: (none)

auth.py
├── imports: hashlib, streamlit, base64
└── depends on: (none)

config.py
├── imports: streamlit
└── depends on: (none)

visualizations.py
├── imports: numpy, plotly
└── depends on: config.py (for color constants)

app.py
├── imports: streamlit, plotly, etc.
└── depends on: all modules above
```

---

## Import Strategy

Add these imports to the top of `app.py`:

```python
# Core modules
import streamlit as st
import anthropic
import base64
import hashlib
from supabase import create_client
from datetime import date, datetime, timedelta
import json
import numpy as np
import plotly.graph_objects as go

# Custom modules
import oura
import oura_ui
from oura import user_today
from intro_page import render_intro_page, user_has_seen_intro

# NEW: Modular imports
from config import (
    configure_page, apply_styling, PRESET_FEELINGS,
    TOPIC_COLORS, DENDRO_COLORS, FEELING_COLORS,
    BIOMETRIC_FIELDS, BIOMETRIC_FEATURE_DIMS
)
from auth import render_login_page, handle_signin, handle_signup, render_logout_button
from data_manager import save_reflection, load_all_entries, load_stats
from nlp_utils import (
    load_nlp_models, extract_keywords, get_embeddings,
    build_biometric_features, biometric_profile_per_phrase,
    extract_noun_phrase_clusters, get_top_similar_phrases,
    run_topic_map, run_dendrogram
)
from insights import (
    cluster_characteristics_from_phrases, describe_cluster_in_words,
    compute_thematic_insights
)
from visualizations import (
    _fmt_metric, _cluster_top_keywords, _draw_dendrogram,
    _render_feelings_violin_single, _render_feelings_violin_compare
)

# Setup
configure_page()
apply_styling()
```

---

## Testing Example

With modular code, testing becomes straightforward:

```python
# test_nlp_utils.py
import pytest
from nlp_utils import extract_keywords, get_top_similar_phrases

def test_extract_keywords():
    text = "I had a great day at the beach with friends"
    keywords = extract_keywords(text)
    assert len(keywords) > 0
    assert all(isinstance(k, str) for k in keywords)

def test_get_top_similar_phrases():
    query = "stress and anxiety"
    phrases = ["work pressure", "family conflict", "health issues", "financial worry"]
    similar = get_top_similar_phrases(query, phrases, top_n=2)
    assert len(similar) <= 2
    assert all(p in phrases for p in similar)
```

---

## File Size Comparison

| File | Before | After |
|------|--------|-------|
| app.py | 2400+ | ~800* |
| config.py | N/A | 200 |
| auth.py | N/A | 150 |
| data_manager.py | N/A | 60 |
| nlp_utils.py | N/A | 500 |
| insights.py | N/A | 400 |
| visualizations.py | N/A | 350 |
| **Total** | **2400+** | **2460*** |

*After: Much easier to navigate due to clear separation

---

## Next Steps

1. ✅ Create modular files (config, auth, data_manager, nlp_utils, insights, visualizations)
2. ⏳ Update app.py to import from modules
3. ⏳ Test each page/tab after refactoring
4. ⏳ Consider creating page-specific modules (pages/topic_map.py, etc.)
5. ⏳ Add type hints and docstrings
6. ⏳ Set up unit tests for each module

---

## Questions?

Refer to `REFACTORING_GUIDE.md` for detailed documentation on each module.
