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
- Match odds support simulated bet slips for flow testing only. Wallet, deposit, withdrawal, real-money betting, and payment flows are not implemented.
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

Current betting and prediction flows are simulation only. Recharge integration and wallet ledger are available for testing, but withdrawal, real betting settlement, automatic payout, and real-money wagering remain disabled.

## GMPay Recharge, Wallet Ledger, and Referrals

M8 adds a FastAPI webhook service and wallet ledger skeleton for USDT recharge.

Configuration:

```env
PAYMENT_PROVIDER=gmpay
GMPAY_PID=1000
GMPAY_BASE_URL=https://hosea.cc.cd
GMPAY_CREATE_ORDER_PATH=/payments/gmpay/v1/order/create-transaction
GMPAY_SECRET=
GMPAY_SIGN_TYPE=md5
GMPAY_NOTIFY_URL=https://your-domain.example/webhooks/gmpay
GMPAY_REDIRECT_URL=
GMPAY_DEFAULT_CURRENCY=cny
GMPAY_DEFAULT_TOKEN=usdt
GMPAY_DEFAULT_NETWORK=tron
GMPAY_DEFAULT_PAYMENT_TYPE=
GMPAY_MIN_RECHARGE_USDT=10
GMPAY_ORDER_EXPIRE_MINUTES=30
APP_PUBLIC_BASE_URL=
ADMIN_USER_IDS=
REFERRAL_DEPOSIT_COMMISSION_RATE=0.00
REFERRAL_AGENT_ENABLED=true
MAX_REFERRAL_LEVEL=1
WALLET_CURRENCY=USDT
WITHDRAW_ENABLED=false
REAL_BETTING_ENABLED=false
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
```

The create-order request includes `pid`; `GMPAY_SECRET` is only used to sign and is never sent in the request body. The signing logic is isolated in `football_score_bot.payments.gmpay.sign_payload`: keep all non-empty fields, exclude `signature`, sort by ASCII key, join as `key=value&key=value`, append `GMPAY_SECRET` directly at the end, then compute lower-case MD5.

Webhook behavior:

- `POST /webhooks/gmpay` accepts JSON and `application/x-www-form-urlencoded` callback bodies.
- GMPay signature is verified before reading the order as paid.
- `success`, `paid`, `2`, and `TRADE_SUCCESS` style statuses are treated as successful payment.
- `order_id`, `trade_id`, `actual_amount`, and `chain_tx_id`/`block_transaction_id`/`txid` are parsed compatibly.
- `order_id`, `trade_id`, `chain_tx_id`, and `wallet_ledger` references are unique/idempotent, so repeat callbacks do not add balance twice.
- Wallet balances are changed only through `wallet_ledger` entries inside database transactions.
- The bot never stores user private keys and does not implement automatic withdrawal.

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

## Admin Commands

Admin commands require `ADMIN_USER_IDS` and should be used in private chat to avoid exposing user data:

```text
/admin_wallet <telegram_user_id>
/admin_deposits
/admin_deposit <order_id>
/admin_adjust_balance <telegram_user_id> <amount> <reason>
/admin_commissions
/admin_settle_commission <commission_id>
/admin_referrals <telegram_user_id>
```

Manual balance adjustments write both `wallet_ledger` and `admin_audit_logs`.

## Risk Notice

Real-money operation requires legal compliance, risk control, payment security, key management, anti-fraud, accounting, and operational review before launch. Real betting settlement, automatic withdrawal, and multi-level agent settlement are not enabled in this version.

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
