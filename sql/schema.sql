-- Target table for validated economic observations.
-- One row per (date, series_id); value is nullable because FRED legitimately
-- reports missing observations (its "." placeholder becomes NULL here).
CREATE TABLE IF NOT EXISTS economic_data (
    date       DATE      NOT NULL,
    series_id  VARCHAR   NOT NULL,
    value      DOUBLE,
    PRIMARY KEY (date, series_id)
);
