"""Add PostGIS extension, location_geom column, GiST spatial index, and trigger.

Revision ID: 005
Revises: 004
Create Date: 2026-07-31 22:05:00
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "005_add_postgis_location_support"
down_revision = "004_add_explorer_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Enable PostGIS Extension
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    # 2. Add Geometry column location_geom (Point, WGS84 SRID 4326)
    op.execute("ALTER TABLE data_points ADD COLUMN IF NOT EXISTS location_geom geometry(Point, 4326);")

    # 3. Create GiST Spatial Index
    op.execute("CREATE INDEX IF NOT EXISTS idx_data_points_location_geom ON data_points USING GIST (location_geom);")

    # 4. Create Trigger Function to automatically set location_geom from metadata latitude & longitude
    op.execute("""
    CREATE OR REPLACE FUNCTION populate_location_geom()
    RETURNS TRIGGER AS $$
    BEGIN
        IF NEW.metadata IS NOT NULL AND NEW.metadata ? 'latitude' AND NEW.metadata ? 'longitude' THEN
            BEGIN
                NEW.location_geom := ST_SetSRID(
                    ST_MakePoint(
                        (NEW.metadata->>'longitude')::float,
                        (NEW.metadata->>'latitude')::float
                    ),
                    4326
                );
            EXCEPTION WHEN OTHERS THEN
                NULL;
            END;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)

    # 5. Attach Trigger to data_points table
    op.execute("DROP TRIGGER IF EXISTS trg_data_points_populate_location_geom ON data_points;")
    op.execute("""
    CREATE TRIGGER trg_data_points_populate_location_geom
    BEFORE INSERT OR UPDATE ON data_points
    FOR EACH ROW
    EXECUTE FUNCTION populate_location_geom();
    """)

    # 6. Backfill existing location data_points
    op.execute("""
    UPDATE data_points
    SET location_geom = ST_SetSRID(
        ST_MakePoint(
            (metadata->>'longitude')::float,
            (metadata->>'latitude')::float
        ),
        4326
    )
    WHERE metadata IS NOT NULL
      AND metadata ? 'latitude'
      AND metadata ? 'longitude'
      AND location_geom IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_data_points_populate_location_geom ON data_points;")
    op.execute("DROP FUNCTION IF EXISTS populate_location_geom();")
    op.execute("DROP INDEX IF EXISTS idx_data_points_location_geom;")
    op.execute("ALTER TABLE data_points DROP COLUMN IF EXISTS location_geom;")
    op.execute("DROP EXTENSION IF EXISTS postgis;")
