# football-score-bot

Telegram football score bot with featured match filtering, API-Football data, Redis cache, PostgreSQL metadata, odds display, group broadcasts, and multilingual UI.

## Features

- `/start` private chat menu with bettable fixtures, live scores, all fixtures, user bets, wallet/referral placeholders, World Cup futures, and settings.
- `/today` reads Redis and shows bettable fixtures only: odds available, pre-match, not suspended, and before cutoff.
- `/live` reads Redis and shows featured live matches only; users can explicitly open the full live list.
- Match detail view shows league, time, teams, score/status, primary 1X2 odds, and market tabs.
- Background cache worker refreshes fixtures and odds so user clicks do not call API-Football directly.
- Group `/subscribe` broadcasts only featured live matches. If no featured live match exists, no group message is sent.
- UI languages: Simplified Chinese, Traditional Chinese, English, Japanese, Korean.
- Match odds support simulated bet slips for flow testing only. Wallet ledger and GMPay recharge callbacks are available; withdrawal, real betting settlement, and real-money wagering remain disabled.
- World Cup futures markets support demo/manual odds and simulated prediction records only.

## Configuration

Copy the environment template:

```bash
cp .env.example .env
```

Required:

- `TELEGRAM_BOT_TOKEN`
- `API_FOOTBALL_KEY`

Featured match controls:

- `FEATURED_LEAGUE_IDS`: comma-separated API-Football league IDs that are always included.
- `FEATURED_COUNTRIES`: country names treated as higher-priority football markets.
- `FEATURED_KEYWORDS`: league keywords such as `World Cup`, `UEFA Champions League`, `Premier League`.
- `MAX_FEATURED_MATCHES`: maximum featured matches shown by default.

Refresh and API budget controls:

- `LIVE_REFRESH_SECONDS=60`
- `TODAY_REFRESH_SECONDS=300`
- `ODDS_REFRESH_SECONDS=120`

Bettable fixture controls:

- `BET_CUTOFF_MINUTES=5`
- `ENABLE_LIVE_BETTING=false`
- `SHOW_ONLY_BETTABLE_MATCHES=true`
- `SHOW_TOMORROW_MATCHES=true`
- `BETTABLE_DAYS_AHEAD=2`
- `MAX_BETTABLE_MATCHES=30`
- `ADMIN_USER_IDS=` comma-separated Telegram user IDs allowed to use `/admin_*`.

The worker owns regular API calls and writes these Redis keys:

- `football:live_fixtures`
- `football:today_fixtures:{date}`
- `football:featured_matches:{date}`
- `football:featured_odds:{date}`
- `football:odds_raw:{date}`
- `football:odds_first_matches:{date}`
- `football:odds_first_matches:updated_at:{date}`
- `football:bettable_matches:{date}`
- `football:bettable_matches:range:{start}:{days}`
- `football:fixture_detail:{fixture_id}`
- `football:fixture_events:{fixture_id}`
- `football:last_update:live`
- `football:last_update:featured`

Handlers read cache first. If Redis is empty, a handler may make one fallback API request and write the cache. This avoids every button click consuming API quota.

## Odds

The bot uses API-Football odds endpoints:

- `/odds?date=YYYY-MM-DD`
- `/odds/live`
- `/odds?fixture=fixture_id`

M4 adds odds market detail pages:

- Match Winner / 1X2
- Correct Score
- Over/Under
- Handicap / Asian Handicap
- HT/FT
- BTTS

Fixture odds are cached in Redis for 120 seconds:

- `football:odds:fixture:{fixture_id}`
- `football:odds:last_update:{fixture_id}`

The API-Football bet-market list is cached for 24 hours:

- `football:odds:markets`

API-Football may return no Correct Score or other detailed markets depending on the fixture, bookmaker, subscription plan, and data coverage. When a market is unavailable, the bot shows a friendly "not open yet" message instead of failing.

M7 adds simulated bet slips on match odds. A simulated bet writes a `bets` row with status `pending`, fixed default stake `$10`, and estimated payout. It does not place real bets, create real-money orders, deduct balances, process deposits, or process withdrawals.

Admin controls:

- `/admin`
- `/admin_stats`
- `/admin_markets`
- `/admin_suspend <fixture_id>`
- `/admin_resume <fixture_id>`
- `/admin_set_cutoff <minutes>`

To upgrade odds coverage, enable an API-Football plan that includes odds endpoints, then tune refresh intervals to keep requests below quota.

If Correct Score coverage remains insufficient, a future version can integrate a specialist odds feed such as odds-api.io, OpticOdds, or OddsJam.

Probe a fixture's available markets without printing secrets:

```bash
python -m football_score_bot.tools.odds_market_probe --fixture-id <id>
```

## World Cup Futures

API-Football remains the source for fixtures, live scores, group tables, and single-match odds. Futures/outrights markets such as World Cup winner, Golden Boot, MVP/Golden Ball, finalists, semi-finalists, group winner, and group qualification are separate market types.

M6 adds a World Cup futures skeleton:

- `/start` includes `🏆 世界杯`.
- The World Cup zone shows a countdown to the FIFA World Cup 2026 opening match on 2026-06-11.
- `futures_markets`, `futures_options`, and `user_predictions` store demo markets, options, and simulated user predictions.
- First startup seeds manual demo odds for `world_cup_winner` and `golden_boot` if `futures_markets` is empty.
- Group qualification, group winner, semi-finalist, finalist, and MVP markets are UI placeholders for now.

These futures odds are demo/manual data and are only for feature testing. The bot does not take real money, deduct balances, create real betting orders, or settle outcomes.

## Safety and Compliance

Default betting and prediction flows are simulation only. Recharge integration and wallet ledger are available for testing. Real betting and withdrawal requests are disabled by default and must be explicitly enabled in `.env`; payout, settlement, and withdrawal payment remain manual admin actions.

## GMPay Recharge, Wallet Ledger, and Referrals

M8 adds a FastAPI webhook service and wallet ledger skeleton for USDT recharge.

Configuration:

```env
PAYMENT_PROVIDER=gmpay
GMPAY_PID=1000
GMPAY_SECRET=
GMPAY_BASE_URL=https://hosea.cc.cd
GMPAY_CREATE_ORDER_PATH=/payments/gmpay/v1/order/create-transaction
GMPAY_DEFAULT_CURRENCY=cny
GMPAY_DEFAULT_TOKEN=usdt
GMPAY_DEFAULT_NETWORK=tron
GMPAY_NOTIFY_URL=https://your-domain.example/webhooks/gmpay
GMPAY_REDIRECT_URL=
GMPAY_SIGN_TYPE=md5
GMPAY_DEFAULT_PAYMENT_TYPE=
GMPAY_MIN_RECHARGE_USDT=10
GMPAY_ORDER_EXPIRE_MINUTES=30
PAYMENT_AMOUNT_TOLERANCE_USDT=0.01
APP_PUBLIC_BASE_URL=
ADMIN_USER_IDS=
REFERRAL_DEPOSIT_COMMISSION_RATE=0.00
REFERRAL_TURNOVER_COMMISSION_RATE=0.00
REFERRAL_AGENT_ENABLED=true
MAX_REFERRAL_LEVEL=1
WALLET_CURRENCY=USDT
WITHDRAW_ENABLED=false
REAL_BETTING_ENABLED=false
BET_REQUIRE_BALANCE_FOR_SIMULATION=true
BET_SETTLEMENT_ADMIN_ONLY=true
MIN_BET_AMOUNT=1
MAX_BET_AMOUNT=100
MIN_WITHDRAW_AMOUNT=10
REBATE_ENABLED=true
REBATE_MODE=none
REBATE_BY_ACTIVE_REFERRALS_ENABLED=false
REBATE_BY_TURNOVER_ENABLED=false
REBATE_SETTLEMENT_ADMIN_ONLY=true
```

`GMPAY_NOTIFY_URL` must point to the API service webhook:

```text
https://your-domain.example/webhooks/gmpay
```

For local development, expose port `8000` with `ngrok`, `cloudflared`, or use Docker Desktop host routing:

```text
http://host.docker.internal:8000/webhooks/gmpay
```

The project calls:

```text
POST {GMPAY_BASE_URL}{GMPAY_CREATE_ORDER_PATH}
GET {GMPAY_BASE_URL}/payments/gmpay/v1/config
```

The create-order request includes `pid`; `GMPAY_SECRET` is only used to sign and is never sent in the request body. The signing logic is isolated in `football_score_bot.payments.gmpay.sign_payload`: keep all non-empty fields, exclude `signature`, sort by ASCII key, join as `key=value&key=value`, append `GMPAY_SECRET` directly at the end, then compute lower-case MD5.

The minimum GMPay create-order body sent by the bot is:

```json
{
  "pid": "1000",
  "order_id": "...",
  "currency": "cny",
  "token": "usdt",
  "network": "tron",
  "amount": 100,
  "notify_url": "https://your-domain.example/webhooks/gmpay",
  "signature": "md5(...)"
}
```

GMPay limits `order_id` to a maximum length of 32 characters. Recharge orders use a short alphanumeric format like `D1779981951A7K9X2`; the Telegram user id is stored separately in `deposit_orders.user_id` and is not embedded in `order_id`.

Do not put `GMPAY_SECRET` in logs, request bodies, or README examples. It belongs only in `.env` and is used for both create-order signing and webhook verification.

The bot no longer asks users to choose a recharge chain. It creates a GMPay order with the default `GMPAY_DEFAULT_TOKEN=usdt` and `GMPAY_DEFAULT_NETWORK=tron` configuration, then sends the user to the GMPay cashier. Chain and token selection must happen on the GMPay payment page.

Users must pay the exact amount shown by the cashier page. Underpayment, overpayment, wrong-chain payment, or split payments may not be credited automatically. Abnormal orders enter manual review and require an admin to check the txid.

Webhook behavior:

- `POST /webhooks/gmpay` accepts JSON and `application/x-www-form-urlencoded` callback bodies.
- GMPay signature is verified before reading the order as paid.
- Failed signature verification returns `401` and does not credit the wallet.
- `success`, `paid`, `2`, and `TRADE_SUCCESS` style statuses are treated as successful payment.
- `order_id`, `trade_id`, `actual_amount`, and `chain_tx_id`/`block_transaction_id`/`txid` are parsed compatibly.
- `order_id`, `trade_id`, `chain_tx_id`, and `wallet_ledger` references are unique/idempotent, so repeat callbacks do not add balance twice.
- Automatic credit requires a successful signed callback with `actual_amount`.
- The credited amount is the callback `actual_amount`.
- If `actual_amount` is missing, or the difference from `amount_requested` is greater than `PAYMENT_AMOUNT_TOLERANCE_USDT`, the order becomes `manual_review` and is not credited automatically.
- Successful callbacks return plain text `ok` with `text/plain`.
- Wallet balances are changed only through `wallet_ledger` entries inside database transactions.
- The bot never stores user private keys and does not implement automatic withdrawal.

## Real Betting, Settlement, and Withdrawal Review

`REAL_BETTING_ENABLED=false` is the default. In this mode bet confirmation keeps the simulated flow and does not deduct or freeze wallet balance.

When `REAL_BETTING_ENABLED=true`, bet confirmation checks wallet balance, freezes the stake, writes `wallet_ledger.type=bet_freeze`, and creates a pending bet with `balance_frozen=true`. Bets are never auto-settled. Admins must manually settle each bet:

- `/admin_bets`
- `/admin_bet <bet_id>`
- `/admin_settle_win <bet_id>`
- `/admin_settle_loss <bet_id>`
- `/admin_settle_void <bet_id>`
- `/admin_cancel_bet <bet_id>`

Winning settlement releases frozen stake and credits `potential_payout`. Loss settlement releases frozen stake without refund. Void and cancel settlement refund stake. Every admin settlement writes `admin_audit_logs`, and settled bets are idempotent.

`WITHDRAW_ENABLED=false` is the default. When enabled, users submit `/withdraw <amount> <USDT-TRC20-address>`. The bot freezes the withdrawal amount and creates `withdraw_requests.status=pending`; it never sends funds automatically.

Withdrawal admins use:

- `/admin_withdrawals`
- `/admin_withdraw <withdraw_id>`
- `/admin_approve_withdraw <withdraw_id>`
- `/admin_reject_withdraw <withdraw_id> <reason>`
- `/admin_mark_withdraw_paid <withdraw_id> <txid>`

Approve only records review approval. Mark paid is used after the admin manually transfers funds. Reject refunds the frozen amount. All operations write `admin_audit_logs`.

Start services:

```bash
docker compose up -d --build
```

Health check:

```bash
curl http://localhost:8000/health
```

Manual callback testing should use a payload signed with the real `GMPAY_SECRET`; unsigned or incorrectly signed callbacks return `401`.

Test helpers:

```bash
python -m football_score_bot.tools.gmpay_create_test_order --amount 10
python -m football_score_bot.tools.gmpay_verify_signature_sample
```

## Referral Commission Rules

Users get an invite link from `/referrals`:

```text
https://t.me/<bot_username>?start=ref_<code>
```

When a new user enters with `start=ref_CODE`, the first parent is bound once. Self-invite is rejected and existing parent bindings are not overwritten.

The first version creates only pending first-level deposit commission records:

- `REFERRAL_DEPOSIT_COMMISSION_RATE=0.00` creates no commission.
- `REFERRAL_DEPOSIT_COMMISSION_RATE=0.02` creates a pending `2 USDT` commission for a `100 USDT` paid deposit.
- Commissions are not automatically credited to wallet balance. Admin settlement only marks the commission as settled.

`/referrals` shows the invite link, direct referrals, active referrals, referral deposit, referral turnover, pending/settled commission, and pending rebate. `/start ref_CODE` binds the first parent only; self-invite is rejected and existing bindings are not overwritten.

## Rebate Skeleton

Rebate is enabled as a skeleton with no automatic wallet credit. Configure active rules directly in `rebate_rules`:

- `mode=active_referrals` matches by effective direct referrals in the period.
- `mode=turnover` matches by settled bet turnover in the period.

Admin commands:

- `/admin_rebate_rules`
- `/admin_rebate_preview <user_id>`
- `/admin_generate_rebates`
- `/admin_settle_rebate <rebate_record_id>`

Generation creates only `pending` `rebate_records`. Admin settlement writes `wallet_ledger.type=rebate` and credits wallet balance.

## Admin Commands

Admin commands require `ADMIN_USER_IDS` and should be used in private chat to avoid exposing user data:

```text
/admin_wallet <telegram_user_id>
/admin_deposits
/admin_deposit <order_id>
/admin_adjust_balance <telegram_user_id> <amount> <reason>
/admin_bets
/admin_bet <bet_id>
/admin_settle_win <bet_id>
/admin_settle_loss <bet_id>
/admin_settle_void <bet_id>
/admin_cancel_bet <bet_id>
/admin_withdrawals
/admin_withdraw <withdraw_id>
/admin_approve_withdraw <withdraw_id>
/admin_reject_withdraw <withdraw_id> <reason>
/admin_mark_withdraw_paid <withdraw_id> <txid>
/admin_commissions
/admin_settle_commission <commission_id>
/admin_rebate_rules
/admin_rebate_preview <user_id>
/admin_generate_rebates
/admin_settle_rebate <rebate_record_id>
/admin_referrals <telegram_user_id>
```

Manual balance adjustments write both `wallet_ledger` and `admin_audit_logs`.

Accounting audit:

```bash
python -m football_score_bot.tools.accounting_audit
```

The audit checks negative balances, pending bet/withdraw frozen coverage, deposit and settlement ledger presence, and wallet balance consistency with latest ledger rows.

## Risk Notice

Real-money operation requires legal compliance, risk control, payment security, key management, anti-fraud, accounting, and operational review before launch. Keep `REAL_BETTING_ENABLED=false` and `WITHDRAW_ENABLED=false` during dry runs. Before trial operation, define max exposure per fixture, settlement SOPs, withdrawal review SOPs, admin permission separation, incident rollback rules, and daily accounting reconciliation.

Before any real-money launch, the product must complete legal compliance review, responsible-gaming controls, payment review, risk controls, settlement rules, audit logs, and jurisdiction-specific licensing checks.

Future provider integrations can be added behind `src/football_score_bot/futures_sources.py`, for example:

- The Odds API `soccer_fifa_world_cup_winner`
- Sportradar futures odds
- Sportmonks odds
- odds-api.io

## Languages

Set `DEFAULT_LANGUAGE=zh-CN` or one of:

- `zh-CN`
- `zh-TW`
- `en`
- `ja`
- `ko`

Users can run `/language` or tap the language settings button. Team and league names are kept as API-Football returns them.

## Run

```bash
docker compose up -d --build
docker compose logs -f bot
```

## Validation

```bash
python -m compileall src/football_score_bot
docker compose down
docker compose up -d --build
docker compose logs --tail 100 bot
```

Manual checks:

- `/start` menu is clear.
- `/today` defaults to bettable fixtures only and includes tomorrow when configured.
- `/bets` shows simulated pending and settled bet slips.
- `/admin_markets` lists current bettable fixture IDs.
- `/admin_suspend <fixture_id>` marks a fixture as closed for normal users.
- `🏆 世界杯` opens the World Cup zone.
- World Cup winner and Golden Boot demo markets show options and odds.
- Confirming a futures option writes a simulated `user_predictions` record only.
- `/live` defaults to featured live matches only.
- Full live list is shown only after tapping the full-list button.
- 1X2 odds show home/draw/away or `-`.
- `/language` switches `zh-CN`, `zh-TW`, `en`, `ja`, `ko`.
- Group `/subscribe` broadcasts featured live matches only.
- Repeated `/today` clicks read Redis odds/fixture caches before falling back to API-Football.
- Logs do not print API keys or Telegram tokens.
## M10 Single Bet Lifecycle

M10 moves betting to a single-ticket lifecycle. Each submitted bet gets a short `bet_no`, an independent detail view, and its own settlement state. `/bets` now paginates pending and settled tickets instead of rendering every ticket into one long message. Pending tickets can show settlement check and delete actions; settled tickets are read-only for normal users.

Normal users can only cancel a pending bet before kickoff and before the configured lock window (`BET_CANCEL_BEFORE_START_MINUTES`). Deleting a ticket never removes the database row; it marks the bet `cancelled`. Settled tickets cannot be cancelled or reopened by normal users.

`REAL_BETTING_ENABLED=false` keeps local and trial betting simulated: bets are created with `is_simulated=true` and no real wallet balance is changed. When `BET_REQUIRE_BALANCE_FOR_SIMULATION=true`, simulated bets still require `wallets.balance >= stake`, but the stake is not deducted or frozen. This is the recommended local and trial setting:

```env
REAL_BETTING_ENABLED=false
BET_REQUIRE_BALANCE_FOR_SIMULATION=true
```

When `REAL_BETTING_ENABLED=true`, placing a bet requires available balance, moves stake from `wallets.balance` to `wallets.frozen_balance`, creates `is_simulated=false`, `balance_frozen=true`, and writes `wallet_ledger type=bet_freeze`. Settlement, void refunds, and user cancellations also write `wallet_ledger`. Enable real betting only after operational, legal, and accounting checks are complete.

If `REAL_BETTING_ENABLED=false` and `BET_REQUIRE_BALANCE_FOR_SIMULATION=false`, betting is fully simulated and does not check wallet balance; the UI must treat these tickets as simulated.

After confirmation succeeds, the bot opens the bet detail card directly. Pending tickets show settlement check and delete actions; settled tickets are read-only for normal users. `/bets` separates pending, manual review, settled, real, and simulated ticket counts.

Super admins can cancel local simulated test tickets without affecting real tickets:

```text
/admin_clear_my_test_bets
/admin_clear_user_test_bets <telegram_user_id>
```

Automatic settlement is controlled by:

- `BET_AUTO_SETTLEMENT_ENABLED`
- `BET_SETTLEMENT_INTERVAL_SECONDS`
- `SETTLEMENT_REQUIRE_FINAL_STATUS`
- `SETTLEMENT_NOTIFY_GROUP_ENABLED`
- `SETTLEMENT_GROUP_CHAT_ID`
- `SETTLEMENT_PUBLIC_WIN_MIN_PAYOUT`

The settlement worker scans pending bets by `fixture_id`, requests API-Football fixture details once per fixture, and only settles final statuses `FT`, `AET`, and `PEN`. Cancelled, postponed, abandoned, or suspended fixtures are voided by default. Network errors are logged as warnings and do not clear cached score data or crash the bot.

Automatic settlement currently supports:

- `match_winner`
- `correct_score`
- `over_under`
- `btts`

Unsupported markets such as handicaps, HT/FT, corners, and unknown markets are moved to `manual_required` with an operator note for manual settlement.

## Roles And Admin Controls

Roles are configured through `SUPER_ADMIN_USER_IDS`, `ADMIN_USER_IDS`, `AGENT_USER_IDS`, and persisted in `user_roles`. Super admins can invite/remove admins and agents. Admins and agents are restricted to their own downstream users for management views. Reopening or reversing settled bets is reserved for the super admin path. Admin actions must write `admin_audit_logs`.

Current deployment uses single bot mode:

- Normal users only see the user menu.
- Admins enter the hidden admin menu with `/admin`.
- `SUPER_ADMIN_USER_IDS` has the highest permission level.
- A separate `ADMIN_BOT_TOKEN` can be introduced later, but this stage keeps admin controls inside the same bot.

Withdrawals remain manual. Users can create withdrawal requests only when `WITHDRAW_ENABLED=true`; approval does not send funds automatically. Operators must mark a withdrawal as paid after external transfer. Rejecting a withdrawal returns frozen funds through wallet ledger entries.

Rebate support is request-first. Users can request rebates, agents/admins can view downstream rebate context, and super admins approve payout. Rebate payout must write `wallet_ledger type=rebate`.

## World Cup Zone

The 2026 World Cup zone includes schedule, standings, champion prediction, group qualification, Golden Boot, MVP, and prediction entry points. If API-Football does not yet expose final 2026 World Cup data, the bot uses built-in demo seed markets from `worldcup_seed.py`. Futures markets are advance markets; final odds and market availability must be reviewed before trial operation.

## Production Safety

Before any real launch or paid trial, complete local legal compliance review, risk controls, wallet reconciliation, payment callback hardening, withdrawal review procedures, API key/token handling review, and operational incident playbooks. Never print Telegram tokens, API keys, GMPay secrets, or database passwords in logs.

## M11 FSM User Flows

Telegram user input flows now use aiogram FSM state:

- Recharge: `/wallet` -> `充值 USDT` -> choose fixed or custom amount -> confirm -> create GMPay order -> open GMPay cashier.
- Custom recharge amounts are validated as numeric, 2 decimal places max, and within `MIN_RECHARGE_AMOUNT` / `MAX_RECHARGE_AMOUNT`.
- Bet amount changes support fixed amounts and custom stake input. The confirmation page recalculates potential payout before submission.
- Withdrawal: `/wallet` -> withdrawal request -> amount -> network -> address -> confirmation. Withdrawals still require admin review and never auto-pay.
- Rebate requests collect a user note, create `rebate_requests status=pending`, and notify the upstream agent or super admin.
- Agent applications show progress against configured thresholds, then collect a note and create `agent_applications status=pending`.
- Super admin manual balance adjustments can run command-style or step-by-step FSM, and still write `wallet_ledger` plus `admin_audit_logs`.

Every FSM flow has a cancel action that clears state and returns to the related menu.

## GMPay Callback Diagnostics

`/webhooks/gmpay` logs callback diagnostics without printing secrets:

- `order_id`
- `trade_id`
- callback status
- `actual_amount`
- signature validity
- matched order flag
- deposit status before and after processing

Unknown orders log `gmpay callback order not found`. Duplicate paid callbacks return `ok` and log `duplicate callback ignored`.

Admin recharge diagnostics:

- `/admin_deposits` shows the latest 20 deposit orders.
- `/admin_deposit <order_id>` shows order amount, status, manual review fields, trade id, txid, network, payment URL, raw create response, raw callback payload, and timestamps.
- `/admin_mark_deposit_paid <order_id> <amount> <txid> <reason>` manually credits an abnormal deposit and writes `wallet_ledger.type=deposit_manual`.
- `/admin_reject_deposit <order_id> <reason>` rejects an abnormal deposit and writes an admin audit log.

GMPay config diagnostics:

```bash
python -m football_score_bot.tools.gmpay_config_probe
```

The probe prints public `supported_assets` and site info only. It does not print `GMPAY_SECRET`.

Before deploying a server, run:

```bash
python -m football_score_bot.tools.deployment_check
```

The check reports only `ok` or `missing` for key configuration, database, Redis, API health, GMPay notify URL, and super admin setup. It does not print sensitive values.
