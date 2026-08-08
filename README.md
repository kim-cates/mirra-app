# Mirra — Daily Reflection & Life Pattern Discovery

A Streamlit app for daily journaling with AI-powered thematic analysis, biometric integration (Oura), and advanced insights into your mood patterns and life themes.

## Planning & Roadmaps

- Miro board: https://miro.com/app/board/uXjVHzho-kY=/
- GitHub Project board: https://github.com/users/kim-cates/projects/2/views/1
- Story backlog source: `stories.yml`


## Setup

### 1. Supabase table

Run this SQL in your Supabase SQL editor:

```sql
create table users (
  id           uuid primary key default gen_random_uuid(),
  username     text unique not null,
  password_hash text not null,
  created_at   timestamptz default now()
);

create table reflections (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references users(id),u
  entry_date      date not null,
  content         text not null,
  mood            numeric(3,1),
  keywords        text[] default '{}',
  feelings        jsonb default '[]',
  updated_at      timestamptz default now(),
  unique(user_id, entry_date)
);

create index on reflections (user_id, entry_date desc);
```

Feelings format: `[{"name": "anxious", "intensity": 7}, {"name": "calm", "intensity": null}]`

### 2. Streamlit secrets

Create `.streamlit/secrets.toml` in the project root, or copy `.streamlit/secrets.example.toml` and fill in the values:

```toml
SUPABASE_URL      = "https://your-project.supabase.co"
SUPABASE_KEY      = "your-anon-public-key"
ANTHROPIC_API_KEY = "sk-ant-..."
OURA_CLIENT_ID    = "your-oura-client-id"
OURA_CLIENT_SECRET = "your-oura-client-secret"
OURA_REDIRECT_URI = "https://your-deployed-app-url/"
```

### 3. Oura OAuth setup

1. Register your app on Oura:
   - https://cloud.ouraring.com/oauth/applications
2. Configure the redirect URI exactly as Oura requires. Usually this is your deployed app URL.
3. Add `OURA_CLIENT_ID`, `OURA_CLIENT_SECRET`, and `OURA_REDIRECT_URI` to `.streamlit/secrets.toml`.
4. Run Mirra and use the `Settings` → `OAuth (recommended for shared use)` tab.
5. Click **Authorize on Oura →**, approve access, and return to Mirra.

If OAuth is not configured, the app will show which value is missing and a sample config block.

### 4. Install & run

```bash
pip install -r requirements.txt
streamlit run app.py
```

### 3. Install & run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Features

### Core Journaling
- **Daily reflection** — one entry per day with content, mood (1–10), and feelings
- **Feelings tracking** — multi-select feelings with optional intensity ratings (1–10)
- **Keyword extraction** — automatically extracts themes from your reflection text
- **Streak counter** — tracks consecutive days with entries
- **Quick stats** — total entries, 30-day mood average, top theme this week

### Advanced Analysis

#### Topic Map
- **UMAP dimensionality reduction** — visualize your reflections in 2D semantic space
- **Auto-clustered topics** — KMeans with silhouette score optimization
- **Biometric-aware clustering** — clusters factor in mood, sleep score, readiness, HRV, and resting HR
- **Per-cluster summaries** — mood averages, top feelings, key reflection terms

#### Phrase Dendrogram
- **Semantic theme explorer** — enter a concept (e.g., "stress", "creative flow") and find related phrases
- **Hierarchical clustering** — see how themes branch and relate to each other
- **Thematic insights** — automatically discover what distinguishes good days from bad days within a theme:
  - **Mood split** — phrases that appear more on high-mood vs low-mood theme days
  - **Biometric splits** — what sleep/readiness/HRV patterns correlate with theme days
  - **Co-occurrence analysis** — which phrases appear together
  - **Cluster mood ranking** — which clusters tend toward positive vs negative moods

#### Weekly Insights
- **Oura biometrics summary** — this week's sleep, readiness, activity, and resting HR
- **Mood distribution** — histogram + KDE showing mood variance this week vs all-time
- **Feelings intensity** — violin plots showing how your feelings fluctuate week-to-week
- **Top themes & feelings** — quick overview of what dominated the week

### Architecture

The app is modularized into focused components:
- `config.py` — styling, constants, page configuration
- `auth.py` — user authentication (login/signup)
- `data_manager.py` — database operations
- `nlp_utils.py` — embeddings, clustering, similarity search (UMAP, KMeans, hierarchical)
- `insights.py` — thematic analysis and insight computation
- `visualizations.py` — chart rendering (Plotly)

See `REFACTORING_GUIDE.md` for detailed module documentation.

## Dependencies

- **Streamlit** — web UI framework
- **Supabase** — PostgreSQL backend
- **sentence-transformers** — semantic embeddings
- **scikit-learn** — ML (KMeans, TF-IDF, vectorization)
- **UMAP** — dimensionality reduction
- **SciPy** — hierarchical clustering
- **Plotly** — interactive charts
- **NumPy/Pandas** — data processing
- **Oura SDK** — biometric data integration (optional)
