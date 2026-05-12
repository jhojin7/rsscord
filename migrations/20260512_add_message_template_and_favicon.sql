-- Add per-thread message template and favicon caching for feeds/domains
ALTER TABLE threads
  ADD COLUMN IF NOT EXISTS message_template TEXT;

-- Add favicon info per feed (or per domain entry if you have a domains table)
ALTER TABLE feeds
  ADD COLUMN IF NOT EXISTS favicon_url TEXT,
  ADD COLUMN IF NOT EXISTS favicon_fetched_at TIMESTAMP;

-- Optional index for lookup by domain if needed:
CREATE INDEX IF NOT EXISTS idx_feeds_favicon_fetched_at ON feeds(favicon_fetched_at);
