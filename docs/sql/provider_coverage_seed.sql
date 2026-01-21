-- Create provider_coverage table (if it doesn't exist) and seed coverage from providers.
-- Assumes PostgreSQL.

CREATE TABLE IF NOT EXISTS provider_coverage (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    comuna VARCHAR(64) NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_coverage_provider_comuna
    ON provider_coverage (provider_id, comuna);

CREATE INDEX IF NOT EXISTS ix_provider_coverage_comuna
    ON provider_coverage (comuna);

-- Seed default coverage from each provider's base comuna.
INSERT INTO provider_coverage (provider_id, comuna)
SELECT p.id, p.comuna
FROM providers p
WHERE p.comuna IS NOT NULL AND p.comuna <> ''
ON CONFLICT (provider_id, comuna) DO NOTHING;
