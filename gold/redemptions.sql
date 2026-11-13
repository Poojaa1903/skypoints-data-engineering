-- Flatten the redemption JSON and join it to the member profile.
-- Dialect: Snowflake.
--
-- bronze.redemption_raw.payload is VARIANT and holds the whole object.
-- LATERAL FLATTEN turns the redemptions array into one row per transaction.
-- The same txn_id on a later feed_date replaces the earlier row.
-- A transaction whose member_id is not in the flat-file members is kept
-- with match_status = 'ORPHAN'. It is not dropped.
--
-- Join key: member_id as text, and only to FLAT-file members, because the
-- country-file ids (1, 2, 3) are not global.
--
-- CALL gold.load_redemptions(DATE '2024-01-15');

CREATE OR REPLACE PROCEDURE gold.load_redemptions(AS_OF DATE)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    redemption_count NUMBER;
BEGIN
    -- Replace redemptions that came from this feed day.
    DELETE FROM gold.redemption
    WHERE feed_date = :AS_OF
       OR txn_id IN (
            SELECT f.value:txn_id::VARCHAR
            FROM bronze.redemption_raw r,
                 LATERAL FLATTEN(input => r.payload:redemptions) f
            WHERE r.load_date = :AS_OF
       );

    INSERT INTO gold.redemption (
        member_id, feed_date, txn_id, txn_date, partner,
        miles_redeemed, status, country_code, match_status
    )
    WITH flat AS (
        SELECT
            r.member_id::VARCHAR                          AS member_id,
            TRY_TO_DATE(r.feed_date, 'YYYYMMDD')          AS feed_date,
            f.value:txn_id::VARCHAR                       AS txn_id,
            TRY_TO_DATE(f.value:txn_date::VARCHAR, 'YYYYMMDD') AS txn_date,
            f.value:partner::VARCHAR                      AS partner,
            f.value:miles_redeemed::NUMBER                AS miles_redeemed,
            f.value:status::VARCHAR                       AS status
        FROM bronze.redemption_raw r,
             LATERAL FLATTEN(input => r.payload:redemptions) f
        WHERE r.load_date = :AS_OF
    ),
    latest AS (
        SELECT *
        FROM flat
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY txn_id
            ORDER BY feed_date DESC
        ) = 1
    )
    SELECT
        l.member_id,
        l.feed_date,
        l.txn_id,
        l.txn_date,
        l.partner,
        l.miles_redeemed,
        l.status,
        m.country_code,
        IFF(m.member_id IS NULL, 'ORPHAN', 'MATCHED') AS match_status
    FROM latest l
    LEFT JOIN gold.member m
        ON m.member_id = l.member_id
       AND m.source_scope = 'FLAT';

    redemption_count := (
        SELECT COUNT(*) FROM gold.redemption
        WHERE feed_date = :AS_OF
           OR txn_date IN (
                SELECT TRY_TO_DATE(f.value:txn_date::VARCHAR, 'YYYYMMDD')
                FROM bronze.redemption_raw r,
                     LATERAL FLATTEN(input => r.payload:redemptions) f
                WHERE r.load_date = :AS_OF
           )
    );

    RETURN 'GOLD redemptions=' || :redemption_count;
END;
$$;
