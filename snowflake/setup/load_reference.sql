-- Load the ISO country list and the alias file into silver.
-- Dialect: Snowflake. Run after PUT of the two config CSVs onto the stage.
--
-- PUT file://config/iso_countries.csv @bronze.skypoints_stage/reference/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
-- PUT file://config/country_aliases.csv @bronze.skypoints_stage/reference/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;

CREATE OR REPLACE PROCEDURE silver.load_reference()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
BEGIN
    TRUNCATE TABLE silver.iso_country;
    TRUNCATE TABLE silver.country_alias;

    COPY INTO silver.iso_country (alpha2, alpha3, country_name)
    FROM @bronze.skypoints_stage/reference/iso_countries.csv
    FILE_FORMAT = (FORMAT_NAME = bronze.ff_csv)
    ON_ERROR = 'ABORT_STATEMENT';

    COPY INTO silver.country_alias (source_code, alpha3)
    FROM @bronze.skypoints_stage/reference/country_aliases.csv
    FILE_FORMAT = (FORMAT_NAME = bronze.ff_csv)
    ON_ERROR = 'ABORT_STATEMENT';

    RETURN 'LOADED reference countries and aliases';
END;
$$;
