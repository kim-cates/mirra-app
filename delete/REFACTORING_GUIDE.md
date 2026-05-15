# Mirra App Refactoring Guide

## Overview

The Mirra app has been refactored into modular components to improve maintainability, testability, and code organization. The original monolithic `app.py` has been broken down into six focused modules plus utility functions.

## Module Structure

### 1. **config.py** - Configuration & Constants
Contains all page configuration, CSS styling, and application constants.

**Key exports:**
- `configure_page()` - Set up Streamlit page config
- `apply_styling()` - Apply global CSS
- Constants: `PRESET_FEELINGS`, `TOPIC_COLORS`, `DENDRO_COLORS`, `FEELING_COLORS`, `BIOMETRIC_FIELDS`, `BIOMETRIC_FEATURE_DIMS`

**Use when:** Updating styling, page configuration, or constants used across the app.

---

### 2. **auth.py** - Authentication
Handles user authentication, login, signup, and logout functionality.

**Key functions:**
- `hash_pw(password)` - Hash passwords securely
- `render_login_page(supabase)` - Display login/signup UI
- `handle_signin(supabase, username, password)` - Sign in logic
- `handle_signup(supabase, username, password)` - Account creation logic
- `render_logout_button()` - Display logout button

**Use when:** Modifying authentication flow, login UI, or password handling.

---

### 3. **data_manager.py** - Data Management
Database operations and data loading/saving.

**Key functions:**
- `save_reflection(supabase, content, mood, keywords, user_id, feelings)` - Save a reflection
- `load_all_entries(supabase, user_id)` - Load all reflections for a user
- `load_stats(rows)` - Calculate reflection statistics

**Use when:** Modifying database schema, data persistence, or statistics calculations.

---

### 4. **nlp_utils.py** - NLP & Machine Learning
Text processing, embeddings, clustering, and advanced NLP operations.

**Key functions:**
- `load_nlp_models()` - Load sentence transformer models
- `extract_keywords(text)` - Extract keywords from text
- `get_embeddings(texts)` - Generate embeddings
- `build_biometric_features(values_per_field)` - Create biometric feature vectors
- `extract_noun_phrase_clusters(rows, top_n)` - Extract common phrases
- `get_top_similar_phrases(query, phrases, top_n)` - Semantic similarity search
- `run_topic_map(texts, biometrics, n_clusters, k_search_range)` - UMAP + KMeans clustering
- `run_dendrogram(phrases_tuple, biometrics, n_clusters, k_search_range)` - Hierarchical clustering

**Use when:** Working with text analysis, embeddings, or clustering algorithms.

---

### 5. **insights.py** - Analysis & Insights
Thematic analysis and insight computation.

**Key functions:**
- `cluster_characteristics_from_phrases(cluster_to_phrases, rows, oura_by_date)` - Analyze cluster characteristics
- `describe_cluster_in_words(profile)` - Generate human-readable cluster descriptions
- `compute_thematic_insights(seed_phrases, cluster_to_phrases, rows, oura_by_date)` - Generate thematic insights

**Use when:** Modifying analysis logic, adding new insight types, or changing how clusters are interpreted.

---

### 6. **visualizations.py** - Visualization Utilities
Plotting and chart rendering functions.

**Key functions:**
- `_fmt_metric(v, suffix, digits)` - Format metric values
- `_cluster_top_keywords(texts_in_cluster, all_texts, top_n)` - Extract cluster keywords
- `_draw_dendrogram(phrases, Z, cluster_ids)` - Render dendrogram chart
- `_render_feelings_violin_single(feelings_data, feeling_order)` - Single violin plot
- `_render_feelings_violin_compare(recent_data, alltime_data, feeling_order)` - Comparative violin plot

**Use when:** Modifying charts, adding new visualizations, or changing plot styling.

---

## Integration with app.py

The main `app.py` should import and use these modules:

```python
import streamlit as st
from config import configure_page, apply_styling, PRESET_FEELINGS
from auth import render_login_page, render_logout_button
from data_manager import save_reflection, load_all_entries, load_stats
from nlp_utils import (
    extract_keywords, run_topic_map, run_dendrogram,
    extract_noun_phrase_clusters, get_top_similar_phrases
)
from insights import compute_thematic_insights
from visualizations import _draw_dendrogram

# Setup
configure_page()
apply_styling()

# Auth check
if not st.session_state.get("logged_in"):
    render_login_page(supabase)
    st.stop()

# Main app logic
```

---

## Future Refactoring Recommendations

### Page Modules
The UI rendering functions could be further broken into separate page modules:

- **pages/topic_map.py** - `render_bertopic_tab(rows, oura_by_date)`
- **pages/dendrogram.py** - `render_dendrogram_tab(rows, oura_by_date)`
- **pages/weekly_insights.py** - `render_weekly_insights_tab(rows, oura_by_date)`
- **pages/intro.py** - Intro page components

This would make each page independently testable and maintainable.

### Client Initialization
Move client setup to a dedicated module:

```python
# clients.py
@st.cache_resource
def get_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

@st.cache_resource
def get_anthropic():
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
```

### Type Hints
Add comprehensive type hints to all functions for better IDE support and documentation.

### Testing
Each module can now be unit tested independently without the Streamlit overhead:

```python
# test_nlp_utils.py
def test_extract_keywords():
    result = extract_keywords("creative projects and flow state")
    assert "creative projects" in result or "flow state" in result
```

---

## Benefits of Modularization

1. **Separation of Concerns** - Each module has a single, well-defined purpose
2. **Testability** - Modules can be tested independently
3. **Reusability** - Functions can be imported into other projects
4. **Maintainability** - Changes are isolated to relevant modules
5. **Readability** - Smaller files are easier to understand
6. **Collaboration** - Multiple developers can work on different modules simultaneously

---

## Migration Checklist

- [ ] Import modules at the top of `app.py`
- [ ] Replace duplicated code with module function calls
- [ ] Test each page/tab after importing modules
- [ ] Verify all imports resolve correctly
- [ ] Run full app to ensure no breaking changes
- [ ] Consider creating page modules for further organization

---

## Questions or Issues?

Refer to individual module docstrings for detailed API documentation. Each function has inline comments explaining its purpose and parameters.
