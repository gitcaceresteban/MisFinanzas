-- =====================================================
-- Esquema de base de datos: Motor Financiero Personal
-- SQLite 3
-- =====================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---------------------------------------------------
-- Usuarios (preparado para futuro multi-usuario)
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    api_token TEXT,
    settings_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------
-- Bancos
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS banks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    country TEXT DEFAULT 'CL',
    color TEXT DEFAULT '#3b82f6',
    color_secondary TEXT,
    logo_url TEXT,
    website TEXT,
    notes TEXT,
    is_seeded INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_banks_active ON banks(active);

-- ---------------------------------------------------
-- Cuentas
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_id INTEGER,
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- corriente, vista, rut, ahorro, digital, efectivo, otra
    currency TEXT NOT NULL DEFAULT 'CLP',
    balance REAL NOT NULL DEFAULT 0,
    credit_line REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'activa', -- activa, cerrada, pausada
    color TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (bank_id) REFERENCES banks(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_accounts_bank ON accounts(bank_id);
CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status);

-- ---------------------------------------------------
-- Tarjetas de crédito
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS credit_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_id INTEGER,
    name TEXT NOT NULL,
    credit_limit REAL NOT NULL DEFAULT 0,
    used_amount REAL NOT NULL DEFAULT 0,
    billing_day INTEGER,         -- día del mes en que factura
    payment_day INTEGER,         -- día del mes en que vence
    status TEXT NOT NULL DEFAULT 'activa', -- activa, bloqueada, cerrada
    has_billed_debt INTEGER NOT NULL DEFAULT 0,
    billed_amount REAL DEFAULT 0,
    unbilled_amount REAL DEFAULT 0,
    future_installments_amount REAL DEFAULT 0,
    pending_installments INTEGER DEFAULT 0,
    color TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (bank_id) REFERENCES banks(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_cards_bank ON credit_cards(bank_id);
CREATE INDEX IF NOT EXISTS idx_cards_status ON credit_cards(status);

-- ---------------------------------------------------
-- Categorías y subcategorías
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER,
    color TEXT DEFAULT '#64748b',
    icon TEXT,
    monthly_budget REAL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_categories_active ON categories(active);

-- ---------------------------------------------------
-- Personas
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    alias TEXT,
    phone TEXT,
    telegram_id TEXT,
    email TEXT,
    notes TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_people_active ON people(active);

-- ---------------------------------------------------
-- Transacciones (gastos e ingresos)
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    type TEXT NOT NULL DEFAULT 'expense', -- expense, income, transfer
    transaction_type TEXT DEFAULT 'normal', -- normal, installments, cash_advance, super_advance, debt_payment, fee_interest, adjustment
    category_id INTEGER,
    description TEXT,
    account_id INTEGER,
    card_id INTEGER,
    payment_method TEXT,
    person_id INTEGER,
    project TEXT,
    tags TEXT,
    attachment_path TEXT,
    status TEXT NOT NULL DEFAULT 'pagado', -- pagado, pendiente, reembolsado, anulado
    origin TEXT NOT NULL DEFAULT 'web', -- web, telegram, iphone, home_assistant, importado, manual, api
    installments_total INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL,
    FOREIGN KEY (card_id) REFERENCES credit_cards(id) ON DELETE SET NULL,
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_tx_card ON transactions(card_id);
CREATE INDEX IF NOT EXISTS idx_tx_person ON transactions(person_id);
CREATE INDEX IF NOT EXISTS idx_tx_status ON transactions(status);
CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(type);

-- ---------------------------------------------------
-- Cuotas de tarjetas de crédito
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS card_installments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    transaction_id INTEGER,
    installment_number INTEGER NOT NULL,
    total_installments INTEGER NOT NULL,
    amount REAL NOT NULL,
    estimated_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendiente', -- pendiente, facturada, pagada
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (card_id) REFERENCES credit_cards(id) ON DELETE CASCADE,
    FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_card ON card_installments(card_id);
CREATE INDEX IF NOT EXISTS idx_ci_status ON card_installments(status);
CREATE INDEX IF NOT EXISTS idx_ci_date ON card_installments(estimated_date);

-- ---------------------------------------------------
-- Deudas entre personas
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS person_debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    direction TEXT NOT NULL, -- they_owe_me, i_owe_them
    original_amount REAL NOT NULL,
    pending_amount REAL NOT NULL,
    paid_amount REAL NOT NULL DEFAULT 0,
    date TEXT NOT NULL,
    expected_date TEXT,
    description TEXT,
    category_id INTEGER,
    related_transaction_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pendiente', -- pendiente, parcial, pagado, vencido, cancelado
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
    FOREIGN KEY (related_transaction_id) REFERENCES transactions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_pd_person ON person_debts(person_id);
CREATE INDEX IF NOT EXISTS idx_pd_status ON person_debts(status);
CREATE INDEX IF NOT EXISTS idx_pd_direction ON person_debts(direction);

-- ---------------------------------------------------
-- Pagos / abonos de deudas entre personas
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS person_debt_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    debt_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    date TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (debt_id) REFERENCES person_debts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pdp_debt ON person_debt_payments(debt_id);

-- ---------------------------------------------------
-- Cuentas del hogar
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS household_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category_id INTEGER,
    amount REAL NOT NULL,
    due_date TEXT,
    paid_date TEXT,
    paid_by_person_id INTEGER,
    paid_from_account_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pendiente', -- pendiente, pagada, parcial, vencida
    split_type TEXT NOT NULL DEFAULT 'equal', -- equal, fixed, percent, custom
    attachment_path TEXT,
    logo_path TEXT,                            -- imagen/logo de la cuenta
    installments_total INTEGER NOT NULL DEFAULT 1,   -- nº de cuotas en que me lo pagan
    installment_number INTEGER NOT NULL DEFAULT 1,   -- cuál cuota es (1..N)
    series_id TEXT,                            -- agrupa las cuotas de una misma compra
    collected_amount REAL NOT NULL DEFAULT 0,  -- total abonado hacia esta cuenta
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
    FOREIGN KEY (paid_by_person_id) REFERENCES people(id) ON DELETE SET NULL,
    FOREIGN KEY (paid_from_account_id) REFERENCES accounts(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_hb_status ON household_bills(status);
CREATE INDEX IF NOT EXISTS idx_hb_due ON household_bills(due_date);
CREATE INDEX IF NOT EXISTS idx_hb_series ON household_bills(series_id);

-- ---------------------------------------------------
-- Abonos (pagos parciales) de cuentas del hogar
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS household_bill_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL,
    participant_id INTEGER,
    person_id INTEGER,
    amount REAL NOT NULL,
    date TEXT NOT NULL,
    account_id INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (bill_id) REFERENCES household_bills(id) ON DELETE CASCADE,
    FOREIGN KEY (participant_id) REFERENCES household_bill_participants(id) ON DELETE SET NULL,
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE SET NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_hbpay_bill ON household_bill_payments(bill_id);
CREATE INDEX IF NOT EXISTS idx_hbpay_date ON household_bill_payments(date);

-- ---------------------------------------------------
-- Participantes en cuentas del hogar
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS household_bill_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    share_amount REAL NOT NULL DEFAULT 0,
    share_percent REAL,
    paid_amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pendiente', -- pendiente, parcial, pagado
    notes TEXT,
    FOREIGN KEY (bill_id) REFERENCES household_bills(id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_hbp_bill ON household_bill_participants(bill_id);
CREATE INDEX IF NOT EXISTS idx_hbp_person ON household_bill_participants(person_id);

-- ---------------------------------------------------
-- Pagos recurrentes
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS recurring_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category_id INTEGER,
    amount REAL NOT NULL,
    amount_is_fixed INTEGER NOT NULL DEFAULT 1, -- 1=fijo, 0=variable
    frequency TEXT NOT NULL DEFAULT 'monthly', -- monthly, weekly, biweekly, yearly, custom
    day_of_month INTEGER,
    account_id INTEGER,
    card_id INTEGER,
    person_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    start_date TEXT,
    end_date TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL,
    FOREIGN KEY (card_id) REFERENCES credit_cards(id) ON DELETE SET NULL,
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_rp_active ON recurring_payments(active);

-- ---------------------------------------------------
-- Presupuestos
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period TEXT NOT NULL DEFAULT 'monthly', -- monthly, yearly
    year INTEGER NOT NULL,
    month INTEGER,
    scope TEXT NOT NULL DEFAULT 'category', -- global, category, account, person
    category_id INTEGER,
    account_id INTEGER,
    person_id INTEGER,
    amount REAL NOT NULL,
    alert_threshold INTEGER DEFAULT 80, -- % en que alerta
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_budgets_period ON budgets(year, month);

-- ---------------------------------------------------
-- Créditos / deudas propias
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    entity TEXT,
    bank_id INTEGER,
    type TEXT NOT NULL DEFAULT 'consumo', -- consumo, automotriz, hipotecario, avance, super_avance, personal, cuotas, otra
    original_amount REAL NOT NULL,
    pending_amount REAL NOT NULL,
    total_installments INTEGER NOT NULL DEFAULT 1,
    paid_installments INTEGER NOT NULL DEFAULT 0,
    pending_installments INTEGER NOT NULL DEFAULT 0,
    installment_amount REAL NOT NULL DEFAULT 0,
    first_payment_date TEXT,
    next_payment_date TEXT,
    interest_rate REAL,
    status TEXT NOT NULL DEFAULT 'vigente', -- vigente, pagada, refinanciada, atrasada
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (bank_id) REFERENCES banks(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_loans_status ON loans(status);

-- ---------------------------------------------------
-- Cuotas de créditos
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS loan_installments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id INTEGER NOT NULL,
    installment_number INTEGER NOT NULL,
    amount REAL NOT NULL,
    due_date TEXT NOT NULL,
    paid_date TEXT,
    paid_amount REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pendiente', -- pendiente, pagada, atrasada
    notes TEXT,
    FOREIGN KEY (loan_id) REFERENCES loans(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_li_loan ON loan_installments(loan_id);
CREATE INDEX IF NOT EXISTS idx_li_due ON loan_installments(due_date);
CREATE INDEX IF NOT EXISTS idx_li_status ON loan_installments(status);

-- ---------------------------------------------------
-- Alertas
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL, -- account_due, card_due, person_unpaid, budget_warn, budget_over, recurring_unregistered, loan_due, low_balance, low_card_limit
    severity TEXT NOT NULL DEFAULT 'info', -- info, warning, error, success
    title TEXT NOT NULL,
    message TEXT,
    related_entity_type TEXT,
    related_entity_id INTEGER,
    action_url TEXT,
    read INTEGER NOT NULL DEFAULT 0,
    dismissed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_alerts_read ON alerts(read);
CREATE INDEX IF NOT EXISTS idx_alerts_dismissed ON alerts(dismissed);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);

-- ---------------------------------------------------
-- Adjuntos
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_att_entity ON attachments(entity_type, entity_id);

-- ---------------------------------------------------
-- Tokens API
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    scopes TEXT,
    last_used_at TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------
-- Auditoría
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL, -- create, update, delete, payment, adjustment
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    changes_json TEXT,
    source TEXT DEFAULT 'web',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_date ON audit_log(created_at);

-- ---------------------------------------------------
-- Configuración general (key/value)
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------
-- Snapshots mensuales de endeudamiento (para ver la tendencia)
-- ---------------------------------------------------
CREATE TABLE IF NOT EXISTS debt_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ym TEXT NOT NULL UNIQUE,          -- 'YYYY-MM'
    cards_debt REAL NOT NULL DEFAULT 0,
    loans_debt REAL NOT NULL DEFAULT 0,
    total_debt REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_debt_snap_ym ON debt_snapshots(ym);
