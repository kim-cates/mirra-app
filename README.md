# Reflections App

A daily journaling app built with Streamlit, Claude AI keyword extraction, and Supabase storage.

## Setup

### 1. Supabase table

Run this SQL in your Supabase SQL editor:

```sql
create table reflections (
  id           uuid primary key default gen_random_uuid(),
  entry_date   date not null unique,
  content      text not null,
  mood         numeric(3,1) not null,
  keywords     text[] default '{}',
  updated_at   timestamptz default now()
);

-- Index for fast date lookups
create index on reflections (entry_date desc);
```

### 2. Streamlit secrets

Create `.streamlit/secrets.toml` in the project root:

```toml
SUPABASE_URL     = "https://your-project.supabase.co"
SUPABASE_KEY     = "your-anon-public-key"
ANTHROPIC_API_KEY = "sk-ant-..."
```

### 3. Install & run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Features

- **Daily reflection** — one entry per day, auto-upserts on re-save
- **Mood slider** — 1–10 scale stored per entry
- **AI keywords** — Claude extracts 5–8 themes from your text automatically
- **Streak counter** — consecutive days with an entry
- **Stats panel** — total entries, 30-day avg mood, top keyword this week
