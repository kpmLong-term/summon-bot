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

PostgreSQL is used when `DATABASE_URL` (or `POSTGRES_URL`) answers. If that URL is missing or the server refuses the connection, game data falls back to `data/summon.db`. MongoDB (`MONGO_URI` or `MONGO_DB_URL`) only mirrors the log. If Mongo is missing or down, the bot keeps running on SQL.

Set `LOG_CHANNEL_ID` (also accepted as `LOGGER_ID` or `LOGIC_CHANNEL_ID`) to a channel where the bot can post. Starts, group add and leave, new members, gifts, bans, mutes, backups, and cleanups go there as rich messages built with [richgram](https://github.com/Badmunda05/richgram). Optional heartbeats use `HEARTBEAT_MINUTES`.

Empty accounts with no cards, no claims, no shop or auction activity, and no visit for `INACTIVE_DAYS` (default 30) are removed in batches of `INACTIVE_BATCH` (default 200). The owner account is never removed. Set `INACTIVE_DAYS=0` to turn cleanup off.

Keep-alive works the same way as a free-host music bot: the process binds `PORT` and serves `GET /health` and `GET /ping`. Every `KEEPALIVE_SECONDS` (default 300) it pings itself. If `KEEPALIVE_URL` is empty it uses `RENDER_EXTERNAL_URL/ping`, then `RAILWAY_PUBLIC_DOMAIN`, then `http://127.0.0.1:$PORT/ping`. `python ping_server.py` is the same loop as a separate process. `supervisor.py` restarts the bot after a crash.

The watchdog starts with the bot: scheduled SQLite or `pg_dump` backups, purge of inactive empty accounts (`INACTIVE_DAYS`), and an optional log-channel heartbeat (`HEARTBEAT_MINUTES`).

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
| /ban /unban /warn /warns /setwarns /kick /mute /purge /lock /setwelcome /groups | Admin, sudo, and owner tools |
| /owner /gencode /broadcast /stars /refund /sublink /backup | Owner tools |

Group admins, sudo, and the owner can set a join welcome (`{name}`, `{username}`, `{chat}`), purge messages the bot has seen, and lock the chat. Warnings in the log channel read `by actor · chat · target`. At the group's warn limit (default 3) the member is banned. `/groups` is owner-only.

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
