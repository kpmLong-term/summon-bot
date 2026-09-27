# Summon

Telegram group collector. Characters spawn after a run of chat messages. The first person to type the exact name keeps the card. Coins, a shop, a market, auctions, streaks, and Telegram Stars sit on top of that loop.

Aiogram 3.31 talks to Bot API 10.3. Kurigram is an optional MTProto client started with `no_updates`, so it never races Aiogram for `getUpdates`.

## Run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill BOT_TOKEN and OWNER_ID
python -m summon_bot
```

With `WEBHOOK_URL` empty, the process long-polls and also serves `/health` and `/app/` on `PORT` for a later public deploy. Set `WEBAPP_URL` to that public HTTPS origin so the album button appears. Telegram only opens Mini Apps from a public URL.

PostgreSQL is used when `DATABASE_URL` is a `postgresql://` URL. If neither Postgres nor Mongo is configured for game data, everything lives in `data/summon.db`. `MONGO_URI` is optional and only mirrors audit events (starts, groups, gifts, backups).

Set `LOG_CHANNEL_ID` to a channel where the bot can post. You will see starts, group joins, gifts, bans, backups, and optional heartbeats (`HEARTBEAT_MINUTES`).

Keep-alive: the bot exposes `GET /ping`. On Render/Railway set `KEEPALIVE_URL=https://your-host/ping` or run `python ping_server.py` beside the bot. `supervisor.py` still restarts after crashes.

Backups land in `data/backups/` on a schedule (`BACKUP_INTERVAL_HOURS`). Owner can run `/backup` anytime. Inactive empty accounts purge when `INACTIVE_DAYS` is greater than zero.

The Mini App under `/app/` uses HTML, CSS, Three.js card orbit, and Anime.js taps. Set `WEBAPP_URL` to your public HTTPS origin.

```bash
sudo cp summon-bot.service.example /etc/systemd/system/summon-bot.service
sudo systemctl enable --now summon-bot
```

`supervisor.py` restarts after a crash. Leave `AUTO_RESTART_MINUTES=0`.

## Play

In a group, chat until a portrait appears, then type the name. The hint button under the portrait spends coins and answers only you.

| Command | What it does |
| --- | --- |
| /collection /hmode /fav /profile | Album, rarity filter, favorite, profile card |
| /daily /spin /quests /streak /achievements | Coins and goals |
| /shop /market /sell /auction /bid | Buy, list, and bid |
| /gift /pay /redeem | Move cards and coins (gift notifies receiver in DM) |
| /search /check /nguess /top | Lookup, quiz, leaderboard |
| /premium /vault | Stars invoice and paid-media pull |
| /spawn /changetime /chance /ban /kick /pin /tagall /addchar | Sudo and admin tools |
| /owner /gencode /broadcast /stars /refund /sublink /backup | Owner tools |

`/addchar` replies to a photo: `Name | Series | Rarity | optional alias`.

Event rarities (Valentine, Summer, Halloween, Christmas, Celestial, Limited) spawn rarely and are not sold in the shop. Add them with `/addchar` or the built-in cast.

## Bot API used on purpose

- Ephemeral commands and `receiver_user_id` so balance, album, and hints do not flood the group
- Rich messages for the menu and help
- Inline button `style` and optional `icon_custom_emoji_id`
- `copy_text` on redeem codes
- Message effects and `setMessageReaction` on a catch
- `setChatMemberTag` after a mythic catch when the bot can manage tags
- Stars invoices (`XTR`), `getMyStarBalance`, `refundStarPayment`, `pre_checkout_query`
- Paid media for `/vault`, granted only from `purchased_paid_media`
- `createChatSubscriptionInviteLink` when `PREMIUM_CHAT_ID` is set
- Quiz polls with `correct_option_ids`, description, and `members_only`
- Inline mode, guest replies via `answerGuestQuery`, and join-request handling for the premium channel
- WebApp button plus checked Mini App `initData`

Kurigram, when `API_ID` and `API_HASH` are set, resolves public usernames the bot has not seen and checks custom emoji documents. A user `SESSION_STRING` is optional. Do not commit it.

## Checks

```bash
python -m unittest tests.test_game
```

Built with [BrainDaemon](https://braindaemon.com)
