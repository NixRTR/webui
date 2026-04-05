-- Enable LZ4 TOAST compression on cake_stats.classes (JSONB).
-- Works with PostgreSQL 14+; complements default_toast_compression = lz4 on the server.
-- Existing rows are rewritten lazily on UPDATE; new inserts use compression immediately.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'cake_stats'
      AND column_name = 'classes'
  ) THEN
    BEGIN
      ALTER TABLE cake_stats ALTER COLUMN classes SET COMPRESSION lz4;
    EXCEPTION
      WHEN OTHERS THEN
        RAISE NOTICE 'cake_stats.classes SET COMPRESSION skipped: %', SQLERRM;
    END;
  END IF;
END $$;
