-- Exécuté une seule fois, à la première création du volume mysql_data.
-- La base (DB_AUDIT_NAME) est créée par l'image MySQL avant ce script.

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
    created_at  DATETIME(3)       NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    request_id  CHAR(36)          NOT NULL,
    username    VARCHAR(255)      NULL,
    action      VARCHAR(100)      NULL,
    method      VARCHAR(10)       NOT NULL,
    path        VARCHAR(255)      NOT NULL,
    status_code SMALLINT UNSIGNED NOT NULL,
    duration_ms INT UNSIGNED      NOT NULL,
    ip_address  VARCHAR(45)       NULL,
    user_agent  VARCHAR(255)      NULL,
    details     JSON              NULL,
    PRIMARY KEY (id),
    KEY idx_audit_log_created_at (created_at),
    KEY idx_audit_log_username_created_at (username, created_at),
    KEY idx_audit_log_action_created_at (action, created_at),
    KEY idx_audit_log_request_id (request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
