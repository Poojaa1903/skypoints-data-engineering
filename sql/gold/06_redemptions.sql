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

INSERT OVERWRITE INTO gold.redemption
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
