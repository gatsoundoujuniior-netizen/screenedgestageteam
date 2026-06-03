-- ============================================================
-- ScreenEdge Africa — Table referentiel_pep
-- PostgreSQL (compliance_db) — VPS 195.200.14.241
-- ============================================================

CREATE TABLE IF NOT EXISTS referentiel_pep (
    id          SERIAL PRIMARY KEY,
    region      TEXT NOT NULL CHECK (region IN ('maghreb', 'uemoa', 'autre')),
    pays        TEXT NOT NULL,
    code_iso    CHAR(2) NOT NULL UNIQUE,
    loi_ref     TEXT,
    def_pep     TEXT,
    statut_gafi TEXT NOT NULL DEFAULT 'clean'
                     CHECK (statut_gafi IN ('clean', 'liste_grise', 'liste_noire')),
    vigilance   TEXT NOT NULL DEFAULT 'standard'
                     CHECK (vigilance IN ('standard', 'renforcee', 'maximale')),
    autorite    TEXT,
    source_url  TEXT,
    notes       TEXT,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Index pour recherches fréquentes de l'agent
CREATE INDEX IF NOT EXISTS idx_ref_pep_code_iso ON referentiel_pep (code_iso);
CREATE INDEX IF NOT EXISTS idx_ref_pep_statut   ON referentiel_pep (statut_gafi);
CREATE INDEX IF NOT EXISTS idx_ref_pep_pays     ON referentiel_pep USING gin (to_tsvector('simple', pays));

-- Trigger : updated_at automatique
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ref_pep_updated_at ON referentiel_pep;
CREATE TRIGGER trg_ref_pep_updated_at
    BEFORE UPDATE ON referentiel_pep
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
